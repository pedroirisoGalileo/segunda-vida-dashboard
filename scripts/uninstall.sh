#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then echo "Ejecutar con sudo"; exit 1; fi
systemctl disable --now dashboard-fb.service dashboard.service dashboard-network.path 2>/dev/null || true
rm -f /etc/systemd/system/dashboard.service /etc/systemd/system/dashboard-fb.service \
      /etc/systemd/system/dashboard-network.service /etc/systemd/system/dashboard-network.path
systemctl daemon-reload
echo "Servicios retirados. Los datos permanecen en /var/lib/dashboard y /etc/dashboard."
echo "Eliminarlos manualmente sólo si ya no se necesitan."
