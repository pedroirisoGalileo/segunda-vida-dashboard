# Resolución de problemas

## Pantalla negra, backlight encendido

1. Detener el renderizador: `sudo systemctl stop dashboard-fb.service`.
2. Comprobar `/dev/fb0` y su resolución.
3. Revisar `journalctl -u dashboard-fb.service -b`.
4. Ver conectores en `/sys/class/drm/card0-*`.
5. Si BIOS/GRUB se ven y Linux no, investigar el driver DRM.

En GMA500/GMA3600 puede servir `video=LVDS-1:1024x600@60e`. Probar siempre en una entrada temporal de GRUB antes de hacerlo permanente.

No usar `FBIOBLANK` a ciegas: algunos GMA500 se congelan. Tampoco asumir que `acpi_backlight=native` es seguro; en el prototipo creó `psb-bl` pero dejó el LVDS sin imagen.

## El backend tarda en aparecer

SciPy y los trabajadores pueden demorar varios segundos en un Atom. Revisar:

```bash
systemctl status dashboard.service
journalctl -u dashboard.service -b
```

## El audio no funciona

```bash
arecord -l
arecord -D plughw:0,0 -f S16_LE -c 2 -r 48000 -d 5 prueba.wav
alsamixer
```

Modificar `AUDIO_DEVICE` si la tarjeta no es `0,0`. No cambiar ganancia después de calibrar dBA.

## Wi‑Fi inaccesible tras aplicar IP fija

Conectar Ethernet, entrar por SSH y ejecutar:

```bash
nmcli connection show
sudo nmcli connection modify dashboard-wifi ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns ""
sudo nmcli connection up dashboard-wifi
```

## Temperatura interior ausente

La función de ejemplo espera acceso SSH por clave y un formato de log específico. Adaptar `read_nanopi()` o desactivar esa integración.

## Consumo alto

- reducir la frecuencia del bucle en `fb_dashboard.py`;
- bajar `fft_size` con pérdida de resolución grave;
- deshabilitar webcam y pruebas de velocidad si no se usan;
- comprobar procesos huérfanos con `ps`.
