# Windows Task Scheduler — daily jobcut run

Schedule `jobcut pull --read` to run every morning with the built-in Task
Scheduler. Replace the placeholders with your own paths.

- `{{JOBCUT_BIN}}` — output of `where jobcut` (e.g. `C:\Users\you\.venv\Scripts\jobcut.exe`)
- `{{DATA_DIR}}` — your data dir (holds `searches\`, `config\`, the `.db` and `out\`)

## Option A — PowerShell (run once, as your user)

```powershell
$action  = New-ScheduledTaskAction -Execute "{{JOBCUT_BIN}}" -Argument "pull --read" -WorkingDirectory "{{DATA_DIR}}"
$trigger = New-ScheduledTaskTrigger -Daily -At 7:20am
$env     = @{ "JOBCUT_DATA_DIR" = "{{DATA_DIR}}" }   # set this as a user env var if the task ignores it
Register-ScheduledTask -TaskName "jobcut-daily" -Action $action -Trigger $trigger -Description "Daily jobcut pull"
```

> Set `JOBCUT_DATA_DIR` as a user environment variable (System → Environment
> Variables) so the scheduled task picks up your data directory.

## Option B — GUI

1. Open **Task Scheduler** → **Create Task**.
2. **Triggers** → New → Daily at 07:20.
3. **Actions** → New → Program: `{{JOBCUT_BIN}}`, Arguments: `pull --read`,
   Start in: `{{DATA_DIR}}`.
4. Save. Use `pull` without `--read` only when you intend a paid scrape.
