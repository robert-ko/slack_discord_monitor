# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

Repository overview
- Multi-project repo containing:
  - DemoStrategies/ (Java/Gradle) — Bookmap L1 API demo/strategies
  - Schwabdev/ (Python package) — Schwab API client library (tokens, REST, streaming)
  - SchwabAPI/ (Python scripts) — Standalone scripts that use Schwab API
  - notification_monitor.py — macOS Notification Center monitor for Slack/Discord (also published at github.com/robert-ko/slack_discord_monitor)
  - Root-level utilities and tests targeting stock_data_fetcher.py

Common commands

Python (Schwabdev package and root tests)
- Install editable package for local development (Python >= 3.11):
  ```powershell path=null start=null
  python -m pip install -e ./Schwabdev
  ```
- Run all unit tests (unittest-based):
  ```powershell path=null start=null
  python -m unittest -v
  ```
- Run a single test case:
  ```powershell path=null start=null
  python -m unittest test_stock_data_fetcher.TestStockDataFetcher.test_cache_functionality
  ```
- Run a specific test file directly:
  ```powershell path=null start=null
  python .\test_stock_data_fetcher.py
  ```
- Run the external data smoke test (prints outputs; not a formal unit test):
  ```powershell path=null start=null
  python .\test_external_data.py
  ```

SchwabAPI scripts
- Token management (requires env vars; see below):
  ```powershell path=null start=null
  python .\SchwabAPI\auth.py N    # New (interactive) auth
  python .\SchwabAPI\auth.py R    # Refresh token
  python .\SchwabAPI\auth.py S    # Set timer/refresh helper
  ```
- Account/Trades monitor:
  ```powershell path=null start=null
  python .\SchwabAPI\SchwabAPI.py P            # Positions
  python .\SchwabAPI\SchwabAPI.py T 30         # Trades (30 days)
  ```
- Option tickers transform:
  ```powershell path=null start=null
  python .\SchwabAPI\option_tickers.py T in.tsv > out.txt   # to API symbols
  python .\SchwabAPI\option_tickers.py F in.txt > out.txt   # from API symbols
  ```
- Market data (quotes/history/chains placeholders per README):
  ```powershell path=null start=null
  python .\SchwabAPI\market_data.py Q tickers.txt
  ```
- High-of-day monitor (doc at README_high_of_day_monitor.md):
  ```powershell path=null start=null
  python .\SchwabAPI\high_of_day_monitor.py
  ```

Java (DemoStrategies/Strategies — Gradle)
- Build the Bookmap strategies jar:
  ```powershell path=null start=null
  gradle -p .\DemoStrategies\Strategies jar
  ```
- Run the standalone demo app (requires compiled classes and Bookmap installed):
  ```powershell path=null start=null
  gradle -p .\DemoStrategies\Strategies runStandalone
  ```
- Print the Gradle compile classpath (helpful for IDE setup):
  ```powershell path=null start=null
  gradle -p .\DemoStrategies\Strategies printClasspath
  ```

Environment and prerequisites
- Python
  - Schwabdev requires Python >= 3.11.
  - Some scripts depend on yfinance and python-dotenv (see README_high_of_day_monitor.md).
- Schwab API credentials (SchwabAPI/auth.py)
  - Provide secrets via environment (or .env loaded by scripts where applicable):
    - {{SCHWAB_API_KEY}}
    - {{SCHWAB_API_SECRET}}
    - {{SCHWAB_TOKEN_FILE}} (path for token.json)
  - Do not print or log these secrets.
- Java/Gradle
  - Gradle installed and on PATH; Java 17 compatibility is configured in DemoStrategies/Strategies/build.gradle.
  - Bookmap installation for running the jar and/or the IntelliJ run config (see DemoStrategies/README.md for JVM --add-opens flags and IDE notes).

High-level architecture

Schwabdev (Python package)
- Purpose: A lightweight Schwab API client providing REST endpoints, token management, and streaming.
- Key modules and responsibilities:
  - schwabdev/client.py
    - Client orchestrates the library: constructs Tokens and Stream, maintains a requests Session, and exposes high-level REST methods (accounts, orders, transactions, quotes, etc.).
    - Helpers: _params_parser (strip None), _time_convert (ISO-8601/EPOCH/EPOCH_MS/YYYY-MM-DD), _format_list (list->CSV).
    - Background thread periodically refreshes access tokens via Tokens and, when updated, rotates the requests Session for clean auth state.
  - schwabdev/tokens.py
    - Handles OAuth flows against api.schwabapi.com, token persistence to a JSON file, and timed refreshes.
    - Validates inputs (length/format of keys, https callback, etc.).
    - Optional self-signed HTTPS capture server to intercept the redirect during initial auth (writes to ~/.schwabdev/). Avoids manual URL copy/paste if capture_callback=True.
    - Notifies via an optional callback when user action is required (e.g., refresh token flow).
  - schwabdev/stream.py
    - WebSocket client for real-time streaming with reconnection and exponential backoff.
    - Persists a subscriptions registry across reconnects; groups subscriptions by fields to reduce request volume.
    - Provides convenience builders (e.g., level_one_equities/level_one_options) and a basic_request() format that matches Schwab’s streamer protocol.
    - start() spins an asyncio event loop in a thread; start_auto() can schedule market-hours-only streaming.
  - schwabdev/enums.py
    - TimeFormat enum used by Client._time_convert.
