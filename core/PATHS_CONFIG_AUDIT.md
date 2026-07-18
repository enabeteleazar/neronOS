# Paths configuration audit

## Problem identified

The runtime path resolution in core relied on a hard-coded tree walk via `Path(__file__).resolve().parents[3]`, which ignored the official runtime environment variables and produced the wrong root/config path when NéronOS was launched under systemd or from the core directory.

## Files modified

- server/core/config/paths.py
- server/core/config.py
- server/core/config_loader.py
- server/core/app.py

## Strategy retained

1. Honor environment variables first:
   - `NERON_ROOT`
   - `NERON_CONFIG`
   - `NERON_IDENTITY_PATH`
2. Fall back to automatic project-tree discovery when those variables are absent.
3. Keep the legacy compatibility aliases exposed through `core.config.paths` intact.

## Tests executed

- `cd /etc/neronOS/server/core && PYTHONPATH=/etc/neronOS/server python3 - <<'PY' ... PY`
- `cd /etc/neronOS/server/core && PYTHONPATH=/etc/neronOS/server python3 - <<'PY' from app import app ... PY`
