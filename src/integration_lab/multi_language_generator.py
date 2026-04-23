"""Multi-language code generator for PayU integration flows.

Shares a single `build_request_spec()` with the cURL generator and renders
Node.js, PHP, and Java equivalents from that spec.

Design: Rather than duplicate 47 flow-specific payload builders per language,
we reuse the payload-building logic already in `code_generator.generate_curl`
by intercepting the payload before cURL rendering.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from .knowledge_base import PaymentFlow, get_flow
from .hash_calculator import (
    generate_payment_hash,
    generate_si_payment_hash,
    generate_postservice_hash,
)
from .code_generator import (
    DEFAULT_SAMPLE_DATA,
    _build_si_details_json,
    _postservice_params_for,
)


# ---------------------------------------------------------------------- #
# Request spec builder (shared across all languages)                     #
# ---------------------------------------------------------------------- #
def build_request_spec(
    flow_id: str,
    merchant_key: str = "YOUR_MERCHANT_KEY",
    merchant_salt: str = "YOUR_MERCHANT_SALT",
    environment: str = "test",
    sample_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a language-agnostic request spec for the given flow.

    Returns:
        {
          "flow": PaymentFlow,
          "api_type": "payment" | "postservice" | "get" | "utility",
          "method": "POST" | "GET",
          "endpoint": str,
          "payload": Dict[str, str],          # form fields (for POST)
          "notes": List[str],
        }
    """
    flow = get_flow(flow_id)
    if not flow:
        raise ValueError(f"Unknown flow '{flow_id}'")

    data = {**DEFAULT_SAMPLE_DATA}
    if sample_data:
        data.update(sample_data)

    endpoint = flow.api_endpoint if environment == "test" else flow.prod_endpoint

    # Utility (no endpoint)
    if not endpoint:
        return {
            "flow": flow,
            "api_type": "utility",
            "method": "",
            "endpoint": "",
            "payload": {},
            "notes": list(flow.notes or []),
        }

    # PostService
    if "postservice" in endpoint.lower():
        command, var1, extra = _postservice_params_for(flow, data)
        hash_val = generate_postservice_hash(
            key=merchant_key, command=command, var1=str(var1), salt=merchant_salt
        )
        payload = {
            "key": merchant_key,
            "command": command,
            "var1": str(var1),
            "hash": hash_val,
        }
        payload.update(extra)
        return {
            "flow": flow,
            "api_type": "postservice",
            "method": "POST",
            "endpoint": endpoint,
            "payload": payload,
            "notes": list(flow.notes or []),
        }

    # GET (HMAC-SHA256)
    if flow.http_method == "GET" or "{payuId}" in endpoint:
        return {
            "flow": flow,
            "api_type": "get",
            "method": "GET",
            "endpoint": endpoint,
            "payload": {},
            "notes": list(flow.notes or []),
        }

    # POST _payment — build payload identically to generate_curl
    payload: Dict[str, str] = {
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

    if flow.integration_type == "Merchant Hosted":
        payload["txn_s2s_flow"] = "4"
        payload["s2s_client_ip"] = "127.0.0.1"
        payload["s2s_device_info"] = "Mozilla/5.0 (compatible; PayUClient/1.0)"

    fid = flow.flow_id

    # Apply flow-specific fields + hash (mirrors generate_curl)
    if fid == "merchant_hosted_upi_intent":
        payload.update({"pg": "UPI", "bankcode": "INTENT"})
        payload["hash"] = generate_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )
    elif fid == "merchant_hosted_upi_collect":
        payload.update({"pg": "UPI", "bankcode": "UPI", "vpa": "test-user@axis"})
        payload["hash"] = generate_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )
    elif fid in ("merchant_hosted_upi_mandate_register", "merchant_hosted_upi_otm_preauth"):
        cycle = "monthly" if "mandate" in fid else "adhoc"
        si_details = _build_si_details_json(billing_cycle=cycle)
        payload.update({"pg": "UPI", "bankcode": "INTENT", "si": "1", "api_version": "7", "si_details": si_details})
        if fid == "merchant_hosted_upi_otm_preauth":
            payload["pre_authorize"] = "1"
        payload["hash"] = generate_si_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"],
            si_details, merchant_salt,
        )
    elif fid in ("merchant_hosted_card_s2s", "merchant_hosted_card_preauth", "merchant_hosted_card_tokenization"):
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
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )
    elif fid in ("merchant_hosted_nb_initiate", "merchant_hosted_nb_pacb"):
        payload.update({"pg": "NB", "bankcode": "TESTPGNB"})
        if fid == "merchant_hosted_nb_pacb":
            payload["pre_authorize"] = "1"
            payload["api_version"] = "6"
        payload["hash"] = generate_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )
    elif fid == "merchant_hosted_nb_tpv":
        beneficiary = json.dumps({
            "beneficiaryAccountNumber": "1234567890",
            "ifscCode": "AXIS0000001",
        }, separators=(",", ":"))
        payload.update({"pg": "NB", "bankcode": "AXNBTPV", "api_version": "6", "beneficiarydetail": beneficiary})
        hs = (f"{payload['key']}|{payload['txnid']}|{payload['amount']}|"
              f"{payload['productinfo']}|{payload['firstname']}|{payload['email']}"
              f"|||||||||||{beneficiary}|{merchant_salt}")
        payload["hash"] = hashlib.sha512(hs.encode("utf-8")).hexdigest().lower()
    elif fid == "merchant_hosted_nb_split_payment":
        split_request = json.dumps({"split_info": [
            {"merchant_id": "CHILD_MID_1", "amount": "60.00"},
            {"merchant_id": "CHILD_MID_2", "amount": "40.00"},
        ]}, separators=(",", ":"))
        payload.update({"pg": "NB", "bankcode": "TESTPGNB", "split_request": split_request})
        hs = (f"{payload['key']}|{payload['txnid']}|{payload['amount']}|"
              f"{payload['productinfo']}|{payload['firstname']}|{payload['email']}"
              f"|||||||||||{merchant_salt}|{split_request}")
        payload["hash"] = hashlib.sha512(hs.encode("utf-8")).hexdigest().lower()
    elif fid == "merchant_hosted_nb_enach_register":
        si_details = _build_si_details_json(billing_cycle="monthly", billing_amount="1.00")
        payload.update({
            "pg": "ENACH", "bankcode": "ICICENCC", "si": "1", "api_version": "7",
            "si_details": si_details, "amount": "1.00",
            "beneficiarydetail": json.dumps({
                "beneficiaryName": "John Doe",
                "beneficiaryAccountNumber": "1234567890",
                "beneficiaryAccountType": "SAVINGS",
                "beneficiaryIfscCode": "ICIC0000001",
            }, separators=(",", ":")),
        })
        payload["hash"] = generate_si_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"],
            si_details, merchant_salt,
        )
    elif fid in ("payu_hosted_subscription", "payu_hosted_upi_otm"):
        si_details = _build_si_details_json()
        payload.update({"si": "1", "api_version": "7", "si_details": si_details})
        if fid == "payu_hosted_upi_otm":
            payload["enforce_paymethod"] = "upi"
        payload["hash"] = generate_si_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"],
            si_details, merchant_salt,
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
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )
    elif fid == "payu_hosted_preauth":
        payload["txn_s2s_flow"] = "4"
        payload["hash"] = generate_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )
    elif fid == "payu_hosted_split_payment":
        payload["split_payment_details"] = json.dumps({"splitInfo": [
            {"merchantCode": "SUB_MID_1", "amount": "50.00"},
            {"merchantCode": "SUB_MID_2", "amount": "50.00"},
        ]}, separators=(",", ":"))
        payload["hash"] = generate_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )
    elif fid == "payu_hosted_cross_border":
        payload.update({
            "address1": "123 Main St", "city": "Mumbai", "state": "Maharashtra",
            "country": "India", "zipcode": "400001",
            "udf5": "INV_" + str(payload["txnid"]),
        })
        payload["hash"] = generate_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"],
            merchant_salt, udf5=payload["udf5"],
        )
    elif fid == "payu_hosted_bank_offers":
        payload["offer_key"] = "YOUR_OFFER_KEY"
        payload["hash"] = generate_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )
    else:
        # Default: standard hash (PayU Hosted Checkout, Checkout Plus, etc.)
        payload["hash"] = generate_payment_hash(
            payload["key"], payload["txnid"], payload["amount"],
            payload["productinfo"], payload["firstname"], payload["email"], merchant_salt,
        )

    return {
        "flow": flow,
        "api_type": "payment",
        "method": "POST",
        "endpoint": endpoint,
        "payload": {k: str(v) for k, v in payload.items()},
        "notes": list(flow.notes or []),
    }


