app.py		→ Point d'entrée principal de Néron.
api/		→ Les routes et services HTTP.
gateway/	→ Entrees HTTP / Telegram / WebSocket
pipeline/	→ Intent / NLP / routing agents
orchestration/	→ Dispatch Central
runtime/	→ Governor + Sandbox
control_plane/	→ Supervision / Lifecycle / Registre
storage/	→ sqLite
identity/	→ Identité + Personnalité de Neron
logging/	→ Centralise les journaux et diagnostics.
config.py	→ Configuration système.
config_loader.py→ Charge la config + env.
constants.py	→ Constantes globales du système.
status.py	→ Fournit l'état courant de Néron.

