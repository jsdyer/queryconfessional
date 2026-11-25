"""Parse dnsmasq query records; replies and forwarding records are not queries."""

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import re

QUERY = re.compile(r"\bquery\[([A-Za-z0-9_-]+)\]\s+(\S+)\s+from\s+(\S+)")
SYSLOG = re.compile(r"^(?:<\d+>)?(\w{3})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\b")
ISO = re.compile(r"^(?:<\d+>\d?\s*)?(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?)")
MONTHS = {name: index for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


@dataclass(frozen=True)
class Query:
    timestamp: int
    domain: str
    device: str
    qtype: str


def parse_line(line: str, year: int, tz) -> Query | None:
    """Return a query or None for unrelated/malformed lines.

    A supplied year and timezone apply only to timestamps that omit them.
    Serial/client prefixes from log-queries=extra do not affect matching.
    """
    query = QUERY.search(line)
    if query is None:
        return None
    qtype, domain, device = query.groups()
    try:
        device = str(ipaddress.ip_address(device))
        iso = ISO.match(line)
        if iso:
            when = datetime.fromisoformat(iso[1].replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=tz)
        else:
            stamp = SYSLOG.match(line)
            if not stamp or stamp[1] not in MONTHS:
                return None
            hour, minute, second = map(int, stamp[3].split(":"))
            when = datetime(year, MONTHS[stamp[1]], int(stamp[2]), hour, minute, second, tzinfo=tz)
        domain = domain.lower().rstrip(".") or "."
        if len(domain) > 253 or any(ord(c) < 32 for c in domain):
            return None
        return Query(int(when.astimezone(timezone.utc).timestamp()), domain, device, qtype.upper())
    except (ValueError, OverflowError):
        return None

