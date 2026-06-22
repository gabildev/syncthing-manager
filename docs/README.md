# Documentation

> 🌐 **English** · [Español](README.es.md)  ·  user-facing guide: [English](../README.md) · [Español](../README.es.md)

Reference notes for building tools on top of **Syncthing**. These are written to be reusable
beyond this project — distilled from the integration work in `syncthing-manager`, with the
hard-won gotchas called out so a future app doesn't relearn them. Each note is bilingual
(English `.md` · Spanish `.es.md`).

| Doc | What's in it |
|---|---|
| [syncthing-rest-api.md](syncthing-rest-api.md) · [ES](syncthing-rest-api.es.md) | The REST API endpoints this project actually uses — method, params, return shape, and the catch for each. A practical cheat-sheet, not the full upstream spec. |
| [syncthing-concepts.md](syncthing-concepts.md) · [ES](syncthing-concepts.es.md) | Mental model + gotchas: device/folder IDs, why the folder ID is immutable, `config.xml` locations per OS, API-key detection, send/receive roles, pending acceptance, `.stignore`/`.stfolder`. |
| [integration-patterns.md](integration-patterns.md) · [ES](integration-patterns.es.md) | Engineering patterns worth reusing: reaching devices over API/SSH/WinRM/passive/agent, discovery + hub expansion, self-extending agent binaries, encrypted credential storage, fast-startup packaging. |

> Upstream API reference (authoritative): <https://docs.syncthing.net/dev/rest.html>
> Config reference: <https://docs.syncthing.net/users/config.html>

The source of truth is always the code (`syncthing_manager/syncthing.py` for the API client,
`renamer.py` for the orchestration). When these docs and the code disagree, the code wins —
update the doc.
