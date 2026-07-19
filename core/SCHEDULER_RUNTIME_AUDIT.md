# Scheduler runtime audit

## Summary
- The Core lifespan was still invoking the legacy scheduler surface `start()` and `stop()` even though the runtime compatibility layer and the active scheduler implementation expose `start_worker()` and `stop_worker()`.
- The startup and shutdown paths now use a dedicated compatibility layer in `core.app` that prefers the worker API and only falls back to the older methods when they are actually available.

## What changed
- Added `_start_scheduler()` and `_stop_scheduler()` helpers in `server/core/app.py`.
- Replaced the legacy scheduler startup/shutdown calls in the lifespan context with these helpers.
- Preserved defensive logging so missing scheduler implementations do not break runtime startup or shutdown.

## Validation
- Verified via direct Python execution with `PYTHONPATH=/etc/neronOS/server`:
  - startup helper invoked `start_worker()`
  - shutdown helper invoked `stop_worker()`
  - legacy `start()` and `stop()` were not called
