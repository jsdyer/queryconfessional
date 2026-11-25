# Query Confessional

A private, self-hosted dashboard for answering **which devices are requesting which domains, and when?** Import dnsmasq logs into a local SQLite database, then filter by device address, domain, DNS query type and time range.

This is installable software, not a public log-upload service. It runs with Python 3.11+ on Linux; there are no runtime Python dependencies, accounts, API keys, cloud services or scheduled public-data downloads. The interface works offline after installation.

<!-- guide:start -->
Query Confessional turns your own dnsmasq query logs into a private device/domain inventory. Import a log, open the local dashboard, choose a device address, and search for a domain such as `example.com`. Compare query counts, first/last activity and daily volumes; export the filtered records to CSV for further investigation.

For example, filter to your media device and a vendor's domain to see whether requests were logged overnight. A DNS lookup does **not** prove a successful connection, page visit, data transfer or malicious behavior. Encrypted DNS and clients using other resolvers are outside the log's coverage.

Requires Linux, Python 3.11+ and access to your own dnsmasq logs. Everything stays on your server. Logs without year/offset information require an explicit import year and source timezone. Reimporting the same unchanged/appended path is safe; copied or renamed captures count as separate sources, so do not import overlapping rotations.
<!-- guide:end -->

## Start with the synthetic sample

The included sample contains only reserved documentation addresses and example domains.

```sh
git clone https://github.com/jsdyer/queryconfessional.git
cd queryconfessional
python3 -m queryconfessional import examples/dnsmasq-sample.txt \
  --db /tmp/queryconfessional-demo.sqlite3 --year 2026 --timezone UTC
python3 -m queryconfessional serve --db /tmp/queryconfessional-demo.sqlite3
```

Open **http://127.0.0.1:8080/**. The sample contains 9 queries, 4 device addresses and 7 domains; two reply/forwarding lines are skipped. The sample deliberately mixes timestamps with and without explicit offsets: the supplied timezone applies only where an offset is absent. Use a separate database for your real logs.

## Install

You can continue running `python3 -m queryconfessional` from the checkout, or install the command in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/queryconfessional --version
```

The dashboard has no CDN assets or telemetry. Installing with pip may download build tooling from your configured package index; running directly from the checkout needs no package download. The operating system must provide its IANA timezone database (`tzdata` on Debian/Ubuntu).

## Enable and import dnsmasq query logging

If your router already collects dnsmasq logs, export those logs without changing the router. Otherwise, on a dnsmasq instance you administer, enable query logging in its configuration:

```ini
log-queries=extra
# Optional dedicated destination; choose a location writable by dnsmasq:
# log-facility=/var/log/dnsmasq-queries.log
```

Apply that configuration using your system's normal service-management procedure. Plain `log-queries`, `extra` and `proto` formats are supported; `only_failed` provides incomplete coverage. Follow the [official dnsmasq logging documentation](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html) for your installed version and log rotation. Read logs with a least-privileged account; the dashboard does not need root.

```sh
python3 -m queryconfessional import /path/to/dnsmasq-queries.log \
  --year 2026 --timezone America/Vancouver
