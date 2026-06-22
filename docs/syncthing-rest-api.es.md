# API REST de Syncthing — referencia práctica

> 🌐 [English](syncthing-rest-api.md) · **Español**

Una chuleta de los endpoints en los que se apoya `syncthing-manager`, con la **trampa** de cada
uno. Es el subconjunto que importa al construir una herramienta de config/automatización; no es la
superficie completa de la API oficial (para eso, ver <https://docs.syncthing.net/dev/rest.html>).

## Básicos

- **URL base**: `https://127.0.0.1:8384` por defecto. La API y la GUI web comparten el mismo
  puerto/listener (`/rest/config/gui` → `address`).
- **Auth**: cabecera `X-API-Key: <key>`. Sin key → `401/403`.
- **TLS**: Syncthing trae un **certificado autofirmado**, así que un cliente HTTP debe desactivar
  la verificación (`verify=False`) y silenciar `InsecureRequestWarning`. Esto es aceptable **solo
  porque el listener por defecto es loopback** (`127.0.0.1`) — no hay red que interceptar (MITM).
  Si hablas con un Syncthing cuya GUI está enlazada a una dirección de LAN/pública, no mantengas a
  ciegas `verify=False`: fija (pin) su certificado o añádelo a tu almacén de confianza, o la
  conexión es genuinamente interceptable. (El ajuste `prefer_secure_channel` de esta herramienta lo
  esquiva para dispositivos no locales tunelizando la llamada de API por SSH/WinRM.)
- **Versión mínima**: los endpoints de config de abajo (`PUT /rest/config/folders/{id}`) requieren
  **Syncthing ≥ 1.12** (los endpoints de config por objeto llegaron en 1.12.0). Las versiones anteriores no tienen REST de config por objeto y se manejan
  editando `config.xml` + reiniciando el servicio.
- **Las escrituras de config son atómicas por objeto y se persisten al instante** — no hay un
  "guardar/commit" aparte. Un `PUT`/`POST`/`DELETE` en `/rest/config/...` surte efecto en vivo.

## Sistema / estado

| Endpoint | Método | Devuelve / uso | Trampa |
|---|---|---|---|
| `/rest/system/ping` | GET | `{"ping":"pong"}` | La mejor sonda para "¿está vivo + es válida mi key?". Distingue `down` (conexión rechazada/timeout) vs `auth` (401/403) vs `ok` mirando el código de estado, no solo el éxito. |
| `/rest/system/status` | GET | `{"myID": ...}` | `myID` es el device ID de **este** nodo — la base de las comprobaciones de identidad. |
| `/rest/system/version` | GET | `{"version","os","arch"}` | `os` es `"windows"`, `"linux"`, `"darwin"`, … — úsalo para detectar el SO de un par y manejar rutas. La versión no cambia en un proceso vivo → cachéala. |
| `/rest/system/connections` | GET | `{connections:{devID:{connected,address,clientVersion}}}` | `address` es la conexión *activa*, que a menudo es una **IPv6** link-local — no una IPv4 marcable. |
| `/rest/system/discovery` | GET | `{devID:{addresses:[...]}}` | Con frecuencia el único sitio donde aparece una **IPv4** usable cuando la conexión viva es IPv6. Best-effort; puede venir vacío. |
| `/rest/system/browse?current=<path>` | GET | `[paths]` | Listado de directorios del lado servidor — el mismo autocompletado que usa la GUI web para elegir carpeta. Se ejecuta en el filesystem del nodo *destino*. |
| `/rest/stats/device` | GET | `{devID:{lastSeen,lastAddress}}` | `lastAddress` puede rellenar una dirección para un dispositivo offline. |

## Carpetas (config)

| Endpoint | Método | Uso | Trampa |
|---|---|---|---|
| `/rest/config/folders` | GET | Lista todas las carpetas. | — |
| `/rest/config/folders` | POST | **Crea** una carpeta a partir de un objeto de config completo. | — |
| `/rest/config/folders/{id}` | GET | La config de una carpeta. | **404 = ausente de verdad**; un timeout/5xx/auth es un error *transitorio*. Trátalos distinto o sobrescribirás/recrearás una carpeta que solo estaba brevemente inalcanzable. |
| `/rest/config/folders/{id}` | PUT | Actualiza una carpeta. | **GET-modify-PUT del objeto entero.** Un PUT parcial tira todos los campos que no enviaste. Haz round-trip de `folder.raw` y cambia solo lo que quieres. |
| `/rest/config/folders/{id}` | DELETE | Quita la carpeta de la config. | La quita solo de *este* nodo. **No** borra los datos en disco. |
| `/rest/db/status?folder={id}` | GET | Estado de runtime (`state: "idle"/"syncing"/"paused"`, completitud). | Esto es *runtime*, separado de la config. Sondéalo para confirmar que una pausa realmente cuajó. |
| `/rest/db/ignores?folder={id}` | GET / POST | Lee / reemplaza los patrones de `.stignore` (`{"ignore":[...]}`). | El POST **reemplaza** la lista entera, no añade. |

### Pausar una carpeta — la trampa

**No** existe `/rest/db/pause` / `/rest/db/resume` para carpetas (ese namespace da 404; esos verbos
existen solo para *dispositivos*). El estado de pausa de una carpeta vive en la **config**: GET de
la carpeta, pon `"paused": true|false`, y PUT de vuelta. Convenientemente, esto significa que un
único PUT que actualiza `label`/`path` y pone `paused:false` aplica el cambio y reanuda la carpeta
a la vez.

Tras un PUT que cambia la ruta, **verifica** la relectura: Syncthing en Windows normaliza las rutas
(añade una `\` final, puede invertir el sentido de las barras), así que compara con las barras
normalizadas y los separadores finales quitados, no con `==`.

> Nota (visto en pruebas con Syncthing 1.20+): una carpeta **pausada** reporta `state` **vacío
> (`""`)** en `/rest/db/status`, no `"paused"` (el runner está simplemente detenido). Si esperas a
> que se pause, acepta `state in ("paused", "")`.

## Dispositivos (config)

| Endpoint | Método | Uso | Trampa |
|---|---|---|---|
| `/rest/config/devices` | GET | Lista los dispositivos configurados. | — |
| `/rest/config/devices/{id}` | GET | Una entrada de dispositivo. | 404 = no está en la config de este nodo. |
| `/rest/config/devices/{id}` | PUT | Añade/acepta un dispositivo, o edita su `name`. | Para aceptar un dispositivo, PUT con cuerpo completo (`deviceID`, `name`, `addresses:["dynamic"]`, `compression`, …). Para renombrar, GET-modify-PUT. |
| `/rest/config/devices/{id}` | DELETE | Quita un dispositivo de la config. | 404 está bien (ya no estaba). Poda un par solo cuando **ninguna** carpeta siga compartiéndose con él. |

Compartir una carpeta con un dispositivo = añadir `{"deviceID": id}` al `devices[]` de esa carpeta
(GET-modify-PUT de la carpeta, no del dispositivo).

## Peticiones pendientes (entrantes)

| Endpoint | Método | Devuelve | Uso |
|---|---|---|---|
| `/rest/cluster/pending/devices` | GET | `{devID:{name,address,time}}` | Dispositivos que intentaron conectar pero aún no están en config. |
| `/rest/cluster/pending/folders` | GET | `{folderID:{offeredBy:{devID:{label}}}}` | Carpetas ofrecidas por dispositivos conocidos que aún no compartimos. |
| `/rest/cluster/pending/devices?device={id}` | DELETE | — | Descarta/ignora un dispositivo pendiente. |
| `/rest/cluster/pending/folders?folder={id}[&device={id}]` | DELETE | — | Descarta una oferta de carpeta pendiente. |

Para **aceptar** un dispositivo/carpeta pendiente no haces DELETE — lo *añades* (PUT del dispositivo,
o añadirlo al `devices[]` de la carpeta). DELETE aquí solo significa "descartar la petición". Un 404
al descartar es benigno.

## Helper de validación

| Endpoint | Método | Devuelve |
|---|---|---|
| `/rest/svc/deviceid?id={id}` | GET | `{"id":"<normalizado>"}` si es válido, `{"error":...}` si no. Deja que Syncthing normalice/valide un device ID en vez de hacerlo con tu propio regex. |

## Reglas de manejo de errores que nos mordieron

1. **Lleva el estado HTTP en tu excepción.** "Carpeta ausente (404)" vs "el host tuvo un parpadeo
   (timeout/5xx)" deben ser distinguibles, o recrearás/sobrescribirás datos en vivo.
2. **La pausa es best-effort.** Un 404 (Syncthing antiguo, o carpeta ausente en ese nodo) o un
   cuerpo vacío de `curl` por SSH no deben abortar la operación — procede y deja que la escritura
   real reporte el error verdadero.
3. **Verifica siempre las escrituras que importan** (cambios de ruta) releyendo y comparando
   valores *normalizados*.
4. **GET-modify-PUT** para cada objeto de config. Nunca construyas a mano un cuerpo de PUT parcial.
