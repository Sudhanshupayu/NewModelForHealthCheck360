"""Structured parser for PayU core-payment log lines.

Every PayU core-payment log line follows the same shape::

    [<log_ts>][Fl: <flow> ][Cl: <class> ][Fn: <fn> ][Ln: <line> ]\
    [ <LEVEL / TAG> ][ <context> ]<pid> <internal_ip> <client_ip>[<body>]

This module turns that raw string into a ``ParsedLog`` dataclass so the
downstream diagnostics layer can match on structured fields instead of
free-text regex. It also handles OpenSearch documents with non-standard
body keys (``log`` vs ``message`` vs ``msg`` vs ``raw``) and pulls the
canonical processId via the repo-wide regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import extract_process_ids_from_text


_HEADER_RX = re.compile(
    r"""
    \[(?P<log_ts>[^\]]+?)\]                      # [21-04-2026 18:07:15.9062]
    \s*\[\s*Fl\s*:\s*(?P<flow>[^\]]*?)\]\s*
    \[\s*Cl\s*:\s*(?P<cls>[^\]]*?)\]\s*
    \[\s*Fn\s*:\s*(?P<fn>[^\]]*?)\]\s*
    \[\s*Ln\s*:\s*(?P<ln>[^\]]*?)\]\s*
    \[\s*(?P<level>[^\]]*?)\s*\]\s*
    \[\s*(?P<context>[^\]]*?)\s*\]
    (?P<tail>.*)$
    """,
    re.VERBOSE | re.DOTALL,
)

# After the header ends with `]` the tail looks like::
#   1860563_…_… 10.251.6.234 14.141.149.50[<body…>]
# We pull the pid + ip-pair off the front, keep the rest as the body.
_TAIL_PREFIX_RX = re.compile(
    r"""
    ^\s*
    (?:(?P<pid>\d{3,}_[A-Fa-f0-9]{8,}_[A-Fa-f0-9]{8,}))?\s*
    (?:(?P<internal_ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}))?\s*
    (?:(?P<client_ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}))?\s*
    \[?(?P<body>.*?)\]?\s*$
    """,
    re.VERBOSE | re.DOTALL,
)

# Level tag → canonical severity. Anything not listed is treated as INFO.
_LEVEL_TO_SEVERITY = {
    "INFO":               "info",
    "DEBUG":              "debug",
    "WARN":               "warn",
    "WARNING":            "warn",
    "ERROR":              "error",
    "CRITICAL":           "critical",
    "FATAL":              "critical",
    "EXCEPTION OCCURED":  "error",
    "EXCEPTION":          "error",
    "EXCEPTION HANDLING": "error",
}


@dataclass
class ParsedLog:
    """A single PayU log line, fully parsed."""

    raw: str                                       # original raw body text
    timestamp: str = ""                            # ES @timestamp if present
    log_ts: str = ""                               # log-internal timestamp
    flow: str = ""                                 # Fl
    cls: str = ""                                  # Cl
    fn: str = ""                                   # Fn
    line_no: str = ""                              # Ln
    level: str = ""                                # raw level tag (e.g. "EXCEPTION OCCURED")
    severity: str = "info"                         # canonical: info/debug/warn/error/critical
    context: str = ""                              # second [..] tag (REQUEST, Query, MISC, GRPC, ...)
    process_id: str = ""
    internal_ip: str = ""
    client_ip: str = ""
    body: str = ""                                 # free-text body after the header
    source: Dict[str, Any] = field(default_factory=dict)  # original ES _source

    # ---- convenience properties --------------------------------------
    @property
    def is_exception(self) -> bool:
        return "EXCEPTION" in (self.level or "").upper()

    @property
    def is_request(self) -> bool:
        return (self.context or "").upper() == "REQUEST"

    @property
    def location(self) -> str:
        """``Flow::Class::Fn:Ln`` locator for rendering."""
        parts = [p for p in (self.flow, self.cls, self.fn) if p]
        base = "::".join(parts)
        return f"{base}:{self.line_no}" if self.line_no else base


def parse_raw_line(raw: str) -> ParsedLog:
    """Parse a single raw PayU log line into a :class:`ParsedLog`."""
    raw = (raw or "").strip()
    if not raw:
        return ParsedLog(raw="")

    m = _HEADER_RX.search(raw)
    if not m:
        # No recognizable header — fall back to whatever pid we can spot.
        pid_candidates = extract_process_ids_from_text(raw)
        return ParsedLog(
            raw=raw,
            body=raw,
            process_id=pid_candidates[-1] if pid_candidates else "",
        )

    level_raw = m.group("level").strip()
    parsed = ParsedLog(
        raw=raw,
        log_ts=m.group("log_ts").strip(),
        flow=m.group("flow").strip(),
        cls=m.group("cls").strip(),
        fn=m.group("fn").strip(),
        line_no=m.group("ln").strip(),
        level=level_raw,
        severity=_LEVEL_TO_SEVERITY.get(level_raw.upper(), "info"),
        context=m.group("context").strip(),
    )

    tail = m.group("tail").lstrip()
    tm = _TAIL_PREFIX_RX.match(tail)
    if tm:
        parsed.process_id = (tm.group("pid") or "").strip()
        parsed.internal_ip = (tm.group("internal_ip") or "").strip()
        parsed.client_ip = (tm.group("client_ip") or "").strip()
        parsed.body = (tm.group("body") or tail).strip()
    else:
        parsed.body = tail

    if not parsed.process_id:
        # Last-chance pid rescue from wherever in the line
        pid_candidates = extract_process_ids_from_text(raw)
        if pid_candidates:
            parsed.process_id = pid_candidates[-1]

    return parsed


def parse_doc(doc: Dict[str, Any]) -> ParsedLog:
    """Parse an OpenSearch ``_source`` document into a :class:`ParsedLog`.

    Tries ``log``, ``message``, ``msg``, ``raw`` in order (PayU's Filebeat
    pipeline stores the body in ``log``).
    """
    raw: Any = None
    for key in ("log", "message", "msg", "raw"):
        v = doc.get(key)
        if isinstance(v, str) and v:
            raw = v
            break
        if isinstance(v, dict):
            # nested — stringify keys we care about
            for inner in ("message", "msg", "log", "raw"):
                if isinstance(v.get(inner), str):
                    raw = v[inner]
                    break
            if raw:
                break

    parsed = parse_raw_line(str(raw or ""))
    parsed.source = doc
    parsed.timestamp = str(
        doc.get("@timestamp") or doc.get("log_timestamp") or parsed.log_ts
    )
    return parsed


def parse_docs(docs: List[Dict[str, Any]]) -> List[ParsedLog]:
    """Parse a list of OpenSearch docs, preserving chronological order."""
    parsed_list = [parse_doc(d) for d in docs or []]
    parsed_list.sort(key=lambda p: (p.timestamp, p.log_ts))
    return parsed_list
