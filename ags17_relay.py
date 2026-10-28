"""Сервер-посредник между SquadCalc и оверлеем-таймером АГС-17 (Python 3.8+, только стандартная библиотека).

SquadCalc (страница в браузере, роль "page") и оверлей на ПК с игрой (роль "overlay") подключаются
к одной сессии по коду и обмениваются данными через этот сервер, ничего не открывая локально:

    ws://<хост>/relay/<КОД>?role=page      страница отправляет текст целей, по строке на цель:
                                           "<секунды>s | <азимут>° | <дистанция>m | <перепад высот>m"
                                           (формат SquadMortarOverlay плюс перепад со знаком, "+12m";
                                           сервер текст не разбирает, а пересылает как есть)
    ws://<хост>/relay/<КОД>?role=overlay   оверлей получает цели; последнее состояние присылается сразу
    http://<хост>/relay/health             проверка доступности (200 "ok")

Сервер -> клиент, JSON в текстовых кадрах:
    {"type": "targets", "text": "<последнее сообщение страницы>"}   (только оверлею)
    {"type": "peers", "pages": N, "overlays": M}                    (всем участникам сессии при изменениях)

Код сессии — это и есть секрет: любой, кто его знает, может читать и подменять цели этой сессии.
Состояние хранится только в памяти; пустые сессии удаляются через сутки.

Запускается за обратным прокси (Caddy), который терминирует HTTP и пробрасывает WebSocket:
    python3 ags17_relay.py [--host 127.0.0.1] [--port 9911]
"""

import argparse
import asyncio
import base64
import hashlib
import json
import re
import struct
import time
from typing import Dict, Optional, Set
from urllib.parse import parse_qs, urlsplit

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455, раздел 1.3
CODE_PATTERN = re.compile(r"^[A-Z0-9]{6,16}$")
ROLES = ("page", "overlay")

MAX_MESSAGE_BYTES = 64 * 1024
MAX_HEAD_BYTES = 8 * 1024
MAX_SESSIONS = 1000
MAX_CONNECTIONS_PER_SESSION = 10
MAX_CONNECTIONS_PER_IP = 40
MAX_CONNECTIONS = 2000
MAX_MESSAGES_PER_SECOND = 20
MESSAGE_BURST = 40
HANDSHAKE_TIMEOUT_SECONDS = 10
SEND_TIMEOUT_SECONDS = 5  # получатель, не читающий дольше, отключается: иначе он тормозит всю сессию
PING_INTERVAL_SECONDS = 25
IDLE_TIMEOUT_SECONDS = 75  # на целый кадр (в том числе pong); дольше — соединение считается мёртвым
SESSION_TTL_SECONDS = 24 * 60 * 60
CLEANUP_INTERVAL_SECONDS = 10 * 60


