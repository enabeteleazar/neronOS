# Runtime audit report — Core isolation

Date: 2026-07-18
Scope: /etc/neronOS/server/core only
Branch: develop

## Problems found

- The main application entrypoint imported router variables that were never defined after the runtime cleanup, causing `import app` to fail with `NameError` during startup.
- The core app still assumed optional routers and external modules were always present, which made startup brittle when legacy or unavailable routes were imported.
- The configuration path layout was partly legacy-oriented; the canonical runtime path is now `core.config.paths`, and the existing configuration modules were verified against that contract.

## Corrections applied

- Reworked the core app bootstrap to resolve routers lazily and defensively.
- Registered only routers that can actually be imported; missing or legacy routes are now skipped instead of crashing the runtime.
- Kept the core runtime self-contained by preserving the available functionality while isolating optional integrations.
- Verified that the configuration stack uses the canonical `core.config.paths` location.

## Files modified

- server/core/app.py

## Files verified without modification

- server/core/config.py
- server/core/config_loader.py
- server/core/config/paths.py

## Commands executed

- `cd /etc/neronOS/server/core && python3 -m compileall .`
- `cd /etc/neronOS/server/core && python3 -c "import app"`
- `cd /etc/neronOS/server/core && python3 - <<'PY' ... PY`

## Test results

- `compileall` completed successfully.
- `import app` completed successfully without raising import-time errors.

## Remaining intentionally non-corrected points

- Optional routers that depend on external or legacy integrations remain disabled when their modules are not present. This preserves startup stability while avoiding hard runtime failures.
- No changes were made outside /etc/neronOS/server/core, and no submodules were modified.
