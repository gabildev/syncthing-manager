# Documentación

> 🌐 [English](README.md) · **Español**  ·  guía de usuario: [English](../README.md) · [Español](../README.es.md)

Notas de referencia para construir herramientas sobre **Syncthing**. Están escritas para ser
reutilizables más allá de este proyecto — destiladas del trabajo de integración de
`syncthing-manager`, con las trampas ganadas a pulso señaladas para que una app futura no las
reaprenda. Cada nota es bilingüe (inglés `.md` · español `.es.md`).

| Doc | Qué contiene |
|---|---|
| [syncthing-rest-api.es.md](syncthing-rest-api.es.md) · [EN](syncthing-rest-api.md) | Los endpoints de la API REST que este proyecto realmente usa — método, parámetros, forma de retorno y la trampa de cada uno. Una chuleta práctica, no la especificación oficial completa. |
| [syncthing-concepts.es.md](syncthing-concepts.es.md) · [EN](syncthing-concepts.md) | Modelo mental + trampas: IDs de dispositivo/carpeta, por qué el ID de carpeta es inmutable, ubicaciones de `config.xml` por SO, detección de API-key, roles envío/recepción, aceptación pendiente, `.stignore`/`.stfolder`. |
| [integration-patterns.es.md](integration-patterns.es.md) · [EN](integration-patterns.md) | Patrones de ingeniería que vale la pena reutilizar: alcanzar dispositivos por API/SSH/WinRM/pasiva/agente, descubrimiento + expansión por hub, binarios de agente auto-extensibles, almacenamiento cifrado de credenciales, empaquetado de arranque rápido. |

> Referencia oficial de la API (autoritativa): <https://docs.syncthing.net/dev/rest.html>
> Referencia de configuración: <https://docs.syncthing.net/users/config.html>

La fuente de verdad es siempre el código (`syncthing_manager/syncthing.py` para el cliente de API,
`renamer.py` para la orquestación). Cuando estos docs y el código discrepen, gana el código —
actualiza el doc.
