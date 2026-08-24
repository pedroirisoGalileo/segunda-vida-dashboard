#!/usr/bin/env python3
import asyncio
import base64
import json
import math
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import psutil
from aiohttp import web
from scipy.signal import bilinear, lfilter

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
SETTINGS_FILE = Path(os.getenv("DASHBOARD_SETTINGS", "/var/lib/dashboard/settings.json"))
SCREEN_STATE_FILE = Path("/var/lib/dashboard/screen_state.json")
NETWORK_REQUEST_FILE = Path("/var/lib/dashboard/network-request.json")
NETWORK_SETTINGS_FILE = Path("/var/lib/dashboard/network-settings.json")
ADMIN_USER = os.getenv("DASHBOARD_ADMIN_USER", "dashboard")
ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", "")
NANOPI_HOST = os.getenv("NANOPI_HOST", "192.168.1.20")
NANOPI_USER = os.getenv("NANOPI_USER", "dashboard-reader")
NANOPI_KEY = os.getenv("NANOPI_KEY", "/etc/dashboard/nanopi_key")
AUDIO_DEVICE = os.getenv("AUDIO_DEVICE", "plughw:0,0")
DBA_SLOPE = float(os.getenv("DBA_SLOPE", "1.497"))
DBA_OFFSET = float(os.getenv("DBA_OFFSET", "84.40"))
RTA_CENTERS = np.array([20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250,
                        315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500,
                        3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000])
MIKROTIK_HOST = os.getenv("MIKROTIK_HOST", "192.168.1.1")
MIKROTIK_USER = os.getenv("MIKROTIK_USER", "admin")
MIKROTIK_PASSWORD = os.getenv("MIKROTIK_PASSWORD", "")
MIKROTIK_INTERFACE = os.getenv("MIKROTIK_INTERFACE", "ether1")

state = {
    "audio": {"left": 0.0, "right": 0.0, "peakLeft": 0.0, "peakRight": 0.0, "weightedDbLeft": -60.0, "weightedDbRight": -60.0, "dbaLeft": 0.0, "dbaRight": 0.0, "spectrum": [-80.0] * 31, "available": False},
    "sensor": {"temperature": None, "humidity": None, "age": None, "online": False},
    "network": {"router": False, "nanopi": False, "internet": False, "devices": []},
    "wan": {"ip": None, "isp": None, "download": None, "upload": None, "latency": None, "tested": None},
    "weather": {"temperature": None, "apparent": None, "humidity": None, "code": None, "wind": None, "high": None, "low": None, "isDay": None, "online": False},
    "router_wan": {"download": 0.0, "upload": 0.0, "link": None, "online": False},
}

DEFAULT_SETTINGS = {
    "location": "Mi localidad",
    "latitude": 0.0,
    "longitude": 0.0,
    "nanopi_host": NANOPI_HOST,
    "router_host": MIKROTIK_HOST,
    "screen_sleep_enabled": True,
    "screen_noise_threshold": 55.0,
    "devices": [{"name": "Router", "host": MIKROTIK_HOST, "port": 80},
                {"name": "Internet", "host": "1.1.1.1", "port": 443}],
}


def load_settings():
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        saved = json.loads(SETTINGS_FILE.read_text())
        if isinstance(saved, dict):
            settings.update(saved)
    except Exception:
        pass
    return settings


def load_screen_state():
    try:
        return json.loads(SCREEN_STATE_FILE.read_text())
    except Exception:
        return {"sleepCount": 0, "wakeCount": 0, "state": "unknown",
                "lastSleep": None, "lastWake": None, "lastWakeDba": None}


