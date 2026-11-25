import csv
from datetime import datetime, timezone
import gzip
import http.client
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from zoneinfo import ZoneInfo

from queryconfessional.parser import parse_line
from queryconfessional.server import make_handler, serve
from queryconfessional.store import initialize, import_file, dashboard, csv_export


class ParserTests(unittest.TestCase):
    def test_plain_extra_proto_ipv6_root_and_non_address_query(self):
        samples = [
            ("query[A] ExAmPlE.com. from 192.0.2.10", "example.com", "192.0.2.10", "A"),
            ("42 192.0.2.10/54321 query[AAAA] example.net from 192.0.2.10", "example.net", "192.0.2.10", "AAAA"),
            ("UDP 42 2001:db8::10/54321 query[HTTPS] example.org from 2001:db8::10", "example.org", "2001:db8::10", "HTTPS"),
            ("TCP 43 192.0.2.10/54321 query[TXT] _service._tcp.example.test from 192.0.2.10", "_service._tcp.example.test", "192.0.2.10", "TXT"),
            ("query[NS] . from 192.0.2.10", ".", "192.0.2.10", "NS")]
        for message, domain, device, qtype in samples:
            with self.subTest(message=message):
                query = parse_line("Nov 24 19:02:03 router dnsmasq[123]: " + message, 2025, ZoneInfo("America/Vancouver"))
                self.assertEqual((query.domain, query.device, query.qtype), (domain, device, qtype))
                self.assertEqual(datetime.fromtimestamp(query.timestamp, timezone.utc).isoformat(), "2025-11-25T03:02:03+00:00")

    def test_offset_and_rfc5424_priority(self):
        for prefix in ("2026-11-24T19:02:03-08:00", "<30>1 2026-11-25T03:02:03Z"):
            query = parse_line(prefix + " router dnsmasq[1]: query[A] example.com from 192.0.2.10", 2000, ZoneInfo("UTC"))
            self.assertEqual(query.timestamp, int(datetime(2026, 11, 25, 3, 2, 3, tzinfo=timezone.utc).timestamp()))

    def test_rejects_missing_timestamp_bad_ip_and_non_queries(self):
        for line in ("query[A] example.com from 192.0.2.10", "Nov 99 00:00:00 query[A] example.com from 192.0.2.10",
                     "Nov 24 00:00:00 query[A] example.com from not-an-ip", "Nov 24 00:00:00 reply example.com is 192.0.2.10",
                     "Nov 24 00:00:00 query[A] <name unprintable> from 192.0.2.10"):
            self.assertIsNone(parse_line(line, 2026, ZoneInfo("UTC")))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = initialize(self.root / "data" / "queries.sqlite3")
        self.log = self.root / "input.txt"
        self.log.write_text("Nov 24 19:02:03 router dnsmasq[123]: query[A] example.com from 192.0.2.10\n" * 2 +
                            "2026-11-24T19:03:00Z router dnsmasq[123]: query[AAAA] example.net from 2001:db8::10\n" +
                            "Nov 24 19:02:03 router dnsmasq[123]: reply example.com is 192.0.2.80\n")

    def import_sample(self):
        return import_file(self.db, self.log, 2026, ZoneInfo("UTC"))

    def test_reimport_idempotent_without_losing_identical_queries(self):
        self.assertEqual(self.import_sample(), {"lines": 4, "queries": 3, "added": 3, "duplicates": 0, "skipped": 1})
        self.assertEqual(self.import_sample()["added"], 0)
        with self.log.open("a") as stream:
            stream.write("Nov 24 19:02:03 router dnsmasq[123]: query[A] example.com from 192.0.2.10\n")
        self.assertEqual(self.import_sample()["added"], 1)
        self.assertEqual(dashboard(self.db, {})["stats"]["queries"], 4)
        self.assertEqual(os.stat(self.db).st_mode & 0o777, 0o600)

    def test_gzip_and_filters(self):
        compressed = self.root / "input.gz"
        with gzip.open(compressed, "wt") as stream:
            stream.write(self.log.read_text())
        self.assertEqual(import_file(self.db, compressed, 2026, ZoneInfo("UTC"))["added"], 3)
        self.assertEqual(dashboard(self.db, {"device": "2001:db8::10"})["stats"]["domains"], 1)
        self.assertEqual(dashboard(self.db, {"domain": "example.com", "qtype": "A"})["stats"]["queries"], 2)
        self.assertEqual(dashboard(self.db, {"after": "2026-11-24T19:02:30Z"})["stats"]["queries"], 1)
        self.assertEqual(dashboard(self.db, {"domain": "%' OR 1=1 --"})["stats"]["queries"], 0)
        with self.assertRaises(ValueError):
            dashboard(self.db, {"after": "2026-11-24T00:00:00"})

    def test_export_escaping_and_utc(self):
        self.import_sample()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO events VALUES ('test',1,'=evil','192.0.2.10','A')")
        rows = list(csv.reader(io.StringIO(csv_export(self.db, {}))))
        self.assertEqual(rows[-1][2], "'=evil")
        self.assertTrue(rows[1][0].endswith("+00:00"))

    def test_empty_database(self):
        data = dashboard(self.db, {})
        self.assertEqual(data["stats"]["queries"], 0)
        self.assertIsNone(data["last_import"])

    def test_copied_files_are_distinct_sources(self):
        self.import_sample()
        copied = self.root / "rotation.txt"
        copied.write_bytes(self.log.read_bytes())
        self.assertEqual(import_file(self.db, copied, 2026, ZoneInfo("UTC"))["added"], 3)
        self.assertEqual(dashboard(self.db, {})["stats"]["queries"], 6)


class HTTPTests(unittest.TestCase):
    setUp = StoreTests.setUp
    import_sample = StoreTests.import_sample

    def start_server(self, token=None):
        self.import_sample()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.db, "127.0.0.1", token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_dashboard_and_host_protection(self):
        self.start_server()
        status, headers, body = self.get("/api/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["stats"]["queries"], 3)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.get("/api/dashboard", {"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.get("/api/dashboard", {"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.get("/api/dashboard?after=bad")[0], 400)
        self.assertEqual(self.get("/../README.md")[0], 404)

    def test_token_and_assets(self):
        token = "a-very-long-testing-token-only"
        self.start_server(token)
        self.assertEqual(self.get("/")[0], 200)
        self.assertEqual(self.get("/app.js")[0], 200)
        self.assertEqual(self.get("/api/dashboard")[0], 401)
        self.assertEqual(self.get("/api/export.csv")[0], 401)
        self.assertEqual(self.get("/api/dashboard", {"Authorization": "Bearer " + token})[0], 200)
        self.assertEqual(self.get("/api/export.csv", {"Authorization": "Bearer " + token})[0], 200)

    def test_remote_bind_requires_token(self):
        with self.assertRaises(ValueError):
            serve(self.db, "0.0.0.0", 8080)


if __name__ == "__main__":
    unittest.main()
