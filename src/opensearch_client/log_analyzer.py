"""Turn PayU core-payment logs into a 7-section **Incident Report**.

Pipeline:
    OpenSearch docs
      → log_parser.parse_docs()                       (structured ParsedLog)
      → diagnostics.extract_transaction_facts()       (what the txn WAS)
      → diagnostics.extract_findings()                (named issues)
      → diagnostics.determine_verdict()               (SUCCESS/DEGRADED/FAILURE)
      → LogAnalyzer.render_incident_report_markdown() (the final report)

Report sections (fixed order):
    1. Verdict
    2. Transaction facts
    3. Per-processId timeline (every pid, same depth)
    4. Findings (every exception / error / warning with root-cause line)
    5. Infra issues
    6. Recommended next steps (LLM-narrated if an llm is passed)
    7. Evidence pack (Jira-ready block + Discover links)
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .client import (
    DEFAULT_OS_BASE_URL,
    DEFAULT_OS_INDEX,
    OpenSearchClient,
    get_opensearch_client,
)
from .diagnostics import (
    Finding,
    PidTimelineEvent,
    TransactionFacts,
    Verdict,
    build_per_pid_events,
    collect_errors_and_warnings,
    determine_verdict,
    extract_findings,
    extract_transaction_facts,
    sev_emoji,
)
from .log_parser import ParsedLog, parse_doc, parse_docs

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# Discover URL (unchanged contract — kept for backward compatibility)    #
# --------------------------------------------------------------------- #
def build_opensearch_discover_url(
    query: str,
    lookback_days: int = 7,
    base_url: str = DEFAULT_OS_BASE_URL,
    index: str = DEFAULT_OS_INDEX,
) -> str:
    """Build a clickable OpenSearch Discover URL for a phrase query."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    time_block = (
        f"(time:(from:'{start.strftime('%Y-%m-%dT%H:%M:%S.000Z')}'"
        f",to:'{now.strftime('%Y-%m-%dT%H:%M:%S.000Z')}'))"
    )
    kql = f'"{query}"'
    q_block = f"(filters:!(),query:(language:kuery,query:'{kql}'))"
    a_block = (
        f"(discover:(columns:!(_source),interval:auto,sort:!()),"
        f"metadata:(indexPattern:'{index}',view:discover))"
    )
    fragment = f"?_g={time_block}&_q={q_block}&_a={a_block}"
    return f"{base_url.rstrip('/')}/_dashboards/app/data-explorer/discover#{fragment}"


