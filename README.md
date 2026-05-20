# slack_discord_monitor

Monitor and filter Slack and Discord messages **without any API access, bot tokens, or admin permissions** — just run it on your Mac.

Captures notifications directly from the macOS Notification Center database, filters by channel and stock symbol, and forwards matched alerts to **OpenClaw** for downstream processing. Works with any Slack workspace or Discord server you're already a member of, no special access required.

## Requirements

- macOS 13+ (Ventura or later)
- Python 3.11+
- **Full Disk Access** granted to your terminal app (Warp, iTerm, Terminal):
  `System Settings > Privacy & Security > Full Disk Access`
- `openclaw_notify.py` (local module, same directory — required even if openclaw is disabled)

## Quick start

```bash
# Clone and run
git clone git@github.com:robert-ko/slack_discord_monitor.git
cd slack_discord_monitor

# Create a config file
python3 notification_monitor.py --init-config

# Edit notification_monitor_config.json to set your channels, then:
python3 notification_monitor.py
```

## Usage

```bash
# Default: monitor Slack + Discord using notification_monitor_config.json
python3 notification_monitor.py

# Show 20 most recent notifications and exit
python3 notification_monitor.py --recent 20

# Monitor specific apps
python3 notification_monitor.py --apps Slack Discord Messages

# Change poll interval to 1 second
python3 notification_monitor.py --poll 1.0

# Filter by channel keyword (overrides config per-app filters)
python3 notification_monitor.py --channel ___main_trading_chat

# Create a sample config file
python3 notification_monitor.py --init-config

# Reset the notification DB before starting (see below)
python3 notification_monitor.py --reset-db

# Test openclaw integration
python3 notification_monitor.py --test-openclaw
```

## Config file

Default path: `notification_monitor_config.json` (same directory as the script).
Use `--init-config` to generate a sample, or create manually:

```json
{
  "_comment": "Channels grouped by app. Use '*' to show all from that app.",
  "poll_interval": 2.0,
  "log_dir": "notification_logs",
  "dismiss_after_capture": false,
  "stock_symbol_filter": true,
  "stock_symbol_exclude_file": "stock_symbol_exclude.txt",
  "alert_keywords": ["halt", "resume"],
  "openclaw_enabled": false,
  "slack": ["___main_trading_chat", "_after_hours"],
  "discord": ["*"]
}
```

| Key | Type | Description |
|-----|------|-------------|
| `poll_interval` | float | Seconds between DB polls (default: 2.0) |
| `log_dir` | string | Directory for notification logs (relative to script or absolute) |
| `dismiss_after_capture` | bool | Delete DB records after reading to prevent overflow (default: false) |
| `stock_symbol_filter` | bool | Only surface notifications containing 3–4 letter stock symbols (default: false) |
| `stock_symbol_exclude_file` | string | Word exclusion list for symbol filter (default: `stock_symbol_exclude.txt`) |
| `alert_keywords` | list | Keywords that always trigger even without stock symbols (case-insensitive) |
| `openclaw_enabled` | bool | Forward matched notifications to openclaw (default: false) |
| `slack` / `discord` / … | list | Channel filter list per app; `["*"]` matches all channels |

## --reset-db flag

Kills the `usernoted` daemon (the process that owns the Notification Center SQLite DB)
so it restarts with a clean DB state, clearing accumulated stale notifications.

```bash
python3 notification_monitor.py --reset-db
```

**What it does:**
1. Runs `killall usernoted` — the daemon restarts automatically within ~1 second.
2. Queries the `app` table; Slack/Discord re-register immediately after restart
   (no waiting required in normal use).
3. Proceeds to the normal polling loop.

**Note on daemons:** `usernoted` owns the DB. `usernotificationsd` only handles
the delivery pipeline — killing it does **not** clear the DB.

**Note:** Normal startup already ignores pre-existing notifications via
`last_rec_id` tracking. Use `--reset-db` only when you also want to flush
the DB itself.

## Logging

Notifications are written to `log_dir/<app>/<YYYY-MM-DD>_<channel>.log`:

```
[2025-09-12 09:31:04] New message in #___main_trading_chat
  MLEC halted  [MLEC; kw:halt]
```

## How it works

macOS stores all delivered notifications in a SQLite database at:

```
~/Library/Group Containers/group.com.apple.usernoted/db2/db
```

The monitor opens this database read-only and polls the `record` table for new
rows matching the configured app bundle IDs. Each record contains a binary plist
with the notification title, body, thread ID, and timestamp. On startup,
`MAX(rec_id)` is recorded so only new notifications are surfaced.

## Troubleshooting

**"Cannot open notification database"**  
Grant Full Disk Access to your terminal app:
`System Settings > Privacy & Security > Full Disk Access`

**"No matching apps found"**  
Slack or Discord has not yet registered with `usernotificationsd`. Send a test
message in either app to trigger registration, then restart the monitor.

**Notifications missed / overflow**  
macOS limits ~20 notifications per app in the `record` table. Enable
`"dismiss_after_capture": true` in config to delete records after reading.

## Files

| File | Description |
|------|-------------|
| `notification_monitor.py` | Main monitoring script |
| `notification_monitor_config.json` | Channel/app filter config |
| `stock_symbol_exclude.txt` | Words excluded from stock symbol detection |
| `notification_logs/` | Per-app, per-channel log files (auto-created) |
| `openclaw_notify.py` | Local notification forwarding module |
