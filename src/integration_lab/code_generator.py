"""Code generator for PayU payment integration.

Generates ready-to-use cURL commands and Python code snippets for each
payment flow (PayU Hosted AND Merchant Hosted / Seamless), with correct
hash computation using the merchant's credentials.
"""

import hashlib
import json
import time
from typing import Any, Dict, Optional

from .knowledge_base import PaymentFlow, get_flow
from .hash_calculator import (
    generate_payment_hash,
    generate_si_payment_hash,
    generate_postservice_hash,
)


DEFAULT_SAMPLE_DATA = {
    "txnid": f"TXN_{int(time.time())}",
    "amount": "100.00",
    "productinfo": "Test Product",
    "firstname": "John",
    "email": "john.doe@example.com",
    "phone": "9876543210",
    "surl": "https://yoursite.com/success",
    "furl": "https://yoursite.com/failure",
}


def _build_si_details_json(
    billing_amount: str = "100.00",
    billing_cycle: str = "adhoc",
    billing_interval: str = "1",
    payment_start_date: str = "2026-04-21",
    payment_end_date: str = "2027-04-21",
) -> str:
    """Build si_details JSON for subscription/OTM flows."""
    si_details = {
        "billingAmount": billing_amount,
        "billingCurrency": "INR",
        "billingCycle": billing_cycle,
        "billingInterval": billing_interval,
        "paymentStartDate": payment_start_date,
        "paymentEndDate": payment_end_date,
        "remarks": "Test subscription via HealthCheck360 Bot",
    }
    return json.dumps(si_details, separators=(",", ":"))


# =============================================================================
# Helpers: render cURL and utility flows
# =============================================================================

def _render_form_curl(endpoint: str, payload: Dict[str, Any]) -> str:
    """Render a POST cURL with application/x-www-form-urlencoded fields."""
    lines = [f"curl -X POST '{endpoint}' \\",
             "  -H 'Content-Type: application/x-www-form-urlencoded' \\"]
    items = list(payload.items())
    for i, (field, value) in enumerate(items):
        value_str = str(value)
        # Keep value inline; single-quote-escape for shell
        escaped = value_str.replace("'", "'\\''")
        suffix = " \\" if i < len(items) - 1 else ""
        lines.append(f"  --data-urlencode '{field}={escaped}'{suffix}")
    return "\n".join(lines)


def _generate_postservice_curl(
    flow: PaymentFlow,
    merchant_key: str,
    merchant_salt: str,
    endpoint: str,
    data: Dict[str, Any],
) -> str:
    """Build a cURL for a PostService (command|var1|salt) API."""
    # Determine command + sample var1 for the specific flow
    command, var1_sample, extra = _postservice_params_for(flow, data)
    var1 = str(var1_sample)
    hash_val = generate_postservice_hash(
        key=merchant_key, command=command, var1=var1, salt=merchant_salt
    )
    payload = {
        "key": merchant_key,
        "command": command,
        "var1": var1,
        "hash": hash_val,
    }
    payload.update(extra)
    return _render_form_curl(endpoint, payload)