# --------------------------------------------------------------------- #
# Incident Report                                                        #
# --------------------------------------------------------------------- #
class LogAnalyzer:
    """Build an Incident Report from the raw OpenSearch bundle."""

    def __init__(
        self,
        docs: List[Dict[str, Any]],
        logs_per_pid_docs: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ):
        self.docs = docs or []
        self.parsed: List[ParsedLog] = parse_docs(self.docs)

        # Per-pid ParsedLog lists (bucketed by the client) — preferred if present.
        self.logs_per_pid: Dict[str, List[ParsedLog]] = {}
        if logs_per_pid_docs:
            for pid, entries in logs_per_pid_docs.items():
                self.logs_per_pid[pid] = [parse_doc(d) for d in entries]
                self.logs_per_pid[pid].sort(key=lambda p: (p.timestamp, p.log_ts))
        else:
            bucket: Dict[str, List[ParsedLog]] = defaultdict(list)
            for p in self.parsed:
                bucket[p.process_id or "unknown"].append(p)
            self.logs_per_pid = dict(bucket)

    # ------------------------------------------------------------------ #
    # Core pieces                                                        #
    # ------------------------------------------------------------------ #
    def compute_report_bundle(self, payu_id: str) -> Dict[str, Any]:
        """Compute structured data for every section of the report."""
        facts = extract_transaction_facts(self.parsed, payu_id_hint=payu_id)
        findings = extract_findings(self.parsed)
        verdict = determine_verdict(facts, findings)
        per_pid_events = build_per_pid_events(self.logs_per_pid)
        errors_warnings = collect_errors_and_warnings(self.parsed, limit=40)
        infra_findings = [f for f in findings if f.category == "infra"]
        non_infra_findings = [f for f in findings if f.category != "infra"]

        return {
            "facts": facts,
            "findings": findings,
            "infra_findings": infra_findings,
            "non_infra_findings": non_infra_findings,
            "verdict": verdict,
            "per_pid_events": per_pid_events,
            "errors_warnings": errors_warnings,
        }

    # ------------------------------------------------------------------ #
    # Markdown rendering                                                 #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _section_1_verdict(v: Verdict) -> str:
        return (
            "## 1. Verdict\n"
            f"{v.emoji} **{v.label}** — {v.headline}\n"
        )

    @staticmethod
    def _section_2_facts(
        f: TransactionFacts,
        total_logs: int,
        pid_count: int,
        expansion_pids: List[str],
    ) -> str:
        lines: List[str] = ["## 2. Transaction facts", ""]
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        rows = [
            ("payuId",            f.payu_id or "_(unknown)_"),
            ("mihpayid",          f.mihpayid or "_(n/a)_"),
            ("merchant txnid",    f.merchant_txnid or "_(n/a)_"),
            ("merchant key",      f.merchant_key or "_(n/a)_"),
            ("merchant id",       f.merchant_id or "_(n/a)_"),
            ("amount",            f"{f.amount or '?'} {f.currency}"),
            ("flow type",         f.flow_type or "_(unknown)_"),
            ("PG selected",       f"id=`{f.pg_id}` ({f.pg_url or 'n/a'})" if f.pg_id else "_(not selected)_"),
            ("bank / mode",       f"{f.bank_code or '-'} / {f.payment_mode or '-'}"),
            ("tokenised",         "—" if f.tokenised is None else ("yes" if f.tokenised else "no")),
            ("split status",      f.split_status or "none"),
            ("final status",      f"`{f.final_status}`" if f.final_status else "_(no terminal status)_"),
            ("error code",        f"`{f.error_code}`" if f.error_code else "_(none)_"),
            ("bank ref",          f.bank_ref_no or "_(n/a)_"),
            ("bank message",      f.bank_message or "_(n/a)_"),
            ("merchant webhook",  f"{f.merchant_webhook_url or '-'} ({f.merchant_webhook_outcome or 'not seen'})"),
            ("call graph",        " → ".join(f"`{c}`" for c in f.call_graph) or "_(none captured)_"),
            ("window",            f"{f.first_ts} → {f.last_ts}"),
            ("logs analysed",     f"{total_logs} across {pid_count} processId(s)"),
        ]
        for k, v in rows:
            lines.append(f"| {k} | {v} |")
        if expansion_pids:
            lines.append(
                f"| expansion pids | {', '.join(f'`{p}`' for p in expansion_pids)} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _section_3_per_pid(
        events_per_pid: Dict[str, List[PidTimelineEvent]],
        pid_log_counts: Dict[str, int],
        lookback_days: int,
    ) -> str:
        lines: List[str] = ["## 3. Per-processId timeline", ""]
        if not events_per_pid:
            lines.append("_(no processIds — no logs were fetched)_")
            lines.append("")
            return "\n".join(lines)

        # Synthetic bucket names that are NOT real processIds
        _synthetic_pid_keys = {"unknown", "direct_payu_id_match", ""}

        for pid, events in events_per_pid.items():
            count = pid_log_counts.get(pid, len(events))
            is_real_pid = pid not in _synthetic_pid_keys
            pid_url = (
                build_opensearch_discover_url(query=pid, lookback_days=lookback_days)
                if is_real_pid
                else ""
            )
            if is_real_pid:
                pid_label = f"`{pid}`"
            elif pid == "direct_payu_id_match":
                pid_label = "_(direct payuId hits — processId not on the line)_"
            else:
                pid_label = "_(pid not captured)_"
            lines.append(f"### 🔹 processId {pid_label} — {count} log line(s)")
            if pid_url:
                lines.append(f"🔗 [Open in OpenSearch Discover]({pid_url})")
            if not events:
                lines.append("_(no salient events)_")
                lines.append("")
                continue
            lines.append("")
            for e in events:
                emoji = sev_emoji(e.severity)
                kind_tag = f"_{e.kind}_"
                lines.append(
                    f"- `{e.timestamp}` {emoji} {kind_tag} — {e.summary}"
                )
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _section_4_findings(non_infra: List[Finding]) -> str:
        lines: List[str] = [
            "## 4. Findings — exceptions / errors / warnings",
            "",
        ]
        if not non_infra:
            lines.append("_(no merchant-config, flow, bank or gateway issues detected)_")
            lines.append("")
            return "\n".join(lines)

        for i, f in enumerate(non_infra, 1):
            emoji = sev_emoji(f.severity)
            count_tag = f" (x{f.count})" if f.count > 1 else ""
            lines.append(
                f"**{i}. {emoji} {f.severity.upper()} — {f.name}**{count_tag}  \n"
                f"   • When: `{f.timestamp}` · pid=`{f.process_id or '-'}` · loc=`{f.location or '-'}`  \n"
                f"   • Category: `{f.category}`  \n"
                f"   • Evidence: `{(f.evidence or '').replace('`','').strip()[:280]}`  \n"
                f"   • Cause: {f.cause}  \n"
                f"   • Fix: {f.fix}"
            )
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _section_5_infra(infra: List[Finding]) -> str:
        lines: List[str] = ["## 5. Infrastructure issues", ""]
        if not infra:
            lines.append("_(no infra-level signals — gRPC / HTTP / DB calls healthy)_")
            lines.append("")
            return "\n".join(lines)

        for i, f in enumerate(infra, 1):
            emoji = sev_emoji(f.severity)
            count_tag = f" (x{f.count})" if f.count > 1 else ""
            lines.append(
                f"**{i}. {emoji} {f.severity.upper()} — {f.name}**{count_tag}  \n"
                f"   • When: `{f.timestamp}` · pid=`{f.process_id or '-'}` · loc=`{f.location or '-'}`  \n"
                f"   • Evidence: `{(f.evidence or '').replace('`','').strip()[:280]}`  \n"
                f"   • Cause: {f.cause}  \n"
                f"   • Fix: {f.fix}"
            )
            lines.append("")
        return "\n".join(lines)

    # ----- Section 6: Next steps (LLM-narrated if provided) -----------
    _NEXT_STEPS_PROMPT = """You are a senior PayU payments support engineer.

I will give you a structured diagnosis of a single PayU transaction. Your job
is to write a concise, opinionated "Recommended next steps" section (4 to 7
bullet points) for the payer-facing merchant / integrator AND for internal
engineering. Be specific: reference real processIds, error codes, bank codes,
URLs, and the exact pattern names in your bullets. Do NOT repeat the verdict
headline verbatim — add value by explaining what to do next.

Format:
## 6. Recommended next steps

- **For the merchant/integrator:** <bullet>
- **For PayU engineering:** <bullet>
- (more as needed, prefix each with one of the two labels above)

DIAGNOSIS:
"""

    def _render_llm_context(
        self,
        facts: TransactionFacts,
        findings: List[Finding],
        verdict: Verdict,
    ) -> str:
        parts: List[str] = []
        parts.append(f"VERDICT: {verdict.label} — {verdict.headline}")
        parts.append("FACTS:")
        for k, v in dataclasses.asdict(facts).items():
            parts.append(f"  {k}: {v}")
        parts.append(f"FINDINGS ({len(findings)}):")
        for f in findings:
            parts.append(
                f"  [{f.severity}] [{f.category}] {f.name} x{f.count} "
                f"(pid={f.process_id}, ts={f.timestamp}) — {f.cause}"
            )
        return "\n".join(parts)

    def _section_6_next_steps(
        self,
        facts: TransactionFacts,
        findings: List[Finding],
        verdict: Verdict,
        llm=None,
    ) -> str:
        if llm is not None and findings:
            ctx = self._render_llm_context(facts, findings, verdict)
            prompt = self._NEXT_STEPS_PROMPT + ctx
            try:
                resp = llm.invoke(prompt)
                narrative = (getattr(resp, "content", None) or str(resp)).strip()
                if narrative.startswith("## 6"):
                    return narrative + "\n"
                return "## 6. Recommended next steps\n\n" + narrative + "\n"
            except Exception as exc:  # pragma: no cover
                logger.warning("LLM next-steps synthesis failed: %s", exc)

        # Deterministic fallback -------------------------------------------
        lines: List[str] = ["## 6. Recommended next steps", ""]
        merchant_steps: List[str] = []
        eng_steps: List[str] = []

        for f in findings:
            bullet = f"{f.name} — {f.fix}"
            if f.category in ("merchant-config", "observability"):
                merchant_steps.append(bullet)
            elif f.category in ("bank", "gateway"):
                merchant_steps.append(bullet)
            else:
                eng_steps.append(bullet)

        if verdict.label == "SUCCESS" and not findings:
            lines.append(
                "- **For the merchant/integrator:** No action required — "
                f"transaction captured cleanly (bank_ref=`{facts.bank_ref_no}`)."
            )
            lines.append("- **For PayU engineering:** No action required.")
        else:
            if not merchant_steps and verdict.label.startswith("DEGRADED"):
                merchant_steps.append(
                    "Transaction captured — review the warnings below only if the "
                    "behaviour was not expected."
                )
            for s in merchant_steps[:5]:
                lines.append(f"- **For the merchant/integrator:** {s}")
            for s in eng_steps[:5]:
                lines.append(f"- **For PayU engineering:** {s}")
            if not merchant_steps and not eng_steps:
                lines.append(
                    "- **For PayU engineering:** Review the per-processId timeline and "
                    "raw evidence — no named patterns matched the logs."
                )
        lines.append("")
        return "\n".join(lines)

    # ----- Section 7: Evidence pack -----------------------------------
    def _raw_snippets_for_jira(
        self,
        errors_warnings: List[ParsedLog],
        max_lines: int = 25,
    ) -> List[ParsedLog]:
        return errors_warnings[:max_lines]

    def _section_7_evidence(
        self,
        payu_id: str,
        facts: TransactionFacts,
        findings: List[Finding],
        verdict: Verdict,
        errors_warnings: List[ParsedLog],
        pid_log_counts: Dict[str, int],
        opensearch_url: str,
        lookback_days: int,
    ) -> str:
        pids = list(pid_log_counts.keys())
        lines: List[str] = ["## 7. Evidence pack", ""]

        # ---- Discover links -------------------------------------------
        lines.append("**🔗 OpenSearch Discover links**")
        lines.append(f"- payuId: [{payu_id}]({opensearch_url})")
        for pid in pids:
            if not pid or pid == "unknown":
                continue
            url = build_opensearch_discover_url(query=pid, lookback_days=lookback_days)
            lines.append(f"- processId `{pid}` ({pid_log_counts[pid]} lines): [open]({url})")
        lines.append("")

        # ---- Raw evidence block ---------------------------------------
        snippets = self._raw_snippets_for_jira(errors_warnings)
        if snippets:
            lines.append("**📋 Raw log evidence (chronological, untruncated)**")
            lines.append("")
            lines.append("```log")
            for i, p in enumerate(snippets, 1):
                header = (
                    f"[{i:02d}] {p.log_ts} | {p.severity.upper():<6} | "
                    f"pid={p.process_id or '-'} | {p.location or '-'}"
                )
                lines.append(header)
                for body_line in (p.body or p.raw).splitlines():
                    lines.append(f"     {body_line}")
                lines.append("")
            lines.append("```")
            lines.append("")

        # ---- Jira-ready text block ------------------------------------
        jira = self._build_jira_block(
            payu_id=payu_id,
            pids=pids,
            pid_log_counts=pid_log_counts,
            facts=facts,
            findings=findings,
            verdict=verdict,
            opensearch_url=opensearch_url,
            lookback_days=lookback_days,
            snippets=snippets,
        )
        lines.append("**🎫 Jira-ready text block (paste into description)**")
        lines.append("")
        lines.append("```text")
        lines.append(jira)
        lines.append("```")
        lines.append("")
        return "\n".join(lines)

    def _build_jira_block(
        self,
        payu_id: str,
        pids: List[str],
        pid_log_counts: Dict[str, int],
        facts: TransactionFacts,
        findings: List[Finding],
        verdict: Verdict,
        opensearch_url: str,
        lookback_days: int,
        snippets: List[ParsedLog],
    ) -> str:
        lines: List[str] = []
        lines.append("===== PayU Transaction Incident =====")
        lines.append(f"verdict         : {verdict.label} — {verdict.headline}")
        lines.append(f"payuId          : {payu_id}")
        lines.append(f"merchant        : key={facts.merchant_key} id={facts.merchant_id}")
        lines.append(f"merchant txnid  : {facts.merchant_txnid}")
        lines.append(f"amount          : {facts.amount} {facts.currency}")
        lines.append(
            f"flow            : {facts.flow_type or 'n/a'} · PG={facts.pg_id or 'n/a'} "
            f"· bank={facts.bank_code or 'n/a'}/{facts.payment_mode or 'n/a'}"
        )
        lines.append(
            f"outcome         : status={facts.final_status or 'n/a'} "
            f"· error_code={facts.error_code or 'n/a'} · bank_ref={facts.bank_ref_no or 'n/a'}"
        )
        if facts.merchant_webhook_url:
            lines.append(
                f"merchant webhook: {facts.merchant_webhook_url} "
                f"→ {facts.merchant_webhook_outcome or 'unknown'}"
            )
        lines.append(f"index           : {DEFAULT_OS_INDEX}")
        lines.append(f"lookback        : {lookback_days} day(s)")
        lines.append(
            f"processIds      : {', '.join(pids) if pids else '(none)'}"
        )
        lines.append(
            "pid counts      : "
            + ", ".join(f"{p}={pid_log_counts[p]}" for p in pids)
        )
        lines.append(f"opensearch url  : {opensearch_url}")
        lines.append("")
        lines.append("----- Findings -----")
        for f in findings:
            lines.append(
                f"[{f.severity.upper()}] [{f.category}] {f.name} "
                f"(pid={f.process_id}, ts={f.timestamp}, x{f.count})"
            )
            lines.append(f"   cause: {f.cause}")
            lines.append(f"   fix  : {f.fix}")
        lines.append("")
        lines.append("----- Raw evidence (errors + warnings, chronological) -----")
        for i, p in enumerate(snippets, 1):
            lines.append(
                f"[{i:02d}] {p.log_ts} | {p.severity.upper():<6} | pid={p.process_id or '-'} | {p.location}"
            )
            lines.append(f"     {(p.body or p.raw)[:1500]}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Public entrypoint                                                  #
    # ------------------------------------------------------------------ #
    def render_incident_report_markdown(
        self,
        payu_id: str,
        lookback_days: int,
        expansion_pids: Optional[List[str]] = None,
        llm=None,
    ) -> Dict[str, Any]:
        """Return a dict with the full markdown report plus structured bits."""
        bundle = self.compute_report_bundle(payu_id)
        facts: TransactionFacts = bundle["facts"]
        findings: List[Finding] = bundle["findings"]
        verdict: Verdict = bundle["verdict"]
        events_per_pid = bundle["per_pid_events"]
        errors_warnings = bundle["errors_warnings"]

        pid_log_counts = {pid: len(entries) for pid, entries in self.logs_per_pid.items()}
        opensearch_url = build_opensearch_discover_url(
            query=payu_id, lookback_days=lookback_days
        )

        report_parts = [
            f"# Incident Report — payuId `{payu_id}`",
            "",
            self._section_1_verdict(verdict),
            self._section_2_facts(
                facts,
                total_logs=len(self.parsed),
                pid_count=len(self.logs_per_pid),
                expansion_pids=expansion_pids or [],
            ),
            self._section_3_per_pid(
                events_per_pid=events_per_pid,
                pid_log_counts=pid_log_counts,
                lookback_days=lookback_days,
            ),
            self._section_4_findings(bundle["non_infra_findings"]),
            self._section_5_infra(bundle["infra_findings"]),
            self._section_6_next_steps(facts, findings, verdict, llm=llm),
            self._section_7_evidence(
                payu_id=payu_id,
                facts=facts,
                findings=findings,
                verdict=verdict,
                errors_warnings=errors_warnings,
                pid_log_counts=pid_log_counts,
                opensearch_url=opensearch_url,
                lookback_days=lookback_days,
            ),
        ]
        markdown = "\n".join(report_parts)

        return {
            "markdown": markdown,
            "facts": dataclasses.asdict(facts),
            "verdict": dataclasses.asdict(verdict),
            "findings": [dataclasses.asdict(f) for f in findings],
            "events_per_pid": {
                pid: [dataclasses.asdict(e) for e in events]
                for pid, events in events_per_pid.items()
            },
            "pid_log_counts": pid_log_counts,
            "opensearch_url": opensearch_url,
        }


# --------------------------------------------------------------------- #
# Public entrypoint                                                      #
# --------------------------------------------------------------------- #
def summarize_logs_for_payu_id(
    payu_id: str,
    lookback_days: int = 7,
    llm=None,
    client: Optional[OpenSearchClient] = None,
) -> Dict[str, Any]:
    """Fetch + analyse + render the Incident Report for one payuId.

    Returns a dict with:
      - ``payu_id``          : str
      - ``total_logs``       : int
      - ``process_ids``      : list[str]
      - ``expansion_pids``   : list[str]
      - ``markdown``         : full Incident Report markdown (7 sections)
      - ``verdict``          : dict (label, emoji, headline)
      - ``facts``            : dict (TransactionFacts)
      - ``findings``         : list[dict]
      - ``events_per_pid``   : dict[str, list[dict]]
      - ``opensearch_url``   : str
      - ``narrative``        : str (only when llm=None and no logs — legacy key)
    """
    os_client = client or get_opensearch_client()
    bundle = os_client.fetch_all_logs_for_payu_id(
        payu_id=payu_id, lookback_days=lookback_days,
    )

    if not bundle["logs"]:
        url = build_opensearch_discover_url(
            query=str(bundle["payu_id"]), lookback_days=lookback_days
        )
        return {
            "payu_id": bundle["payu_id"],
            "total_logs": 0,
            "process_ids": [],
            "expansion_pids": [],
            "markdown": (
                f"# Incident Report — payuId `{bundle['payu_id']}`\n\n"
                "## 1. Verdict\n"
                "⚪ **NO DATA** — no log lines were found in "
                f"`{DEFAULT_OS_INDEX}` for the last {lookback_days} day(s).\n\n"
                f"🔗 Try widening the window manually: {url}\n"
            ),
            "opensearch_url": url,
            "narrative": "",
        }

    analyzer = LogAnalyzer(
        docs=bundle["logs"], logs_per_pid_docs=bundle.get("logs_per_pid"),
    )
    rendered = analyzer.render_incident_report_markdown(
        payu_id=bundle["payu_id"],
        lookback_days=lookback_days,
        expansion_pids=bundle.get("expansion_pids") or [],
        llm=llm,
    )

    return {
        "payu_id": bundle["payu_id"],
        "total_logs": len(bundle["logs"]),
        "process_ids": bundle.get("process_ids") or [],
        "expansion_pids": bundle.get("expansion_pids") or [],
        "counts_per_pid": bundle.get("counts_per_pid") or {},
        **rendered,
    }
