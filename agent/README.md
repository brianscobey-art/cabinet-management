# Order Pack agent

The Order Pack board and its Run buttons live in the cloud, at
<https://cabinettron.com/ordering-platform/pack>. But the actual work — the
OneDrive folders, the PDFs, desktop Outlook, the logged-in VendorSuite session —
only exists on Brian's PC. This agent is the bridge.

The cloud never reaches down into the PC. The agent reaches **up**: it asks the
server "anything queued for me?", does the work locally, and reports back.

## What it does today (Phase A)

1. **Scans the folder chain.** Every `ORDERPACK_SCAN_MINUTES` (default 15) it
   walks `Sold Jobs\New Orders` and reports which job folder is sitting in which
   stage folder, with a list of the files inside each. That is what makes the
   board show physical reality instead of a checkbox somebody forgot to tick.
2. **Runs queued commands.** Pressing *Scan folders now* on the page queues a
   run; the agent claims it, streams its output back line by line, and marks it
   done or failed.

Stage automation arrives in later phases (stage 4 first). Until then the agent
fails an unknown run kind loudly rather than leaving it stuck on "running".

## Starting it

```
start_orderpack_agent.bat
```

That launches it hidden with `pythonw` (no console window). `watchdog.py`
also restarts it automatically if it ever dies, so putting the watchdog in your
logon tasks covers both the app and the agent.

To stop a hidden one, create an empty file named `orderpack_agent.stop` in this
folder — the agent notices it on the next poll and exits.

Useful one-offs:

```
python agent\orderpack_agent.py --once
```

runs a single scan and exits (handy for checking the connection).

## Settings

Read from environment variables first, then `backend\.env`, then the defaults
baked into the script.

| Variable | Default | What it is |
|---|---|---|
| `ORDERPACK_API_BASE` | `https://www.cabinettron.com` | Where to report. Must be the canonical host — the bare `cabinettron.com` 301-redirects to `www`, and a redirected POST silently becomes a GET. The agent refuses to follow redirects so a wrong value fails loudly. Point at `http://localhost:8000` to test against a local backend. |
| `ORDERPACK_AGENT_KEY` | (built-in dev key) | Shared secret. **Must match the server's** `ORDERPACK_AGENT_KEY`. Change it from the default on both sides. |
| `NEW_ORDERS_DIR` | the OneDrive New Orders folder | Root holding the four stage folders. |
| `ORDERPACK_SCAN_MINUTES` | `15` | How often to scan on its own. `0` = only when asked. |
| `ORDERPACK_POLL_SECONDS` | `20` | How often to check for queued runs. |

## Log

`agent\orderpack_agent.log`, next to this file. It is gitignored — it's local
to the PC. A `403` in the log means the agent key doesn't match the server's.

## What it will never do

- Store or ask for any password. VendorSuite uses DR Horton's WS-Fed SSO and
  Brian signs on himself; stage 1 will depend on that session already being live.
- Touch the deprecated `Sold Jobs\Builders\DR Horton\...` tree.
- Invent an install pay amount. Unreadable means blank plus a note.
- Bypass the stage-4 check that the SO total equals the Carter PO total exactly.
