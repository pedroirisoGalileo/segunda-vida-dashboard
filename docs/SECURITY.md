# Seguridad

El proyecto está pensado para una red doméstica, no para exposición directa a Internet.

- La administración y webcam requieren autenticación Basic, pero HTTP no cifra el tráfico.
- Usar firewall, VPN o proxy HTTPS si se accede desde fuera de la LAN.
- Crear cuentas de sólo lectura para sensores y routers.
- No subir archivos `/etc/dashboard/*.env` ni claves SSH.
- Cambiar inmediatamente las contraseñas de ejemplo.
- Revisar fotografías antes de publicarlas.
- Conservar acceso Ethernet al modificar Wi‑Fi o IP.

Los reportes de vulnerabilidades pueden enviarse mediante un issue sin incluir credenciales ni datos de una red real.
