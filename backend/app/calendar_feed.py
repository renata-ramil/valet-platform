"""A per-user ICS feed of upcoming scheduled deliveries, and a read-only
ICS import that proposes a delivery 15 minutes before any imported event
that has a location. No external calendar library: ICS is a simple enough
line-oriented format that a small hand-rolled parser and generator covers
the subset this needs (VEVENT with DTSTART/SUMMARY/LOCATION)."""

import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx

PROPOSAL_LEAD_MINUTES = 15
IMPORT_TIMEOUT_SECONDS = 5.0
IMPORT_MAX_BYTES = 262_144


class UnsafeUrlError(Exception):
    pass


def _assert_safe_url(url: str) -> None:
    # Basic SSRF guard: only http(s), and the resolved host must not be a
    # private, loopback, or link-local address. Not exhaustive (does not
    # stop DNS rebinding between check and fetch), but stops the easy case
    # of a resident pointing the importer at internal infrastructure.
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https URLs are supported")
    if not parsed.hostname:
        raise UnsafeUrlError("URL has no host")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError("Could not resolve host") from exc
    for _family, _type, _proto, _canonname, sockaddr in addresses:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise UnsafeUrlError("URL resolves to a non-public address")


def _escape_ics_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def generate_feed(user_name: str, events: list[dict]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Valet platform//Resident deliveries//EN",
        f"X-WR-CALNAME:{_escape_ics_text(user_name)}'s car deliveries",
    ]
    for event in events:
        start = event["ready_by"].astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event['id']}@valet-platform",
            f"DTSTAMP:{start}",
            f"DTSTART:{start}",
            f"SUMMARY:{_escape_ics_text(event['summary'])}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


@dataclass
class ImportedEvent:
    summary: str
    start: datetime
    location: str | None


_DTSTART_RE = re.compile(r"^DTSTART[^:]*:(\d{8}T\d{6}Z?)")


def _parse_ics_datetime(raw: str) -> datetime | None:
    try:
        if raw.endswith("Z"):
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        return datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_ics(text: str) -> list[ImportedEvent]:
    events = []
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            current = {"summary": None, "start": None, "location": None}
        elif line == "END:VEVENT":
            if current and current["summary"] and current["start"]:
                events.append(
                    ImportedEvent(
                        summary=current["summary"],
                        start=current["start"],
                        location=current["location"],
                    )
                )
            current = None
        elif current is not None:
            if line.startswith("SUMMARY"):
                current["summary"] = line.split(":", 1)[-1]
            elif line.startswith("LOCATION"):
                location = line.split(":", 1)[-1].strip()
                current["location"] = location or None
            else:
                match = _DTSTART_RE.match(line)
                if match:
                    current["start"] = _parse_ics_datetime(match.group(1))
    return events


def fetch_and_parse(url: str) -> list[ImportedEvent]:
    _assert_safe_url(url)
    with httpx.Client(timeout=IMPORT_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = client.get(url)
        response.raise_for_status()
        content = response.content[:IMPORT_MAX_BYTES]
    return parse_ics(content.decode("utf-8", errors="replace"))


def propose_deliveries(events: list[ImportedEvent], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    proposals = []
    for event in events:
        if not event.location:
            continue
        if event.start <= now:
            continue
        ready_by = event.start - timedelta(minutes=PROPOSAL_LEAD_MINUTES)
        if ready_by <= now:
            continue
        proposals.append(
            {
                "event_summary": event.summary,
                "event_start": event.start.isoformat(),
                "event_location": event.location,
                "proposed_ready_by": ready_by.isoformat(),
            }
        )
    return proposals
