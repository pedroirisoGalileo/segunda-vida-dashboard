#!/usr/bin/env python3
import fcntl
import glob
import json
import mmap
import os
import signal
import struct
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1024, 600
FB = "/dev/fb0"
TTY = "/dev/tty1"
KDSETMODE, KD_TEXT, KD_GRAPHICS = 0x4B3A, 0x00, 0x01
INPUT_EVENT = struct.Struct("llHHI")
EV_KEY, KEY_F2, KEY_F10 = 1, 60, 68
BG, CARD, EDGE = "#07100f", "#0e1a18", "#244239"
INK, MUTED, GREEN, AMBER, RED = "#effff8", "#829a91", "#58f0a5", "#f4bd58", "#ff626b"
THEMES = {
    "original": ("#07100f", "#0e1a18", "#244239", "#effff8", "#829a91", "#58f0a5", "#f4bd58", "#ff626b"),
    "oceano": ("#06101a", "#0b1b29", "#1c4055", "#eef9ff", "#7895a5", "#45c8ff", "#ffd166", "#ff6577"),
    "ambar": ("#120d05", "#211709", "#4b3515", "#fff4da", "#a58d67", "#ffb52e", "#ffe08a", "#ff6b45"),
    "violeta": ("#0d0815", "#191025", "#3c2755", "#fbf2ff", "#9b87aa", "#c98cff", "#ffd166", "#ff668f"),
    "rojo": ("#120707", "#211010", "#522525", "#fff3f0", "#a78984", "#ff6659", "#ffc857", "#ff304f"),
    "monocromo": ("#080a09", "#131615", "#343a37", "#f1f4f2", "#8d9691", "#c8d0cc", "#e1e5e3", "#ffffff"),
}
CUSTOM_KEYS = ("background", "card", "edge", "text", "muted", "accent", "warning", "danger")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
running = True
SCREEN_STATE_FILE = "/var/lib/dashboard/screen_state.json"
FORCED_REST_SECONDS = 300


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


F10, F12, F14, F18, F22, F46, F60 = font(10), font(12), font(14), font(18, True), font(22, True), font(46, True), font(60, True)
F30, F78, F118 = font(30, True), font(78, True), font(118, True)


def valid_color(value, fallback):
    value = str(value).strip().lower()
    return value if len(value) == 7 and value[0] == "#" and all(c in "0123456789abcdef" for c in value[1:]) else fallback


def apply_theme(data):
    global BG, CARD, EDGE, INK, MUTED, GREEN, AMBER, RED
    settings = (data or {}).get("settings", {})
    name = str(settings.get("theme", "original")).lower()
    colors = THEMES.get(name, THEMES["original"])
    if name == "personalizado":
        source = settings.get("custom_colors") or {}
        colors = tuple(valid_color(source.get(key, fallback), fallback)
                       for key, fallback in zip(CUSTOM_KEYS, THEMES["original"]))
    BG, CARD, EDGE, INK, MUTED, GREEN, AMBER, RED = colors


def dim_color(value, factor):
    red, green, blue = (int(value[index:index + 2], 16) for index in (1, 3, 5))
    return f"#{round(red * factor):02x}{round(green * factor):02x}{round(blue * factor):02x}"


def stop(*_):
    global running
    running = False


def keyboard_device():
    for path in glob.glob("/dev/input/by-path/*-event-kbd"):
        try:
            return os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            pass
    return None