def clean_settings(value):
    current = load_settings()
    result = {
        "location": str(value.get("location", current["location"]))[:60].strip() or current["location"],
        "latitude": max(-90.0, min(90.0, float(value.get("latitude", current["latitude"])))),
        "longitude": max(-180.0, min(180.0, float(value.get("longitude", current["longitude"])))),
        "nanopi_host": str(value.get("nanopi_host", current["nanopi_host"]))[:255].strip(),
        "router_host": str(value.get("router_host", current["router_host"]))[:255].strip(),
        "screen_sleep_enabled": value.get("screen_sleep_enabled", current["screen_sleep_enabled"]) in
                                (True, 1, "1", "true", "True", "si", "sí", "on"),
        "screen_noise_threshold": max(35.0, min(90.0, float(
            value.get("screen_noise_threshold", current["screen_noise_threshold"])))),
        "devices": [],
    }
    for item in value.get("devices", current["devices"])[:6]:
        name, host = str(item.get("name", "Equipo"))[:24].strip(), str(item.get("host", ""))[:255].strip()
        if host:
            result["devices"].append({"name": name or "Equipo", "host": host,
                                      "port": max(1, min(65535, int(item.get("port", 80))))})
    return result


def dbfs(value):
    return max(-60.0, min(3.0, 20.0 * math.log10(max(value, 1) / 32768.0)))


def meter_value(level_db):
    return max(0.0, min(1.0, (level_db + 48.0) / 51.0))


def dba_value(weighted_dbfs):
    return max(20.0, min(110.0, DBA_SLOPE * weighted_dbfs + DBA_OFFSET))


def dba_meter_value(level_dba):
    return max(0.0, min(1.0, (level_dba - 30.0) / 60.0))


def a_weighting(sample_rate):
    f1, f2, f3, f4 = 20.598997, 107.65265, 737.86223, 12194.217
    a1000 = 1.9997
    numerator = [(2 * math.pi * f4) ** 2 * 10 ** (a1000 / 20), 0, 0, 0, 0]
    denominator = np.polymul([1, 4 * math.pi * f4, (2 * math.pi * f4) ** 2],
                             [1, 4 * math.pi * f1, (2 * math.pi * f1) ** 2])
    denominator = np.polymul(np.polymul(denominator, [1, 2 * math.pi * f3]), [1, 2 * math.pi * f2])
    return bilinear(numerator, denominator, sample_rate)


def audio_worker():
    sample_rate = 48000
    weight_b, weight_a = a_weighting(sample_rate)
    fft_size = 8192
    fft_window = np.hanning(fft_size)
    fft_freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
    band_edges = RTA_CENTERS[:, None] * np.array([2 ** (-1/6), 2 ** (1/6)])
    band_bins = []
    for center, (low, high) in zip(RTA_CENTERS, band_edges):
        bins = (fft_freqs >= low) & (fft_freqs < high)
        if not bins.any():
            bins[np.argmin(np.abs(fft_freqs - center))] = True
        band_bins.append(bins)
    smoothed_spectrum = np.full(31, -80.0)
    command = ["arecord", "-q", "-D", AUDIO_DEVICE, "-f", "S16_LE", "-c", "2", "-r", str(sample_rate), "-t", "raw"]
    while True:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            state["audio"]["available"] = True
            filter_state_l = np.zeros(max(len(weight_a), len(weight_b)) - 1)
            filter_state_r = np.zeros(max(len(weight_a), len(weight_b)) - 1)
            while process.poll() is None:
                chunk = process.stdout.read(12800)
                if not chunk:
                    break
                samples = np.frombuffer(chunk, dtype="<i2").reshape(-1, 2).astype(np.float64)
                left, right = samples[:, 0], samples[:, 1]
                l_rms, r_rms = np.sqrt(np.mean(left * left)), np.sqrt(np.mean(right * right))
                weighted_l, filter_state_l = lfilter(weight_b, weight_a, left, zi=filter_state_l)
                weighted_r, filter_state_r = lfilter(weight_b, weight_a, right, zi=filter_state_r)
                weighted_db_l = dbfs(np.sqrt(np.mean(weighted_l * weighted_l)))
                weighted_db_r = dbfs(np.sqrt(np.mean(weighted_r * weighted_r)))
                dba_l, dba_r = dba_value(weighted_db_l), dba_value(weighted_db_r)
                mono = (left + right) * 0.5
                fft_input = np.zeros(fft_size)
                take = min(fft_size, len(mono))
                fft_input[-take:] = mono[-take:]
                amplitude = np.abs(np.fft.rfft(fft_input * fft_window)) / (fft_window.sum() * 32768.0 / 2.0)
                power = amplitude ** 2
                band_db = np.array([
                    10.0 * math.log10(max(power[bins].sum(), 1e-12))
                    for bins in band_bins
                ])
                band_db = np.clip(band_db, -80.0, 0.0)
                # Ataque rápido y caída más lenta: movimiento fluido sin parpadeo.
                smoothed_spectrum = np.where(band_db > smoothed_spectrum,
                                             0.82 * band_db + 0.18 * smoothed_spectrum,
                                             0.20 * band_db + 0.80 * smoothed_spectrum)
                lv, rv = dba_meter_value(dba_l), dba_meter_value(dba_r)
                audio = state["audio"]
                audio["left"], audio["right"] = lv, rv
                audio["weightedDbLeft"], audio["weightedDbRight"] = round(weighted_db_l, 2), round(weighted_db_r, 2)
                audio["dbaLeft"], audio["dbaRight"] = round(dba_l, 1), round(dba_r, 1)
                audio["spectrum"] = np.round(smoothed_spectrum, 1).tolist()
                audio["peakLeft"] = max(lv, audio["peakLeft"] - 0.006)
                audio["peakRight"] = max(rv, audio["peakRight"] - 0.006)
            process.terminate()
        except Exception:
            state["audio"]["available"] = False
        time.sleep(2)


