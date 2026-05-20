#!/usr/bin/env python3
"""
macOS Notification Monitor for Slack/Discord

Monitors notifications by polling the macOS Notification Center database,
which contains the actual notification title and body text.

Usage:
    python3 notification_monitor.py              # Monitor (default: poll DB)
    python3 notification_monitor.py --recent 20  # Show 20 most recent notifications
    python3 notification_monitor.py --apps Slack Discord Messages
    python3 notification_monitor.py --poll 1.0    # Poll every 1 second

Permissions:
    - Full Disk Access (System Settings > Privacy & Security > Full Disk Access)
      must be granted to Terminal / iTerm / Warp (whichever you run this from).
"""

import sqlite3
import json
import os
import re
import plistlib
import argparse
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openclaw_notify import notify as openclaw_notify


# macOS Notification Center database path (macOS 13+)
NOTIFICATION_DB_PATH = (
    Path.home() / "Library/Group Containers/group.com.apple.usernoted/db2/db"
)

# Default config file path (same directory as this script)
DEFAULT_CONFIG_PATH = Path(__file__).parent / "notification_monitor_config.json"

# App bundle identifiers we care about (lowercase for matching)
APP_IDENTIFIERS = {
    "slack": "com.tinyspeck.slackmacgap",
    "discord": "com.hnc.discord",
}


