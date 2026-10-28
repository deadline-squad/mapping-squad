"""Таймер зажатия S для АГС-17 (Squad) — маленький оверлей для Windows.

SquadCalc считает, сколько секунд нужно держать S для цели на карте (с учётом разницы
высот) и присылает результат сюда через сервер-посредник по коду сессии, поэтому браузер
со SquadCalc и этот оверлей могут быть на разных устройствах и в разных сетях. Скрипт следит
за зажатием S и пищит, когда время дошло до цели. Цель берётся последняя из поставленных
в SquadCalc; можно и вручную ввести дистанцию в метрах (для ручного ввода считается ровная земля).

Подключение:
    1. В SquadCalc: Настройки -> оружие -> включить "Связать оверлей-таймер"; рядом покажется код.
    2. Здесь: ввести код в поле и нажать Enter (или ✔) либо запустить `python ags17_timer.py КОД`.
       Код запоминается в файле ags17_timer.session рядом со скриптом.
В поле ввода цифры (до 4) — это дистанция в метрах, всё остальное — код сессии.

Если индикатор клавиш в окне (S○ W○ F8○) не загорается при нажатии — игра, скорее всего, запущена
от администратора, и Windows не отдаёт клавиши обычному процессу: запустите с флагом --admin
(`python ags17_timer.py --admin КОД`, появится запрос UAC) или откройте консоль от администратора.

Управление: S (зажать) — отсчёт времени, W — сброс (ствол снова вертикально),
F8 — скрипт сам зажимает S на оставшееся до цели время (повторное F8 отпускает S).
Автозажатие шлёт S в окно, которое сейчас в фокусе: перед F8 верните фокус в игру (клик в окне
оверлея отнимает фокус у игры). Программное нажатие клавиш может считаться читом: античит
(EasyAntiCheat) и правила сервера Squad вы принимаете на себя.

Физика АГС-17 та же, что в SquadCalc (src/data/weapons.js): навесная траектория,
ствол стартует на TOP_ELEVATION и опускается на ELEVATION_RATE °/с до LOWEST_ELEVATION.
Параметры подобраны по 67 замерам "время зажатия -> дальность" (ошибка 6.4 м).

Только стандартная библиотека Python 3.8+; клавиши и звук работают только в Windows.
"""

import argparse
import asyncio
import base64
import ctypes
import hashlib
import json
import math
import os
import queue
import re
import ssl
import struct
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

try:
    import tkinter as tk
except ImportError:
    tk = None

try:
    import winsound
except ImportError:
    winsound = None

# ================= ФИЗИКА (как в SquadCalc, src/data/weapons.js) =================
MUZZLE_VELOCITY = 230.0  # м/с
GRAVITY = 9.78 * 2.801  # м/с²; эффективное значение: граната пролетает максимум ~1925 м
LAUNCH_HEIGHT = 1.0  # м; высота ствола над землёй
TOP_ELEVATION = 85.84  # °, верхнее положение ствола (старт отсчёта): отсюда ровно 280 м
LOWEST_ELEVATION = 47.4  # °, нижний предел: отсюда ~1925 м
ELEVATION_RATE = 9.17  # °/с, на сколько опускается ствол при зажатой S

# ================= СЕТЬ (сервер-посредник ags17_relay.py) =================
DEFAULT_SERVER = "calc.tk104.duckdns.org:443"  # порт 443 — по шифрованному соединению (wss), остальные — без шифрования
SESSION_FILE = Path(__file__).with_name("ags17_timer.session")
TLS_PORT = 443
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455, раздел 1.3
CODE_PATTERN = re.compile(r"^[A-Z0-9]{6,16}$")
RECONNECT_DELAY_SECONDS = 5
HANDSHAKE_TIMEOUT_SECONDS = 10
IDLE_TIMEOUT_SECONDS = 90  # посредник шлёт ping каждые 25 с

# ================= КЛАВИШИ И ОКНО =================
VK_S = 0x53
VK_W = 0x57
VK_AUTO_HOLD = 0x77  # F8
POLL_MS = 10
PRECISE_SPIN_SECONDS = 0.003  # последние миллисекунды ожидания — активный цикл, sleep на Windows грубый
BEEP_FREQUENCY_HZ = 1200
BEEP_DURATION_MS = 120


