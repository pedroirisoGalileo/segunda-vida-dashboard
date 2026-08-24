# Instrucciones para agentes de código

Este archivo está dirigido a Codex y otros agentes que reciban autorización para modificar Segunda Vida Dashboard.

## Objetivo del proyecto

Mantener una distribución pequeña, segura y reproducible que convierta computadoras x86 antiguas en paneles ambientales y de red. El prototipo original es una Samsung 100NZB / Intel Classmate con Atom, 2 GB de RAM y pantalla 1024×600, pero el repositorio debe conservar valores genéricos y no depender de una vivienda o red concreta.

## Antes de modificar

1. Leer completamente `README.md` y el documento relacionado con la tarea.
2. Revisar `docs/ARCHITECTURE.md`, `docs/SECURITY.md` y `docs/TROUBLESHOOTING.md` si se toca backend, red, servicios, audio o framebuffer.
3. Inspeccionar cambios existentes y no sobrescribir trabajo ajeno.
4. Nunca copiar al repositorio archivos reales de `/etc/dashboard`, claves SSH, contraseñas, SSID, IP públicas ni fotografías sin revisar.

## Mapa del código

- `app/server.py`: backend `aiohttp`, captura ALSA, ponderación A, FFT/RTA, clima, sensores, red y API.
- `app/fb_dashboard.py`: renderizado Pillow directo sobre `/dev/fb0`, teclado F10 y presentación 1024×600.
- `app/config_menu.py`: menú local de configuración en consola.
- `app/network_config.py`: helper privilegiado y deliberadamente limitado para NetworkManager.
- `app/static/`: panel web público y vista administrativa.
- `systemd/`: unidades del backend, framebuffer y configuración de red.
- `scripts/`: instalación y desinstalación.
- `config/`: ejemplos sin secretos.
- `docs/`: decisiones técnicas, seguridad y diagnóstico.

## Principios de implementación

- Priorizar CPU y memoria bajas. El hardware objetivo puede tener un Atom y 1–2 GB de RAM.
- Evitar dependencias de escritorio, Electron y navegadores para la pantalla local.
- Capturar el audio una sola vez y reutilizar sus bloques para dBA, vúmetros y RTA.
- Mantener fallos aislados: si clima, sensor, router o Internet no responden, el panel debe continuar.
- Conservar compatibilidad con Python incluido en Debian estable.
- Tratar resolución, dispositivo ALSA, localidad, hosts y credenciales como configuración, no como datos fijos.
- Toda entrada destinada a `nmcli`, rutas, red o procesos debe validarse y pasarse como lista de argumentos, nunca mediante una shell interpolada.
- El backend debe continuar sin privilegios. Las operaciones root pertenecen a helpers pequeños y auditables.

## Seguridad obligatoria

- No agregar contraseñas reales ni valores domésticos a defaults, ejemplos, pruebas, documentación o commits.
- No devolver contraseñas Wi‑Fi mediante la API.
- Mantener `O_NOFOLLOW` o protección equivalente en archivos intercambiados con servicios root.
- No ampliar `sudoers`, permisos de dispositivos o privilegios systemd sin justificarlo en `docs/SECURITY.md`.
- La webcam sólo debe capturar bajo una solicitud administrativa autenticada.
- No exponer el servicio directamente a Internet ni afirmar que HTTP Basic cifra credenciales.

## Reglas para framebuffer y GMA500

- No usar `FBIOBLANK` automáticamente: se observó un bloqueo completo en GMA500.
- No recomendar `acpi_backlight=native` para la Samsung 100NZB: crea `psb-bl` pero rompe la imagen LVDS.
- La solución comprobada del prototipo es `video=LVDS-1:1024x600@60e` sin `quiet`.
- Cualquier parámetro de kernel debe probarse primero mediante una entrada GRUB temporal y de un solo arranque.
- El renderizador debe restaurar `KD_TEXT` en un bloque `finally`.
- No asumir 1024×600 para nuevos equipos: documentar o parametrizar cualquier soporte de resolución adicional.

## Reglas para audio

- No presentar los dBA como medición certificada.
- No cambiar ganancia ALSA, `DBA_SLOPE` o `DBA_OFFSET` sin advertir que se invalida la calibración.
- Evitar una segunda instancia de `arecord`.
- Si se modifica la FFT, verificar las 31 bandas, normalización, carga de CPU y comportamiento en silencio.

## Red y cambios que pueden cortar acceso

- No aplicar una red o IP durante instalación, migración o prueba salvo solicitud explícita.
- Mostrar una advertencia antes de cambiar SSID, DHCP o IP fija.
- Recomendar Ethernet como recuperación.
- Validar IPv4, prefijo, gateway, DNS, SSID y puertos.
- No cambiar el nombre estable de la conexión sin una migración compatible.

## Validaciones mínimas

Ejecutar antes de cada commit:

```bash
python3 -m py_compile app/*.py
sh -n scripts/*.sh
git diff --check
rg -n -i 'password|passwd|ssid|192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.' . \
  --glob '!README.md' --glob '!docs/**' --glob '!config/*.example'
```

Revisar manualmente cada coincidencia de secretos; palabras como `password` pueden ser nombres legítimos de campos.

Cuando exista acceso a una máquina de prueba, verificar proporcionalmente:

```bash
systemctl is-active dashboard.service dashboard-fb.service dashboard-network.path
curl -fsS http://127.0.0.1:8088/api/status
journalctl -u dashboard.service -b --no-pager
journalctl -u dashboard-fb.service -b --no-pager
```

No reiniciar, suspender, apagar, cambiar red ni escribir en backlight sin autorización expresa y una vía de recuperación.

## Documentación y entrega

- Actualizar `README.md` cuando cambie instalación, configuración o comportamiento visible.
- Actualizar arquitectura o seguridad cuando cambien procesos, privilegios o persistencia.
- Explicar límites y riesgos, no sólo el caso exitoso.
- Dejar el árbol sin procesos de prueba, artefactos, capturas privadas ni archivos temporales.
- Entregar un resumen de cambios, validaciones realizadas y cualquier paso manual pendiente.

## Fotografías

Las imágenes del prototipo se ubican en `photos/`. Antes de agregarlas:

- borrar metadatos de ubicación si no son necesarios;
- ocultar credenciales, IP públicas, QR y números de serie sensibles;
- optimizar tamaño sin destruir legibilidad;
- agregar texto alternativo y una referencia desde el README.
