"""OpenSearch client for querying PayU UAT logs.

Accesses the VPC-hosted OpenSearch dashboard via the internal search API.
The endpoint is open on the VPC (no cookies required) - the `osd-xsrf` header
and user-agent are what are validated.
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


# Default OpenSearch dashboard configuration (UAT)
DEFAULT_OS_BASE_URL = os.getenv(
    "OPENSEARCH_BASE_URL",
    "https://vpc-eks-uat-new-3eqofejeq2kkjgq2fxoo56j374.ap-south-1.es.amazonaws.com",
)
DEFAULT_OS_INDEX = os.getenv("OPENSEARCH_INDEX", "corepayment-php-app-logs-*")
DEFAULT_OS_SEARCH_PATH = "/_dashboards/internal/search/opensearch"


class OpenSearchClient:
    """Client for querying the PayU OpenSearch dashboard."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        index: Optional[str] = None,
        timeout: int = 60,
    ):
        self.base_url = (base_url or DEFAULT_OS_BASE_URL).rstrip("/")
        self.index = index or DEFAULT_OS_INDEX
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "osd-xsrf": "osd-fetch",
                "osd-version": "2.11.0",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/133.0.0.0 Safari/537.36"
                ),
                "Referer": f"{self.base_url}/_dashboards/app/data-explorer/discover",
            }
        )

    # ------------------------------------------------------------------ #
    # Low-level search                                                    #
    # ------------------------------------------------------------------ #
    def _search(
        self,
        query_body: Dict[str, Any],
        size: int = 500,
        search_after: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a raw OpenSearch search via the dashboard internal API.

        Args:
            query_body: ES DSL `query` object.
            size: page size (up to 10_000 but keep reasonable — 500–1000).
            search_after: sort-values from the previous page's last hit, used
                to paginate with `search_after` (no `from` offset).
        """
        url = f"{self.base_url}{DEFAULT_OS_SEARCH_PATH}"

        body: Dict[str, Any] = {
            "sort": [
                {"@timestamp": {"order": "asc", "unmapped_type": "boolean"}}
            ],
            "size": size,
            "version": True,
            "stored_fields": ["*"],
            "script_fields": {},
            "docvalue_fields": [
                {"field": "@timestamp", "format": "date_time"},
                {"field": "log_timestamp", "format": "date_time"},
            ],
            "_source": {"excludes": []},
            "query": query_body,
            "highlight": {
                "pre_tags": ["@opensearch-dashboards-highlighted-field@"],
                "post_tags": ["@/opensearch-dashboards-highlighted-field@"],
                "fields": {"*": {}},
                "fragment_size": 2147483647,
            },
        }
        if search_after is not None:
            body["search_after"] = search_after

        payload = {"params": {"index": self.index, "body": body}}

        logger.info(
            "OpenSearch query -> size=%s search_after=%s query=%s",
            size, search_after, query_body,
        )

        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except RequestException as exc:
            logger.error("OpenSearch request failed: %s", exc)
            raise
        except ValueError as exc:
            logger.error("OpenSearch response not JSON: %s", exc)
            raise

        return data

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _time_range(lookback_days: int = 7) -> Dict[str, Any]:
        """Return an @timestamp range filter for the last `lookback_days`."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=lookback_days)
        return {
            "range": {
                "@timestamp": {
                    "gte": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "lte": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "format": "strict_date_optional_time",
                }
            }
        }

    @staticmethod
    def _extract_hits(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flatten the nested dashboards internal-search response to OS hits.

        Returns the raw hit envelopes (including `sort` values and `_source`).
        """
        # Dashboards wraps the raw ES response under `rawResponse`.
        raw = response.get("rawResponse") or response
        hits = (raw.get("hits") or {}).get("hits") or []
        return hits

    @staticmethod
    def _extract_total(response: Dict[str, Any]) -> int:
        raw = response.get("rawResponse") or response
        total = (raw.get("hits") or {}).get("total") or {}
        if isinstance(total, dict):
            return int(total.get("value", 0))
        try:
            return int(total)
        except Exception:
            return 0

    # ------------------------------------------------------------------ #
    # High-level queries                                                 #
    # ------------------------------------------------------------------ #
    def _phrase_query(
        self, phrase: str, lookback_days: int
    ) -> Dict[str, Any]:
        """Build a `multi_match` phrase query scoped to the lookback window."""
        return {
            "bool": {
                "must": [],
                "filter": [
                    {
                        "multi_match": {
                            "type": "phrase",
                            "query": str(phrase),
                            "lenient": True,
                        }
                    },
                    self._time_range(lookback_days),
                ],
                "should": [],
                "must_not": [],
            }
        }

    def search_by_payu_id(
        self,
        payu_id: str,
        lookback_days: int = 7,
        size: int = 500,
        max_hits: int = 10000,
    ) -> Dict[str, Any]:
        """Fetch ALL log entries that mention a given payu_id (paginated).

        Uses `search_after` pagination so we never miss processIds that only
        appear in later hits. Pagination stops when either the index is
        drained or ``max_hits`` is reached.

        Returns a dict with keys:
          - hits: list of log documents (_source)
          - total: total hit count reported by OpenSearch for the first page
          - process_ids: sorted list of discovered processIds
        """
        query = self._phrase_query(str(payu_id), lookback_days)

        collected: List[Dict[str, Any]] = []
        search_after: Optional[List[Any]] = None
        reported_total = 0
        pages = 0

        while len(collected) < max_hits:
            raw = self._search(query, size=size, search_after=search_after)
            if pages == 0:
                reported_total = self._extract_total(raw)
            hits = self._extract_hits(raw)
            pages += 1
            if not hits:
                break

            collected.extend(h.get("_source", {}) for h in hits)

            last_sort = hits[-1].get("sort")
            if not last_sort:
                break
            search_after = last_sort

            if len(hits) < size:
                break  # drained

        process_ids = _collect_process_ids(collected)
        logger.info(
            "Phase 1 (payuId=%s) fetched %d docs across %d page(s); "
            "discovered %d processIds: %s",
            payu_id, len(collected), pages, len(process_ids),
            sorted(process_ids),
        )

        return {
            "hits": collected,
            "total": reported_total,
            "process_ids": sorted(process_ids),
        }

    def fetch_all_logs_for_process_id(
        self,
        process_id: str,
        lookback_days: int = 7,
        page_size: int = 500,
        max_hits: int = 10000,
    ) -> List[Dict[str, Any]]:
        """Fetch EVERY log line for a single processId, paginated.

        Uses `search_after` to page through results chronologically.
        Caps at `max_hits` to prevent pathological loops on busy processIds.
        """
        if not process_id:
            return []

        query = self._phrase_query(str(process_id), lookback_days)

        collected: List[Dict[str, Any]] = []
        search_after: Optional[List[Any]] = None
        pages = 0

        while len(collected) < max_hits:
            raw = self._search(query, size=page_size, search_after=search_after)
            hits = self._extract_hits(raw)
            pages += 1
            if not hits:
                break

            collected.extend(h.get("_source", {}) for h in hits)

            # Cursor is the `sort` of the last hit
            last_sort = hits[-1].get("sort")
            if not last_sort:
                break
            search_after = last_sort

            if len(hits) < page_size:
                break  # drained

        logger.info(
            "Fetched %d logs for processId=%s across %d page(s)",
            len(collected), process_id, pages,
        )
        return collected

    def fetch_all_logs_for_payu_id(
        self,
        payu_id: str,
        lookback_days: int = 7,
        discovery_size: int = 500,
        max_discovery_hits: int = 10000,
        per_pid_page_size: int = 500,
        max_hits_per_pid: int = 10000,
        expansion_rounds: int = 1,
    ) -> Dict[str, Any]:
        """Exhaustive multi-phase fetch for a payuId.

        Phase 1 (DISCOVERY): paginated phrase search for the payuId across the
                             index to discover every processId that mentioned
                             it. Walks every string in every doc so no pid is
                             missed regardless of field layout.
        Phase 2 (FULL FETCH): for each discovered processId, paginate through
                              every log line (up to `max_hits_per_pid`).
        Phase 3 (EXPANSION): re-scan the logs fetched in Phase 2 for any
                             additional processIds we hadn't seen; fetch all
                             of their logs too. Repeats up to
                             `expansion_rounds` times to chain any further
                             cross-references.

        Returns:
            {
              "payu_id": "...",
              "process_ids":  ["...", ...],          # union after expansion
              "logs_per_pid": {"pid1": [..], ...},   # per-pid deduped
              "counts_per_pid": {"pid1": N, ...},
              "total_primary": N,
              "logs":         [ordered, deduped, merged list of log dicts],
              "expansion_pids": [...],               # pids found only via expansion
            }
        """
        # Phase 1: discover processIds tied to this payuId (paginated)
        primary = self.search_by_payu_id(
            payu_id=payu_id,
            lookback_days=lookback_days,
            size=discovery_size,
            max_hits=max_discovery_hits,
        )
        discovered: List[str] = list(primary["process_ids"])

        logs_per_pid: Dict[str, List[Dict[str, Any]]] = {}
        direct_bucket = "direct_payu_id_match"
        direct = list(primary["hits"])
        if direct:
            logs_per_pid[direct_bucket] = direct

        # Phase 2: exhaustively fetch every log for every discovered processId
        def _fetch_pid(pid: str) -> None:
            if pid in logs_per_pid:
                return
            pid_logs = self.fetch_all_logs_for_process_id(
                process_id=pid,
                lookback_days=lookback_days,
                page_size=per_pid_page_size,
                max_hits=max_hits_per_pid,
            )
            logs_per_pid[pid] = _dedupe_logs(pid_logs)

        for pid in discovered:
            _fetch_pid(pid)

        # Phase 3: expansion — scan Phase 2 output for brand-new processIds
        expansion_pids: List[str] = []
        seen: set = set(discovered)
        for _ in range(max(0, expansion_rounds)):
            new_docs: List[Dict[str, Any]] = []
            for bucket_name, bucket in logs_per_pid.items():
                if bucket_name == direct_bucket:
                    continue
                new_docs.extend(bucket)
            found = _collect_process_ids(new_docs)
            newly = [p for p in sorted(found) if p not in seen]
            if not newly:
                break
            logger.info(
                "Phase 3 expansion discovered %d new processIds: %s",
                len(newly), newly,
            )
            for pid in newly:
                seen.add(pid)
                expansion_pids.append(pid)
                _fetch_pid(pid)

        process_ids = sorted(seen)

        # Flatten + dedupe across pids + sort chronologically
        all_docs: List[Dict[str, Any]] = []
        for bucket in logs_per_pid.values():
            all_docs.extend(bucket)
        merged = _dedupe_logs(all_docs)
        merged.sort(key=_log_timestamp_key)

        logger.info(
            "Exhaustive fetch for payuId=%s: %d processIds, %d total logs "
            "(primary=%d, expansion=%d)",
            payu_id, len(process_ids), len(merged),
            len(direct), len(expansion_pids),
        )

        return {
            "payu_id": str(payu_id),
            "process_ids": process_ids,
            "logs_per_pid": logs_per_pid,
            "counts_per_pid": {pid: len(docs) for pid, docs in logs_per_pid.items()},
            "total_primary": primary["total"],
            "logs": merged,
            "expansion_pids": expansion_pids,
        }


# ---------------------------------------------------------------------- #
# Module helpers                                                         #
# ---------------------------------------------------------------------- #
_PROCESS_ID_KEYS = ("processId", "process_id", "processID", "processid")

# PayU core-payment processIds look like:
#   1860563_69e76f866b6ce_69e76f7bdc763
#   <mid>_<hex13+>_<hex13+>
# They appear as the LAST token of each log line (after the final "]"):
#   [… ][ INFO ][ Query ]1860563_69e76f866b6ce_69e76f7bdc763
# We match digits + _ + hex + _ + hex, each hex segment at least 8 chars.
_PROCESS_ID_REGEX = re.compile(
    r"(?<![A-Za-z0-9_])(\d{3,}_[A-Fa-f0-9]{8,}_[A-Fa-f0-9]{8,})(?![A-Za-z0-9_])"
)


def _message_text_of(doc: Dict[str, Any]) -> str:
    """Return the primary message/log text of a document (preferred fields)."""
    for k in ("message", "log", "msg", "raw"):
        v = doc.get(k)
        if isinstance(v, str) and v:
            return v
    # Fall back to any string value concatenated
    try:
        return " ".join(
            str(v) for v in doc.values() if isinstance(v, (str, int, float))
        )
    except Exception:
        return ""


def _walk_all_strings(value: Any, collected: List[str], limit: int = 5000) -> None:
    """Recursively collect every string inside a doc (dicts, lists, strs).

    This is how we make sure the processId regex matches the raw line even if
    the log shipper stored the body under a non-standard key (e.g. `stream`,
    `kubernetes.log`, `_source.log`, serialised JSON).
    """
    if len(collected) >= limit:
        return
    if isinstance(value, str):
        if value:
            collected.append(value)
        return
    if isinstance(value, dict):
        for v in value.values():
            _walk_all_strings(v, collected, limit)
            if len(collected) >= limit:
                return
        return
    if isinstance(value, list):
        for v in value:
            _walk_all_strings(v, collected, limit)
            if len(collected) >= limit:
                return
        return
    # ints/floats/bools/None — no strings to extract


def extract_process_ids_from_text(text: str) -> List[str]:
    """Extract every PayU processId occurrence from a raw log text."""
    if not text:
        return []
    return _PROCESS_ID_REGEX.findall(text)


def _collect_process_ids(docs: List[Dict[str, Any]]) -> set:
    """Walk each log doc and collect every processId found.

    PayU core-payment logs embed the processId inside the raw log line (after
    the final `]…]`), e.g.::

        [ INFO ][ Query ]1860563_69e76f866b6ce_69e76f7bdc763 10.251.6.234 …

    So extraction walks every string value in the doc (top-level or nested)
    and runs the regex over it. Structured fields named `processId` /
    `process_id` are still honoured when present.
    """
    ids: set = set()
    for d in docs:
        # 1. Structured fields (when the shipper was kind enough to parse them)
        for key in _PROCESS_ID_KEYS:
            if key in d and d[key]:
                ids.add(str(d[key]))

        # 2. Walk every string anywhere in the doc and scan it
        all_strings: List[str] = []
        _walk_all_strings(d, all_strings)
        for s in all_strings:
            matches = extract_process_ids_from_text(s)
            if matches:
                ids.update(matches)

    return ids


def _dedupe_logs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedupe logs by (@timestamp, message) tuple, preserving order."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for d in docs:
        key = (
            str(d.get("@timestamp") or d.get("log_timestamp") or ""),
            str(d.get("message") or d.get("log") or d.get("msg") or "")[:200],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _log_timestamp_key(doc: Dict[str, Any]):
    return str(doc.get("@timestamp") or doc.get("log_timestamp") or "")


# Singleton helper
_client: Optional[OpenSearchClient] = None


def get_opensearch_client() -> OpenSearchClient:
    global _client
    if _client is None:
        _client = OpenSearchClient()
    return _client