def elevation_for(distance: float, height_diff: float = 0.0) -> Optional[float]:
    """Угол возвышения (навесная траектория), которым граната долетит до цели.

    Та же формула, что SquadFiringSolution.getElevation в SquadCalc.

    Args:
        distance: горизонтальная дистанция до цели, м.
        height_diff: высота цели минус высота оружия, м.

    Returns:
        Угол в градусах или None, если цель вне диапазона углов ствола.
    """
    if distance <= 0:
        return None
    discriminant = MUZZLE_VELOCITY ** 4 - GRAVITY * (
        GRAVITY * distance ** 2 + 2 * (height_diff - LAUNCH_HEIGHT) * MUZZLE_VELOCITY ** 2
    )
    if discriminant < 0:
        return None
    elevation = math.degrees(math.atan((MUZZLE_VELOCITY ** 2 + math.sqrt(discriminant)) / (GRAVITY * distance)))
    if not LOWEST_ELEVATION <= elevation <= TOP_ELEVATION:
        return None
    return elevation


def hold_time_for(distance: float, height_diff: float = 0.0) -> Optional[float]:
    """Сколько секунд держать S, чтобы попасть в цель (None — цель недостижима)."""
    elevation = elevation_for(distance, height_diff)
    if elevation is None:
        return None
    return max(0.0, (TOP_ELEVATION - elevation) / ELEVATION_RATE)


def distance_at(hold_time: float) -> float:
    """Дистанция на ровной земле, на которую бьёт ствол после `hold_time` секунд зажатия S."""
    elevation = math.radians(max(LOWEST_ELEVATION, TOP_ELEVATION - ELEVATION_RATE * hold_time))
    vertical = MUZZLE_VELOCITY * math.sin(elevation)
    flight_time = (vertical + math.sqrt(vertical ** 2 + 2 * GRAVITY * LAUNCH_HEIGHT)) / GRAVITY
    return MUZZLE_VELOCITY * math.cos(elevation) * flight_time


# Границы округляются внутрь, чтобы каждая целая дистанция из диапазона была достижима
MIN_DISTANCE = math.ceil(distance_at(0))
MAX_DISTANCE = math.floor(distance_at((TOP_ELEVATION - LOWEST_ELEVATION) / ELEVATION_RATE))
MAX_MANUAL_DISTANCE_DIGITS = 4  # в поле ввода: до 4 цифр — дистанция, остальное — код сессии


@dataclass(frozen=True)
class Target:
    """Цель из SquadCalc. hold_time/distance равны None, если неизвестны или цель недостижима."""

    hold_time: Optional[float]
    bearing: Optional[float]
    distance: Optional[int]


def parse_targets(message: str) -> List[Target]:
    """Разбирает сообщение SquadCalc: по строке на цель, "1.25s | 123.4° | 1500m | +12m".

    Через сервер-посредник дистанция приходит всегда; четвёртое поле (перепад высот) таймеру не нужно
    и пропускается. Недостижимые цели приходят как "---" или "NaNs": у них hold_time = None.
    """
    targets = []
    for line in message.splitlines():
        parts = [part.strip() for part in line.split("|")]
        # Только значение с "s" — время; у других орудий SquadCalc шлёт мил или градусы без суффикса
        hold_time = _to_float(parts[0][:-1]) if parts[0].endswith("s") else None
        bearing = _to_float(parts[1].rstrip("°")) if len(parts) > 1 else None
        distance = _to_float(parts[2].rstrip("m")) if len(parts) > 2 else None
        targets.append(Target(hold_time, bearing, None if distance is None else round(distance)))
    return targets


def _to_float(text: str) -> Optional[float]:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


class Tracker:
    """Накапливает время зажатия S и сообщает, когда оно дошло до цели."""

    def __init__(self) -> None:
        self.held = 0.0
        self.target_time: Optional[float] = None
        self._reached = False

    def reset(self) -> None:
        """Возвращает ствол в верхнее положение: время и сигнал обнуляются."""
        self.held = 0.0
        self._reached = False

    def set_target(self, hold_time: Optional[float]) -> None:
        """Выбирает цель; если время уже вышло, сигнал не повторяется."""
        self.target_time = hold_time
        self._reached = hold_time is None or self.held >= hold_time

    def advance(self, elapsed: float, holding: bool) -> bool:
        """Добавляет `elapsed` секунд, если S зажата. Возвращает True один раз — в момент достижения цели."""
        if holding:
            self.held += elapsed
        if self._reached or self.target_time is None or self.held < self.target_time:
            return False
        self._reached = True
        return True


