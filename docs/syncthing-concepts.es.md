# Conceptos y trampas de Syncthing

> 🌐 [English](syncthing-concepts.md) · **Español**

El modelo mental que necesitas antes de automatizar Syncthing, y los filos que cuestan horas
reales de depuración. Va de la mano con [syncthing-rest-api.es.md](syncthing-rest-api.es.md).

## IDs de dispositivo

- Un device ID es una cadena larga, estable y auto-certificada (el hash del certificado TLS del
  nodo). Identifica a un nodo aunque cambie de dirección. **No** es secreto — es cómo se nombran
  los pares entre sí.
- `GET /rest/system/status → myID` es "quién soy yo". Es el ancla de las **comprobaciones de
  identidad**: un agente enviado a una máquina confirma que está en la correcta comparando el
  `myID` local con el device ID esperado antes de hacer nada.
- Valida/normaliza IDs con `GET /rest/svc/deviceid?id=...` en vez de con tu propio regex.

## Los IDs de carpeta son inmutables

La trampa más importante de todas. Syncthing **no tiene API para cambiar el ID de una carpeta**,
y el ID es la clave que usan los pares para asociar la carpeta en todo el clúster.

Para "renombrar" un ID hay que **borrar + recrear** en cada dispositivo:
1. Obtén la config actual de la carpeta.
2. DELETE de la carpeta antigua (la antigua y la nueva no pueden coexistir en la misma ruta —
   Syncthing prohíbe dos carpetas apuntando al mismo directorio).
3. POST de una carpeta nueva con el ID nuevo y la *misma* ruta/dispositivos/opciones. Si el POST
   falla, recrea la original para revertir.

Hazlo en **cada** dispositivo, no solo en uno. Si solo cambian algunos, el clúster queda
temporalmente partido: los pares que siguen con el ID antiguo ven la carpeta quedarse obsoleta y
reciben un aviso de "carpeta nueva ofrecida". Eso es esperado para cualquier dispositivo que no
pudiste alcanzar (se queda con el ID antiguo hasta que un agente o una pasada posterior lo
actualice). La etiqueta y la ruta en disco, en cambio, *sí* son mutables con un `PUT` normal.

## label vs path vs ID

Tres cosas independientes que se suelen confundir:

- **label** — el nombre legible que se muestra. Texto libre, mutable, puramente cosmético.
- **path** — el directorio en disco. Mutable vía PUT, pero cambiarlo **no** mueve los datos;
  tienes que renombrar el directorio en disco *y* actualizar la config para que cuadren. Si no
  puedes renombrar el directorio (p. ej. un remoto solo-API sin shell), cambia solo la etiqueta y
  deja la ruta — apuntar la config a una ruta inexistente deja la carpeta en estado de error.
- **ID** — la clave del clúster. Inmutable (ver arriba).

## config.xml — dónde vive

Cuando no hay canal API/SSH lees/parcheas `config.xml` directamente. Su ubicación varía mucho;
busca los candidatos en este orden (ver `discovery.py`):

**Windows**
- `%LOCALAPPDATA%\Syncthing\config.xml`
- `%APPDATA%\Syncthing\config.xml`

**Linux / macOS** (rutas XDG e históricas)
- `$XDG_STATE_HOME/syncthing/config.xml`, `~/.local/state/syncthing/config.xml`
- `$XDG_DATA_HOME/syncthing/config.xml`, `~/.local/share/syncthing/config.xml`
- `$XDG_CONFIG_HOME/syncthing/config.xml`, `~/.config/syncthing/config.xml`
- `~/.syncthing/config.xml`
- `~/Library/Application Support/Syncthing/config.xml` (macOS)
- Snap: `~/snap/syncthing/current/.local/{state,share,config}/syncthing/config.xml`
- Servicio del sistema: `/var/lib/syncthing/.local/state/syncthing/config.xml`

En un remoto también puedes deducir la ruta real desde el **proceso en ejecución**: inspecciona
`/proc/<pid>` buscando un argumento `--home=`/`-home`, o lee el `ExecStart` de la unidad systemd.
El proceso es más fiable que adivinar.

La API key es el elemento `<gui><apikey>` de ese XML; el puerto de la GUI/API es el `address` del
`<gui>`. Así arrancas un cliente de API cuando la key no se conoce aún.

## Roles de envío/recepción

Una carpeta tiene un **type** por nodo:
- `sendreceive` (por defecto) — bidireccional.
- `sendonly` — este nodo empuja, ignora los cambios entrantes.
- `receiveonly` — este nodo acepta, nunca empuja sus cambios locales.

Cuando modelas la topología, el rol vive en la copia de la config de carpeta de cada nodo, así que
un "enlace" entre dos nodos puede ser asimétrico (A sendonly ↔ B receiveonly). Reconcilia leyendo
cada lado, no asumiendo simetría.

## Flujo de aceptación pendiente

Compartir es **consentimiento mutuo**. Cuando A comparte una carpeta con B, B no la recibe
automáticamente — B la ve en `GET /rest/cluster/pending/folders` y debe aceptar (añadir la carpeta,
o añadir a A a su lista de dispositivos). Igualmente, un dispositivo nuevo aparece en
`pending/devices` hasta que se acepta.

Por eso "cambiar el ID de carpeta en todo el clúster" no puede ser totalmente desatendido para
dispositivos que no alcanzas por programa: alguien/algo tiene que aceptar en el otro extremo. La
respuesta de la herramienta es el **agente** (ejecutar código localmente en ese dispositivo) o la
**exploración pasiva** (esperar y aplicar en el momento en que el dispositivo reconecte a un nodo
que *sí* controlas).

## .stfolder y .stignore

- **`.stfolder`** es un directorio marcador que Syncthing crea dentro de una carpeta para probar
  que la ruta existe y es la carpeta prevista. Tras mover un directorio puede que tengas que
  asegurarte de que está. También sirve de marcador de seguridad: las operaciones destructivas lo
  comprueban antes de tocar un árbol, para no hacer `rm -rf` de una ruta arbitraria.
- **`.stignore`** contiene los patrones de exclusión. Léelo/reemplázalo con
  `GET`/`POST /rest/db/ignores` (reemplaza, no añade).

## Carpetas cifradas

Syncthing admite carpetas no-confiables/cifradas (una contraseña por compartición). Si lees la
config de carpeta de forma genérica, no asumas que todos los pares tienen texto plano — la vista
de un par cifrado es distinta. El payload del agente de este proyecto puede ir cifrado de forma
independiente a eso (ver [integration-patterns.es.md](integration-patterns.es.md#encryption)).

## Versionado y reinicios

- Los cambios de config vía REST son en vivo; en general **no** reinicias Syncthing.
- El único caso que necesita reinicio es la vía legacy de editar `config.xml` (Syncthing < 1.12, o
  sin canal REST en absoluto): editas el XML y luego reinicias el servicio para que lo cargue.
