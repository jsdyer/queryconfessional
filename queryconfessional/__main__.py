import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__
from .server import serve
from .store import initialize, import_file


def default_db():
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return str(base / "queryconfessional" / "queries.sqlite3")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Private dnsmasq DNS query inventory. No external services.")
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="command", required=True)
    importer = subs.add_parser("import", help="Import plain text or gzip-compressed dnsmasq logs")
    importer.add_argument("paths", nargs="+", help="Non-overlapping capture files; copied/renamed paths count as new sources")
    importer.add_argument("--db", default=default_db(), help="SQLite database path")
    importer.add_argument("--year", type=int, required=True, help="Year for timestamps that omit it (split files spanning New Year)")
    importer.add_argument("--timezone", required=True, help="IANA timezone for timestamps that omit an offset, e.g. America/Vancouver")
    web = subs.add_parser("serve", help="Open the read-only local dashboard")
    web.add_argument("--db", default=default_db())
    web.add_argument("--bind", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            if not 1970 <= args.year <= 9999:
                raise ValueError("--year must be between 1970 and 9999")
            tz = ZoneInfo(args.timezone)
            db = initialize(args.db)
            for filename in args.paths:
                result = import_file(db, filename, args.year, tz)
                # File paths and queried domains are deliberately not echoed.
                print(json.dumps(result))
                if result["queries"] == 0:
                    print("No timestamped dnsmasq query records found; check the input format, year and timezone.", file=sys.stderr)
                    return 2
        else:
            if not 1 <= args.port <= 65535:
                raise ValueError("--port must be between 1 and 65535")
            db = initialize(args.db)
            serve(db, args.bind, args.port, os.environ.get("QUERYCONFESSIONAL_TOKEN"))
        return 0
    except (OSError, ValueError, ZoneInfoNotFoundError, sqlite3.Error) as exc:
        # Avoid logging whole source lines, database contents, or tokens.
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