# ---------------------------------------------------------------------- #
# Language renderers                                                     #
# ---------------------------------------------------------------------- #
def _py_dict_literal(d: Dict[str, str], indent: str = "    ") -> str:
    """Render a Python-like dict literal (already used by existing Python gen)."""
    lines = ["{"]
    for k, v in d.items():
        lines.append(f'{indent}"{k}": {json.dumps(v)},')
    lines.append("}")
    return "\n".join(lines)


# ---- Node.js --------------------------------------------------------------
def generate_nodejs_code(
    flow_id: str,
    merchant_key: str = "YOUR_MERCHANT_KEY",
    merchant_salt: str = "YOUR_MERCHANT_SALT",
    environment: str = "test",
) -> str:
    spec = build_request_spec(flow_id, merchant_key, merchant_salt, environment)
    flow = spec["flow"]

    if spec["api_type"] == "utility":
        lines = [
            f"// {flow.name} is a client-side utility — no API call.",
            "",
        ]
        for n in flow.notes:
            lines.append(f"// • {n}")
        if flow.flow_id == "merchant_hosted_acs_template_decoder":
            lines += [
                "",
                "// Decode ACS template in browser:",
                "const html = atob(acsTemplateBase64);",
                "window.open(URL.createObjectURL(new Blob([html], {type: 'text/html'})));",
            ]
        return "\n".join(lines)

    if spec["api_type"] == "get":
        return _nodejs_get_template(flow, merchant_key, merchant_salt, spec["endpoint"])

    payload_json = json.dumps(spec["payload"], indent=2)

    header = f"""/**
 * PayU {flow.name} ({flow.integration_type})
 * Generated by HealthCheck360 Bot — Node.js (axios)
 */
const axios = require('axios');
const crypto = require('crypto');
const qs = require('querystring');

const MERCHANT_KEY = '{merchant_key}';
const MERCHANT_SALT = '{merchant_salt}';
const PAYU_ENDPOINT = '{spec["endpoint"]}';

// NOTE: payload below is pre-built with sample data and a valid hash.
// In production, build txnid dynamically and recompute the hash.
const payload = {payload_json};

async function main() {{
  try {{
    const response = await axios.post(
      PAYU_ENDPOINT,
      qs.stringify(payload),
      {{
        headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
        maxRedirects: 0,
        validateStatus: (s) => s < 400 || s === 302,
      }}
    );
    console.log('Status:', response.status);
    console.log('Body:', (response.data || '').toString().slice(0, 500));
  }} catch (err) {{
    console.error('Request failed:', err.response?.status, err.message);
  }}
}}

// Re-compute hash helper (for dynamic payloads)
function sha512(s) {{
  return crypto.createHash('sha512').update(s, 'utf8').digest('hex');
}}

main();
"""
    return header


