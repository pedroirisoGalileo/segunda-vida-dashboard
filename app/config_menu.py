#!/usr/bin/env python3
import curses
import json
from pathlib import Path

FILE = Path("/var/lib/dashboard/settings.json")
NETWORK_FILE = Path("/var/lib/dashboard/network-settings.json")
NETWORK_REQUEST = Path("/var/lib/dashboard/network-request.json")
DEFAULT = {"location":"Mi localidad","latitude":0.0,"longitude":0.0,
           "nanopi_host":"192.168.1.20","router_host":"192.168.1.1","devices":[],
           "screen_sleep_enabled":False,"screen_sleep_minutes":5,
           "screen_noise_threshold":55.0,"theme":"original",
           "custom_colors":{"background":"#07100f","card":"#0e1a18","edge":"#244239",
                            "text":"#effff8","muted":"#829a91","accent":"#58f0a5",
                            "warning":"#f4bd58","danger":"#ff626b"}}

CHOICES = {
    "screen_sleep_enabled": [("no", "Desactivado"), ("si", "Activado")],
    "screen_sleep_minutes": [(str(value), f"{value} minutos") for value in (1, 2, 5, 10, 15, 30)],
    "screen_noise_threshold": [(str(value), f"{value} dBA") for value in range(35, 91, 5)],
    "theme": [
        ("original", "Original verde"), ("oceano", "Océano azul"),
        ("ambar", "Ámbar retro"), ("violeta", "Violeta"),
        ("rojo", "Rojo"), ("monocromo", "Monocromo"),
        ("personalizado", "Personalizado"),
    ],
    "wifi_mode": [("dhcp", "DHCP automático"), ("static", "IP fija")],
}


def choice_label(key, value):
    options = CHOICES.get(key, [])
    if not options:
        return str(value)
    return next((label for option, label in options if option == str(value)), options[0][1])


def choose(stdscr, title, key, current):
    options = CHOICES[key]
    selected = next((index for index, (value, _) in enumerate(options) if value == str(current)), 0)
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        stdscr.addstr(1, 3, title[:max(1, width - 6)], curses.A_BOLD)
        stdscr.addstr(2, 3, "Flechas: elegir · Enter: aceptar · Esc: cancelar"[:max(1, width - 6)])
        top = max(0, min(selected - max(0, height - 8), len(options) - max(1, height - 6)))
        for row, index in enumerate(range(top, min(len(options), top + height - 6)), 4):
            marker = "● " if index == selected else "  "
            attr = curses.A_REVERSE if index == selected else curses.A_NORMAL
            stdscr.addstr(row, 5, (marker + options[index][1])[:max(1, width - 10)], attr)
        stdscr.refresh()
        pressed = stdscr.getch()
        if pressed in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(options)
        elif pressed in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(options)
        elif pressed in (10, 13):
            return options[selected][0]
        elif pressed == 27:
            return str(current)


def load():
    try:
        return {**DEFAULT, **json.loads(FILE.read_text())}
    except Exception:
        return dict(DEFAULT)


