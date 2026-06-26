---
name: jobcut-open
description: >-
  Start the jobcut web console from chat — no terminal. Use when the user says
  "open jobcut", "abrí jobcut", "launch the jobcut app", "levantá la consola", or
  "start jobcut". Launches `jobcut serve` in the background (taking over a stale
  server if needed) and gives back the URL to open.
---

# jobcut-open

Starts the jobcut web console for the user so they never touch the terminal. The
user just says *"open jobcut"* and Claude brings the console up and hands back the
URL. Read-only on the database — it only launches the server.

**CLI-only.** No SQL, no DB edits. This skill runs `jobcut serve` (and reads the
running server). It never writes to `jobcut.db`.

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works).
- Run from the **jobcut project folder**, or have `JOBCUT_DATA_DIR` exported, so the
  server serves the right database.

## Steps

1. **Is it already running?** Check the default URL:
   ```
   curl -fsS -o /dev/null --max-time 1 http://127.0.0.1:8000 && echo UP || echo DOWN
   ```
   If **UP**, tell the user it's already running and give the URL — done.

2. **Launch it (detached, in the background)** so the chat isn't blocked by the
   long-running server. `--replace` takes over the port if a stale server is holding
   it (avoids "address already in use"); `--open` also opens the browser on a desktop:
   ```
   mkdir -p tmp
   nohup jobcut serve --replace --open > tmp/serve.log 2>&1 &
   ```

3. **Wait until it's serving** (poll the log / the port, ~20s max):
   ```
   for i in $(seq 1 20); do
     grep -q "serving the built" tmp/serve.log 2>/dev/null && break
     curl -fsS -o /dev/null --max-time 1 http://127.0.0.1:8000 && break
     sleep 1
   done
   ```

4. **Report the URL.** Tell the user the console is up at **http://127.0.0.1:8000**
   (API docs at `/docs`). On a desktop the browser opens automatically; otherwise the
   user clicks the URL. The console reads the DB per request, so it always shows the
   latest data.

## Notes

- One process owns the port. If the user keeps asking and it's already up, just give
  the URL (step 1) instead of relaunching.
- `--replace` only restarts the **server** (frees the port and takes over) — it does
  not touch any data.
- Prefer this for "open the app". To *also* pull/score new jobs first, use
  `jobcut-daily`; to decide what to apply to, `jobcut-review` (which can also open the
  console). For a permanent double-click launcher without chat, the CLI command
  `jobcut shortcut` writes a desktop launcher.
- Hard-codes no path — everything resolves from the working directory or
  `JOBCUT_DATA_DIR`.
