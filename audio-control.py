import win32gui
import win32process
import psutil
import time
import serial
import json
import tkinter as tk
from tkinter import ttk
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

import threading
from queue import Queue
import sys
import os
import serial.tools.list_ports
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, ISimpleAudioVolume


def find_port():
    ports = serial.tools.list_ports.comports()
    return ports[0].device

def load_config():
    config_name = 'config.json'
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    config_path = os.path.join(base_path, config_name)

    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden der {config_name}: {e}")
        detected_port = find_port()
        return {
            "connection": {"port": detected_port, "baud_rate": 9600},
            "settings": {"step": 0.02, "flyout_time": 1.5, "sleep_time": 0.02},
            "channels": [ {"id": 1, "type": "master"}, {"id": 2, "type": "app", "target": "firefox.exe"}, {"id": 3, "type": "foreground"}, {"id": 4, "type": "app", "target": "discord.exe"} ]
        }

config = load_config()

COM_PORT = config['connection']['port']
BAUD_RATE = config['connection']['baud_rate']
VOL_STEP = config['settings']['step']
FLYOUT_TIME = config['settings']['flyout_time']
SLEEP_TIME = config['settings']['sleep_time']

CHANNELS: dict = {str(ch.get('id')): ch for ch in config.get('channels', [])}
MAPPED_APPS = [ch['target'].lower() for ch in CHANNELS.values() if ch.get('type') == 'app']

print(f"Konfiguration geladen. Aktive Kanäle: {list(CHANNELS.keys())}")


last_valid_foreground_exe = None

overlay_queue = Queue()


def overlay_thread_func():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#1c1c1c")

    win_width = 380

    app_text = tk.StringVar(value="")
    app_label = tk.Label(root, textvariable=app_text, bg="#1c1c1c", font=("Segoe UI", 16, "bold"))
    app_label.pack(fill="x", pady=(10, 2))

    vol_text = tk.StringVar(value="")
    vol_label = tk.Label(root, textvariable=vol_text, fg="#ffffff", bg="#1c1c1c", font=("Segoe UI", 14, "normal"))
    vol_label.pack(fill="x", pady=(2, 10))

    bar_style = ttk.Style()
    bar_style.theme_use('default')

    bar_var = tk.DoubleVar(value=0)
    vol_bar = ttk.Progressbar(root, variable=bar_var, maximum=100, length=200, mode='determinate')
    vol_bar.pack(pady=(5, 12), padx=20, fill="x")

    root.withdraw()
    hide_timer = None

    def hide_overlay():
        root.withdraw()

    def check_queue():
        nonlocal hide_timer
        while not overlay_queue.empty():
            app_name, vol_status, color = overlay_queue.get()

            app_text.set(app_name)
            app_label.config(fg=color)
            vol_text.set(f"Lautstärke: {vol_status}")

            numeric_volume = 0 if "STUMM" in vol_status else int(vol_status.replace("%", ""))
            bar_var.set(numeric_volume)

            bar_style.configure("TProgressbar", thickness=8, troughcolor='#2d2d2d', background=color,
                                bordercolor='#1c1c1c')
            vol_bar.config(style="TProgressbar")

            root.update_idletasks()

            win_height = root.winfo_reqheight()

            screen_width = root.winfo_screenwidth()
            x_pos = (screen_width - win_width) // 2
            y_pos = 50

            root.geometry(f"{win_width}x{win_height}+{x_pos}+{y_pos}")

            if not root.winfo_viewable():
                root.deiconify()

            if hide_timer:
                root.after_cancel(hide_timer)

            hide_timer = root.after(int(FLYOUT_TIME * 1000), hide_overlay)

        root.after(50, check_queue)

    GWL_EXSTYLE = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOPMOST = 0x00000008

    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOPMOST)

    root.after(50, check_queue)
    root.mainloop()


threading.Thread(target=overlay_thread_func, daemon=True).start()


