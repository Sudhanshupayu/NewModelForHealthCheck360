"""Transaction diagnostics & pattern library for PayU core-payment logs.

Two responsibilities:

1. **Fact extraction** — build a :class:`TransactionFacts` snapshot of what
   the transaction actually *was* (merchant, amount, flow type, PG used,
   final status, error code, bank ref no, etc.) by scanning parsed logs.

2. **Pattern matching** — run every log body against a library of named
   PayU patterns (gRPC unreachable, tokenisation skipped, invalid child
   merchants, webhook delivery failure, bank decline, hash mismatch, …)
   and produce a list of :class:`Finding` objects with severity, cause
   and a canned fix.

The combination feeds the Incident Report rendered by ``log_analyzer.py``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Pattern, Tuple

from .log_parser import ParsedLog


# ===================================================================== #
# Data shapes                                                            #
# ===================================================================== #
@dataclass
class TransactionFacts:
    payu_id: str = ""
    mihpayid: str = ""
    merchant_txnid: str = ""
    merchant_key: str = ""
    merchant_id: str = ""
    amount: str = ""
    currency: str = "INR"
    flow_type: str = ""                # Seamless / NonSeamless / (blank)
    pg_id: str = ""                    # selected PG id (e.g. "51")
    pg_url: str = ""                   # post_uri for the gateway (e.g. pgsim01.payu.in/initiate)
    bank_code: str = ""                # AMON, KKBK, UTIB, etc.
    payment_mode: str = ""             # CASH, CC, DC, NB, UPI, ...
    final_status: str = ""             # initiated / in progress / captured / failed / bounced
    error_code: str = ""               # E000, E1501, ...
    bank_ref_no: str = ""              # bank-side reference
    bank_message: str = ""             # "Transaction Completed Successfully", etc.
    tokenised: Optional[bool] = None
    split_status: str = ""             # invalidSplitReceived, none, ...
    merchant_webhook_url: str = ""
    merchant_webhook_outcome: str = ""  # "success" / "failed" / ""
    call_graph: List[str] = field(default_factory=list)
    # Window
    first_ts: str = ""
    last_ts: str = ""


@dataclass
class Finding:
    severity: str      # critical / error / warning / info
    category: str      # merchant-config / infra / bank / gateway / flow / observability
    name: str
    cause: str
    fix: str
    timestamp: str = ""
    process_id: str = ""
    location: str = ""
    evidence: str = ""
    count: int = 1


@dataclass
class Verdict:
    label: str         # SUCCESS / FAILURE / DEGRADED / UNKNOWN
    emoji: str
    headline: str      # one-liner explaining why


# Severity → emoji mapping for human rendering
_SEV_EMOJI = {
    "critical": "🛑",
    "error":    "🔴",
    "warning":  "🟠",
    "warn":     "🟠",
    "info":     "🔵",
    "debug":    "⚪",
}
_SEV_RANK = {"critical": 4, "error": 3, "warning": 2, "warn": 2, "info": 1, "debug": 0}


def sev_emoji(sev: str) -> str:
    return _SEV_EMOJI.get((sev or "").lower(), "⚪")


# ===================================================================== #
# Fact extractor                                                         #
# ===================================================================== #
_PHP_STRING_RX = r's:\d+:"(?P<{name}>(?:[^"\\]|\\.)*)"'   # placeholder per call


def _php_val(body: str, key: str) -> Optional[str]:
    """Extract a value from a PHP-serialized array for a given string key.

    Matches ``s:N:"<key>";s:M:"<value>"`` and returns ``<value>`` if found.
    """
    rx = re.compile(rf's:\d+:"{re.escape(key)}";s:\d+:"([^"]*)"')
    m = rx.search(body)
    return m.group(1) if m else None


def _json_val(body: str, key: str) -> Optional[str]:
    """Extract a quoted JSON string value for ``key`` from a body."""
    rx = re.compile(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"')
    m = rx.search(body)
    return m.group(1) if m else None


# Regex helpers for structured UPDATE bindings ---------------------------
# Example tail:  - [103,"captured","Transaction Completed Successfully","6aeb7080-…","E000",null,403993715537264905]
_FINAL_UPDATE_RX = re.compile(
    r"UPDATE\s+transaction\s+SET\s+uniqueness\s*=\s*\?,\s*status\s*=\s*\?,\s*field9\s*=\s*\?,"
    r"\s*bank_ref_no\s*=\s*\?,\s*error_code\s*=\s*\?"
    r".*?\-\s*\[(?P<uniq>\d+)\s*,\s*\"(?P<status>[^\"]*)\"\s*,\s*\"(?P<field9>[^\"]*)\"\s*,"
    r"\s*\"?(?P<bank_ref>[^\",]*)\"?\s*,\s*\"(?P<err>E\d+)\"",
    re.DOTALL | re.IGNORECASE,
)

# `UPDATE transaction SET status = ?, paymentgatewayid = ? WHERE id = ? - ["in progress",51,…]`
_STATUS_PG_UPDATE_RX = re.compile(
    r"UPDATE\s+transaction\s+SET\s+status\s*=\s*\?,\s*paymentgatewayid\s*=\s*\?"
    r".*?\-\s*\[\"(?P<status>[^\"]*)\"\s*,\s*(?P<pg>\d+)",
    re.DOTALL | re.IGNORECASE,
)

# ibibo_code + mode update: - ["AMON","CASH",…]
_BANK_MODE_UPDATE_RX = re.compile(
    r"UPDATE\s+transaction\s+SET\s+ibibo_code\s*=\s*\?,\s*mode\s*=\s*\?"
    r".*?\-\s*\[\"(?P<bank>[^\"]*)\"\s*,\s*\"(?P<mode>[^\"]*)\"",
    re.DOTALL | re.IGNORECASE,
)

_FINAL_PG_RX = re.compile(r"Final Selected Pg:\s*(\d+)", re.IGNORECASE)
_FLOW_TYPE_RX = re.compile(r'"flowType"\s*:\s*"([^"]+)"')
_POST_URI_RX = re.compile(r'"post_uri"\s*:\s*"([^"]+)"')

_ACTION_CALLED_RX = re.compile(r"Action Called\s*-\s*(\S+)")
_MERCHANT_WEBHOOK_REQ_RX = re.compile(
    r"merchant curl call for payuId\s+\d+:\s+Url is\s+(\S+)"
)
_MERCHANT_WEBHOOK_RESP_RX = re.compile(
    r"merchant curl call for payuId\s+\d+\..*?Response received is\s+(\{.*?\})",
    re.DOTALL,
)

# ---- S2S / merchant-hosted failure response parsers --------------------
# Many seamless/S2S flows deliver the TERMINAL outcome inline via an
# "S2S response sent back is: {...}" log line rather than the legacy
# UPDATE-transaction SQL. We parse those bodies here.
_S2S_RESPONSE_MARKER = "S2S response sent back is"
_S2S_RESULT_STATUS_RX = re.compile(
    r'"status"\s*:\s*"(?P<status>[A-Za-z_\-]+)"'
)
_S2S_UNMAPPED_RX = re.compile(
    r'"unmappedStatus"\s*:\s*"(?P<status>[A-Za-z_\-]+)"', re.IGNORECASE,
)
_S2S_ERROR_CODE_RX = re.compile(
    r'"(?:error|errorCode|statusCode)"\s*:\s*"(E\d+)"'
)
_S2S_ERROR_MSG_RX = re.compile(
    r'"(?:error_Message|errorMessage|field9)"\s*:\s*"([^"]+)"'
)
_S2S_BANKCODE_RX = re.compile(r'"bankcode"\s*:\s*"([^"]+)"')
_S2S_MODE_RX = re.compile(r'"mode"\s*:\s*"([^"]+)"')
_S2S_MIHPAYID_RX = re.compile(r'"mihpayid"\s*:\s*"([^"]+)"')
_S2S_BANK_REF_RX = re.compile(r'"bank_ref_no"\s*:\s*"([^"]+)"')
_S2S_PG_TYPE_RX = re.compile(r'"PG_TYPE"\s*:\s*"([^"]+)"')
_S2S_META_MESSAGE_RX = re.compile(r'"message"\s*:\s*"([^"]+)"')
_S2S_FIELD7_RX = re.compile(r'"field7"\s*:\s*"([^"]+)"')

_TERMINAL_FAILURE_STATUSES = {"failure", "failed", "cancelled", "userCancelled".lower(), "dropped", "bounced"}
_TERMINAL_SUCCESS_STATUSES = {"success", "successful", "captured"}


def _is_terminal_s2s_failure(body: str) -> bool:
    """Is this a terminal-failure S2S response?"""
    if _S2S_RESPONSE_MARKER not in body:
        return False
    # Must contain a terminal failure token alongside an E-error-code
    has_fail_status = bool(
        re.search(
            r'"(?:status|unmappedStatus|unmappedstatus)"\s*:\s*"(?:failure|failed|cancelled|dropped|bounced)"',
            body,
            re.IGNORECASE,
        )
    )
    has_err = bool(_S2S_ERROR_CODE_RX.search(body))
    return has_fail_status or (has_err and '"status":"failure"' in body.lower())


def extract_transaction_facts(
    parsed_logs: List[ParsedLog], payu_id_hint: str = ""
) -> TransactionFacts:
    """Walk parsed logs and build a :class:`TransactionFacts` snapshot."""
    facts = TransactionFacts(payu_id=payu_id_hint)

    if parsed_logs:
        facts.first_ts = parsed_logs[0].log_ts
        facts.last_ts = parsed_logs[-1].log_ts

    for p in parsed_logs:
        body = p.body

        # --- action chain ---------------------------------------------
        if p.is_request:
            m = _ACTION_CALLED_RX.search(body)
            if m and m.group(1) not in facts.call_graph:
                facts.call_graph.append(m.group(1))

        # --- merchant request fields (PHP-serialized) ------------------
        if "Action Called" in body and "with params" in body:
            for key_src, dst in (
                ("key", "merchant_key"),
                ("txnid", "merchant_txnid"),
                ("amount", "amount"),
            ):
                if not getattr(facts, dst):
                    v = _php_val(body, key_src)
                    if v:
                        setattr(facts, dst, v)

        # --- merchant_id + mihpayid (multiple sources) -----------------
        if "INSERT INTO transaction SET merchantid" in body and not facts.merchant_id:
            m = re.search(
                r"INSERT INTO transaction SET merchantid\s*=\s*\?.*?-\s*\[(\d+)",
                body, re.DOTALL,
            )
            if m:
                facts.merchant_id = m.group(1)

        if not facts.mihpayid:
            v = _json_val(body, "mihpayid") or _php_val(body, "mihpayid")
            if v:
                facts.mihpayid = v

        # --- flow type ------------------------------------------------
        if not facts.flow_type:
            m = _FLOW_TYPE_RX.search(body)
            if m:
                facts.flow_type = m.group(1)

        # --- PG selection ---------------------------------------------
        if not facts.pg_id:
            m = _FINAL_PG_RX.search(body)
            if m:
                facts.pg_id = m.group(1)
        if not facts.pg_url:
            m = _POST_URI_RX.search(body)
            if m:
                # JSON-escaped slashes come through as \/ — unescape for display
                facts.pg_url = m.group(1).replace(r"\/", "/")

        # --- bank / payment mode --------------------------------------
        if not facts.bank_code:
            m = _BANK_MODE_UPDATE_RX.search(body)
            if m:
                facts.bank_code = m.group("bank")
                facts.payment_mode = m.group("mode")

        # --- intermediate `in progress` status + PG id ----------------
        m = _STATUS_PG_UPDATE_RX.search(body)
        if m:
            # We'll keep overwriting — the *last* one wins
            facts.final_status = m.group("status")
            if not facts.pg_id:
                facts.pg_id = m.group("pg")

        # --- FINAL status/error/bank_ref_no ---------------------------
        m = _FINAL_UPDATE_RX.search(body)
        if m:
            facts.final_status = m.group("status")
            facts.error_code = m.group("err")
            facts.bank_message = m.group("field9")
            facts.bank_ref_no = m.group("bank_ref").strip()

        # --- Terminal S2S failure response ----------------------------
        # Many seamless/S2S flows (Pure S2S cards, 3DS ACS, UPI Collect,
        # NB S2S, etc.) never write the legacy UPDATE transaction SQL.
        # Their terminal state is delivered inline as:
        #    S2S response sent back is: { ...,"result":{"status":"failure",
        #        "error":"E2502","error_Message":"Bank was unable to
        #        authenticate.","field7":"AUCNEGATIVE",... }}
        if _is_terminal_s2s_failure(body):
            sm = _S2S_RESULT_STATUS_RX.search(body) or _S2S_UNMAPPED_RX.search(body)
            if sm:
                facts.final_status = sm.group("status").lower()
            ec = _S2S_ERROR_CODE_RX.search(body)
            if ec:
                facts.error_code = ec.group(1)
            em = _S2S_ERROR_MSG_RX.search(body)
            if em:
                facts.bank_message = em.group(1)
            bc = _S2S_BANKCODE_RX.search(body)
            if bc and not facts.bank_code:
                facts.bank_code = bc.group(1)
            mo = _S2S_MODE_RX.search(body)
            if mo and not facts.payment_mode:
                facts.payment_mode = mo.group(1)
            mih = _S2S_MIHPAYID_RX.search(body)
            if mih and not facts.mihpayid:
                facts.mihpayid = mih.group(1)
            br = _S2S_BANK_REF_RX.search(body)
            if br and br.group(1) and not facts.bank_ref_no:
                facts.bank_ref_no = br.group(1)
            if not facts.flow_type:
                pg = _S2S_PG_TYPE_RX.search(body)
                if pg:
                    # Presence of an S2S response + PG_TYPE implies seamless/S2S flow
                    facts.flow_type = f"Seamless ({pg.group(1)})"

        # --- tokenisation flag ----------------------------------------
        if facts.tokenised is None:
            if re.search(r"marking the transaction as non tokenized", body, re.I):
                facts.tokenised = False
            elif re.search(r"enable_tokenized_flow\"\s*:\s*true", body):
                facts.tokenised = True

        # --- split status ---------------------------------------------
        if not facts.split_status:
            m = re.search(r'"splitStatus"\s*:\s*"([^"]+)"', body)
            if m:
                facts.split_status = m.group(1)
            elif "Invalid child merchants" in body:
                facts.split_status = "invalidSplitReceived"

        # --- merchant webhook -----------------------------------------
        if not facts.merchant_webhook_url:
            m = _MERCHANT_WEBHOOK_REQ_RX.search(body)
            if m:
                facts.merchant_webhook_url = m.group(1).rstrip(".,;")
        if facts.merchant_webhook_url and not facts.merchant_webhook_outcome:
            if "merchant curl call" in body and "Response received" in body:
                if re.search(r'"success"\s*:\s*false|"error"\s*:\s*\{', body):
                    facts.merchant_webhook_outcome = "failed"
                elif re.search(r'HTTP\s+2\d{2}|"success"\s*:\s*true', body):
                    facts.merchant_webhook_outcome = "success"

    # Normalise currency / amount for display
    if facts.amount and not facts.currency:
        facts.currency = "INR"

    return facts


# ===================================================================== #
# Pattern library                                                        #
# ===================================================================== #
# Each pattern: regex → Finding template. `severity` is the effective severity.
@dataclass
class _Pattern:
    regex: Pattern[str]
    name: str
    severity: str
    category: str
    cause: str
    fix: str


_PATTERNS: List[_Pattern] = [
    # --- merchant-config / flow -----------------------------------------
    _Pattern(
        regex=re.compile(
            r"MANDATORY INPUT VARIABLES MISSING FOR PERFORMING TOKENISED TRANSACTION"
            r"\s*-\s*(?P<field>[\w,\s]+?)\s+therefore marking the transaction as non tokenized",
            re.IGNORECASE,
        ),
        name="Tokenisation skipped — missing required field",
        severity="warning",
        category="merchant-config",
        cause=(
            "The merchant requested a tokenised card flow but did not supply the "
            "required field. PayU fell back to a non-tokenised flow."
        ),
        fix=(
            "If a tokenised txn was intended, include `user_credentials` (and any "
            "other flagged field) in the payment request. Otherwise this is expected."
        ),
    ),
    _Pattern(
        regex=re.compile(r"Invalid child merchants", re.IGNORECASE),
        name="Split transaction rejected — invalid child merchants",
        severity="warning",
        category="merchant-config",
        cause=(
            "One or more `paymentParts[].merchantId` values in the request do not "
            "resolve to active sub-merchants under this parent merchant."
        ),
        fix=(
            "Verify child merchant IDs via `healthcheck360.payu.in/merchant/<id>"
            "/product-details`. Remove `paymentParts` if this was not meant to be "
            "a split transaction."
        ),
    ),
    _Pattern(
        regex=re.compile(r"EXCEPTION OCCURED.*?Exception Code\s*:\s*(?P<code>EX\d+)", re.IGNORECASE | re.DOTALL),
        name="Vendor flow pre-init exception",
        severity="warning",
        category="flow",
        cause=(
            "A legacy vendor/aggregator flow raised an exception during init. "
            "Typically handled by fallback; non-fatal if the final state is captured."
        ),
        fix=(
            "Non-fatal if final status = `captured`. Investigate only if recurring "
            "for this merchant or if the final status is not captured."
        ),
    ),
    _Pattern(
        regex=re.compile(r"Hash\s+mismatch|hash\s+validation\s+failed", re.IGNORECASE),
        name="Hash mismatch",
        severity="critical",
        category="merchant-config",
        cause=(
            "The hash computed by PayU does not match the one sent by the merchant."
        ),
        fix=(
            "Recompute the SHA-512 hash using the correct formula and salt "
            "version. Use the bot's `generate_integration_code` to verify the "
            "formula for the flow."
        ),
    ),
    _Pattern(
        regex=re.compile(r"Invalid merchant key|Merchant key is invalid", re.IGNORECASE),
        name="Invalid merchant key",
        severity="critical",
        category="merchant-config",
        cause="The `key` in the payment request does not match an active PayU merchant.",
        fix="Confirm the live/test key from the PayU dashboard and update the payload.",
    ),

    # --- bank / gateway -------------------------------------------------
    _Pattern(
        regex=re.compile(r'"errorCode"\s*:\s*"E1501"'),
        name="EMI ineligible (E1501) — amount below bank minimum",
        severity="info",
        category="bank",
        cause=(
            "An EMI pre-eligibility check returned E1501. Transaction amount is "
            "below the issuing bank's minimum threshold for EMI processing."
        ),
        fix="No action required — this is an informational eligibility check.",
    ),
    _Pattern(
        regex=re.compile(r"bank\s+declin|BANK_DECLINED|card\s+declined", re.IGNORECASE),
        name="Bank declined transaction",
        severity="error",
        category="bank",
        cause="The issuing bank declined the transaction.",
        fix="Ask customer to retry with a different card, verify 2FA, or check funds.",
    ),
    _Pattern(
        regex=re.compile(
            r'"(?:error|errorCode|statusCode)"\s*:\s*"E2502"|Bank\s+was\s+unable\s+to\s+authenticate',
            re.IGNORECASE,
        ),
        name="Bank authentication failed (E2502) — 3DS/ACS negative",
        severity="critical",
        category="bank",
        cause=(
            "The card issuer's 3DS / ACS layer returned a negative "
            "authentication result. The cardholder could NOT be authenticated "
            "(wrong OTP, expired 2FA session, or bank-side block). "
            "`error_Message` / `field9` carried the exact bank message."
        ),
        fix=(
            "Ask the customer to retry — entering the correct OTP, or using a "
            "different card / network. Repeated E2502 on the same card or BIN "
            "range means the bank is consistently failing 3DS; consider "
            "routing or contacting the issuer."
        ),
    ),
    _Pattern(
        regex=re.compile(r'"field7"\s*:\s*"AUCNEGATIVE"'),
        name="Bank 3DS returned AUCNEGATIVE (negative authentication)",
        severity="error",
        category="bank",
        cause=(
            "`field7=AUCNEGATIVE` is the PayU-normalised bank response for "
            "a negative authentication verdict from the card issuer's ACS."
        ),
        fix=(
            "Retry with correct OTP/credentials, or a different card. "
            "Persistent AUCNEGATIVE on a specific card = bank is blocking."
        ),
    ),
    _Pattern(
        regex=re.compile(r"Payu\s+unable\s+to\s+parse\s+ACS\s+page", re.IGNORECASE),
        name="ACS page parse failure (native 3DS decoder)",
        severity="critical",
        category="gateway",
        cause=(
            "PayU's native 3DS flow could not parse the ACS page returned by "
            "the card issuer — the HTML shape did not match any known "
            "template. Often caused by new ACS templates rolled out by banks."
        ),
        fix=(
            "File with PayU engineering — the ACS template decoder needs an "
            "update for this issuer. Merchant can retry with a different card "
            "or opt out of native 3DS and use the standard redirect flow."
        ),
    ),
    _Pattern(
        regex=re.compile(
            r'"(?:status|unmappedStatus|unmappedstatus)"\s*:\s*"(?:failure|failed|cancelled|dropped|bounced)"',
            re.IGNORECASE,
        ),
        name="Transaction marked failure in S2S response",
        severity="error",
        category="gateway",
        cause=(
            "PayU returned a terminal failure status (`status=failure` / "
            "`unmappedStatus=failed`) to the merchant via the S2S response. "
            "Inspect the accompanying `error` / `error_Message` fields for "
            "the specific reason."
        ),
        fix=(
            "Look at the exact error_code + error_Message in the same log "
            "line — it already tells you whether this was a 3DS negative, "
            "a timeout, a hash mismatch, or a bank decline."
        ),
    ),

    # --- infra ----------------------------------------------------------
    _Pattern(
        regex=re.compile(
            r"failed to connect to all addresses.*?tcp handshaker shutdown",
            re.IGNORECASE | re.DOTALL,
        ),
        name="gRPC AsyncQuery unreachable (TCP handshake failure)",
        severity="error",
        category="infra",
        cause=(
            "gRPC call to the internal AsyncQuery service "
            "(commonly 10.251.1.174:9090) failed during TCP handshake."
        ),
        fix=(
            "Non-fatal — system auto-falls-back to synchronous HTTPS curl. "
            "Engineering should investigate AsyncQuery service health if persistent."
        ),
    ),
    _Pattern(
        regex=re.compile(r"Deadline\s+Exceeded", re.IGNORECASE),
        name="gRPC deadline exceeded",
        severity="warning",
        category="infra",
        cause="A gRPC call exceeded its deadline.",
        fix=(
            "Check downstream service health. Usually paired with an HTTP fallback "
            "in the same flow — inspect whether the fallback succeeded."
        ),
    ),
    _Pattern(
        regex=re.compile(r"Connection\s+timed\s+out", re.IGNORECASE),
        name="Connection timeout",
        severity="warning",
        category="infra",
        cause="A TCP connection to an internal/external service timed out.",
        fix="Verify target host reachability and timeout budgets.",
    ),

    # --- observability / merchant webhook -------------------------------
    _Pattern(
        regex=re.compile(
            r"merchant curl call for payuId.*?Response received is.*?"
            r'(?:"success"\s*:\s*false|"error"\s*:\s*\{)',
            re.DOTALL,
        ),
        name="Merchant webhook delivery failed",
        severity="warning",
        category="observability",
        cause=(
            "PayU posted the payment response to the merchant's configured callback "
            "URL, but the merchant endpoint returned an error (`success:false` or "
            "an error object)."
        ),
        fix=(
            "Merchant must verify their webhook endpoint accepts POSTs and returns "
            "HTTP 2xx. If using webhook.site for testing, ensure the token is "
            "valid. PayU retries on configured schedule."
        ),
    ),
]


def extract_findings(parsed_logs: List[ParsedLog]) -> List[Finding]:
    """Run every pattern against every parsed log and return findings.

    Duplicate findings (same pattern + same process_id) are collapsed into
    a single ``Finding`` with ``count`` incremented.
    """
    grouped: Dict[Tuple[str, str], Finding] = {}

    for p in parsed_logs:
        body = p.body or p.raw or ""
        if not body:
            continue
        for pat in _PATTERNS:
            if pat.regex.search(body):
                key = (pat.name, p.process_id or "")
                if key in grouped:
                    grouped[key].count += 1
                    continue
                grouped[key] = Finding(
                    severity=pat.severity,
                    category=pat.category,
                    name=pat.name,
                    cause=pat.cause,
                    fix=pat.fix,
                    timestamp=p.log_ts,
                    process_id=p.process_id or "",
                    location=p.location,
                    evidence=body[:320],
                )

    findings = list(grouped.values())
    findings.sort(key=lambda f: (-_SEV_RANK.get(f.severity, 0), f.timestamp))
    return findings


# ===================================================================== #
# Verdict                                                                #
# ===================================================================== #
_SUCCESS_STATUSES = {"captured", "success", "successful"}
_FAILURE_STATUSES = {"failed", "failure", "bounced", "dropped", "userCancelled".lower()}
_PENDING_STATUSES = {"initiated", "in progress", "pending"}


def determine_verdict(
    facts: TransactionFacts, findings: List[Finding]
) -> Verdict:
    """Produce a coarse verdict label for the transaction."""
    status = (facts.final_status or "").strip().lower()
    err = (facts.error_code or "").upper()
    has_critical = any(f.severity == "critical" for f in findings)
    has_error = any(f.severity == "error" for f in findings)
    has_warning = any(f.severity in ("warning", "warn") for f in findings)

    if status in _SUCCESS_STATUSES and err in ("", "E000"):
        if has_critical:
            return Verdict(
                label="DEGRADED SUCCESS",
                emoji="🟡",
                headline=(
                    f"Captured (error_code={err or 'E000'}) but "
                    f"{sum(1 for f in findings if f.severity == 'critical')} critical "
                    "finding(s) logged — review required."
                ),
            )
        if has_error or has_warning:
            return Verdict(
                label="DEGRADED SUCCESS",
                emoji="🟡",
                headline=(
                    f"Captured (error_code={err or 'E000'}) with non-fatal "
                    "warnings / infra alerts during the flow."
                ),
            )
        return Verdict(
            label="SUCCESS",
            emoji="🟢",
            headline=f"Captured cleanly (error_code={err or 'E000'}, bank_ref={facts.bank_ref_no or 'n/a'}).",
        )

    if status in _FAILURE_STATUSES or has_critical:
        return Verdict(
            label="FAILURE",
            emoji="🔴",
            headline=(
                f"Transaction did not capture "
                f"(status={status or 'unknown'}, error_code={err or 'n/a'})."
            ),
        )

    if status in _PENDING_STATUSES:
        return Verdict(
            label="PENDING",
            emoji="🟠",
            headline=(
                f"Last seen status = `{status}`. Transaction is still in flight or "
                "never reached a terminal state in the analysed window."
            ),
        )

    if not status:
        return Verdict(
            label="UNKNOWN",
            emoji="⚪",
            headline=(
                "Could not determine a final transaction state from the analysed "
                "logs. Widen the lookback window or verify the payuId."
            ),
        )

    return Verdict(
        label="UNKNOWN",
        emoji="⚪",
        headline=f"Last seen status = `{status}` — manual review suggested.",
    )


# ===================================================================== #
# Per-processId structured timeline                                      #
# ===================================================================== #
@dataclass
class PidTimelineEvent:
    timestamp: str
    severity: str
    location: str
    kind: str          # action / db-write / exception / grpc / http-out / outcome / misc
    summary: str       # short one-liner


_KIND_RULES = [
    ("action",    lambda p: p.is_request and "Action Called" in p.body),
    ("outcome",   lambda p: "UPDATE transaction SET uniqueness" in p.body),
    ("outcome",   lambda p: "setAsSuccess" in (p.fn or "") or "TDR computed" in p.body),
    ("outcome",   lambda p: "setAsFailed" in (p.fn or "")
                           or "setTransactionAsFailed" in p.body
                           or "doFinishTransaction" in (p.fn or "")),
    ("outcome",   lambda p: _is_terminal_s2s_failure(p.body)),
    ("exception", lambda p: p.is_exception),
    ("grpc",      lambda p: (p.flow or "").lower() == "grpc" or "gRPC call for" in p.body),
    ("http-out",  lambda p: (p.cls or "").startswith("Curl") or "curl call for payuId" in p.body),
    ("db-write",  lambda p: p.context.lower() == "query" and (
        "INSERT " in p.body or "UPDATE " in p.body or "DELETE " in p.body
    )),
]


def _classify_kind(p: ParsedLog) -> str:
    for kind, pred in _KIND_RULES:
        try:
            if pred(p):
                return kind
        except Exception:  # pragma: no cover
            continue
    return "misc"


def _summarise(p: ParsedLog) -> str:
    body = p.body
    if "Action Called" in body:
        m = _ACTION_CALLED_RX.search(body)
        if m:
            return f"Action `{m.group(1)}` called"
    if "UPDATE transaction SET uniqueness" in body:
        m = _FINAL_UPDATE_RX.search(body)
        if m:
            return (
                f"Final UPDATE transaction → status=`{m.group('status')}`, "
                f"error_code=`{m.group('err')}`, bank_ref=`{m.group('bank_ref').strip() or 'n/a'}`"
            )
    # S2S terminal response — the real failure signal for S2S/seamless flows
    if _S2S_RESPONSE_MARKER in body:
        status_m = _S2S_RESULT_STATUS_RX.search(body)
        err_m = _S2S_ERROR_CODE_RX.search(body)
        msg_m = _S2S_ERROR_MSG_RX.search(body)
        meta_m = _S2S_META_MESSAGE_RX.search(body)
        parts = []
        if status_m:
            parts.append(f"status=`{status_m.group('status')}`")
        if err_m:
            parts.append(f"error=`{err_m.group(1)}`")
        if msg_m:
            parts.append(f"msg=\"{msg_m.group(1)[:120]}\"")
        elif meta_m:
            parts.append(f"msg=\"{meta_m.group(1)[:120]}\"")
        if parts:
            return "S2S response → " + ", ".join(parts)
    if p.is_exception:
        return f"Exception in `{p.location}` — {body[:160]}"
    if "gRPC call for" in body:
        m = re.search(r'code":(\d+),"details":"([^"]+)"', body)
        if m:
            return f"gRPC error code={m.group(1)} — {m.group(2)[:120]}"
        return "gRPC call"
    if "curl call for payuId" in body:
        m = re.search(r"Url is\s+(\S+)", body)
        if m:
            role = "REQUEST" if body.startswith("REQUEST") else (
                "RESPONSE" if body.startswith("RESPONSE") else "curl"
            )
            return f"{role} → {m.group(1)[:160]}"
    if p.context.lower() == "query":
        m = re.search(r"(INSERT INTO\s+\S+|UPDATE\s+\S+|DELETE\s+FROM\s+\S+)", body)
        if m:
            return m.group(1)
    # default
    return body[:160]


def build_per_pid_events(
    logs_per_pid: Dict[str, List[ParsedLog]],
) -> Dict[str, List[PidTimelineEvent]]:
    """For each processId, return a compact list of key timeline events."""
    out: Dict[str, List[PidTimelineEvent]] = {}
    for pid, logs in logs_per_pid.items():
        events: List[PidTimelineEvent] = []
        for p in logs:
            kind = _classify_kind(p)
            # Skip low-signal db-writes unless they are the FINAL update
            if kind == "db-write" and "UPDATE transaction SET uniqueness" not in p.body:
                continue
            # Promote severity for S2S terminal failure responses that are
            # logged at INFO level but clearly carry a failure outcome
            severity = p.severity
            if severity in ("info", "debug") and _is_terminal_s2s_failure(p.body):
                severity = "error"
            events.append(
                PidTimelineEvent(
                    timestamp=p.log_ts,
                    severity=severity,
                    location=p.location,
                    kind=kind,
                    summary=_summarise(p),
                )
            )
        # Cap for display readability, but ALWAYS keep outcome + exception
        # + error events (those are why the user is looking at the logs).
        if len(events) > 25:
            keep_idx = set(range(0, 12)) | set(range(len(events) - 13, len(events)))
            for i, e in enumerate(events):
                if e.kind in ("outcome", "exception") or e.severity in ("error", "critical", "warn"):
                    keep_idx.add(i)
            events = [events[i] for i in sorted(keep_idx)]
        out[pid] = events
    return out


# ===================================================================== #
# Error/warn catalogue (for section 4 of the Incident Report)            #
# ===================================================================== #
def collect_errors_and_warnings(
    parsed_logs: List[ParsedLog], limit: int = 30
) -> List[ParsedLog]:
    """Return every ERROR / EXCEPTION / WARN line, chronologically."""
    bad = [p for p in parsed_logs if p.severity in ("error", "critical", "warn")]
    # Also catch lines whose level tag says INFO but whose body clearly screams
    inflation_signals = (
        "Invalid child merchants",
        "MANDATORY INPUT VARIABLES MISSING",
        "gRPC call for payuId",
        "Connection timed out",
        "Deadline Exceeded",
        '"success":false',
        # S2S / merchant-hosted terminal failures
        '"status":"failure"',
        '"status":"failed"',
        '"unmappedStatus":"failure"',
        '"unmappedstatus":"failed"',
        '"error":"E',
        '"statusCode":"E',
        '"field7":"AUCNEGATIVE"',
        "Payu unable to parse ACS page",
        "Bank was unable to authenticate",
    )
    for p in parsed_logs:
        if p in bad:
            continue
        if any(sig in p.body for sig in inflation_signals):
            bad.append(p)
    bad.sort(key=lambda p: (p.timestamp, p.log_ts))
    return bad[:limit]