def encode_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Кадр сервера (без маски): FIN + opcode, длина в 7/16/64 бит."""
    length = len(payload)
    if length < 126:
        header = struct.pack(">BB", 0x80 | opcode, length)
    elif length < 1 << 16:
        header = struct.pack(">BBH", 0x80 | opcode, 126, length)
    else:
        header = struct.pack(">BBQ", 0x80 | opcode, 127, length)
    return header + payload


def unmask(data: bytes, mask: bytes) -> bytes:
    """Снимает маску клиента (RFC 6455, 5.3) через целочисленный XOR: поразрядный цикл на Python тормозит весь сервер."""
    if not data:
        return data
    key = (mask * (len(data) // 4 + 1))[: len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(len(data), "big")


class Connection:
    """Один участник сессии."""

    def __init__(self, writer: asyncio.StreamWriter, role: str) -> None:
        self.writer = writer
        self.role = role

    async def send(self, opcode: int, payload: bytes = b"") -> bool:
        """Отправляет кадр; False (и соединение сброшено), если получатель не принимает данные."""
        try:
            self.writer.write(encode_frame(opcode, payload))
            await asyncio.wait_for(self.writer.drain(), SEND_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, ConnectionError, OSError):
            self.writer.transport.abort()  # сбрасывает буфер и освобождает ждущий drain() других задач
            return False
        return True

    async def send_json(self, message: dict) -> bool:
        return await self.send(0x1, json.dumps(message, ensure_ascii=False).encode("utf-8"))


class Session:
    """Участники одного кода и последнее сообщение страницы."""

    def __init__(self) -> None:
        self.last_text: Optional[str] = None
        self.connections: Set[Connection] = set()
        self.touched = time.monotonic()

    def members(self, role: str):
        return [connection for connection in self.connections if connection.role == role]

    async def broadcast_peers(self) -> None:
        message = {"type": "peers", "pages": len(self.members("page")), "overlays": len(self.members("overlay"))}
        await asyncio.gather(*(connection.send_json(message) for connection in list(self.connections)))


class Relay:
    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}
        self.connection_count = 0
        self.connections_by_ip: Dict[str, int] = {}

    async def serve(self, host: str, port: int) -> None:
        server = await asyncio.start_server(self._handle, host, port, limit=MAX_HEAD_BYTES)
        asyncio.ensure_future(self._cleanup_forever())
        async with server:
            await server.serve_forever()

    async def _cleanup_forever(self) -> None:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            expired = [
                code
                for code, session in self.sessions.items()
                if not session.connections and time.monotonic() - session.touched > SESSION_TTL_SECONDS
            ]
            for code in expired:
                del self.sessions[code]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._serve_client(reader, writer)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError, OSError):
            pass
        finally:
            writer.close()

    async def _serve_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HANDSHAKE_TIMEOUT_SECONDS)
        request_line, *header_lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in header_lines:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()

        parts = request_line.split(" ")
        if len(parts) != 3 or parts[0] != "GET":
            await self._respond(writer, "405 Method Not Allowed")
            return
        url = urlsplit(parts[1])

        if url.path == "/relay/health":
            await self._respond(writer, "200 OK", b"ok")
            return

        route = re.fullmatch(r"/relay/([A-Za-z0-9]+)", url.path)
        role = parse_qs(url.query).get("role", [""])[0]
        is_upgrade = headers.get("upgrade", "").lower() == "websocket" and "sec-websocket-key" in headers
        if route is None or role not in ROLES or not is_upgrade:
            await self._respond(writer, "400 Bad Request")
            return
        code = route.group(1).upper()
        if not CODE_PATTERN.match(code):
            await self._respond(writer, "400 Bad Request")
            return

        # За Caddy все соединения приходят с 127.0.0.1: настоящий адрес берётся из X-Forwarded-For
        peer = writer.get_extra_info("peername")
        client_ip = headers.get("x-forwarded-for", "").split(",")[0].strip() or (peer[0] if peer else "")

        session = self.sessions.get(code)
        if (
            self.connection_count >= MAX_CONNECTIONS
            or self.connections_by_ip.get(client_ip, 0) >= MAX_CONNECTIONS_PER_IP
            or (session is not None and len(session.connections) >= MAX_CONNECTIONS_PER_SESSION)
            or (session is None and not self._make_room_for_session())
        ):
            await self._respond(writer, "503 Service Unavailable")
            return

        accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + WEBSOCKET_GUID).encode()).digest())
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
        )
        await writer.drain()

        # Сессия создаётся только после успешного рукопожатия: оборванные попытки не занимают места
        session = self.sessions.setdefault(code, Session())
        connection = Connection(writer, role)
        session.connections.add(connection)
        self.connection_count += 1
        self.connections_by_ip[client_ip] = self.connections_by_ip.get(client_ip, 0) + 1
        pinger = asyncio.ensure_future(self._ping_forever(connection))
        try:
            await session.broadcast_peers()
            if role == "overlay" and session.last_text is not None:
                await connection.send_json({"type": "targets", "text": session.last_text})
            await self._read_frames(reader, connection, session)
        finally:
            pinger.cancel()
            session.connections.discard(connection)
            session.touched = time.monotonic()
            self.connection_count -= 1
            self.connections_by_ip[client_ip] -= 1
            if self.connections_by_ip[client_ip] == 0:
                del self.connections_by_ip[client_ip]
            if not session.connections and session.last_text is None and self.sessions.get(code) is session:
                del self.sessions[code]  # пустая сессия без данных никому не нужна
            await session.broadcast_peers()

    def _make_room_for_session(self) -> bool:
        """Для новой сессии нужно место: при переполнении вытесняется самая давняя сессия без участников."""
        if len(self.sessions) < MAX_SESSIONS:
            return True
        idle = [(session.touched, code) for code, session in self.sessions.items() if not session.connections]
        if not idle:
            return False
        del self.sessions[min(idle)[1]]
        return True

    @staticmethod
    async def _respond(writer: asyncio.StreamWriter, status: str, body: bytes = b"") -> None:
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
        )
        await writer.drain()

    @staticmethod
    async def _ping_forever(connection: Connection) -> None:
        while await connection.send(0x9):
            await asyncio.sleep(PING_INTERVAL_SECONDS)

    async def _read_frames(self, reader: asyncio.StreamReader, connection: Connection, session: Session) -> None:
        text = bytearray()
        allowance = float(MESSAGE_BURST)
        last_frame = time.monotonic()
        while True:
            frame = await asyncio.wait_for(self._read_frame(reader), IDLE_TIMEOUT_SECONDS)
            if frame is None:
                return
            opcode, final, payload = frame

            now = time.monotonic()
            allowance = min(float(MESSAGE_BURST), allowance + (now - last_frame) * MAX_MESSAGES_PER_SECOND)
            last_frame = now
            if allowance < 1:
                return  # слишком частые кадры: отключаем
            allowance -= 1

            if opcode == 0x8:  # close
                await connection.send(0x8)
                return
            if opcode == 0x9:  # ping
                await connection.send(0xA, payload[:125])
            elif opcode in (0x0, 0x1):  # текст или продолжение фрагментированного сообщения
                text += payload
                if len(text) > MAX_MESSAGE_BYTES:
                    return
                if final:
                    message = text.decode("utf-8", errors="replace")
                    text.clear()
                    await self._on_message(connection, session, message)

    @staticmethod
    async def _read_frame(reader: asyncio.StreamReader):
        """Читает один кадр клиента: (opcode, fin, данные) или None, если кадр недопустим."""
        first, second = await reader.readexactly(2)
        if not second & 0x80:  # клиент обязан маскировать кадры (RFC 6455, 5.1)
            return None
        length = second & 0x7F
        if length == 126:
            (length,) = struct.unpack(">H", await reader.readexactly(2))
        elif length == 127:
            (length,) = struct.unpack(">Q", await reader.readexactly(8))
        if length > MAX_MESSAGE_BYTES:
            return None
        mask = await reader.readexactly(4)
        payload = unmask(await reader.readexactly(length), mask)
        return first & 0x0F, bool(first & 0x80), payload

    @staticmethod
    async def _on_message(connection: Connection, session: Session, message: str) -> None:
        if connection.role != "page":
            return
        session.last_text = message
        session.touched = time.monotonic()
        await asyncio.gather(
            *(overlay.send_json({"type": "targets", "text": message}) for overlay in session.members("overlay"))
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9911)
    arguments = parser.parse_args()
    asyncio.run(Relay().serve(arguments.host, arguments.port))


if __name__ == "__main__":
    main()