def trigger_overlay(app_name, percent, color, muted=False):
    status = "STUMM" if muted else f"{percent}%"
    overlay_queue.put((app_name, status, color))



def get_device():
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


def vol_change(direction, color="green"):
    volume = get_device()
    current = volume.GetMasterVolumeLevelScalar()
    new_vol = min(current + VOL_STEP, 1.0) if direction == "UP" else max(current - VOL_STEP, 0.0)
    volume.SetMasterVolumeLevelScalar(new_vol, None)

    is_muted = volume.GetMute()
    trigger_overlay("Master-Audio", round(new_vol * 100), color, is_muted)


def app_vol_change(app_name, direction, color="cyan"):
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        if session.Process and session.Process.name().lower() == app_name.lower():
            volume = session._ctl.QueryInterface(ISimpleAudioVolume)
            current = volume.GetMasterVolume()
            new_vol = min(current + VOL_STEP, 1.0) if direction == "UP" else max(current - VOL_STEP, 0.0)
            volume.SetMasterVolume(new_vol, None)

            is_muted = volume.GetMute()
            trigger_overlay(session.Process.name(), round(new_vol * 100), color, is_muted)


def toggle_mute(app_name=None, color="cyan"):
    if app_name:
        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            if session.Process and session.Process.name().lower() == app_name.lower():
                vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                current_mute = vol.GetMute()
                vol.SetMute(not current_mute, None)
                trigger_overlay(session.Process.name(), round(vol.GetMasterVolume() * 100), color, not current_mute)
    else:
        vol = get_device()
        current_mute = vol.GetMute()
        vol.SetMute(not current_mute, None)
        trigger_overlay("Master-Audio", round(vol.GetMasterVolumeLevelScalar() * 100), color, not current_mute)


def is_app_volume_controllable(exe_name):
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        if session.Process and session.Process.name().lower() == exe_name:
            return True
    return False


def get_foreground_exe():
    global last_valid_foreground_exe
    hwnd = win32gui.GetForegroundWindow()
    if hwnd == 0:
        return last_valid_foreground_exe
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        proc = psutil.Process(pid)
        exe_name = proc.name().lower()
        if exe_name in MAPPED_APPS:
            return last_valid_foreground_exe
        elif is_app_volume_controllable(exe_name):
            last_valid_foreground_exe = exe_name
            return exe_name
        else:
            return last_valid_foreground_exe
    except psutil.NoSuchProcess:
        return last_valid_foreground_exe



try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
except serial.SerialException:
    ser = None
    print(f"Konnte {COM_PORT} nicht öffnen.")


while True:
    line = ""

    if ser is None or not ser.is_open:
        try:
            ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        except serial.SerialException:
            time.sleep(2)
            continue

    try:
        line = ser.readline().decode('utf-8').strip()
    except (serial.SerialException, AttributeError):
        if ser and ser.is_open:
            ser.close()
        ser = None

        while True:
            try:
                ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
                break
            except serial.SerialException:
                time.sleep(2)

    if not line:
        time.sleep(SLEEP_TIME)
        continue

    parts = line.split('_')
    if len(parts) >= 2:
        cmd_type = parts[0]
        ch_id = parts[-1]

        if ch_id in CHANNELS:
            ch = CHANNELS[ch_id]

            if ch['type'] == 'foreground':
                target_app = get_foreground_exe()
                print(target_app)
            else:
                target_app = ch.get('target')

            # Wir holen uns die Farbe aus dem aktuellen Kanal (Standard: weiß)
            ch_color = ch.get('color', 'white')

            if cmd_type == "VOL":
                direction = parts[1]
                if ch['type'] == 'master':
                    vol_change(direction, color=ch_color)
                elif target_app:
                    app_vol_change(target_app, direction, color=ch_color)
            elif cmd_type == "BUTTON":
                if ch['type'] == 'master':
                    toggle_mute(color=ch_color)
                elif target_app:
                    toggle_mute(target_app, color=ch_color)

    time.sleep(SLEEP_TIME)