def _postservice_params_for(flow: PaymentFlow, data: Dict[str, Any]) -> tuple:
    """Return (command, var1_sample, extra_fields_dict) for a postservice flow."""
    txnid = data.get("txnid", DEFAULT_SAMPLE_DATA["txnid"])
    sample_mihpayid = "403993715537264905"

    # Find command from the flow's fixed_value on 'command' field
    command = "verify_payment"
    for f in flow.required_fields:
        if f.name == "command" and f.fixed_value:
            command = f.fixed_value
            break

    fid = flow.flow_id
    if fid == "merchant_hosted_upi_mandate_status":
        var1 = json.dumps({"authPayuId": sample_mihpayid, "requestId": f"REQ_{int(time.time())}"}, separators=(",", ":"))
        return (command, var1, {})
    if fid == "merchant_hosted_upi_mandate_modify":
        var1 = json.dumps({"authPayuId": sample_mihpayid, "requestId": f"REQ_{int(time.time())}", "amount": "150.00"}, separators=(",", ":"))
        return (command, var1, {})
    if fid == "merchant_hosted_upi_pre_debit":
        var1 = json.dumps({"authPayuId": sample_mihpayid, "requestId": f"REQ_{int(time.time())}", "debitDate": "2026-05-01", "amount": "100.00"}, separators=(",", ":"))
        return (command, var1, {})
    if fid == "merchant_hosted_upi_si_transaction":
        var1 = json.dumps({
            "authpayuid": sample_mihpayid, "amount": "100.00", "txnid": txnid,
            "firstname": data.get("firstname", "John"), "email": data.get("email", "john@example.com"),
            "phone": data.get("phone", "9876543210"),
            "udf1": "ABCDE1234F||01/01/1990", "udf3": "INV_001||Acme Corp",
        }, separators=(",", ":"))
        return (command, var1, {})
    if fid == "merchant_hosted_nb_enach_status":
        var1 = json.dumps({"authpayuid": sample_mihpayid, "requestId": f"REQ_{int(time.time())}"}, separators=(",", ":"))
        return (command, var1, {})
    if fid == "merchant_hosted_nb_enach_execute":
        var1 = json.dumps({
            "authpayuid": sample_mihpayid, "invoiceDisplayNumber": "INV_001",
            "amount": "100.00", "txnid": txnid,
            "phone": data.get("phone", "9876543210"), "email": data.get("email", "john@example.com"),
        }, separators=(",", ":"))
        return (command, var1, {})
    if fid in ("merchant_hosted_upi_otm_capture", "merchant_hosted_nb_pacb_capture"):
        return (command, sample_mihpayid, {
            "var2": f"CAPTURE_{int(time.time())}",
            "var3": "100.00",
        })
    if fid in ("merchant_hosted_upi_otm_cancel_refund", "merchant_hosted_nb_refund"):
        return (command, sample_mihpayid, {
            "var2": f"REFUND_{int(time.time())}",
            "var3": "100.00",
        })
    if fid == "merchant_hosted_nb_split_refund":
        extra = {
            "var2": f"REFUND_{int(time.time())}",
            "var3": "100.00",
            "var5": json.dumps({"splitInfo": [
                {"merchantId": "CHILD_MID_1", "amount": "60.00"},
                {"merchantId": "CHILD_MID_2", "amount": "40.00"},
            ]}, separators=(",", ":")),
        }
        return (command, sample_mihpayid, extra)
    if fid == "merchant_hosted_nb_offers":
        return (command, "100.00", {"var2": "NB", "var3": "AXIB"})
    if fid in ("merchant_hosted_nb_bank_selection", "merchant_hosted_nb_bank_list"):
        return (command, "default", {})
    if fid == "merchant_hosted_check_action_status":
        return (command, sample_mihpayid, {})
    if fid == "merchant_hosted_settlement":
        return (command, "2026-04-01", {})

    # Default: command=verify_payment, var1=txnid
    return (command, txnid, {})


def _generate_get_curl(
    flow: PaymentFlow,
    merchant_key: str,
    merchant_salt: str,
    endpoint: str,
    data: Dict[str, Any],
) -> str:
    """Build a cURL for a GET API (e.g. UPI OTM Status Check with HMAC-SHA256)."""
    sample_payuid = "403993715537264905"
    url = endpoint.replace("{payuId}", sample_payuid)

    # HMAC-SHA256 signature example (placeholder guidance — actual generation needs real time)
    lines = [
        f"# NOTE: Replace <DATE>, <DIGEST>, and <SIGNATURE> with live values at request time.",
        f"# DATE format:  $(date -u +'%a, %d %b %Y %H:%M:%S GMT')",
        f"# DIGEST: base64(sha256('')) for empty GET body == 47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=",
        f"# SIGNATURE: base64(hmac_sha256('{merchant_salt}', 'date: <DATE>\\ndigest: SHA-256=<DIGEST>'))",
        f"",
        f"curl -X GET '{url}' \\",
        f"  -H 'accept: application/json' \\",
        f"  -H 'Date: <DATE>' \\",
        f"  -H 'Digest: SHA-256=<DIGEST>' \\",
        f"  -H 'Authorization: hmac username=\"{merchant_key}\", algorithm=\"hmac-sha256\", "
        f"headers=\"date digest\", signature=\"<SIGNATURE>\"'",
    ]
    return "\n".join(lines)


