import tkinter as tk
import time
import threading
import ctypes
import winsound

# ====== КЛАВИШИ ======
user32 = ctypes.windll.user32

def key_down(vk):
    return user32.GetAsyncKeyState(vk) & 0x8000

VK_S = 0x53
VK_W = 0x57

# ================= ТАБЛИЦА =================
TABLE = [
    (0.000, 280), (0.055, 325), (0.100, 350), (0.150, 375),
    (0.200, 400), (0.250, 425), (0.300, 450), (0.320, 475),
    (0.350, 500), (0.390, 525), (0.420, 550), (0.480, 575),
    (0.520, 600), (0.560, 625), (0.610, 650), (0.650, 675),
    (0.690, 700), (0.730, 725), (0.770, 750), (0.830, 775),
    (0.880, 800), (0.920, 825), (0.950, 850), (1.000, 875),
    (1.050, 900), (1.090, 925), (1.160, 950), (1.195, 975),
    (1.240, 1000), (1.290, 1025), (1.330, 1050), (1.385, 1075),
    (1.430, 1100), (1.470, 1125), (1.540, 1150), (1.575, 1175),
    (1.650, 1200), (1.696, 1225), (1.760, 1250), (1.804, 1275),
    (1.860, 1300), (1.905, 1325), (1.980, 1350), (2.032, 1375),
    (2.070, 1400), (2.160, 1425), (2.210, 1450), (2.272, 1475),
    (2.340, 1500), (2.410, 1525), (2.450, 1550), (2.540, 1575),
    (2.600, 1600), (2.670, 1625), (2.730, 1650), (2.826, 1675),
    (2.920, 1700), (3.010, 1725), (3.120, 1750), (3.193, 1775),
    (3.300, 1800), (3.430, 1825), (3.550, 1850), (3.700, 1875),
    (3.840, 1900), (3.950, 1915), (4.100, 1930),
]

def time_by_distance(dist):
    for i in range(len(TABLE)-1):
        t1, d1 = TABLE[i]
        t2, d2 = TABLE[i+1]
        if d1 <= dist <= d2:
            k = (dist - d1) / (d2 - d1)
            return t1 + k * (t2 - t1)
    return TABLE[-1][0]

def ms_per_meter(dist):
    for i in range(len(TABLE)-1):
        t1, d1 = TABLE[i]
        t2, d2 = TABLE[i+1]
        if d1 <= dist <= d2:
            return (t2 - t1) * 1000 / (d2 - d1)
    return 1

# ================= СОСТОЯНИЕ =================
current_time = 0.0
current_distance = 280

target_distance = None
target_time = 0

confirmed = False
beeped = False
prev_w = False

# ================= СБРОС =================
def reset():
    global current_time, current_distance, beeped
    current_time = 0.0
    current_distance = 280
    beeped = False

# ================= ЛОГИКА =================
def loop():
    global current_time, current_distance, beeped, prev_w

    last = time.time()

    while True:
        now = time.time()
        dt = now - last
        last = now

        s = key_down(VK_S)
        w = key_down(VK_W)

        if w and not prev_w:
            reset()
        prev_w = w

        if confirmed and s:
            current_time += dt
            current_distance += (dt * 1000 / ms_per_meter(current_distance))

        if confirmed and not beeped and current_time >= target_time:
            winsound.Beep(1200, 120)
            beeped = True

        update_ui()
        time.sleep(0.005)

# ================= UI =================
root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
root.configure(bg="black")

frame = tk.Frame(root, bg="black")
# ================= ВЕРХНЯЯ ПАНЕЛЬ =================
topbar = tk.Frame(root, bg="#111111")
topbar.pack(fill="x")

# ===== КРЕСТИК =====
def close_app():
    root.quit()
    root.destroy()

close_btn = tk.Label(
    topbar,
    text="✕",
    fg="red",
    bg="#111111",
    font=("Consolas", 14, "bold"),
    cursor="hand2"
)

close_btn.pack(side="right", padx=5)

close_btn.bind("<Button-1>", lambda e: close_app())
frame.pack()

entry = tk.Entry(frame, width=6, font=("Consolas", 14))
entry.pack(side="left")

def confirm():
    global target_distance, target_time, confirmed
    try:
        target_distance = int(entry.get())
        target_time = time_by_distance(target_distance)
        confirmed = True
        entry.delete(0, tk.END)  # 🔥 очистка поля
        update_ui()
    except:
        pass

btn = tk.Button(frame, text="✔", command=confirm)
btn.pack(side="left")

# 🎯 ЦЕЛЬ
lbl_target = tk.Label(root, font=("Consolas", 14), bg="black", fg="orange")
lbl_target.pack()

# 📏 ТЕКУЩЕЕ
lbl_dist = tk.Label(root, font=("Consolas", 22), bg="black")
lbl_dist.pack()

# ⏱ ВРЕМЯ
lbl_time = tk.Label(root, font=("Consolas", 16), bg="black")
lbl_time.pack()

def update_ui():
    if not confirmed:
        lbl_target.config(text="TARGET: ---")
        lbl_dist.config(text="ВВОД", fg="gray")
        lbl_time.config(text="0.000", fg="gray")
    else:
        lbl_target.config(text=f"TARGET: {target_distance} м")
        lbl_dist.config(text=f"{current_distance:.0f} м", fg="cyan")
        lbl_time.config(text=f"{current_time:.3f} s", fg="white")

threading.Thread(target=loop, daemon=True).start()
root.mainloop()