def read_nanopi():
    nanopi_host = load_settings()["nanopi_host"]
    command = [
        "ssh", "-i", NANOPI_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
        "-o", "StrictHostKeyChecking=accept-new", f"{NANOPI_USER}@{nanopi_host}",
        "journalctl", "-u", "dht_led_hice.service", "-n", "80", "--no-pager",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=6)
        match = re.search(r"Temp\s*=\s*([\d.]+).*?Hum\s*=\s*([\d.]+)", result.stdout, re.S)
        if match:
            return {"temperature": float(match.group(1)), "humidity": float(match.group(2)), "age": "última lectura", "online": True}
    except Exception:
        pass
    return {"temperature": None, "humidity": None, "age": None, "online": False}


async def sensor_worker():
    while True:
        state["sensor"] = await asyncio.to_thread(read_nanopi)
        await asyncio.sleep(30)


async def network_worker():
    while True:
        devices = load_settings()["devices"]
        results = await asyncio.gather(*(asyncio.to_thread(tcp_online, item["host"], item["port"])
                                         for item in devices))
        monitored = [dict(item, online=online) for item, online in zip(devices, results)]
        by_name = {item["name"].lower(): item["online"] for item in monitored}
        state["network"] = {"router": by_name.get("router", False), "nanopi": by_name.get("nanopi", False),
                            "internet": by_name.get("internet", False), "devices": monitored}
        await asyncio.sleep(15)


