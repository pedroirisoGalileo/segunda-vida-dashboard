#!/usr/bin/env python3
import ipaddress
import json
import os
import subprocess
from pathlib import Path

REQUEST = Path("/var/lib/dashboard/network-request.json")
SAVED = Path("/var/lib/dashboard/network-settings.json")
CONNECTION = "dashboard-wifi"


def run(*args):
    subprocess.run(["nmcli", *args], check=True, timeout=40)


def main():
    descriptor = os.open(REQUEST, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r", encoding="utf-8") as source:
        request = json.load(source)
    REQUEST.unlink(missing_ok=True)
    ssid = str(request.get("ssid", "")).strip()
    mode = request.get("mode", "dhcp")
    if not ssid or len(ssid) > 32 or mode not in ("dhcp", "static"):
        raise ValueError("SSID o modo inválido")
    try:
        subprocess.run(["nmcli", "-g", "NAME", "connection", "show", CONNECTION], check=True,
                       capture_output=True, timeout=10)
    except subprocess.CalledProcessError:
        run("connection", "add", "type", "wifi", "ifname", "wlp1s0", "con-name", CONNECTION, "ssid", ssid)
    run("connection", "modify", CONNECTION, "802-11-wireless.ssid", ssid,
        "connection.autoconnect", "yes", "connection.autoconnect-priority", "20",
        "802-11-wireless.cloned-mac-address", "permanent")
    password = str(request.get("password", ""))
    if password:
        run("connection", "modify", CONNECTION, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password)
    if mode == "dhcp":
        run("connection", "modify", CONNECTION, "ipv4.method", "auto", "ipv4.addresses", "",
            "ipv4.gateway", "", "ipv4.dns", "", "ipv4.route-metric", "600")
        saved = {"ssid": ssid, "mode": "dhcp", "address": "", "gateway": "", "dns": ""}
    else:
        interface = ipaddress.ip_interface(str(request.get("address", "")).strip())
        gateway = ipaddress.ip_address(str(request.get("gateway", "")).strip())
        dns_values = [str(ipaddress.ip_address(item.strip())) for item in str(request.get("dns", "")).split(",") if item.strip()]
        if interface.version != 4 or gateway.version != 4:
            raise ValueError("Sólo IPv4 es compatible")
        dns = ",".join(dns_values)
        run("connection", "modify", CONNECTION, "ipv4.method", "manual", "ipv4.addresses", str(interface),
            "ipv4.gateway", str(gateway), "ipv4.dns", dns, "ipv4.route-metric", "600")
        saved = {"ssid": ssid, "mode": "static", "address": str(interface), "gateway": str(gateway), "dns": dns}
    descriptor = os.open(SAVED, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        json.dump(saved, target, ensure_ascii=False, indent=2)
        target.write("\n")
    run("connection", "up", CONNECTION, "ifname", "wlp1s0")


if __name__ == "__main__":
    main()