def pressed_key(keyboard):
    if keyboard is None:
        return None
    try:
        raw = os.read(keyboard, INPUT_EVENT.size * 16)
        for _, _, kind, code, value in INPUT_EVENT.iter_unpack(
                raw[:len(raw) // INPUT_EVENT.size * INPUT_EVENT.size]):
            if kind == EV_KEY and value == 1:
                return code
        return None
    except BlockingIOError:
        return None


def configuration_menu(tty):
    fcntl.ioctl(tty, KDSETMODE, KD_TEXT)
    try:
        menu = Path(__file__).resolve().with_name("config_menu.py")
        subprocess.run(["/usr/bin/python3", str(menu)],
                       stdin=tty, stdout=tty, stderr=tty, check=False)
    finally:
        fcntl.ioctl(tty, KDSETMODE, KD_GRAPHICS)


def screen_history():
    try:
        with open(SCREEN_STATE_FILE, "r", encoding="utf-8") as source:
            return json.load(source)
    except Exception:
        return {"sleepCount": 0, "wakeCount": 0, "state": "awake",
                "lastSleep": None, "lastWake": None, "lastWakeDba": None}


def record_screen(history, state_name, level_dba):
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    history["state"] = state_name
    if state_name == "asleep":
        history["sleepCount"] = int(history.get("sleepCount", 0)) + 1
        history["lastSleep"] = timestamp
    else:
        history["wakeCount"] = int(history.get("wakeCount", 0)) + 1
        history["lastWake"] = timestamp
        history["lastWakeDba"] = round(level_dba, 1)
    temporary = SCREEN_STATE_FILE + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as target:
            json.dump(history, target, ensure_ascii=False, indent=2)
        os.replace(temporary, SCREEN_STATE_FILE)
    except OSError:
        pass


def status():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8088/api/status", timeout=2) as response:
            return json.load(response)
    except Exception:
        return None


def text(draw, xy, value, fill=None, f=F14, anchor=None):
    if fill is None:
        fill = INK
    draw.text(xy, str(value), font=f, fill=fill, anchor=anchor)


def card(draw, box, eyebrow, title):
    draw.rounded_rectangle(box, 18, fill=CARD, outline=EDGE, width=1)
    x, y = box[0] + 18, box[1] + 16
    text(draw, (x, y), eyebrow, GREEN, F10)
    text(draw, (x, y + 18), title, INK, F18)


def weather_icon(draw, x, y, code, is_day, background=None):
    if background is None:
        background = CARD
    if code is None:
        text(draw, (x, y), "?", MUTED, F46)
        return
    if code <= 2 and is_day:
        cx, cy, radius = x + 28, y + 27, 17
        draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=AMBER)
        for dx, dy in ((0,-28),(0,28),(-28,0),(28,0),(-20,-20),(20,-20),(-20,20),(20,20)):
            draw.line((cx + dx*.70, cy + dy*.70, cx + dx, cy + dy), fill=AMBER, width=3)
    elif code <= 2:
        draw.ellipse((x + 8, y + 3, x + 48, y + 43), fill=AMBER)
        draw.ellipse((x + 23, y - 3, x + 56, y + 34), fill=background)
        for sx, sy in ((61,6),(72,24),(55,35)):
            draw.ellipse((x+sx, y+sy, x+sx+4, y+sy+4), fill=MUTED)
    if code > 0:
        cloud = INK if is_day else MUTED
        draw.ellipse((x + 18, y + 23, x + 51, y + 50), fill=cloud)
        draw.ellipse((x + 38, y + 13, x + 75, y + 50), fill=cloud)
        draw.ellipse((x + 58, y + 27, x + 84, y + 51), fill=cloud)
        draw.rounded_rectangle((x + 15, y + 34, x + 86, y + 53), 9, fill=cloud)
    if 51 <= code <= 99:
        for i in range(4):
            draw.line((x + 24 + i*15, y + 60, x + 19 + i*15, y + 72), fill=GREEN, width=3)


def meter(draw, x, top, bottom, value, label):
    text(draw, (x + 22, top - 25), label, INK, F14, "mm")
    count, gap = 28, 4
    seg_h = (bottom - top - gap * (count - 1)) / count
    lit = round(max(0, min(1, value or 0)) * count)
    for n in range(count):
        level = count - n
        color = dim_color(EDGE, 0.65)
        if level <= lit:
            color = RED if level > 24 else AMBER if level > 18 else GREEN
        y = top + n * (seg_h + gap)
        draw.rectangle((x, int(y), x + 44, int(y + seg_h)), fill=color)


def render(data):
    apply_theme(data)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    text(d, (22, 28), "P", BG, F22)
    d.rounded_rectangle((17, 17, 63, 63), 12, fill=GREEN)
    text(d, (40, 40), "P", BG, F22, "mm")
    text(d, (76, 22), "SEGUNDA VIDA", GREEN, F10)
    text(d, (76, 40), "Panel ambiental", INK, F18)
    now = datetime.now()
    text(d, (512, 38), now.strftime("%H:%M"), INK, F46, "mm")
    text(d, (512, 72), now.strftime("%d/%m/%Y"), MUTED, F12, "mm")

    card(d, (22, 102, 370, 550), "AMBIENTE", "Nivel sonoro")
    location = (data or {}).get("settings", {}).get("location", "Mi localidad")
    card(d, (383, 102, 687, 393), location.upper()[:32], "Clima exterior")
    card(d, (700, 102, 1002, 393), "CONECTIVIDAD", "Red doméstica")
    d.rounded_rectangle((383, 405, 1002, 550), 18, fill=CARD, outline=EDGE, width=1)

    if not data:
        text(d, (512, 300), "Esperando datos…", AMBER, F22, "mm")
        return im

    sys = data["system"]
    text(d, (76, 67), f"CPU {sys['cpu']}%   MEM {sys['memory']}%   DISCO {sys['disk']}%", MUTED, F10)

    audio = data["audio"]
    meter(d, 123, 195, 480, audio.get("left"), "L")
    meter(d, 227, 195, 480, audio.get("right"), "R")
    for db in (90, 80, 70, 60, 50, 40, 30):
        level = max(0, min(1, (db - 30) / 60))
        y = round(480 - level * (480 - 195))
        d.line((176, y, 218, y), fill=EDGE, width=1)
        text(d, (197, y - 1), str(db), RED if db >= 90 else AMBER if db >= 70 else MUTED, F10, "mm")
    current_dba = max(audio.get("dbaLeft", 0), audio.get("dbaRight", 0))
    category = "Ruido elevado" if current_dba >= 70 else "Ambiente moderado" if current_dba >= 55 else "Ambiente tranquilo"
    text(d, (42, 501), f"{current_dba:.1f} dBA", INK, F18)
    text(d, (42, 525), category, MUTED, F12)

    w = data["weather"]
    is_day = w.get("isDay")
    if is_day is None:
        is_day = 7 <= datetime.now().hour < 19
    # Zona principal del clima: dos mitades equilibradas, con icono ampliado.
    icon = Image.new("RGB", (100, 82), CARD)
    weather_icon(ImageDraw.Draw(icon), 4, 4, w.get("code"), is_day)
    icon = icon.resize((145, 119), Image.Resampling.LANCZOS)
    im.paste(icon, (393, 174))
    text(d, (610, 217), "--°" if w.get("temperature") is None else f"{round(w['temperature'])}°", INK, F60, "mm")
    descriptions = {0:"Despejado",1:"Mayormente despejado",2:"Algo nublado",3:"Nublado"}
    desc = descriptions.get(w.get("code"), "Lluvia" if (w.get("code") or 0) >= 51 else "Variable")
    text(d, (535, 282), f"Exterior · {desc}", MUTED, F12, "mm")
    text(d, (405, 305), "Máx / mín", MUTED, F10)
    high, low = w.get("high"), w.get("low")
    weather_range = "--° / --°" if high is None or low is None else f"{round(high)}° / {round(low)}°"
    text(d, (405, 325), weather_range, INK, F18)
    sensor = data["sensor"]
    text(d, (540, 305), "Interior · NanoPi", MUTED, F10)
    inside = "--"
    if sensor.get("temperature") is not None:
        inside = f"{sensor['temperature']:.1f}° · {round(sensor.get('humidity',0))}%".replace(".", ",")
    text(d, (540, 325), inside, INK, F18)

    rw, wan = data["routerWan"], data["wan"]
    text(d, (720, 180), "↓ WAN AHORA", MUTED, F10)
    text(d, (720, 200), f"{rw.get('download',0):.2f} Mbps", INK, F18)
    text(d, (860, 180), "↑ WAN AHORA", MUTED, F10)
    text(d, (860, 200), f"{rw.get('upload',0):.2f} Mbps", INK, F18)
    text(d, (720, 242), f"IP  {wan.get('ip') or '--'}", GREEN, F10)
    isp = wan.get("isp") or "--"
    text(d, (720, 260), f"ISP {isp[:36]}", GREEN, F10)
    test = "pendiente" if wan.get("download") is None else f"↓ {wan['download']} · ↑ {wan['upload']} Mbps"
    text(d, (720, 280), f"TEST {test}", MUTED, F10)
    devices = data["network"].get("devices") or [
        {"name":"Router", "online":data["network"]["router"]},
        {"name":"NanoPi", "online":data["network"]["nanopi"]},
        {"name":"Internet", "online":data["network"]["internet"]},
    ]
    for i, device in enumerate(devices[:6]):
        name, ok = device["name"], device["online"]
        column, row = i // 3, i % 3
        x, y = 720 + column * 140, 315 + row * 24
        if ok:
            d.ellipse((x - 1, y - 2, x + 13, y + 12), fill=GREEN)
        else:
            d.line((x, y, x + 10, y + 10), fill=RED, width=3)
            d.line((x + 10, y, x, y + 10), fill=RED, width=3)
        text(d, (x + 17, y - 2), name[:12], INK, F10)

    spectrum = audio.get("spectrum") or [-80] * 31
    chart_left, chart_top, chart_right, chart_bottom = 405, 420, 980, 524
    bar_step = (chart_right - chart_left) / 31
    bar_width = max(4, int(bar_step - 3))
    for i, level_db in enumerate(spectrum[:31]):
        # Escala visual de -55 a -5 dBFS: el ruido ambiente queda en el tercio inferior.
        level = max(0.0, min(1.0, (level_db + 55.0) / 50.0))
        x = int(chart_left + i * bar_step)
        y = int(chart_bottom - level * (chart_bottom - chart_top))
        color = RED if level_db > -10 else AMBER if level_db > -24 else GREEN
        d.rounded_rectangle((x, y, x + bar_width, chart_bottom), 2, fill=color)
    for db in (-40, -20):
        y = int(chart_bottom - ((db + 55) / 50) * (chart_bottom - chart_top))
        d.line((chart_left, y, chart_right, y), fill=EDGE, width=1)
    for i, label in ((0,"20"),(7,"100"),(13,"400"),(17,"1k"),(23,"4k"),(30,"20k")):
        x = int(chart_left + i * bar_step + bar_width / 2)
        text(d, (x, 533), label, MUTED, F10, "mm")
    text(d, (22, 578), "●  SISTEMA LOCAL · SIN XORG", GREEN, F10)
    return im


def short_time(value):
    if not value:
        return "--:--"
    return str(value).rsplit("T", 1)[-1][:5]


def rest_date(now):
    days = ("LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM")
    months = ("ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
              "JUL", "AGO", "SEP", "OCT", "NOV", "DIC")
    return f"{days[now.weekday()]} {now.day:02d} {months[now.month - 1]}."


def render_rest(data):
    """Pantalla oscura informativa; nunca produce un framebuffer negro uniforme."""
    apply_theme(data)
    background = dim_color(BG, 0.38)
    primary, secondary, faint = dim_color(INK, 0.48), dim_color(MUTED, 0.58), dim_color(EDGE, 0.72)
    image = Image.new("RGB", (W, H), background)
    draw = ImageDraw.Draw(image)
    now = datetime.now()
    weather = (data or {}).get("weather", {})
    sensor = (data or {}).get("sensor", {})

    draw.line((512, 58, 512, 542), fill=dim_color(EDGE, 0.55), width=1)

    sunrise, sunset = short_time(weather.get("sunrise")), short_time(weather.get("sunset"))
    text(draw, (256, 82), f"☀  AMANECE {sunrise}     ☾  ANOCHECE {sunset}", faint, F14, "mm")
    text(draw, (256, 265), now.strftime("%H:%M"), primary, F118, "mm")
    text(draw, (256, 390), rest_date(now), secondary, F30, "mm")

    is_day = weather.get("isDay")
    if is_day is None:
        is_day = 7 <= now.hour < 19
    icon = Image.new("RGB", (110, 88), background)
    weather_icon(ImageDraw.Draw(icon), 8, 7, weather.get("code"), is_day, background)
    icon = icon.point(lambda value: round(value * 0.52))
    icon = icon.resize((176, 141), Image.Resampling.LANCZOS)
    image.paste(icon, (565, 145))
    outside = "--°" if weather.get("temperature") is None else f"{round(weather['temperature'])}°"
    text(draw, (850, 220), outside, primary, F78, "mm")

    inside = "--°" if sensor.get("temperature") is None else f"{sensor['temperature']:.1f}°".replace(".", ",")
    high = "--°" if weather.get("high") is None else f"{round(weather['high'])}°"
    low = "--°" if weather.get("low") is None else f"{round(weather['low'])}°"
    for x, label, value in ((610, "INTERIOR", inside), (770, "MÁX", high), (920, "MÍN", low)):
        text(draw, (x, 375), label, faint, F12, "mm")
        text(draw, (x, 420), value, secondary, F30, "mm")
    return image


def write_frame(memory, image):
    memory.seek(0)
    memory.write(image.tobytes("raw", "BGRX"))
    memory.flush()


def main():
    tty = os.open(TTY, os.O_RDWR)
    fb = os.open(FB, os.O_RDWR)
    keyboard = keyboard_device()
    memory = mmap.mmap(fb, W * H * 4, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
    fcntl.ioctl(tty, KDSETMODE, KD_GRAPHICS)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    screen_awake = True
    quiet_since = time.monotonic()
    sound_average = None
    forced_rest_until = 0.0
    rest_frame_due = 0.0
    history = screen_history()
    try:
        while running:
            key_code = pressed_key(keyboard)
            data = status()
            audio = data.get("audio", {}) if data else {}
            audio_ok = bool(audio.get("available"))
            current_dba = max(audio.get("dbaLeft", 0), audio.get("dbaRight", 0))
            now = time.monotonic()
            sound_average = current_dba if sound_average is None else 0.07 * current_dba + 0.93 * sound_average
            settings = data.get("settings", {}) if data else {}
            auto_rest = bool(settings.get("screen_sleep_enabled", False))
            try:
                rest_seconds = max(60, min(1800, int(settings.get("screen_sleep_minutes", 5)) * 60))
                noise_threshold = max(35.0, min(90.0, float(settings.get("screen_noise_threshold", 55))))
            except (TypeError, ValueError):
                rest_seconds, noise_threshold = 300, 55.0

            if key_code == KEY_F2:
                if forced_rest_until > now:
                    forced_rest_until = 0.0
                    screen_awake = True
                    quiet_since = now
                    record_screen(history, "awake", current_dba)
                else:
                    forced_rest_until = now + FORCED_REST_SECONDS
                    screen_awake = False
                    rest_frame_due = 0.0
                    record_screen(history, "asleep", current_dba)

            if key_code == KEY_F10:
                forced_rest_until = 0.0
                screen_awake = True
                write_frame(memory, render(data))
                configuration_menu(tty)
                quiet_since = time.monotonic()
                rest_frame_due = 0.0
                continue

            if forced_rest_until and now >= forced_rest_until:
                forced_rest_until = 0.0
                screen_awake = True
                quiet_since = now
                sound_average = current_dba
                record_screen(history, "awake", current_dba)

            forced_rest = forced_rest_until > now

            if forced_rest:
                pass
            elif not audio_ok or not auto_rest:
                screen_awake = True
                quiet_since = now
            elif screen_awake:
                # Sólo el ruido sostenido reinicia la inactividad; un pico breve no cuenta como presencia.
                if sound_average >= noise_threshold:
                    quiet_since = now
                elif now - quiet_since >= rest_seconds:
                    screen_awake = False
                    rest_frame_due = 0.0
                    record_screen(history, "asleep", current_dba)
            elif current_dba >= noise_threshold or key_code is not None:
                screen_awake = True
                quiet_since = now
                sound_average = current_dba
                record_screen(history, "awake", current_dba)

            if screen_awake:
                write_frame(memory, render(data))
            elif now >= rest_frame_due:
                write_frame(memory, render_rest(data))
                rest_frame_due = now + 0.5
            time.sleep(1 / 15)
    finally:
        fcntl.ioctl(tty, KDSETMODE, KD_TEXT)
        memory.close()
        if keyboard is not None:
            os.close(keyboard)
        os.close(fb)
        os.close(tty)


if __name__ == "__main__":
    main()