python3 -m queryconfessional serve
```

Default storage is `$XDG_DATA_HOME/queryconfessional/queries.sqlite3`, or `~/.local/share/queryconfessional/queries.sqlite3`. Set `--db /private/path/queries.sqlite3` on both commands to use another database. Newly created data directories are mode `0700`; database files are mode `0600`. Existing parent-directory permissions are not changed.

The importer prints counts for lines, recognized queries, added records, duplicates and skipped records. It exits nonzero when a file contains no supported queries. Skipped records include replies/forwarding entries, malformed records, unsupported timestamps and unprintable names. Neither raw log lines nor domains are printed during import. It streams text and `.gz` files without loading the entire source into memory.

### Time and repeat-import rules

- Native dnsmasq/syslog timestamps omit the year and timezone. Both `--year` and `--timezone` are required to make those assumptions visible. ISO 8601 timestamps retain their explicit year and offset.
- A log spanning December–January must be split into separate year-specific files before import. The importer does not guess rollover years. Ambiguous daylight-saving fallback timestamps use the earlier occurrence because the source does not distinguish them; prefer timestamped logs with explicit offsets.
- Reimport an unchanged or append-only file **at the same absolute path**, with the same time settings: existing lines are skipped and new lines are added. Identical lines at different positions remain separate queries.
- **Copied, renamed, recompressed or rotated files under a different path are separate sources. Import each capture once under one stable path; do not import overlapping rotations.** This initial release does not merge rotations or automatically tail logs. Separate files can contain genuinely identical same-second queries, so content-only deduplication would lose records.
- Correcting year/timezone assumptions or importing overlapping files requires rebuilding a separate database from the original non-overlapping captures. Do not mix demo data with real logs.

For recurring imports, run the same import command from your own scheduler only while the source is append-only at that path. Review the rotation policy first. There is deliberately no GitHub Actions schedule collecting private network logs.

## Use the dashboard

- Filter by device address, literal domain substring, query type and local date/time.
- View total queries, distinct domains/device addresses and first/last matching activity.
- Inspect the top 100 domains and devices, and click an entry to filter the inventory.
- View daily counts for the latest 90 observed UTC days, plus the latest 200 matching query records. Summary totals cover **all** matching records, not just these display limits.
- Export up to 50,000 matching records to CSV; narrow the filters for larger exports. CSV times use UTC, and cells that could be interpreted as spreadsheet formulas are escaped.
- After importing more logs, choose **Apply filters** to refresh. The page does not automatically poll or keep a live connection open.

Addresses are shown exactly as observed, with IPv6 normalized. An IP address is not a permanent device identity: DHCP leases, NAT, relays and changing IPv6 addresses matter. This release does not identify device owners, resolve domains, label sites as trackers, assess reputation, or record successful connections or traffic volume.

## Private access and storage

The default listener binds only to `127.0.0.1`. To view a server's dashboard from your own computer, use an SSH tunnel:

```sh
ssh -L 8080:127.0.0.1:8080 user@your-server
```

Then open http://127.0.0.1:8080/ locally. This is the recommended remote-access method.

For advanced use behind an authenticated HTTPS reverse proxy or on a trusted network, non-loopback binding is available. It **requires** a token of at least 24 characters in `QUERYCONFESSIONAL_TOKEN`; set it through your private service environment or secret manager, never commit it. The dashboard will ask for the token and hold it only in tab memory. Do not expose the built-in HTTP server directly to the Internet or send a token over an untrusted unencrypted connection. It is a small local dashboard server, not a hardened public application host.

```sh
# First supply QUERYCONFESSIONAL_TOKEN through a private environment.
python3 -m queryconfessional serve --bind 0.0.0.0 --port 8080
```

No external network calls are made by the application. API requests are read-only, local Host headers are checked against DNS rebinding, cross-origin browser requests are rejected, responses are not cached, and access logs are disabled. Stored records contain timestamps, addresses, domains and query types; the imports table also records local source paths and counts. The SQLite database is **not encrypted**. Protect the machine, backups and exports, and stop the server before moving/removing its database. To erase an inventory, remove its database and any exported copies according to your storage/backup policy.

## Development and integration

```sh
python3 -m unittest discover -s tests -v
node --check queryconfessional/static/app.js
```

Tests use synthetic reserved addresses and cover plain/extra/proto formats, IPv6, root/underscore domains, timezone handling, malformed records, repeat imports, gzip, filters, exports, HTTP authorization and DNS-rebinding protection. CI runs against Python 3.11 and 3.13.

CoolCode integration: classify this tool as **Install yourself**, link to this README, and list “Linux, Python 3.11+, access to dnsmasq query logs” as requirements. Do not expose a public `/api` route, register this as a public data-refresh workload, or copy private logs into the catalogue repository. No API keys or external data-source registrations are needed.

License: [MIT](LICENSE).