def normalize_code(text: str) -> Optional[str]:
    """Приводит введённый код ("abcd-2345") к виду сервера; None, если это не код сессии."""
    code = re.sub(r"[\s-]", "", text).upper()
    return code if CODE_PATTERN.match(code) else None


def load_code() -> Optional[str]:
    """Читает код, сохранённый при прошлом запуске."""
    try:
        return normalize_code(SESSION_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):  # нет файла или он не в UTF-8: код просто введут заново
        return None


def save_code(code: str) -> None:
    try:
        SESSION_FILE.write_text(code, encoding="utf-8")
    except OSError:
        pass  # не критично: код придётся ввести заново при следующем запуске


def encode_client_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Кадр клиента: по RFC 6455 клиент обязан маскировать данные случайным ключом."""
    length = len(payload)
    if length < 126:
        header = struct.pack(">BB", 0x80 | opcode, 0x80 | length)
    else:
        header = struct.pack(">BBH", 0x80 | opcode, 0x80 | 126, length)
    mask = os.urandom(4)
    return header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


class RelayClient:
    """Подключение к посреднику по коду сессии (WebSocket-клиент RFC 6455) с автопереподключением.

    Работает в своём потоке; результаты кладёт в очередь `events`: ("status", текст) и ("targets", [Target]).
    """

    def __init__(self, events: "queue.Queue", host: str, port: int) -> None:
        self.events = events
        self.host = host
        self.port = port
        self.loop = asyncio.new_event_loop()
        self._session: Optional["asyncio.Future"] = None

    def start(self) -> None:
        """Запускает цикл событий в фоновом потоке."""
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def set_code(self, code: str) -> None:
        """Подключается к сессии `code` (разрывая прежнюю). Можно вызывать из любого потока."""
        self.loop.call_soon_threadsafe(self._start_session, code)

    def _start_session(self, code: str) -> None:
        if self._session is not None:
            self._session.cancel()
        self._session = asyncio.ensure_future(self._keep_connected(code))

    async def _keep_connected(self, code: str) -> None:
        label = f"{code[:len(code) // 2]}-{code[len(code) // 2:]}"
        while True:
            try:
                await self._connect_once(code, label)
            except Exception:  # любой сбой соединения — повтор; отмена (CancelledError) сюда не попадает
                pass
            self.events.put(("status", f"{label} · нет связи, повтор через {RECONNECT_DELAY_SECONDS} с"))
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def _connect_once(self, code: str, label: str) -> None:
        self.events.put(("status", f"{label} · подключаемся…"))
        tls = ssl.create_default_context() if self.port == TLS_PORT else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, ssl=tls, server_hostname=self.host if tls else None),
            HANDSHAKE_TIMEOUT_SECONDS,
        )
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            writer.write(
                f"GET /relay/{code}?role=overlay HTTP/1.1\r\nHost: {self.host}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n".encode()
            )
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HANDSHAKE_TIMEOUT_SECONDS)
            status_line, *header_lines = head.decode("latin-1").split("\r\n")
            headers = {line.partition(":")[0].strip().lower(): line.partition(":")[2].strip() for line in header_lines}
            expected = base64.b64encode(hashlib.sha1((key + WEBSOCKET_GUID).encode()).digest()).decode()
            if " 101 " not in status_line or headers.get("sec-websocket-accept") != expected:
                raise ValueError(f"сервер отказал: {status_line}")
            await self._read_frames(reader, writer, label)
        finally:
            writer.close()

    async def _read_frames(self, reader, writer, label: str) -> None:
        text = bytearray()
        while True:
            first, second = await asyncio.wait_for(reader.readexactly(2), IDLE_TIMEOUT_SECONDS)
            opcode = first & 0x0F
            final = bool(first & 0x80)
            length = second & 0x7F
            if length == 126:
                (length,) = struct.unpack(">H", await reader.readexactly(2))
            elif length == 127:
                (length,) = struct.unpack(">Q", await reader.readexactly(8))
            payload = await reader.readexactly(length)

            if opcode == 0x8:  # close
                return
            if opcode == 0x9:  # ping
                writer.write(encode_client_frame(0xA, payload[:125]))
                await writer.drain()
            elif opcode in (0x0, 0x1):  # текст или продолжение фрагментированного сообщения
                text += payload
                if final:
                    self._handle_message(text.decode("utf-8", errors="replace"), label)
                    text.clear()

    def _handle_message(self, raw: str, label: str) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        if message.get("type") == "targets":
            self.events.put(("targets", parse_targets(message.get("text", ""))))
        elif message.get("type") == "peers":
            state = "SquadCalc подключён" if message.get("pages", 0) > 0 else "ждём SquadCalc"
            self.events.put(("status", f"{label} · {state}"))


def is_admin() -> bool:
    """Запущен ли процесс с правами администратора (вне Windows — всегда False)."""
    windll = getattr(ctypes, "windll", None)
    return bool(windll and windll.shell32.IsUserAnAdmin())


def relaunch_as_admin() -> bool:
    """Перезапускает скрипт с теми же аргументами от администратора (запрос UAC). True — запрос принят."""
    arguments = " ".join(f'"{argument}"' for argument in [os.path.abspath(sys.argv[0])] + sys.argv[1:])
    # ShellExecuteW возвращает значение больше 32 при успехе
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, arguments, None, 1) > 32


def make_key_reader() -> Callable[[int], bool]:
    """Опрос клавиш через GetAsyncKeyState (работает и когда окно игры в фокусе). Вне Windows клавиши недоступны."""
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return lambda virtual_key: False
    return lambda virtual_key: bool(windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)


class _KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MouseInput(ctypes.Structure):
    # Нужна только для размера объединения: SendInput сверяет sizeof(INPUT)
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", _KeyboardInput), ("mi", _MouseInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("union", _InputUnion)]


class KeyInjector:
    """Программное нажатие клавиши через SendInput (только Windows).

    Шлёт скан-коды, а не виртуальные коды: так нажатие видят игры, читающие клавиатуру
    напрямую. Скан-код берётся из текущей раскладки, поэтому работает и на русской.
    """

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    MAPVK_VK_TO_VSC = 0

    def __init__(self, virtual_key: int) -> None:
        self.user32 = ctypes.windll.user32
        self.scan_code = self.user32.MapVirtualKeyW(virtual_key, self.MAPVK_VK_TO_VSC)

    def _send(self, flags: int) -> None:
        keyboard_input = _KeyboardInput(0, self.scan_code, self.KEYEVENTF_SCANCODE | flags, 0, 0)
        event = _Input(self.INPUT_KEYBOARD, _InputUnion(ki=keyboard_input))
        self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))

    def press(self) -> None:
        self._send(0)

    def release(self) -> None:
        self._send(self.KEYEVENTF_KEYUP)


def hold_key(injector, seconds: float, cancel: threading.Event) -> None:
    """Зажимает клавишу ровно на `seconds` секунд (или пока не сработает `cancel`) и гарантированно отпускает."""
    injector.press()
    try:
        deadline = time.perf_counter() + seconds
        while not cancel.is_set():
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            if remaining > PRECISE_SPIN_SECONDS and cancel.wait(remaining - PRECISE_SPIN_SECONDS):
                return
    finally:
        injector.release()


def beep() -> None:
    """Короткий сигнал в отдельном потоке: Beep блокирует вызывающего на время звучания."""
    if winsound is not None:
        threading.Thread(target=winsound.Beep, args=(BEEP_FREQUENCY_HZ, BEEP_DURATION_MS), daemon=True).start()


class TimerWindow:
    """Оверлей поверх игры: цель, дистанция ствола сейчас и время зажатия S."""

    def __init__(
        self, root, events: "queue.Queue", read_key: Callable[[int], bool], relay: RelayClient, injector=None
    ) -> None:
        self.root = root
        self.events = events
        self.read_key = read_key
        self.relay = relay
        self.injector = injector
        self.auto_hold: Optional[threading.Thread] = None
        self.cancel_auto_hold = threading.Event()
        self.previous_auto_hold_key = False
        self.tracker = Tracker()
        self.target_text = "---"
        self.previous_w = False
        self.shown_keys = ""
        self.rights = "админ" if is_admin() else "не админ"
        self.last_tick = time.perf_counter()
        self._build()
        self.root.after(POLL_MS, self._tick)

    def _build(self) -> None:
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")

        topbar = tk.Frame(self.root, bg="#111111")
        topbar.pack(fill="x")
        self.status_label = tk.Label(topbar, text="запуск", fg="gray", bg="#111111", font=("Consolas", 9))
        self.status_label.pack(side="left", padx=5)
        close = tk.Label(topbar, text="✕", fg="red", bg="#111111", font=("Consolas", 14, "bold"), cursor="hand2")
        close.pack(side="right", padx=5)
        close.bind("<Button-1>", lambda event: self.root.destroy())
        for draggable in (topbar, self.status_label):
            draggable.bind("<ButtonPress-1>", self._start_drag)
            draggable.bind("<B1-Motion>", self._drag)

        entry_row = tk.Frame(self.root, bg="black")
        entry_row.pack()
        self.entry = tk.Entry(entry_row, width=6, font=("Consolas", 14))
        self.entry.pack(side="left")
        self.entry.bind("<Return>", lambda event: self._confirm())
        tk.Button(entry_row, text="✔", command=self._confirm).pack(side="left")

        self.target_label = tk.Label(self.root, font=("Consolas", 14), bg="black", fg="orange")
        self.target_label.pack()
        self.distance_label = tk.Label(self.root, font=("Consolas", 22), bg="black")
        self.distance_label.pack()
        self.time_label = tk.Label(self.root, font=("Consolas", 16), bg="black")
        self.time_label.pack()
        # Диагностика: показывает, видит ли скрипт нажатия (● нажата, ○ нет)
        self.keys_label = tk.Label(self.root, font=("Consolas", 9), bg="black", fg="gray")
        self.keys_label.pack()
        self._render()
        self._show_keys(False, False, False)

    def _start_drag(self, event) -> None:
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event) -> None:
        self.root.geometry(f"+{event.x_root - self.drag_offset[0]}+{event.y_root - self.drag_offset[1]}")

    def _confirm(self) -> None:
        """Поле ввода: до 4 цифр — дистанция в метрах (заменяет цель из SquadCalc до его следующего обновления),
        иначе — код сессии SquadCalc."""
        text = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        if text.isdigit() and len(text) <= MAX_MANUAL_DISTANCE_DIGITS:
            self._set_manual_distance(int(text))
            return
        code = normalize_code(text)
        if code is None:
            self.status_label.config(text="не код сессии и не дистанция")
            return
        save_code(code)
        self.relay.set_code(code)

    def _set_manual_distance(self, distance: int) -> None:
        hold_time = hold_time_for(distance)
        if hold_time is None:
            self.status_label.config(text=f"{distance} м вне дальности ({MIN_DISTANCE}-{MAX_DISTANCE})")
            return
        self._set_target(hold_time, f"{distance} м · {hold_time:.2f} s")

    def _set_target(self, hold_time: Optional[float], text: str) -> None:
        self.tracker.set_target(hold_time)
        self.target_text = text
        self._render()

    def _handle_events(self) -> None:
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                return
            if kind == "status":
                self.status_label.config(text=value)
            elif kind == "targets":
                self._use_newest(value)

    def _use_newest(self, targets: List[Target]) -> None:
        """SquadCalc присылает все цели на карте; берём последнюю поставленную. Пустой список снимает цель."""
        if not targets or targets[-1].hold_time is None:
            self._set_target(None, "---")
            return
        newest = targets[-1]
        distance = f"{newest.distance} м · " if newest.distance is not None else ""
        self._set_target(newest.hold_time, f"{distance}{newest.hold_time:.2f} s")

    def _tick(self) -> None:
        try:
            self._poll()
        except Exception as error:  # сбой одного такта не должен останавливать цикл молча
            self.status_label.config(text=f"ошибка: {error}")
            traceback.print_exc()
        self.root.after(POLL_MS, self._tick)

    def _poll(self) -> None:
        now = time.perf_counter()
        elapsed, self.last_tick = now - self.last_tick, now

        holding = self.read_key(VK_S)
        reset_pressed = self.read_key(VK_W)
        auto_hold_pressed = self.read_key(VK_AUTO_HOLD)
        self._show_keys(holding, reset_pressed, auto_hold_pressed)

        if reset_pressed and not self.previous_w:
            self.tracker.reset()
        self.previous_w = reset_pressed

        if auto_hold_pressed and not self.previous_auto_hold_key:
            self._toggle_auto_hold()
        self.previous_auto_hold_key = auto_hold_pressed

        if self.tracker.advance(elapsed, holding):
            beep()

        self._handle_events()
        self._render()

    def _show_keys(self, s_down: bool, w_down: bool, auto_hold_down: bool) -> None:
        text = " ".join(f"{name}{'●' if down else '○'}" for name, down in (("S", s_down), ("W", w_down), ("F8", auto_hold_down)))
        if text != self.shown_keys:
            self.shown_keys = text
            self.keys_label.config(text=f"{text} · {self.rights}", fg="lime" if "●" in text else "gray")

    def _toggle_auto_hold(self) -> None:
        """F8: зажимает S на оставшееся до цели время; если уже зажато — отпускает."""
        if self.auto_hold is not None and self.auto_hold.is_alive():
            self.cancel_auto_hold.set()
            return
        target_time = self.tracker.target_time
        if self.injector is None or target_time is None:
            return
        remaining = target_time - self.tracker.held
        if remaining <= 0:
            return
        self.cancel_auto_hold.clear()
        self.auto_hold = threading.Thread(
            target=hold_key, args=(self.injector, remaining, self.cancel_auto_hold), daemon=True
        )
        self.auto_hold.start()

    def _render(self) -> None:
        self.target_label.config(text=f"ЦЕЛЬ: {self.target_text}")
        if self.tracker.target_time is None:
            self.distance_label.config(text="ВВОД", fg="gray")
            self.time_label.config(text=f"{self.tracker.held:.3f} s", fg="gray")
            return
        self.distance_label.config(text=f"~{distance_at(self.tracker.held):.0f} м", fg="cyan")
        self.time_label.config(text=f"{self.tracker.held:.3f} s", fg="white")


def main() -> None:
    if tk is None:
        raise SystemExit("Нужен tkinter (в установщике Python Windows он есть по умолчанию).")
    parser = argparse.ArgumentParser(description="Таймер зажатия S для АГС-17, связанный со SquadCalc по коду сессии.")
    parser.add_argument("code", nargs="?", help="код сессии из SquadCalc (по умолчанию — сохранённый)")
    parser.add_argument("--admin", action="store_true", help="перезапустить от администратора (если игра запущена от админа)")
    parser.add_argument("--server", default=DEFAULT_SERVER, help=f"хост:порт посредника (по умолчанию {DEFAULT_SERVER})")
    arguments = parser.parse_args()
    if arguments.admin and getattr(ctypes, "windll", None) is not None and not is_admin():
        if relaunch_as_admin():
            return
        print("Запрос прав администратора отклонён, запускаем без них.")
    host, _, port = arguments.server.rpartition(":")
    if not host or not port.isdigit():
        parser.error("--server нужно указать как хост:порт, например tk104.duckdns.org:9910")

    events: "queue.Queue" = queue.Queue()
    relay = RelayClient(events, host, int(port))
    relay.start()
    code = normalize_code(arguments.code or "") or load_code()
    if code is None:
        events.put(("status", "введите код сессии из SquadCalc"))
    else:
        save_code(code)
        relay.set_code(code)

    windll = getattr(ctypes, "windll", None)
    injector = KeyInjector(VK_S) if windll is not None else None
    if windll is not None:
        windll.winmm.timeBeginPeriod(1)  # точность sleep ~1 мс вместо ~15 мс

    root = tk.Tk()
    window = TimerWindow(root, events, make_key_reader(), relay, injector)
    try:
        root.mainloop()
    finally:
        window.cancel_auto_hold.set()  # не оставить S зажатой при закрытии
        if window.auto_hold is not None:
            window.auto_hold.join(timeout=1)
        if windll is not None:
            windll.winmm.timeEndPeriod(1)


if __name__ == "__main__":
    main()