def _nodejs_get_template(flow, merchant_key, merchant_salt, endpoint):
    return f"""/**
 * PayU {flow.name} (HMAC-SHA256 GET) — Node.js
 */
const axios = require('axios');
const crypto = require('crypto');

const MERCHANT_KEY = '{merchant_key}';
const MERCHANT_SALT = '{merchant_salt}';
const payuId = '403993715537264905';   // replace with your payuId
const url = '{endpoint}'.replace('{{payuId}}', payuId);

const date = new Date().toUTCString();
const body = '';
const digest = crypto.createHash('sha256').update(body).digest('base64');
const signingString = `date: ${{date}}\\ndigest: SHA-256=${{digest}}`;
const signature = crypto.createHmac('sha256', MERCHANT_SALT)
  .update(signingString)
  .digest('base64');

const headers = {{
  accept: 'application/json',
  Date: date,
  Digest: `SHA-256=${{digest}}`,
  Authorization:
    `hmac username="${{MERCHANT_KEY}}", algorithm="hmac-sha256", ` +
    `headers="date digest", signature="${{signature}}"`,
}};

axios.get(url, {{ headers }})
  .then(r => console.log(r.status, r.data))
  .catch(e => console.error('Error:', e.response?.status, e.message));
"""


# ---- PHP ------------------------------------------------------------------
def generate_php_code(
    flow_id: str,
    merchant_key: str = "YOUR_MERCHANT_KEY",
    merchant_salt: str = "YOUR_MERCHANT_SALT",
    environment: str = "test",
) -> str:
    spec = build_request_spec(flow_id, merchant_key, merchant_salt, environment)
    flow = spec["flow"]

    if spec["api_type"] == "utility":
        lines = [
            "<?php",
            f"// {flow.name} is a client-side utility — no API call.",
        ]
        for n in flow.notes:
            lines.append(f"// • {n}")
        return "\n".join(lines)

    if spec["api_type"] == "get":
        return _php_get_template(flow, merchant_key, merchant_salt, spec["endpoint"])

    # Build PHP associative array
    payload_php = _php_assoc_array(spec["payload"])

    return f"""<?php
/**
 * PayU {flow.name} ({flow.integration_type})
 * Generated by HealthCheck360 Bot — PHP (cURL)
 */

$merchantKey  = '{merchant_key}';
$merchantSalt = '{merchant_salt}';
$endpoint     = '{spec["endpoint"]}';

// NOTE: payload is pre-built with sample data + valid hash.
// Recompute hash at runtime for dynamic txnid / amount.
$payload = {payload_php};

$ch = curl_init($endpoint);
curl_setopt_array($ch, [
    CURLOPT_POST           => true,
    CURLOPT_POSTFIELDS     => http_build_query($payload),
    CURLOPT_HTTPHEADER     => ['Content-Type: application/x-www-form-urlencoded'],
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => false,
]);

$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

echo "Status: $httpCode\\n";
echo "Body:   " . substr((string)$response, 0, 500) . "\\n";

// Helper: regenerate PayU SHA-512 hash when building payload dynamically
function payu_hash($key, $txnid, $amount, $productinfo, $firstname, $email,
                   $salt, $udf1='', $udf2='', $udf3='', $udf4='', $udf5='',
                   $siDetails='') {{
    if ($siDetails !== '') {{
        $hashString = implode('|', [$key, $txnid, $amount, $productinfo, $firstname,
            $email, $udf1, $udf2, $udf3, $udf4, $udf5, '', '', '', '', '', $siDetails, $salt]);
    }} else {{
        $hashString = implode('|', [$key, $txnid, $amount, $productinfo, $firstname,
            $email, $udf1, $udf2, $udf3, $udf4, $udf5, '', '', '', '', '', $salt]);
    }}
    return strtolower(hash('sha512', $hashString));
}}
"""