def _utility_flow_explanation(flow: PaymentFlow) -> str:
    """For utility flows (no API), explain what to do."""
    lines = [f"# {flow.name} is a client-side utility — no API call.", ""]
    for note in flow.notes:
        lines.append(f"# • {note}")
    if flow.flow_id == "merchant_hosted_acs_template_decoder":
        lines.append("")
        lines.append("# Example decode (bash):")
        lines.append("# echo \"$ACS_TEMPLATE_BASE64\" | base64 -d > acs.html && open acs.html")
        lines.append("")
        lines.append("# Example decode (Python):")
        lines.append("# import base64")
        lines.append("# html = base64.b64decode(acs_template).decode('utf-8')")
        lines.append("# # then window.open(URL.createObjectURL(new Blob([html], {type:'text/html'})))")
    return "\n".join(lines)


# =============================================================================
# Main cURL generator
# =============================================================================

def generate_curl(
    flow_id: str,
    merchant_key: str = "YOUR_MERCHANT_KEY",
    merchant_salt: str = "YOUR_MERCHANT_SALT",
    environment: str = "test",
    sample_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate cURL command for a payment flow.
    
    Args:
        flow_id: Flow identifier
        merchant_key: PayU merchant key
        merchant_salt: PayU merchant salt v1
        environment: "test" or "production"
        sample_data: Override default sample field values
        
    Returns:
        Ready-to-use cURL command as string
    """
    flow = get_flow(flow_id)
    if not flow:
        return f"Error: Unknown flow '{flow_id}'"

    data = {**DEFAULT_SAMPLE_DATA}
    if sample_data:
        data.update(sample_data)

    endpoint = flow.api_endpoint if environment == "test" else flow.prod_endpoint

    # Utility (no endpoint) flows
    if not endpoint:
        return _utility_flow_explanation(flow)

    # PostService (command|var1) flows
    if "postservice" in endpoint.lower():
        return _generate_postservice_curl(flow, merchant_key, merchant_salt, endpoint, data)

    # GET API flows (HMAC-SHA256 — UPI OTM Status Check)
    if flow.http_method == "GET" or "{payuId}" in endpoint:
        return _generate_get_curl(flow, merchant_key, merchant_salt, endpoint, data)

    # POST _payment flows — build payload based on flow
    payload = {
        "key": merchant_key,
        "txnid": data.get("txnid", DEFAULT_SAMPLE_DATA["txnid"]),
        "amount": data.get("amount", DEFAULT_SAMPLE_DATA["amount"]),
        "productinfo": data.get("productinfo", DEFAULT_SAMPLE_DATA["productinfo"]),
        "firstname": data.get("firstname", DEFAULT_SAMPLE_DATA["firstname"]),
        "email": data.get("email", DEFAULT_SAMPLE_DATA["email"]),
        "phone": data.get("phone", DEFAULT_SAMPLE_DATA["phone"]),
        "surl": data.get("surl", DEFAULT_SAMPLE_DATA["surl"]),
        "furl": data.get("furl", DEFAULT_SAMPLE_DATA["furl"]),
    }

    # Merchant Hosted flows set S2S fields
    if flow.integration_type == "Merchant Hosted":
        payload["txn_s2s_flow"] = "4"
        payload["s2s_client_ip"] = "127.0.0.1"
        payload["s2s_device_info"] = "Mozilla/5.0 (compatible; PayUClient/1.0)"

    fid = flow.flow_id

    # ----- Merchant Hosted: UPI Intent / Collect -----
    if fid == "merchant_hosted_upi_intent":
        payload.update({"pg": "UPI", "bankcode": "INTENT"})
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )
        return _render_form_curl(endpoint, payload)

    if fid == "merchant_hosted_upi_collect":
        payload.update({"pg": "UPI", "bankcode": "UPI", "vpa": "test-user@axis"})
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )
        return _render_form_curl(endpoint, payload)

    # ----- Merchant Hosted: UPI Mandate Register / UPI OTM PreAuth -----
    if fid in ("merchant_hosted_upi_mandate_register", "merchant_hosted_upi_otm_preauth"):
        payload.update({"pg": "UPI", "bankcode": "INTENT", "si": "1", "api_version": "7"})
        billing_cycle = "monthly" if "mandate" in fid else "adhoc"
        si_details = _build_si_details_json(billing_cycle=billing_cycle)
        payload["si_details"] = si_details
        if fid == "merchant_hosted_upi_otm_preauth":
            payload["pre_authorize"] = "1"
        payload["hash"] = generate_si_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], si_details=si_details, salt=merchant_salt,
        )
        return _render_form_curl(endpoint, payload)

    # ----- Merchant Hosted: Card S2S / PreAuth / Tokenization -----
    if fid in (
        "merchant_hosted_card_s2s",
        "merchant_hosted_card_preauth",
        "merchant_hosted_card_tokenization",
    ):
        payload.update({
            "pg": "CC", "bankcode": "CC",
            "ccnum": "5123456789012346", "ccname": "John Doe",
            "ccvv": "100", "ccexpmon": "05", "ccexpyr": "2030",
        })
        if fid == "merchant_hosted_card_preauth":
            payload["pre_authorize"] = "1"
        if fid == "merchant_hosted_card_tokenization":
            payload["store_card"] = "1"
            payload["user_credentials"] = f"{merchant_key}:customer_123"
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )
        return _render_form_curl(endpoint, payload)

    # ----- Merchant Hosted: NB Initiate / NB PACB -----
    if fid in ("merchant_hosted_nb_initiate", "merchant_hosted_nb_pacb"):
        payload.update({"pg": "NB", "bankcode": "TESTPGNB"})
        if fid == "merchant_hosted_nb_pacb":
            payload["pre_authorize"] = "1"
            payload["api_version"] = "6"
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )
        return _render_form_curl(endpoint, payload)

    # ----- Merchant Hosted: NB TPV (hash has beneficiarydetail embedded) -----
    if fid == "merchant_hosted_nb_tpv":
        payload.update({"pg": "NB", "bankcode": "AXNBTPV", "api_version": "6"})
        beneficiary = json.dumps({
            "beneficiaryAccountNumber": "1234567890",
            "ifscCode": "AXIS0000001",
        }, separators=(",", ":"))
        payload["beneficiarydetail"] = beneficiary
        # Hash: key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||beneficiarydetail|salt
        hs = (f"{payload['key']}|{payload['txnid']}|{payload['amount']}|"
              f"{payload['productinfo']}|{payload['firstname']}|{payload['email']}"
              f"|||||||||||{beneficiary}|{merchant_salt}")
        payload["hash"] = hashlib.sha512(hs.encode("utf-8")).hexdigest().lower()
        return _render_form_curl(endpoint, payload)

    # ----- Merchant Hosted: NB Split Payment (split_request after salt) -----
    if fid == "merchant_hosted_nb_split_payment":
        payload.update({"pg": "NB", "bankcode": "TESTPGNB"})
        split_request = json.dumps({
            "split_info": [
                {"merchant_id": "CHILD_MID_1", "amount": "60.00"},
                {"merchant_id": "CHILD_MID_2", "amount": "40.00"},
            ]
        }, separators=(",", ":"))
        payload["split_request"] = split_request
        hs = (f"{payload['key']}|{payload['txnid']}|{payload['amount']}|"
              f"{payload['productinfo']}|{payload['firstname']}|{payload['email']}"
              f"|||||||||||{merchant_salt}|{split_request}")
        payload["hash"] = hashlib.sha512(hs.encode("utf-8")).hexdigest().lower()
        return _render_form_curl(endpoint, payload)

    # ----- Merchant Hosted: NB eNACH Register -----
    if fid == "merchant_hosted_nb_enach_register":
        payload.update({
            "pg": "ENACH", "bankcode": "ICICENCC",
            "si": "1", "api_version": "7",
        })
        si_details = _build_si_details_json(billing_cycle="monthly", billing_amount="1.00")
        payload["si_details"] = si_details
        payload["beneficiarydetail"] = json.dumps({
            "beneficiaryName": "John Doe",
            "beneficiaryAccountNumber": "1234567890",
            "beneficiaryAccountType": "SAVINGS",
            "beneficiaryIfscCode": "ICIC0000001",
        }, separators=(",", ":"))
        payload["amount"] = "1.00"
        payload["hash"] = generate_si_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], si_details=si_details, salt=merchant_salt,
        )
        return _render_form_curl(endpoint, payload)

    # ----- PayU Hosted flows (existing) -----
    if fid in ("payu_hosted_subscription", "payu_hosted_upi_otm"):
        payload["si"] = "1"
        payload["api_version"] = "7"
        si_details = _build_si_details_json()
        payload["si_details"] = si_details
        if fid == "payu_hosted_upi_otm":
            payload["enforce_paymethod"] = "upi"
        payload["hash"] = generate_si_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], si_details=si_details, salt=merchant_salt,
        )
    elif fid == "payu_hosted_tpv":
        payload["txn_s2s_flow"] = "4"
        payload["beneficiarydetail"] = json.dumps({
            "beneficiaryAccountNumber": "1234567890",
            "beneficiaryIFSC": "HDFC0000001",
            "beneficiaryName": "John Doe",
            "beneficiaryAccountType": "Savings",
        }, separators=(",", ":"))
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )
    elif fid == "payu_hosted_preauth":
        payload["txn_s2s_flow"] = "4"
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )
    elif fid == "payu_hosted_split_payment":
        payload["split_payment_details"] = json.dumps({
            "splitInfo": [
                {"merchantCode": "SUB_MID_1", "amount": "50.00"},
                {"merchantCode": "SUB_MID_2", "amount": "50.00"},
            ]
        }, separators=(",", ":"))
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )
    elif fid == "payu_hosted_cross_border":
        payload.update({
            "address1": "123 Main St", "city": "Mumbai", "state": "Maharashtra",
            "country": "India", "zipcode": "400001",
            "udf5": "INV_" + str(payload["txnid"]),
        })
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt, udf5=payload["udf5"],
        )
    elif fid == "payu_hosted_bank_offers":
        payload["offer_key"] = "YOUR_OFFER_KEY"
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )
    else:
        # Default: standard payment hash (PayU Hosted Checkout, Checkout Plus, etc.)
        payload["hash"] = generate_payment_hash(
            key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
            productinfo=payload["productinfo"], firstname=payload["firstname"],
            email=payload["email"], salt=merchant_salt,
        )

    return _render_form_curl(endpoint, payload)


# =============================================================================
# Python code generator
# =============================================================================

def generate_python_code(
    flow_id: str,
    merchant_key: str = "YOUR_MERCHANT_KEY",
    merchant_salt: str = "YOUR_MERCHANT_SALT",
    environment: str = "test",
) -> str:
    """Generate Python code snippet for a payment flow.
    
    Args:
        flow_id: Flow identifier
        merchant_key: PayU merchant key
        merchant_salt: PayU merchant salt v1
        environment: "test" or "production"
        
    Returns:
        Ready-to-use Python code
    """
    flow = get_flow(flow_id)
    if not flow:
        return f"# Error: Unknown flow '{flow_id}'"

    endpoint = flow.api_endpoint if environment == "test" else flow.prod_endpoint

    # Utility or GET flows get a simpler template
    if not endpoint:
        return _utility_flow_explanation(flow)

    # PostService Python template
    if "postservice" in endpoint.lower():
        return _python_postservice_template(flow, merchant_key, merchant_salt, endpoint)

    if flow.http_method == "GET" or "{payuId}" in endpoint:
        return _python_get_template(flow, merchant_key, merchant_salt, endpoint)

    # _payment POST template
    header = f'''"""
PayU {flow.name} Integration ({flow.integration_type})
Generated by HealthCheck360 Bot
"""

import hashlib
import json
import requests


def generate_payu_hash(key, txnid, amount, productinfo, firstname, email, salt,
                      udf1="", udf2="", udf3="", udf4="", udf5="", si_details=None):
    """Generate SHA-512 hash for PayU payment request."""
    if si_details:
        hash_string = (
            f"{{key}}|{{txnid}}|{{amount}}|{{productinfo}}|{{firstname}}|{{email}}"
            f"|{{udf1}}|{{udf2}}|{{udf3}}|{{udf4}}|{{udf5}}||||||{{si_details}}|{{salt}}"
        )
    else:
        hash_string = (
            f"{{key}}|{{txnid}}|{{amount}}|{{productinfo}}|{{firstname}}|{{email}}"
            f"|{{udf1}}|{{udf2}}|{{udf3}}|{{udf4}}|{{udf5}}||||||{{salt}}"
        )
    return hashlib.sha512(hash_string.encode("utf-8")).hexdigest().lower()


MERCHANT_KEY = "{merchant_key}"
MERCHANT_SALT = "{merchant_salt}"
PAYU_ENDPOINT = "{endpoint}"

payload = {{
    "key": MERCHANT_KEY,
    "txnid": "TXN_" + str(int(__import__('time').time())),
    "amount": "100.00",
    "productinfo": "Test Product",
    "firstname": "John",
    "email": "john.doe@example.com",
    "phone": "9876543210",
    "surl": "https://yoursite.com/success",
    "furl": "https://yoursite.com/failure",
}}
'''

    body = ""
    fid = flow.flow_id

    # Merchant Hosted: S2S common fields
    if flow.integration_type == "Merchant Hosted":
        body += '''
# ===== S2S Flow fields (mandatory for Merchant Hosted) =====
payload["txn_s2s_flow"] = "4"
payload["s2s_client_ip"] = "127.0.0.1"
payload["s2s_device_info"] = "Mozilla/5.0"
'''

    # Flow specifics
    if fid == "merchant_hosted_upi_intent":
        body += '''
# ===== UPI Intent =====
payload["pg"] = "UPI"
payload["bankcode"] = "INTENT"   # or TEZ, PHONEPE, PAYTM, BHIM

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT,
)
'''
    elif fid == "merchant_hosted_upi_collect":
        body += '''
# ===== UPI Collect (with VPA) =====
payload["pg"] = "UPI"
payload["bankcode"] = "UPI"
payload["vpa"] = "customer@okaxis"   # customer's VPA

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT,
)
'''
    elif fid in ("merchant_hosted_upi_mandate_register", "merchant_hosted_upi_otm_preauth"):
        cycle = "monthly" if "mandate" in fid else "adhoc"
        pre_auth = '\npayload["pre_authorize"] = "1"' if fid == "merchant_hosted_upi_otm_preauth" else ""
        body += f'''
# ===== UPI Autopay / OTM =====
si_details = json.dumps({{
    "billingAmount": "100.00",
    "billingCurrency": "INR",
    "billingCycle": "{cycle}",
    "billingInterval": "1",
    "paymentStartDate": "2026-04-22",
    "paymentEndDate": "2027-04-22",
    "remarks": "Recurring payment"
}}, separators=(",", ":"))

payload["pg"] = "UPI"
payload["bankcode"] = "INTENT"
payload["si"] = "1"
payload["api_version"] = "7"
payload["si_details"] = si_details{pre_auth}

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT, si_details=si_details,
)
'''
    elif fid in ("merchant_hosted_card_s2s", "merchant_hosted_card_preauth", "merchant_hosted_card_tokenization"):
        extra = ""
        if fid == "merchant_hosted_card_preauth":
            extra = '\npayload["pre_authorize"] = "1"'
        if fid == "merchant_hosted_card_tokenization":
            extra = '''\npayload["store_card"] = "1"
payload["user_credentials"] = f"{MERCHANT_KEY}:customer_123"'''
        body += f'''
# ===== Card S2S (PCI DSS required) =====
payload["pg"] = "CC"
payload["bankcode"] = "CC"
payload["ccnum"] = "5123456789012346"
payload["ccname"] = "John Doe"
payload["ccvv"] = "100"
payload["ccexpmon"] = "05"
payload["ccexpyr"] = "2030"{extra}

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT,
)
'''
    elif fid in ("merchant_hosted_nb_initiate", "merchant_hosted_nb_pacb"):
        pacb = '\npayload["pre_authorize"] = "1"\npayload["api_version"] = "6"' if fid == "merchant_hosted_nb_pacb" else ""
        body += f'''
# ===== Net Banking =====
payload["pg"] = "NB"
payload["bankcode"] = "TESTPGNB"   # from getNetbankingStatus{pacb}

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT,
)
'''
    elif fid == "merchant_hosted_nb_tpv":
        body += '''
# ===== NB TPV — hash has beneficiarydetail embedded =====
beneficiary = json.dumps({
    "beneficiaryAccountNumber": "1234567890",
    "ifscCode": "AXIS0000001",
}, separators=(",", ":"))

payload["pg"] = "NB"
payload["bankcode"] = "AXNBTPV"   # TPV-enabled bankcode
payload["api_version"] = "6"
payload["beneficiarydetail"] = beneficiary

# Custom hash: key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||beneficiarydetail|salt
hash_string = (
    f"{payload['key']}|{payload['txnid']}|{payload['amount']}|"
    f"{payload['productinfo']}|{payload['firstname']}|{payload['email']}"
    f"|||||||||||{beneficiary}|{MERCHANT_SALT}"
)
payload["hash"] = hashlib.sha512(hash_string.encode("utf-8")).hexdigest().lower()
'''
    elif fid == "merchant_hosted_nb_split_payment":
        body += '''
# ===== NB Split Payment — split_request appended AFTER salt in hash =====
split_request = json.dumps({
    "split_info": [
        {"merchant_id": "CHILD_MID_1", "amount": "60.00"},
        {"merchant_id": "CHILD_MID_2", "amount": "40.00"},
    ]
}, separators=(",", ":"))

payload["pg"] = "NB"
payload["bankcode"] = "TESTPGNB"
payload["split_request"] = split_request

hash_string = (
    f"{payload['key']}|{payload['txnid']}|{payload['amount']}|"
    f"{payload['productinfo']}|{payload['firstname']}|{payload['email']}"
    f"|||||||||||{MERCHANT_SALT}|{split_request}"
)
payload["hash"] = hashlib.sha512(hash_string.encode("utf-8")).hexdigest().lower()
'''
    elif fid == "merchant_hosted_nb_enach_register":
        body += '''
# ===== NB eNACH Register =====
si_details = json.dumps({
    "billingAmount": "1.00",
    "billingCurrency": "INR",
    "billingCycle": "monthly",
    "billingInterval": "1",
    "paymentStartDate": "2026-04-22",
    "paymentEndDate": "2027-04-22",
    "remarks": "eNACH Autopay"
}, separators=(",", ":"))

payload["pg"] = "ENACH"
payload["bankcode"] = "ICICENCC"
payload["si"] = "1"
payload["api_version"] = "7"
payload["si_details"] = si_details
payload["amount"] = "1.00"
payload["beneficiarydetail"] = json.dumps({
    "beneficiaryName": "John Doe",
    "beneficiaryAccountNumber": "1234567890",
    "beneficiaryAccountType": "SAVINGS",
    "beneficiaryIfscCode": "ICIC0000001",
}, separators=(",", ":"))

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT, si_details=si_details,
)
'''
    elif fid in ("payu_hosted_subscription", "payu_hosted_upi_otm"):
        extra = '\npayload["enforce_paymethod"] = "upi"' if fid == "payu_hosted_upi_otm" else ""
        body += f'''
# ===== Subscription / OTM =====
si_details = json.dumps({{
    "billingAmount": "100.00",
    "billingCurrency": "INR",
    "billingCycle": "adhoc",
    "billingInterval": "1",
    "paymentStartDate": "2026-04-22",
    "paymentEndDate": "2027-04-22",
    "remarks": "Test subscription"
}}, separators=(",", ":"))

payload["si"] = "1"
payload["api_version"] = "7"
payload["si_details"] = si_details{extra}

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT, si_details=si_details,
)
'''
    elif fid == "payu_hosted_tpv":
        body += '''
# ===== PayU Hosted TPV =====
payload["txn_s2s_flow"] = "4"
payload["beneficiarydetail"] = json.dumps({
    "beneficiaryAccountNumber": "1234567890",
    "beneficiaryIFSC": "HDFC0000001",
    "beneficiaryName": "John Doe",
    "beneficiaryAccountType": "Savings",
}, separators=(",", ":"))

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT,
)
'''
    elif fid == "payu_hosted_cross_border":
        body += '''
# ===== Cross Border (billing address mandatory) =====
payload["address1"] = "123 Main St"
payload["city"] = "Mumbai"
payload["state"] = "Maharashtra"
payload["country"] = "India"
payload["zipcode"] = "400001"
payload["udf5"] = "INV_" + payload["txnid"]   # Invoice ID mandatory

payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], udf5=payload["udf5"], salt=MERCHANT_SALT,
)
'''
    else:
        body += '''
payload["hash"] = generate_payu_hash(
    key=payload["key"], txnid=payload["txnid"], amount=payload["amount"],
    productinfo=payload["productinfo"], firstname=payload["firstname"],
    email=payload["email"], salt=MERCHANT_SALT,
)
'''

    footer = '''
# ===== Send Payment Request =====
response = requests.post(
    PAYU_ENDPOINT,
    data=payload,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    allow_redirects=False,
)

print("Status Code:", response.status_code)
print("Response:", response.text[:500])
'''

    return header + body + footer


def _python_postservice_template(flow, merchant_key, merchant_salt, endpoint):
    """Python template for PostService APIs."""
    command = "verify_payment"
    for f in flow.required_fields:
        if f.name == "command" and f.fixed_value:
            command = f.fixed_value
            break

    return f'''"""
PayU {flow.name} (PostService API)
Generated by HealthCheck360 Bot
"""

import hashlib
import json
import requests


def generate_ps_hash(key, command, var1, salt):
    """Hash: sha512(key|command|var1|salt)"""
    hs = f"{{key}}|{{command}}|{{var1}}|{{salt}}"
    return hashlib.sha512(hs.encode("utf-8")).hexdigest().lower()


MERCHANT_KEY = "{merchant_key}"
MERCHANT_SALT = "{merchant_salt}"
ENDPOINT = "{endpoint}"

command = "{command}"
var1 = "YOUR_TXNID_OR_MIHPAYID"   # replace with actual value (see flow notes)

payload = {{
    "key": MERCHANT_KEY,
    "command": command,
    "var1": var1,
    "hash": generate_ps_hash(MERCHANT_KEY, command, var1, MERCHANT_SALT),
}}
# Some commands require var2, var3, var5 (capture, refund, split refund, offers)

response = requests.post(
    ENDPOINT,
    data=payload,
    headers={{"Content-Type": "application/x-www-form-urlencoded"}},
)
print("Status:", response.status_code)
print("Body:", response.text)
'''


def _python_get_template(flow, merchant_key, merchant_salt, endpoint):
    """Python template for HMAC-signed GET APIs (UPI OTM Status Check)."""
    return f'''"""
PayU {flow.name} (HMAC-SHA256 Auth)
Generated by HealthCheck360 Bot
"""

import base64
import hashlib
import hmac
from email.utils import formatdate
import requests


MERCHANT_KEY = "{merchant_key}"
MERCHANT_SALT = "{merchant_salt}"
ENDPOINT = "{endpoint}"

payu_id = "403993715537264905"   # replace with your payuId
url = ENDPOINT.replace("{{payuId}}", payu_id)

# Generate headers for HMAC-SHA256 signature
date_str = formatdate(timeval=None, localtime=False, usegmt=True)
body = b""   # empty for GET
digest = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")

signing_string = f"date: {{date_str}}\\ndigest: SHA-256={{digest}}"
signature = base64.b64encode(
    hmac.new(MERCHANT_SALT.encode("utf-8"), signing_string.encode("utf-8"), hashlib.sha256).digest()
).decode("ascii")

headers = {{
    "accept": "application/json",
    "Date": date_str,
    "Digest": f"SHA-256={{digest}}",
    "Authorization": (
        f'hmac username="{{MERCHANT_KEY}}", algorithm="hmac-sha256", '
        f'headers="date digest", signature="{{signature}}"'
    ),
}}

response = requests.get(url, headers=headers)
print("Status:", response.status_code)
print("Body:", response.text)
'''
