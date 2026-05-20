# Notification Monitor

Monitors macOS Notification Center in real time for Slack and Discord messages,
filtering by channel and optionally detecting stock symbols or alert keywords.
Reads directly from the Notification Center SQLite database without AppleScript
or Accessibility APIs.

## Requirements

- macOS 13+ (Ventura or later)
- Python 3.11+
- **Full Disk Access** granted to your terminal app (Warp, iTerm, Terminal):
  `System Settings > Privacy & Security > Full Disk Access`
- `openclaw_notify` module (local, same directory)

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

## Config File

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

### Config keys

| Key | Type | Description |
|-----|------|-------------|
| `poll_interval` | float | Seconds between DB polls (default: 2.0) |
| `log_dir` | string | Directory for notification logs (relative to script dir or absolute) |
| `dismiss_after_capture` | bool | Delete records from DB after capturing to prevent overflow (default: false) |
| `stock_symbol_filter` | bool | Only surface notifications containing 3–4 letter stock symbols (default: false) |
| `stock_symbol_exclude_file` | string | Path to word exclusion list for stock symbol filter (default: `stock_symbol_exclude.txt`) |
| `alert_keywords` | list | Keywords that always trigger even without stock symbols (case-insensitive) |
| `openclaw_enabled` | bool | Forward matched notifications to openclaw (default: false) |
| `slack` / `discord` / ... | list | Channel filter list per app; use `["*"]` to match all channels |

## Logging

Notifications are written to `log_dir/<app>/<YYYY-MM-DD>_<channel>.log`:

```
[2025-09-12 09:31:04] New message in #___main_trading_chat
  MLEC halted  [MLEC; kw:halt]
```

## --reset-db flag

Kills the `usernotificationsd` daemon so it restarts with a clean DB state,
clearing any accumulated stale notifications before the monitor begins polling.

```bash
python3 notification_monitor.py --reset-db
```

**What it does:**
1. Runs `killall usernotificationsd` — the daemon restarts automatically.
2. Polls the `app` table for up to 60 seconds (printing dots) waiting for
   Slack/Discord to re-register their notification permissions with the daemon.
   Re-registration happens the next time either app delivers a notification,
   so sending yourself a test message in Slack/Discord will unblock it immediately.
3. Once apps are registered, starts the normal polling loop.

**When to use it:**
- The notification DB has accumulated a large backlog of old records.
- You want to guarantee the monitor sees only notifications delivered after startup.

**Note:** Normal startup (without `--reset-db`) already ignores pre-existing
notifications via `last_rec_id` tracking, so this flag is only needed if you
also want to flush the DB itself.

## How it works

The macOS Notification Center stores all delivered notifications in a SQLite
database at:

```
~/Library/Group Containers/group.com.apple.usernoted/db2/db
```

The monitor opens this database read-only and polls the `record` table for new
rows matching the configured app bundle IDs. Each record contains a binary plist
(`data` column) with the notification title, body, thread ID, and timestamp.

## Troubleshooting

**"Cannot open notification database"**
Terminal app does not have Full Disk Access. Grant it in:
`System Settings > Privacy & Security > Full Disk Access`

**"No matching apps found"**
Slack or Discord has not yet registered with `usernotificationsd`. This is normal
after a fresh macOS boot or after using `--reset-db`. Send a test message in
Slack/Discord to trigger registration, then restart the monitor.

**Notifications missed / overflow**
macOS limits ~20 notifications per app in the `record` table. Enable
`"dismiss_after_capture": true` in config to delete records after reading,
preventing overflow.

## Files

- `notification_monitor.py` — Main monitoring script
- `notification_monitor_config.json` — Channel/app filter config
- `stock_symbol_exclude.txt` — Common words excluded from stock symbol detection
- `notification_logs/` — Per-app, per-channel log files (auto-created)
- `openclaw_notify.py` — Local notification forwarding module