def _php_get_template(flow, merchant_key, merchant_salt, endpoint):
    return f"""<?php
/**
 * PayU {flow.name} (HMAC-SHA256 GET) — PHP
 */
$merchantKey  = '{merchant_key}';
$merchantSalt = '{merchant_salt}';
$payuId       = '403993715537264905';   // replace with your payuId
$url          = str_replace('{{payuId}}', $payuId, '{endpoint}');

$date   = gmdate('D, d M Y H:i:s') . ' GMT';
$body   = '';
$digest = base64_encode(hash('sha256', $body, true));
$signingString = "date: $date\\ndigest: SHA-256=$digest";
$signature = base64_encode(hash_hmac('sha256', $signingString, $merchantSalt, true));

$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_HTTPHEADER => [
        'accept: application/json',
        "Date: $date",
        "Digest: SHA-256=$digest",
        'Authorization: hmac username="' . $merchantKey . '", '
            . 'algorithm="hmac-sha256", headers="date digest", signature="' . $signature . '"',
    ],
    CURLOPT_RETURNTRANSFER => true,
]);
$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

echo "Status: $httpCode\\n";
echo "Body:   $response\\n";
"""


def _php_assoc_array(d: Dict[str, str]) -> str:
    """Render a Dict as a PHP associative array literal."""
    lines = ["["]
    for k, v in d.items():
        v_str = str(v).replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"    '{k}' => '{v_str}',")
    lines.append("]")
    return "\n".join(lines)