def load_config(config_path: Path | None = None) -> dict:
    """Load configuration from a JSON file.
    
    Config format:
        {
            "poll_interval": 2.0,
            "slack": ["___main_trading_chat", "_after_hours"],
            "discord": ["*"]     // "*" means show all from that app
        }
    
    Returns the parsed dict, or empty dict if file doesn't exist.
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            cfg = json.load(f)
        print(f"Loaded config from: {path}")
        return cfg
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not load config {path}: {e}")
        return {}


# Config keys that are settings, not app names
_CONFIG_RESERVED_KEYS = {
    "_comment", "poll_interval", "log_dir", "dismiss_after_capture",
    "stock_symbol_filter", "stock_symbol_exclude_file",
    "alert_keywords",
    "openclaw_enabled",
}

# Regex for potential stock symbols: standalone 3-4 uppercase letters
_STOCK_SYMBOL_RE = re.compile(r'\b[A-Z]{3,4}\b')


def load_exclude_words(filepath: Path | None) -> set[str]:
    """Load exclusion words from a text file (one word per line, # comments)."""
    if not filepath or not filepath.exists():
        return set()
    words = set()
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                words.add(line.upper())
    return words


def detect_stock_symbols(text: str, exclude: set[str]) -> list[str]:
    """Find potential stock symbols in text.
    
    Returns a sorted, deduplicated list of 3-4 uppercase letter words
    that are NOT in the exclude set.
    """
    matches = _STOCK_SYMBOL_RE.findall(text)
    symbols = sorted(set(m for m in matches if m not in exclude))
    return symbols


def detect_alert_keywords(text: str, keywords: list[str]) -> list[str]:
    """Check if text contains any alert keywords (case-insensitive).
    
    Returns list of matched keywords.
    """
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def build_app_filters(cfg: dict) -> dict[str, list[str]]:
    """Build a mapping of app_name -> list of channel filters from config.
    
    Returns e.g.:
        {"slack": ["___main_trading_chat"], "discord": ["*"]}
    
    Keys are lowercase app names. A channel list of ["*"] means show all.
    Only includes apps that have an entry in the config.
    """
    filters = {}
    for key, value in cfg.items():
        if key.startswith("_") or key in _CONFIG_RESERVED_KEYS:
            continue
        if isinstance(value, list):
            filters[key.lower()] = value
    return filters


def create_default_config(config_path: Path | None = None):
    """Write a sample config file."""
    path = config_path or DEFAULT_CONFIG_PATH
    sample = {
        "_comment": "Channels grouped by app. Use '*' to show all from an app. Logs saved to log_dir/app/YYYY-MM-DD_channel.log",
        "poll_interval": 2.0,
        "log_dir": "notification_logs",
        "slack": [
            "___main_trading_chat",
        ],
        "discord": [
            "mainchannel",
        ],
    }
    with open(path, "w") as f:
        json.dump(sample, f, indent=2)
    print(f"Created sample config: {path}")
    print("Edit it to add/remove channels per app, then re-run.")

# macOS Core Data epoch: 2001-01-01 00:00:00 UTC
# delivered_date values are seconds since this epoch
CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def core_data_to_datetime(timestamp: float) -> datetime:
    """Convert macOS Core Data timestamp to datetime."""
    from datetime import timedelta
    return CORE_DATA_EPOCH + timedelta(seconds=timestamp)


def find_notification_db() -> Optional[Path]:
    """Find an accessible notification database."""
    if NOTIFICATION_DB_PATH.exists():
        try:
            conn = sqlite3.connect(f"file:{NOTIFICATION_DB_PATH}?mode=ro", uri=True)
            conn.execute("SELECT 1")
            conn.close()
            return NOTIFICATION_DB_PATH
        except sqlite3.OperationalError:
            pass
    return None


def get_app_ids(conn: sqlite3.Connection, app_names: list[str]) -> dict[int, str]:
    """
    Look up app_id -> display_name mapping for the requested apps.
    Matches against the 'identifier' column in the 'app' table.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT app_id, identifier FROM app")
    rows = cursor.fetchall()

    # Build set of bundle-id substrings to match
    match_terms = []
    for name in app_names:
        low = name.lower()
        if low in APP_IDENTIFIERS:
            match_terms.append(APP_IDENTIFIERS[low])
        else:
            match_terms.append(low)

    result = {}
    for app_id, identifier in rows:
        ident_low = (identifier or "").lower()
        if any(term in ident_low for term in match_terms):
            result[app_id] = identifier
    return result


def parse_notification(data_blob: bytes) -> dict:
    """
    Parse the plist data blob from a notification record.
    Returns dict with 'app', 'title', 'body', 'thread', 'date'.
    """
    try:
        parsed = plistlib.loads(data_blob)
    except Exception:
        return {}

    req = parsed.get("req", {})
    result = {
        "app": parsed.get("app", "?"),
        "title": req.get("titl", ""),
        "body": req.get("body", ""),
        "thread": req.get("thre", ""),
        "iden": req.get("iden", ""),
    }

    # Convert Core Data date if present
    raw_date = parsed.get("date")
    if raw_date:
        try:
            result["date"] = core_data_to_datetime(raw_date)
        except Exception:
            result["date"] = None
    return result


def matches_filter(
    notif: dict,
    app_filters: dict[str, list[str]] | None,
    channels: list[str] | None = None,
) -> bool:
    """Check if a notification passes the configured filters.
    
    Args:
        notif: Parsed notification dict (has 'app', 'title', 'body').
        app_filters: From config — {"slack": ["channel1"], "discord": ["*"]}.
        channels: From --channel CLI flag (flat keyword list, legacy behavior).
    
    If neither app_filters nor channels is set, everything matches.
    """
    # CLI --channel flag takes priority (flat keyword match, any app)
    if channels:
        title = (notif.get("title", "") or "").lower()
        body = (notif.get("body", "") or "").lower()
        text = title + " " + body
        return any(ch.lower() in text for ch in channels)

    # Config-based per-app filters
    if not app_filters:
        return True

    app_id = (notif.get("app", "") or "").lower()
    # Figure out which app name this notification belongs to
    matched_app = None
    for app_name, bundle_id in APP_IDENTIFIERS.items():
        if bundle_id in app_id or app_name in app_id:
            matched_app = app_name
            break

    if matched_app is None:
        # Unknown app — only show if no filters are configured
        return False

    if matched_app not in app_filters:
        # App exists but isn't in the config — skip it
        return False

    channel_list = app_filters[matched_app]
    if "*" in channel_list:
        return True

    # Match channel names against title + body
    title = (notif.get("title", "") or "").lower()
    body = (notif.get("body", "") or "").lower()
    text = title + " " + body
    return any(ch.lower() in text for ch in channel_list)


def detect_channel(notif: dict) -> str:
    """Extract a channel name from the notification title.
    
    Slack titles look like: "New message in #___main_trading_chat"
    Discord titles look like: "⁨User⁩ (⁨#mainchannel⁩, ⁨Category⁩)"
    
    Returns a filesystem-safe channel name, or 'unknown'.
    """
    title = notif.get("title", "") or ""
    
    # Slack: "New message in #channel_name"
    m = re.search(r"#([\w_-]+)", title)
    if m:
        return m.group(1)
    
    # Discord: look for channel between special chars  ⁨#name⁩
    # The invisible chars are U+2068 / U+2069
    m = re.search(r"[#\u2068]([^\u2069,()]+)", title)
    if m:
        raw = m.group(1).strip().strip("#")
        # Strip emoji prefixes like 💊┃  or 🏅┃
        raw = re.sub(r"^[^\w]+┃", "", raw)
        if raw:
            # Make filesystem-safe
            return re.sub(r"[^\w-]+", "_", raw).strip("_") or "unknown"
    
    return "unknown"


def resolve_app_name(notif: dict) -> str:
    """Return a short app name like 'slack' or 'discord'."""
    app_id = (notif.get("app", "") or "").lower()
    for app_name, bundle_id in APP_IDENTIFIERS.items():
        if bundle_id in app_id or app_name in app_id:
            return app_name
    return app_id.rsplit(".", 1)[-1] if "." in app_id else app_id


def log_notification(notif: dict, log_dir: Path | None):
    """Append a notification to a log file organized as log_dir/app/YYYY-MM-DD_channel.log"""
    if not log_dir:
        return
    
    app_name = resolve_app_name(notif)
    channel = detect_channel(notif)
    dt = notif.get("date")
    date_str = dt.astimezone().strftime("%Y-%m-%d") if dt else datetime.now().strftime("%Y-%m-%d")
    ts = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S") if dt else "?"
    
    app_dir = log_dir / app_name
    app_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = app_dir / f"{date_str}_{channel}.log"
    title = notif.get("title", "")
    body = notif.get("body", "")
    symbols = notif.get("symbols")
    keywords = notif.get("keywords")
    tags = []
    if symbols:
        tags.append(', '.join(symbols))
    if keywords:
        tags.append('kw:' + ','.join(keywords))
    tag_str = f"  [{'; '.join(tags)}]" if tags else ""
    line = f"[{ts}] {title}\n  {body}{tag_str}\n"
    
    with open(log_file, "a") as f:
        f.write(line)


OPENCLAW_SOURCE = "notification_monitor"


def speak_tts(text: str):
    """Speak text aloud using macOS say command (non-blocking)."""
    try:
        subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"  (tts error: {e})")


def format_tts_text(notif: dict) -> str:
    """Format notification for TTS — keep it short and speakable."""
    parts = []
    symbols = notif.get("symbols", [])
    keywords = notif.get("keywords", [])
    if symbols:
        # Spell out each symbol letter by letter for clarity
        parts.append(", ".join(" ".join(s) for s in symbols))
    if keywords:
        parts.extend(keywords)
    return ", ".join(parts)


def send_to_openclaw(notif: dict, openclaw_enabled: bool):
    """Send a notification to openclaw if enabled."""
    if not openclaw_enabled:
        return
    app_name = resolve_app_name(notif)
    body = notif.get("body", "")
    symbols = notif.get("symbols", [])
    symbol = symbols[0] if symbols else None
    result = openclaw_notify(
        source=OPENCLAW_SOURCE,
        channel=app_name,
        message=body,
        symbol=symbol,
    )
    if not result.get("ok"):
        print(f"  (openclaw error: {result.get('error', result)})")
    # TTS after sending to openclaw
    tts_text = format_tts_text(notif)
    if tts_text:
        speak_tts(tts_text)


def dismiss_notifications(db_path: Path, rec_ids: list[int]):
    """Delete captured notification records from the DB to free up slots.
    
    macOS Notification Center limits ~20 notifications per app in the 'record' table.
    Removing captured records prevents overflow so new notifications aren't dropped.
    Also cleans related rows from 'delivered' and 'displayed' tables.
    """
    if not rec_ids:
        return
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in rec_ids)
        cursor.execute(f"DELETE FROM record WHERE rec_id IN ({placeholders})", rec_ids)
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"  (dismiss error: {e})")


def format_notification(notif: dict) -> str:
    """Pretty-print a single notification."""
    dt = notif.get("date")
    ts = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S") if dt else "?"
    app = notif.get("app", "?")
    # Shorten app identifier to just the app name
    app_short = app.rsplit(".", 1)[-1] if "." in app else app
    title = notif.get("title", "")
    body = notif.get("body", "")
    symbols = notif.get("symbols")
    keywords = notif.get("keywords")
    tags = []
    if symbols:
        tags.append(', '.join(symbols))
    if keywords:
        tags.append('kw:' + ','.join(keywords))
    tag_str = f"  [{'; '.join(tags)}]" if tags else ""
    return f"[{ts}] {app_short}: {title}\n           {body}{tag_str}"


def fetch_recent(
    db_path: Path,
    app_ids: dict[int, str],
    limit: int = 10,
    app_filters: dict[str, list[str]] | None = None,
    channels: list[str] | None = None,
    log_dir: Path | None = None,
    dismiss: bool = False,
    symbol_filter: bool = False,
    exclude_words: set[str] | None = None,
    alert_keywords: list[str] | None = None,
    openclaw_enabled: bool = False,
) -> list[dict]:
    """
    Fetch the most recent notifications for the given app IDs.
    If channels is set, only returns notifications matching those filters.
    Returns newest-first.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()

    placeholders = ",".join("?" for _ in app_ids)
    # Fetch more rows than limit when filtering, since we filter in Python
    fetch_limit = limit * 10 if (channels or app_filters) else limit
    cursor.execute(
        f"SELECT rec_id, app_id, data, delivered_date FROM record "
        f"WHERE app_id IN ({placeholders}) "
        f"ORDER BY delivered_date DESC LIMIT ?",
        list(app_ids.keys()) + [fetch_limit],
    )

    results = []
    captured_ids = []
    for rec_id, app_id, data, delivered_date in cursor.fetchall():
        notif = parse_notification(data) if data else {}
        notif["rec_id"] = rec_id
        if not notif.get("date") and delivered_date:
            notif["date"] = core_data_to_datetime(delivered_date)
        if matches_filter(notif, app_filters, channels):
            # Stock symbol filter
            if symbol_filter:
                text = (notif.get("title", "") or "") + " " + (notif.get("body", "") or "")
                symbols = detect_stock_symbols(text, exclude_words or set())
                matched_keywords = detect_alert_keywords(text, alert_keywords or [])
                if not symbols and not matched_keywords:
                    captured_ids.append(rec_id)  # still dismiss even if no symbols
                    continue
                if symbols:
                    notif["symbols"] = symbols
                if matched_keywords:
                    notif["keywords"] = matched_keywords
            results.append(notif)
            log_notification(notif, log_dir)
            send_to_openclaw(notif, openclaw_enabled)
            captured_ids.append(rec_id)
            if len(results) >= limit:
                break

    conn.close()

    if dismiss and captured_ids:
        dismiss_notifications(db_path, captured_ids)

    return results


def poll_new_notifications(
    db_path: Path,
    app_ids: dict[int, str],
    interval: float = 2.0,
    app_filters: dict[str, list[str]] | None = None,
    channels: list[str] | None = None,
    log_dir: Path | None = None,
    dismiss: bool = False,
    symbol_filter: bool = False,
    exclude_words: set[str] | None = None,
    alert_keywords: list[str] | None = None,
    openclaw_enabled: bool = False,
):
    """
    Continuously poll the database for new notifications.
    Prints each new notification as it appears.
    If dismiss=True, deletes captured records from the DB to free up slots.
    """
    # Start by getting the latest rec_id so we only show new ones
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()

    placeholders = ",".join("?" for _ in app_ids)
    cursor.execute(
        f"SELECT MAX(rec_id) FROM record WHERE app_id IN ({placeholders})",
        list(app_ids.keys()),
    )
    row = cursor.fetchone()
    last_rec_id = row[0] if row and row[0] else 0
    conn.close()

    print(f"Watching for new notifications (last seen rec_id={last_rec_id})...")
    if dismiss:
        print("Dismiss after capture: ON (notifications removed from DB after logging)")
    print(f"Polling every {interval}s. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(interval)
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT rec_id, app_id, data, delivered_date FROM record "
                    f"WHERE app_id IN ({placeholders}) AND rec_id > ? "
                    f"ORDER BY rec_id ASC",
                    list(app_ids.keys()) + [last_rec_id],
                )
                captured_ids = []
                for rec_id, app_id, data, delivered_date in cursor.fetchall():
                    notif = parse_notification(data) if data else {}
                    notif["rec_id"] = rec_id
                    if not notif.get("date") and delivered_date:
                        notif["date"] = core_data_to_datetime(delivered_date)
                    if matches_filter(notif, app_filters, channels):
                        # Stock symbol filter
                        if symbol_filter:
                            text = (notif.get("title", "") or "") + " " + (notif.get("body", "") or "")
                            symbols = detect_stock_symbols(text, exclude_words or set())
                            matched_keywords = detect_alert_keywords(text, alert_keywords or [])
                            if not symbols and not matched_keywords:
                                last_rec_id = rec_id
                                captured_ids.append(rec_id)  # still dismiss
                                continue
                            if symbols:
                                notif["symbols"] = symbols
                            if matched_keywords:
                                notif["keywords"] = matched_keywords
                        print(format_notification(notif))
                        log_notification(notif, log_dir)
                        send_to_openclaw(notif, openclaw_enabled)
                        captured_ids.append(rec_id)
                    last_rec_id = rec_id
                conn.close()
                if dismiss and captured_ids:
                    dismiss_notifications(db_path, captured_ids)
            except sqlite3.OperationalError as e:
                print(f"  (db read error: {e}, retrying...)")
    except KeyboardInterrupt:
        print("\nStopped.")


def reset_notification_db():
    """Kill usernotificationsd so it restarts with a fresh DB state.

    This clears any stale/queued notifications from the Notification Center
    database before we start polling. The daemon restarts automatically.
    """
    result = subprocess.run(
        ["killall", "usernotificationsd"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("Killed usernotificationsd — waiting for restart...")
        time.sleep(1)  # brief pause; app re-registration is handled by retry loop
    else:
        # Process wasn't running or no permission — not fatal
        print(f"Note: could not kill usernotificationsd ({result.stderr.strip()})")


def check_full_disk_access() -> bool:
    """Check if we likely have Full Disk Access."""
    test_path = Path.home() / "Library/Mail"
    try:
        list(test_path.iterdir())
        return True
    except PermissionError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Monitor Slack/Discord notifications on macOS (reads Notification Center DB)"
    )
    parser.add_argument(
        "--recent", type=int, metavar="N", default=0,
        help="Show N most recent notifications and exit",
    )
    parser.add_argument(
        "--apps", nargs="+", default=None,
        help="Apps to monitor (default: from config or Slack Discord)",
    )
    parser.add_argument(
        "--poll", type=float, metavar="SECS", default=None,
        help="Polling interval in seconds (default: from config or 2.0)",
    )
    parser.add_argument(
        "--channel", nargs="+", metavar="FILTER", default=None,
        help="Filter by channel name or keyword in title/body (case-insensitive). "
             "Multiple values are OR'd. E.g.: --channel ___main_trading_chat",
    )
    parser.add_argument(
        "--config", type=Path, metavar="FILE", default=None,
        help=f"Path to config JSON file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--init-config", action="store_true",
        help="Create a sample config file and exit",
    )
    parser.add_argument(
        "--test-openclaw", action="store_true",
        help="Send a test notification to openclaw and exit",
    )
    parser.add_argument(
        "--reset-db", action="store_true",
        help="Kill usernotificationsd to clear stale notifications, then wait for apps to re-register (may take 15s+)",
    )
    args = parser.parse_args()

    # Handle --init-config
    if args.init_config:
        create_default_config(args.config)
        return

    print("macOS Notification Monitor")
    print("=" * 60)

    # Load config file (CLI args override config values)
    cfg = load_config(args.config)
    app_filters = build_app_filters(cfg)
    # Which apps to query from the DB
    if args.apps:
        apps = args.apps
    elif app_filters:
        apps = list(app_filters.keys())
    else:
        apps = ["Slack", "Discord"]
    channels = args.channel  # CLI-only flat filter (overrides config per-app filters)
    poll_interval = args.poll if args.poll is not None else cfg.get("poll_interval", 2.0)
    dismiss = cfg.get("dismiss_after_capture", False)
    symbol_filter = cfg.get("stock_symbol_filter", False)
    exclude_words = set()
    if symbol_filter:
        exclude_file_raw = cfg.get("stock_symbol_exclude_file", "stock_symbol_exclude.txt")
        exclude_path = Path(exclude_file_raw)
        if not exclude_path.is_absolute():
            exclude_path = Path(__file__).parent / exclude_path
        exclude_words = load_exclude_words(exclude_path)
        print(f"Stock symbol filter: ON ({len(exclude_words)} excluded words from {exclude_path.name})")
    # Alert keywords (always trigger even without stock symbols)
    alert_keywords = cfg.get("alert_keywords", [])
    if alert_keywords:
        print(f"Alert keywords: {', '.join(alert_keywords)}")
    # Openclaw integration
    openclaw_enabled = cfg.get("openclaw_enabled", False)
    if openclaw_enabled:
        print("Openclaw: ON (via openclaw_notify module)")

    # Handle --test-openclaw
    if args.test_openclaw:
        print(f"Sending test via openclaw_notify...")
        result = openclaw_notify(
            source=OPENCLAW_SOURCE,
            channel="slack",
            message="MLEC halt down",
            symbol="MLEC",
        )
        print(f"Result: {result}")
        speak_tts("M L E C")
        return
    # Log directory (relative to script dir, or absolute)
    log_dir_raw = cfg.get("log_dir")
    log_dir = None
    if log_dir_raw:
        log_dir = Path(log_dir_raw)
        if not log_dir.is_absolute():
            log_dir = Path(__file__).parent / log_dir
        print(f"Logging to: {log_dir}")

    # Check permissions
    has_fda = check_full_disk_access()
    print(f"Full Disk Access: {'Yes' if has_fda else 'No (limited functionality)'}")

    # Optionally kill usernotificationsd to clear stale notifications
    if args.reset_db:
        reset_notification_db()

    # Find database
    db_path = find_notification_db()
    if not db_path:
        print("\nERROR: Cannot open notification database.")
        print("Grant Full Disk Access to your terminal app in:")
        print("  System Settings > Privacy & Security > Full Disk Access")
        return

    print(f"Database: {db_path}")

    # Resolve app IDs — if --reset-db was used, retry until apps re-register (or 60s timeout)
    app_ids = {}
    max_attempts = 60 if args.reset_db else 1
    for attempt in range(max_attempts):
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        app_ids = get_app_ids(conn, apps)
        conn.close()
        if app_ids:
            break
        if args.reset_db:
            if attempt == 0:
                print("Waiting for apps to register with notification daemon...", end="", flush=True)
            else:
                print(".", end="", flush=True)
            time.sleep(1)
    if not app_ids:
        if args.reset_db:
            print()  # newline after dots
        print(f"\nNo matching apps found for: {apps}")
        print("Known mappings:")
        for name, ident in APP_IDENTIFIERS.items():
            print(f"  {name} -> {ident}")
        return
    if args.reset_db and attempt > 0:
        print()  # newline after dots

    print(f"Matched apps: {app_ids}")
    if channels:
        print(f"Channel filter (CLI): {channels}")
    elif app_filters:
        for app_name, ch_list in app_filters.items():
            label = "all" if "*" in ch_list else ", ".join(ch_list)
            print(f"  {app_name}: {label}")
    print()

    if args.recent > 0:
        # One-shot: show recent notifications (don't dismiss on --recent)
        notifications = fetch_recent(db_path, app_ids, limit=args.recent, app_filters=app_filters, channels=channels, log_dir=log_dir, dismiss=False, symbol_filter=symbol_filter, exclude_words=exclude_words, alert_keywords=alert_keywords, openclaw_enabled=openclaw_enabled)
        for notif in reversed(notifications):  # oldest first
            print(format_notification(notif))
        print(f"\n({len(notifications)} notifications shown)")
    else:
        # Show last 5 for context, then poll
        print("--- Last 5 notifications ---")
        recent = fetch_recent(db_path, app_ids, limit=5, app_filters=app_filters, channels=channels, log_dir=log_dir, dismiss=False, symbol_filter=symbol_filter, exclude_words=exclude_words, alert_keywords=alert_keywords, openclaw_enabled=False)
        for notif in reversed(recent):
            print(format_notification(notif))
        print("\n--- Watching for new notifications ---")
        poll_new_notifications(db_path, app_ids, interval=poll_interval, app_filters=app_filters, channels=channels, log_dir=log_dir, dismiss=dismiss, symbol_filter=symbol_filter, exclude_words=exclude_words, alert_keywords=alert_keywords, openclaw_enabled=openclaw_enabled)


if __name__ == "__main__":
    main()