- Public API surface:
  - from schwabdev import Client
  - Construct with app_key/app_secret/callback_url, optional tokens_file, and capture_callback if you want automatic callback capture.

SchwabAPI (Python scripts)
- Purpose: A set of standalone utilities built around Schwab API. Not a package; run as scripts.
- Notable scripts (per README.md):
  - auth.py — obtains and refreshes tokens; relies on SCHWAB_API_KEY, SCHWAB_API_SECRET, SCHWAB_TOKEN_FILE.
  - SchwabAPI.py — object-oriented positions/trades retrieval across accounts; prints aggregated account position/mark data.
  - market_data.py, option_tickers.py — transform utilities and quote retrieval.
  - high_of_day_monitor.py — streaming monitor/alerts example (see README_high_of_day_monitor.md).

DemoStrategies (Java/Gradle for Bookmap L1 API)
- Purpose: Example strategies/adapters for Bookmap using L1 API (both Simplified and Core).
- Gradle configuration (DemoStrategies/Strategies/build.gradle):
  - Java 17 source/target compatibility; compileOnly dependencies on com.bookmap.api api-core/api-simplified.
  - Outputs bm-strategies.jar; includes runStandalone (JavaExec) pointing to velox.api.layer1.standalone.StandaloneStockOrderBookApp.
  - Provides an IntelliJ run configuration generator with required --add-opens flags (Windows includes sun.awt.windows) and pointers to Bookmap.jar.
- Documentation: DemoStrategies/README.md provides a deep conceptual overview (data flow, module types, generators, indicators, IDE setup).

Testing
- Root-level tests use unittest and validate stock_data_fetcher.py behavior (caching, error handling, and optional real API calls with yfinance mocked by unittest.mock).
- No central pytest/tox configuration or lint rules were detected in the repo.

notification_monitor (root-level)
- Purpose: Monitors macOS Notification Center DB in real time for Slack/Discord messages.
  No API keys, bot tokens, or admin access required — reads the SQLite DB directly.
  Forwards matched alerts to OpenClaw via openclaw_notify.py.
- Key commands:
  ```bash path=null start=null
  python3 notification_monitor.py                    # Normal startup
  python3 notification_monitor.py --reset-db         # Kill usernoted to flush stale DB, then start
  python3 notification_monitor.py --recent 20        # Show last 20 notifications and exit
  python3 notification_monitor.py --init-config      # Generate sample config file
  python3 notification_monitor.py --test-openclaw    # Send a test alert to OpenClaw
  ```
- Config: notification_monitor_config.json — sets poll interval, per-app channel filters,
  stock symbol filter, alert keywords, dismiss-after-capture, openclaw toggle.
- DB location: ~/Library/Group Containers/group.com.apple.usernoted/db2/db (SQLite, read-only).
- Daemon notes:
  - usernoted (/usr/sbin/usernoted) — owns the notification DB. Kill this to reset.
  - usernotificationsd — handles delivery pipeline only; killing it does NOT clear the DB.
  - killall usernoted restarts the daemon automatically and app IDs (Slack/Discord) repopulate
    immediately without waiting.
- Requires Full Disk Access for the terminal app running the script.
- Documentation: README.md (repo root, also at github.com/robert-ko/slack_discord_monitor)
  and README_notification_monitor.md.

Notes for future Warp sessions
- Prefer running Python from a virtual environment and installing Schwabdev in editable mode for examples to import properly.
- When running SchwabAPI/auth.py for the first time with capture_callback enabled via Schwabdev.Client, the library will generate TLS assets in ~/.schwabdev and spin up a local HTTPS server to receive the redirect.
- For Bookmap demos, ensure Java 17 and Gradle are available; follow the DemoStrategies/README.md guidance for JVM --add-opens flags and IDE run configuration.
- notification_monitor --reset-db kills usernoted (not usernotificationsd) to flush the DB.
  App IDs re-register immediately after restart — no long wait required.