def read_router_wan():
    if not MIKROTIK_PASSWORD:
        return None
    token = base64.b64encode(f"{MIKROTIK_USER}:{MIKROTIK_PASSWORD}".encode()).decode()
    router_host = load_settings()["router_host"]
    request = urllib.request.Request(
        f"http://{router_host}/rest/interface/ethernet?.proplist=.id,rx-bytes,tx-bytes&name={urllib.parse.quote(MIKROTIK_INTERFACE)}",
        headers={"Authorization": "Basic " + token, "User-Agent": "SegundaVidaDashboard/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.load(response)[0]
        return int(data["rx-bytes"]), int(data["tx-bytes"])
    except Exception:
        return None


async def router_wan_worker():
    previous, previous_time = None, None
    while True:
        now = time.monotonic()
        counters = await asyncio.to_thread(read_router_wan)
        if counters and previous and counters[0] >= previous[0] and counters[1] >= previous[1]:
            elapsed = max(0.1, now - previous_time)
            state["router_wan"] = {
                "download": round((counters[0] - previous[0]) * 8 / elapsed / 1_000_000, 2),
                "upload": round((counters[1] - previous[1]) * 8 / elapsed / 1_000_000, 2),
                "link": "1 Gbps", "online": True,
            }
        elif not counters:
            state["router_wan"]["online"] = False
        if counters:
            previous, previous_time = counters, now
        await asyncio.sleep(2)


def fetch_json(url, timeout=12):
    request = urllib.request.Request(url, headers={"User-Agent": "SegundaVidaDashboard/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def read_weather():
    settings = load_settings()
    params = urllib.parse.urlencode({
        "latitude": settings["latitude"], "longitude": settings["longitude"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
        "daily": "temperature_2m_max,temperature_2m_min", "timezone": "America/Argentina/Buenos_Aires",
        "forecast_days": 1,
    })
    try:
        data = fetch_json("https://api.open-meteo.com/v1/forecast?" + params)
        current, daily = data["current"], data["daily"]
        return {
            "temperature": current["temperature_2m"], "apparent": current["apparent_temperature"],
            "humidity": current["relative_humidity_2m"], "code": current["weather_code"],
            "wind": current["wind_speed_10m"], "high": daily["temperature_2m_max"][0],
            "low": daily["temperature_2m_min"][0], "isDay": bool(current["is_day"]), "online": True,
        }
    except Exception:
        return dict(state["weather"], online=False)


async def weather_worker():
    while True:
        state["weather"] = await asyncio.to_thread(read_weather)
        await asyncio.sleep(600)


def read_wan_identity():
    try:
        data = fetch_json("http://ip-api.com/json/?fields=status,query,isp,org", 8)
        if data.get("status") == "success":
            return data.get("query"), data.get("isp") or data.get("org")
    except Exception:
        pass
    return None, None


def run_speed_test():
    result = {"download": None, "upload": None, "latency": None, "tested": int(time.time())}
    try:
        measurement = subprocess.run([
            "curl", "-fsS", "--max-time", "15", "-o", "/dev/null",
            "-w", "%{speed_download} %{time_starttransfer}",
            "https://speed.cloudflare.com/__down?bytes=5000000",
        ], capture_output=True, text=True, timeout=18, check=True)
        speed, latency = map(float, measurement.stdout.split())
        result["download"] = round(speed * 8 / 1_000_000, 1)
        result["latency"] = round(latency * 1000)
    except Exception:
        pass
    try:
        body = bytes(1_000_000)
        measurement = subprocess.run([
            "curl", "-fsS", "--max-time", "15", "-o", "/dev/null",
            "-w", "%{speed_upload}", "-X", "POST", "--data-binary", "@-",
            "https://speed.cloudflare.com/__up",
        ], input=body, capture_output=True, timeout=18, check=True)
        result["upload"] = round(float(measurement.stdout) * 8 / 1_000_000, 1)
    except Exception:
        pass
    return result


async def wan_worker():
    identity_due = 0
    while True:
        if time.time() >= identity_due:
            ip, isp = await asyncio.to_thread(read_wan_identity)
            if ip:
                state["wan"]["ip"], state["wan"]["isp"] = ip, isp
            identity_due = time.time() + 21600
        state["wan"].update(await asyncio.to_thread(run_speed_test))
        await asyncio.sleep(1800)


def tcp_online(host, port, timeout=0.35):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def battery_state():
    battery = psutil.sensors_battery()
    if not battery:
        return {"percent": None, "plugged": True}
    return {"percent": round(battery.percent), "plugged": battery.power_plugged}


async def api_status(_request):
    disk = psutil.disk_usage("/")
    payload = {
        "system": {
            "cpu": round(psutil.cpu_percent(interval=None)),
            "memory": round(psutil.virtual_memory().percent),
            "disk": round(disk.percent),
            "uptime": round(time.time() - psutil.boot_time()),
            "battery": battery_state(),
        },
        "audio": dict(state["audio"]),
        "sensor": dict(state["sensor"]),
        "network": dict(state["network"]),
        "wan": dict(state["wan"]),
        "weather": dict(state["weather"]),
        "routerWan": dict(state["router_wan"]),
        "settings": load_settings(),
        "screen": load_screen_state(),
        "timestamp": int(time.time()),
    }
    return web.json_response(payload)


def authorized(request):
    if not ADMIN_PASSWORD:
        return False
    value = request.headers.get("Authorization", "")
    if not value.startswith("Basic "):
        return False
    try:
        user, password = base64.b64decode(value[6:]).decode().split(":", 1)
        return user == ADMIN_USER and password == ADMIN_PASSWORD
    except Exception:
        return False


def require_admin(request):
    if authorized(request):
        return None
    return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="Dashboard admin"'}, text="Autenticación requerida")


async def admin_page(request):
    denied = require_admin(request)
    if denied is not None:
        return denied
    return web.FileResponse(STATIC / "admin.html")


async def api_settings(request):
    denied = require_admin(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        return web.json_response(load_settings())
    try:
        settings = clean_settings(await request.json())
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = SETTINGS_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(SETTINGS_FILE)
        return web.json_response({"ok": True, "settings": settings})
    except Exception as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)


def current_network_settings():
    saved = {"ssid": "", "mode": "dhcp", "address": "", "gateway": "", "dns": ""}
    try:
        saved.update(json.loads(NETWORK_SETTINGS_FILE.read_text()))
    except Exception:
        pass
    try:
        result = subprocess.run(["nmcli", "-t", "-f", "GENERAL.CONNECTION,GENERAL.STATE,IP4.ADDRESS,IP4.GATEWAY",
                                 "device", "show", "wlp1s0"], capture_output=True, text=True, timeout=5)
        saved["deviceStatus"] = result.stdout
    except Exception:
        saved["deviceStatus"] = ""
    saved["pending"] = NETWORK_REQUEST_FILE.exists()
    return saved


async def api_network_settings(request):
    denied = require_admin(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        return web.json_response(current_network_settings())
    try:
        value = await request.json()
        request_value = {key: str(value.get(key, "")) for key in ("ssid", "password", "mode", "address", "gateway", "dns")}
        if not request_value["ssid"] or request_value["mode"] not in ("dhcp", "static"):
            raise ValueError("SSID o modo inválido")
        NETWORK_REQUEST_FILE.write_text(json.dumps(request_value, ensure_ascii=False) + "\n")
        return web.json_response({"ok": True, "message": "Cambio solicitado; la conexión puede cambiar de IP"})
    except Exception as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)


async def camera(request):
    denied = require_admin(request)
    if denied is not None:
        return denied
    target = Path("/run/dashboard/camera.jpg")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "video4linux2",
        "-input_format", "mjpeg", "-video_size", "640x480", "-i", "/dev/video0",
        "-frames:v", "1", "-y", str(target),
    ]
    try:
        await asyncio.wait_for(asyncio.to_thread(subprocess.run, command, check=True), timeout=30)
        return web.FileResponse(target, headers={"Cache-Control": "no-store"})
    except Exception:
        return web.Response(status=503, text="No se pudo obtener la imagen de la cámara")


async def index(_request):
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store, max-age=0"})


async def start_background(app):
    threading.Thread(target=audio_worker, daemon=True).start()
    app["sensor_task"] = asyncio.create_task(sensor_worker())
    app["network_task"] = asyncio.create_task(network_worker())
    app["weather_task"] = asyncio.create_task(weather_worker())
    app["wan_task"] = asyncio.create_task(wan_worker())
    app["router_wan_task"] = asyncio.create_task(router_wan_worker())


async def stop_background(app):
    app["sensor_task"].cancel()
    app["network_task"].cancel()
    app["weather_task"].cancel()
    app["wan_task"].cancel()
    app["router_wan_task"].cancel()


app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/api/status", api_status)
app.router.add_get("/admin", admin_page)
app.router.add_get("/api/settings", api_settings)
app.router.add_post("/api/settings", api_settings)
app.router.add_get("/api/network-settings", api_network_settings)
app.router.add_post("/api/network-settings", api_network_settings)
app.router.add_get("/api/camera.jpg", camera)
app.router.add_static("/static", STATIC)
app.on_startup.append(start_background)
app.on_cleanup.append(stop_background)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8088, access_log=None)
