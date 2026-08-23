# Arquitectura

## Procesos

`dashboard.service` ejecuta el backend como usuario sin privilegios. Mantiene trabajadores asíncronos para clima, sensores, red, WAN y estado local. Un hilo separado captura ALSA y actualiza el estado de audio.

`dashboard-fb.service` se ejecuta sobre `tty1`, cambia la consola a `KD_GRAPHICS` y escribe imágenes BGRX en `/dev/fb0`. Al finalizar restaura `KD_TEXT`.

`dashboard-network.path` observa una solicitud efímera. `dashboard-network.service`, ejecutado como root, valida IPv4 y aplica únicamente una conexión NetworkManager conocida. Esto evita ejecutar el servidor web con privilegios administrativos.

## Flujo de datos

El backend conserva el último valor válido de cada fuente y publica `/api/status`. El framebuffer consulta la API local; la vista web consume la misma API. Si Internet o un sensor fallan, el panel continúa con el resto de las fuentes.

## Persistencia

- `/etc/dashboard/dashboard.env`: credenciales y audio;
- `/etc/dashboard/mikrotik.env`: integración opcional;
- `/var/lib/dashboard/settings.json`: localidad y equipos;
- `/var/lib/dashboard/network-settings.json`: red sin contraseña;
- NetworkManager conserva la clave Wi‑Fi en su almacenamiento root.

## Límites conocidos

- diseño físico fijo para 1024×600;
- calibración acústica dependiente de cada micrófono;
- sensor NanoPi y MikroTik son adaptadores específicos, no requisitos;
- algunos controladores antiguos necesitan parámetros de kernel;
- no existe garantía de control físico de backlight.