# ---- Java -----------------------------------------------------------------
def generate_java_code(
    flow_id: str,
    merchant_key: str = "YOUR_MERCHANT_KEY",
    merchant_salt: str = "YOUR_MERCHANT_SALT",
    environment: str = "test",
) -> str:
    spec = build_request_spec(flow_id, merchant_key, merchant_salt, environment)
    flow = spec["flow"]

    if spec["api_type"] == "utility":
        lines = [
            "// " + flow.name + " is a client-side utility — no API call.",
            "// " + "\n// ".join(flow.notes) if flow.notes else "",
        ]
        return "\n".join([x for x in lines if x])

    if spec["api_type"] == "get":
        return _java_get_template(flow, merchant_key, merchant_salt, spec["endpoint"])

    payload_java = _java_map_literal(spec["payload"])

    class_name = "PayUIntegration"
    return f"""/**
 * PayU {flow.name} ({flow.integration_type})
 * Generated by HealthCheck360 Bot — Java 11+ (HttpClient)
 */
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.stream.Collectors;

public class {class_name} {{
    private static final String MERCHANT_KEY  = "{merchant_key}";
    private static final String MERCHANT_SALT = "{merchant_salt}";
    private static final String PAYU_ENDPOINT = "{spec["endpoint"]}";

    public static void main(String[] args) throws Exception {{
        Map<String, String> payload = new LinkedHashMap<>();
{payload_java}

        String body = payload.entrySet().stream()
            .map(e -> URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8)
                    + "=" + URLEncoder.encode(e.getValue(), StandardCharsets.UTF_8))
            .collect(Collectors.joining("&"));

        HttpClient client = HttpClient.newBuilder()
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(PAYU_ENDPOINT))
            .header("Content-Type", "application/x-www-form-urlencoded")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build();

        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        System.out.println("Status: " + response.statusCode());
        System.out.println("Body:   " + response.body().substring(0, Math.min(500, response.body().length())));
    }}

    /** SHA-512 hash helper for PayU payment requests. */
    public static String payuHash(String key, String txnid, String amount,
                                  String productinfo, String firstname, String email,
                                  String salt, String udf1, String udf2, String udf3,
                                  String udf4, String udf5, String siDetails) throws Exception {{
        String hashString;
        if (siDetails != null && !siDetails.isEmpty()) {{
            hashString = String.join("|", key, txnid, amount, productinfo, firstname,
                email, udf1, udf2, udf3, udf4, udf5, "", "", "", "", "", siDetails, salt);
        }} else {{
            hashString = String.join("|", key, txnid, amount, productinfo, firstname,
                email, udf1, udf2, udf3, udf4, udf5, "", "", "", "", "", salt);
        }}
        MessageDigest md = MessageDigest.getInstance("SHA-512");
        byte[] digest = md.digest(hashString.getBytes(StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        for (byte b : digest) sb.append(String.format("%02x", b));
        return sb.toString();
    }}
}}
"""