def editor(stdscr):
    curses.curs_set(0)
    settings = load()
    try:
        network = json.loads(NETWORK_FILE.read_text())
    except Exception:
        network = {"ssid":"MI-WIFI", "mode":"dhcp", "address":"", "gateway":"", "dns":""}
    devices = (settings.get("devices") or [])[:6]
    while len(devices) < 6:
        devices.append({"name":"", "host":"", "port":80})
    custom = {**DEFAULT["custom_colors"], **(settings.get("custom_colors") or {})}
    fields = [
        ["Localidad", "location", str(settings["location"])],
        ["Latitud", "latitude", str(settings["latitude"])],
        ["Longitud", "longitude", str(settings["longitude"])],
        ["NanoPi", "nanopi_host", str(settings["nanopi_host"])],
        ["Router", "router_host", str(settings["router_host"])],
        ["Reposo automático si/no", "screen_sleep_enabled",
         "si" if settings.get("screen_sleep_enabled", False) else "no"],
        ["Espera reposo minutos", "screen_sleep_minutes",
         str(round(float(settings.get("screen_sleep_minutes", 5))))],
        ["Umbral reposo dBA", "screen_noise_threshold",
         str(round(float(settings.get("screen_noise_threshold", 55))))],
        ["Skin", "theme", str(settings.get("theme") or "original")],
        ["Color fondo", "color_background", custom["background"]],
        ["Color tarjetas", "color_card", custom["card"]],
        ["Color bordes", "color_edge", custom["edge"]],
        ["Color texto", "color_text", custom["text"]],
        ["Color secundario", "color_muted", custom["muted"]],
        ["Color acento", "color_accent", custom["accent"]],
        ["Color advertencia", "color_warning", custom["warning"]],
        ["Color alarma", "color_danger", custom["danger"]],
    ]
    for i, dev in enumerate(devices, 1):
        fields += [[f"Equipo {i} nombre", f"d{i}n", str(dev["name"])],
                   [f"Equipo {i} IP", f"d{i}h", str(dev["host"])],
                   [f"Equipo {i} puerto", f"d{i}p", str(dev["port"])]]
    fields += [["WiFi SSID", "wifi_ssid", str(network.get("ssid", ""))],
               ["WiFi contraseña", "wifi_password", ""],
               ["IPv4 dhcp/static", "wifi_mode", str(network.get("mode", "dhcp"))],
               ["IP fija/prefijo", "wifi_address", str(network.get("address", ""))],
               ["Gateway", "wifi_gateway", str(network.get("gateway", ""))],
               ["DNS (con comas)", "wifi_dns", str(network.get("dns", ""))]]
    selected, message = 0, "Flechas: mover · Enter: editar · F2: guardar · Esc: salir"
    while True:
        stdscr.erase(); h, w = stdscr.getmaxyx()
        stdscr.addstr(1, 3, "CONFIGURACIÓN DEL PANEL", curses.A_BOLD)
        stdscr.addstr(2, 3, message[:w-6])
        start = max(0, min(selected - max(0, h - 8), len(fields) - max(1, h - 6)))
        for screen_row, idx in enumerate(range(start, min(len(fields), start + h - 6)), 4):
            label, field_key, value = fields[idx]
            attr = curses.A_REVERSE if idx == selected else curses.A_NORMAL
            stdscr.addstr(screen_row, 3, (label + ":")[:22].ljust(23), attr)
            stdscr.addstr(screen_row, 27, choice_label(field_key, value)[:max(1,w-30)], attr)
        stdscr.refresh(); key = stdscr.getch()
        if key in (curses.KEY_UP, ord('k')): selected = (selected - 1) % len(fields)
        elif key in (curses.KEY_DOWN, ord('j')): selected = (selected + 1) % len(fields)
        elif key in (10, 13):
            if fields[selected][1] in CHOICES:
                fields[selected][2] = choose(stdscr, fields[selected][0], fields[selected][1], fields[selected][2])
            else:
                curses.echo(); curses.curs_set(1)
                stdscr.move(min(4 + selected - start, h - 2), 27); stdscr.clrtoeol()
                value = stdscr.getstr(min(4 + selected - start, h - 2), 27, max(1,w-30)).decode("utf-8", "ignore")
                curses.noecho(); curses.curs_set(0); fields[selected][2] = value
        elif key == curses.KEY_F2:
            values = {key:value for _, key, value in fields}
            try:
                saved = {"location":values["location"], "latitude":float(values["latitude"]),
                         "longitude":float(values["longitude"]), "nanopi_host":values["nanopi_host"],
                         "router_host":values["router_host"],
                         "screen_sleep_enabled":values["screen_sleep_enabled"].strip().lower() in
                                                ("si", "sí", "s", "1", "true", "on"),
                         "screen_sleep_minutes":max(1, min(30, int(values["screen_sleep_minutes"]))),
                         "screen_noise_threshold":max(35.0, min(90.0, float(values["screen_noise_threshold"]))),
                         "theme":values["theme"].strip().lower(),
                         "custom_colors":{name:values[f"color_{name}"].strip().lower()
                                          for name in ("background", "card", "edge", "text", "muted",
                                                       "accent", "warning", "danger")},
                         "devices":[]}
                for i in range(1,7):
                    if values[f"d{i}h"].strip():
                        saved["devices"].append({"name":values[f"d{i}n"].strip() or "Equipo",
                                                 "host":values[f"d{i}h"].strip(), "port":int(values[f"d{i}p"])})
                FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp=FILE.with_suffix(".tmp"); tmp.write_text(json.dumps(saved,ensure_ascii=False,indent=2)+"\n"); tmp.replace(FILE)
                network_request = {"ssid":values["wifi_ssid"], "password":values["wifi_password"],
                                   "mode":values["wifi_mode"], "address":values["wifi_address"],
                                   "gateway":values["wifi_gateway"], "dns":values["wifi_dns"]}
                changed = any(str(network_request[key]) != str(network.get(key, ""))
                              for key in ("ssid", "mode", "address", "gateway", "dns")) or bool(network_request["password"])
                if changed and network_request["ssid"] and network_request["mode"] in ("dhcp", "static"):
                    NETWORK_REQUEST.write_text(json.dumps(network_request, ensure_ascii=False) + "\n")
                message="Guardado ✓ · Esc para volver al panel"
            except Exception as error: message="Error: " + str(error)
        elif key == 27: return


if __name__ == "__main__":
    curses.wrapper(editor)
