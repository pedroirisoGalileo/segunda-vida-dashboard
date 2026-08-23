#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Ejecutar con sudo: sudo $0 USUARIO"
    exit 1
fi

DASHBOARD_USER=${1:-}
if [ -z "$DASHBOARD_USER" ] || ! id "$DASHBOARD_USER" >/dev/null 2>&1; then
    echo "Uso: sudo $0 USUARIO_EXISTENTE"
    exit 1
fi

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
echo "Instalando para el usuario $DASHBOARD_USER desde $PROJECT_DIR"

apt-get update
apt-get install -y python3-aiohttp python3-numpy python3-pil python3-psutil python3-scipy \
    alsa-utils curl ffmpeg fonts-dejavu-core network-manager openssh-client

install -d -m 755 /opt/segunda-vida-dashboard/static /etc/dashboard
install -m 755 "$PROJECT_DIR/app/server.py" /opt/segunda-vida-dashboard/server.py
install -m 755 "$PROJECT_DIR/app/fb_dashboard.py" /opt/segunda-vida-dashboard/fb_dashboard.py
install -m 755 "$PROJECT_DIR/app/config_menu.py" /opt/segunda-vida-dashboard/config_menu.py
install -m 755 "$PROJECT_DIR/app/network_config.py" /opt/segunda-vida-dashboard/network_config.py
install -m 644 "$PROJECT_DIR/app/static/"* /opt/segunda-vida-dashboard/static/

for unit in dashboard.service dashboard-fb.service dashboard-network.service dashboard-network.path; do
    sed "s|User=dashboard|User=$DASHBOARD_USER|; s|Group=dashboard|Group=$DASHBOARD_USER|" \
        "$PROJECT_DIR/systemd/$unit" > "/etc/systemd/system/$unit"
done

printf "Usuario administrativo [dashboard]: "
read ADMIN_USER
ADMIN_USER=${ADMIN_USER:-dashboard}
printf "Contraseña administrativa: "
stty -echo
read ADMIN_PASSWORD
stty echo
printf "\n"
if [ -z "$ADMIN_PASSWORD" ]; then
    echo "La contraseña no puede estar vacía"
    exit 1
fi

umask 077
cat > /etc/dashboard/dashboard.env <<EOF
DASHBOARD_ADMIN_USER=$ADMIN_USER
DASHBOARD_ADMIN_PASSWORD=$ADMIN_PASSWORD
AUDIO_DEVICE=plughw:0,0
DBA_SLOPE=1.0
DBA_OFFSET=80.0
NANOPI_HOST=192.168.1.20
NANOPI_USER=dashboard-reader
NANOPI_KEY=/etc/dashboard/nanopi_key
EOF
cat > /etc/dashboard/mikrotik.env <<EOF
MIKROTIK_HOST=192.168.1.1
MIKROTIK_USER=dashboard-reader
MIKROTIK_PASSWORD=
MIKROTIK_INTERFACE=ether1
EOF

systemctl daemon-reload
systemctl enable --now dashboard.service dashboard-network.path
echo "Backend instalado. Abrir http://IP:8088/admin y luego habilitar dashboard-fb.service."
