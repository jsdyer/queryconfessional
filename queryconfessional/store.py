"""SQLite storage and bounded, parameterized dashboard queries."""

from datetime import datetime, timezone
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3

from .parser import parse_line

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    timestamp INTEGER NOT NULL,
    domain TEXT NOT NULL,
    device TEXT NOT NULL,
    qtype TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_time ON events(timestamp);
CREATE INDEX IF NOT EXISTS events_device_time ON events(device,timestamp);
CREATE INDEX IF NOT EXISTS events_domain_time ON events(domain,timestamp);
CREATE TABLE IF NOT EXISTS imports (
    source TEXT PRIMARY KEY,
    imported_at TEXT NOT NULL,
    lines INTEGER NOT NULL,
    queries INTEGER NOT NULL,
    skipped INTEGER NOT NULL
);
"""


def initialize(path):
    path = Path(path).expanduser().resolve()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
    # SQLite and its journal inherit this restrictive creation mask.
    old_mask = os.umask(0o077)
    try:
        with sqlite3.connect(path) as conn:
            conn.executescript(SCHEMA)
        path.chmod(0o600)
    finally:
        os.umask(old_mask)
    return path


def import_file(db, filename, year, tz):
    source = Path(filename).expanduser().resolve()
    opener = gzip.open if source.suffix.lower() == ".gz" else open
    counts = {"lines": 0, "queries": 0, "added": 0, "duplicates": 0, "skipped": 0}
    with opener(source, "rt", encoding="utf-8", errors="replace") as stream, sqlite3.connect(db) as conn:
        # All lines are streamed. A transaction prevents a partial import on failure.
        for number, line in enumerate(stream, 1):
            counts["lines"] += 1
            query = parse_line(line, year, tz)
            if query is None:
                counts["skipped"] += 1
                continue
            counts["queries"] += 1
            # Preserve legitimate repeated queries on separate lines. Same-path
            # reimports are idempotent, including when appending to a log.
            identity = json.dumps([str(source), number, line.rstrip("\r\n"), query.timestamp])
            digest = hashlib.sha256(identity.encode()).hexdigest()
            result = conn.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)",
                                  (digest, query.timestamp, query.domain, query.device, query.qtype))
            counts["added"] += result.rowcount
        counts["duplicates"] = counts["queries"] - counts["added"]
        conn.execute("INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?)", (
            str(source), datetime.now(timezone.utc).isoformat(), counts["lines"], counts["queries"], counts["skipped"]))
    return counts


def filters(params):
    clauses, args = [], []
    for field in ("device", "qtype"):
        value = params.get(field, "").strip()
        if len(value) > 256:
            raise ValueError("Filter is too long")
        if value:
            clauses.append(f"{field} = ?")
            args.append(value)
    domain = params.get("domain", "").strip().lower()
    if len(domain) > 253:
        raise ValueError("Domain filter is too long")
    if domain:
        # Literal substring matching: % and _ do not become SQL wildcards.
        clauses.append("instr(domain, ?) > 0")
        args.append(domain)
    for param, operator in (("after", ">="), ("before", "<=")):
        value = params.get(param, "").strip()
        if value:
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("Timezone is required")
            except ValueError:
                raise ValueError(f"Invalid {param} timestamp; use ISO 8601 with timezone") from None
            clauses.append(f"timestamp {operator} ?")
            args.append(int(stamp.timestamp()))
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), args


def connect(db):
    conn = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def dashboard(db, params):
    where, args = filters(params)
    with connect(db) as conn:
        stats = dict(conn.execute("SELECT count(*) queries, count(DISTINCT device) devices, "
                                  "count(DISTINCT domain) domains, min(timestamp) first, max(timestamp) last "
                                  "FROM events" + where, args).fetchone())
        domains = [dict(row) for row in conn.execute("SELECT domain, count(*) queries, count(DISTINCT device) devices, "
                    "min(timestamp) first, max(timestamp) last FROM events" + where + " GROUP BY domain ORDER BY queries DESC, domain LIMIT 100", args)]
        devices = [dict(row) for row in conn.execute("SELECT device, count(*) queries, count(DISTINCT domain) domains, "
                    "min(timestamp) first, max(timestamp) last FROM events" + where + " GROUP BY device ORDER BY queries DESC, device LIMIT 100", args)]
        recent = [dict(row) for row in conn.execute("SELECT timestamp, device, domain, qtype FROM events" + where +
                    " ORDER BY timestamp DESC, id DESC LIMIT 200", args)]
        types = [dict(row) for row in conn.execute("SELECT qtype, count(*) queries FROM events" + where + " GROUP BY qtype ORDER BY queries DESC", args)]
        activity = [dict(row) for row in conn.execute("SELECT strftime('%Y-%m-%d',timestamp,'unixepoch') day, count(*) queries "
                    "FROM events" + where + " GROUP BY day ORDER BY day DESC LIMIT 90", args)][::-1]
        last_import = conn.execute("SELECT max(imported_at) FROM imports").fetchone()[0]
        all_types = [row[0] for row in conn.execute("SELECT DISTINCT qtype FROM events ORDER BY qtype")]
        all_devices = [row[0] for row in conn.execute("SELECT DISTINCT device FROM events ORDER BY device LIMIT 10000")]
    return {"stats": stats, "domains": domains, "devices": devices, "recent": recent, "types": types,
            "activity": activity, "last_import": last_import, "all_types": all_types, "all_devices": all_devices,
            "limits": {"domains": 100, "devices": 100, "recent": 200, "activity_days": 90}}


def csv_export(db, params):
    where, args = filters(params)
    with connect(db) as conn:
        rows = conn.execute("SELECT timestamp,device,domain,qtype FROM events" + where + " ORDER BY timestamp DESC LIMIT 50001", args).fetchall()
    if len(rows) > 50000:
        raise ValueError("Export exceeds 50,000 rows; narrow the date or device filters")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("timestamp_utc", "device", "domain", "query_type"))
    for row in rows:
        values = [datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat(), row["device"], row["domain"], row["qtype"]]
        # A domain is untrusted log input. Avoid spreadsheet formula execution.
        writer.writerow(["'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
    return output.getvalue()