def _java_get_template(flow, merchant_key, merchant_salt, endpoint):
    return f"""/**
 * PayU {flow.name} (HMAC-SHA256 GET) — Java 11+
 */
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Base64;

public class PayUHmacGet {{
    public static void main(String[] args) throws Exception {{
        String merchantKey  = "{merchant_key}";
        String merchantSalt = "{merchant_salt}";
        String payuId       = "403993715537264905";
        String url          = "{endpoint}".replace("{{payuId}}", payuId);

        String date = ZonedDateTime.now(ZoneOffset.UTC)
            .format(DateTimeFormatter.RFC_1123_DATE_TIME);
        String body = "";
        String digest = Base64.getEncoder().encodeToString(
            MessageDigest.getInstance("SHA-256").digest(body.getBytes(StandardCharsets.UTF_8)));

        String signingString = "date: " + date + "\\ndigest: SHA-256=" + digest;
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(merchantSalt.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        String signature = Base64.getEncoder().encodeToString(
            mac.doFinal(signingString.getBytes(StandardCharsets.UTF_8)));

        HttpRequest req = HttpRequest.newBuilder()
            .uri(URI.create(url))
            .header("accept", "application/json")
            .header("Date", date)
            .header("Digest", "SHA-256=" + digest)
            .header("Authorization",
                "hmac username=\\"" + merchantKey + "\\", algorithm=\\"hmac-sha256\\", " +
                "headers=\\"date digest\\", signature=\\"" + signature + "\\"")
            .GET().build();

        HttpResponse<String> r = HttpClient.newHttpClient()
            .send(req, HttpResponse.BodyHandlers.ofString());
        System.out.println("Status: " + r.statusCode());
        System.out.println("Body:   " + r.body());
    }}
}}
"""


def _java_map_literal(d: Dict[str, str]) -> str:
    lines = []
    for k, v in d.items():
        v_str = str(v).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'        payload.put("{k}", "{v_str}");')
    return "\n".join(lines)


# ---------------------------------------------------------------------- #
# Dispatcher                                                              #
# ---------------------------------------------------------------------- #
SUPPORTED_LANGUAGES = ("curl", "python", "nodejs", "node", "js", "javascript", "php", "java")


def generate_code(
    flow_id: str,
    language: str = "curl",
    merchant_key: str = "YOUR_MERCHANT_KEY",
    merchant_salt: str = "YOUR_MERCHANT_SALT",
    environment: str = "test",
) -> Tuple[str, str]:
    """Generate integration code in the requested language.

    Returns:
        (markdown_fence_language, code_string)
    """
    from .code_generator import generate_curl, generate_python_code  # late import

    lang = (language or "curl").lower().strip()
    if lang in ("curl", "bash", "sh"):
        return ("bash", generate_curl(flow_id, merchant_key, merchant_salt, environment))
    if lang in ("python", "py"):
        return ("python", generate_python_code(flow_id, merchant_key, merchant_salt, environment))
    if lang in ("nodejs", "node", "js", "javascript"):
        return ("javascript", generate_nodejs_code(flow_id, merchant_key, merchant_salt, environment))
    if lang == "php":
        return ("php", generate_php_code(flow_id, merchant_key, merchant_salt, environment))
    if lang == "java":
        return ("java", generate_java_code(flow_id, merchant_key, merchant_salt, environment))

    # Fallback — return cURL with a note
    return (
        "bash",
        f"# Unsupported language '{language}'. Supported: curl, python, nodejs, php, java.\n"
        + generate_curl(flow_id, merchant_key, merchant_salt, environment),
    )
