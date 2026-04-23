"""Merchant Hosted (Seamless / S2S) payment flows for PayU Integration Lab.

Covers all UPI, Cards, and Net Banking S2S flows from:
https://payu.in/integrationlab/seamless

Each flow is structured as a PaymentFlow with its specific hash formula,
endpoint, command (for postservice APIs), and HealthCheck360 product mapping.
"""

from typing import Dict

from .knowledge_base import PaymentFlow, FlowField


# Common hash formulas
HASH_PAYMENT = "key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||salt"
HASH_PAYMENT_SI = "key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||si_details|salt"
HASH_POSTSERVICE = "key|command|var1|salt"
HASH_NB_TPV = "key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||beneficiarydetail|salt"
HASH_NB_SPLIT = "key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||salt|split_request"

POSTSERVICE_URL = "https://test.payu.in/merchant/postservice.php?form=2"
POSTSERVICE_PROD = "https://info.payu.in/merchant/postservice.php?form=2"
PAYMENT_URL = "https://test.payu.in/_payment"
PAYMENT_PROD = "https://secure.payu.in/_payment"


def _f(name: str, desc: str, mandatory: bool = True, fixed: str = None) -> FlowField:
    return FlowField(name=name, description=desc, mandatory=mandatory, fixed_value=fixed)


# =============================================================================
# Common field groups
# =============================================================================

BASE_S2S_FIELDS = [
    _f("key", "Merchant key"),
    _f("txnid", "Unique transaction ID"),
    _f("amount", "Transaction amount"),
    _f("productinfo", "Product description"),
    _f("firstname", "Customer first name"),
    _f("email", "Customer email"),
    _f("phone", "Customer phone (10 digits)"),
    _f("surl", "Success callback URL"),
    _f("furl", "Failure callback URL"),
    _f("hash", "SHA-512 hash"),
    _f("txn_s2s_flow", "S2S flow indicator", fixed="4"),
    _f("s2s_client_ip", "Customer IP address"),
    _f("s2s_device_info", "Customer device info (UA)"),
]

POSTSERVICE_FIELDS = [
    _f("key", "Merchant key"),
    _f("command", "API command"),
    _f("var1", "Command-specific variable"),
    _f("hash", "SHA-512 hash"),
]


# =============================================================================
# Seamless flow definitions
# =============================================================================

SEAMLESS_FLOWS: Dict[str, PaymentFlow] = {}


def _add(flow: PaymentFlow):
    SEAMLESS_FLOWS[flow.flow_id] = flow


# -------------------------- UPI Flows --------------------------

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_intent",
    name="UPI Intent (S2S)",
    description="UPI Intent flow where customer pays via UPI app deeplink or QR code (S2S merchant-hosted).",
    integration_type="Merchant Hosted",
    required_products=["UPI"],
    required_banking_codes=["upi"],
    required_modes=["upi"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="UPI"),
        _f("bankcode", "UPI app (INTENT/TEZ/PHONEPE/PAYTM/BHIM/AMAZONPAY/CRED)"),
    ],
    hash_formula=HASH_PAYMENT,
    corrective_checks=[
        "UPI product must be Fully Ready",
        "Banking code 'upi' enabled",
        "Android requires Smart Intent per NPCI mandate; web uses QR",
    ],
    notes=[
        "pg=UPI with bankcode=INTENT/TEZ/PHONEPE etc.",
        "Response returns intentURIData (upi://pay?...) or acsTemplate (base64 HTML)",
        "Always confirm via verify_payment after user approval",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_collect",
    name="UPI Collect / One-Time S2S",
    description="UPI Collect flow where customer approves a payment request sent to their VPA.",
    integration_type="Merchant Hosted",
    required_products=["UPI"],
    required_banking_codes=["upi"],
    required_modes=["upi"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="UPI"),
        _f("bankcode", "Bank code", fixed="UPI"),
        _f("vpa", "Customer VPA (e.g. user@okaxis)"),
    ],
    hash_formula=HASH_PAYMENT,
    corrective_checks=[
        "UPI product Fully Ready",
        "Banking code 'upi' enabled",
        "vpa is mandatory for Collect (bankcode=UPI)",
    ],
    notes=[
        "udf1=PAN||DOB and udf3=InvoiceID||MerchantName may be required by AD bank",
        "Poll check_payment while pending; also verify via verify_payment",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_mandate_register",
    name="UPI Autopay - Mandate Registration",
    description="Register a UPI mandate for recurring debits (Autopay).",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay", "UPI"],
    required_banking_codes=["upi", "standinginstruction"],
    required_modes=["upi", "standinginstruction"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="UPI"),
        _f("bankcode", "UPI or INTENT"),
        _f("si", "Stored instrument flag", fixed="1"),
        _f("api_version", "API version", fixed="7"),
        _f("si_details", "Mandate JSON (billingAmount, billingCurrency, billingCycle, billingInterval, paymentStartDate, paymentEndDate)"),
    ],
    hash_formula=HASH_PAYMENT_SI,
    corrective_checks=[
        "UPI Autopay product Fully Ready",
        "Banking codes 'upi' AND 'standinginstruction' both enabled",
        "SI Update callback URL configured",
    ],
    notes=[
        "si=1 with api_version=7; si_details JSON included in hash",
        "UPI Autopay billingAmount max INR 15,000 (auto-debit); amount must be > ₹2",
        "vpa mandatory when bankcode=UPI (Collect); use INTENT + txn_s2s_flow=4 for Intent",
    ],
    required_callbacks=["siUpdateCallback"],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_autopay_verify",
    name="UPI Autopay - Verify Payment",
    description="Verify UPI Autopay mandate registration to retrieve authPayuId.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upi", "standinginstruction"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="verify_payment"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 = txnid used during mandate registration",
        "Response mihpayid becomes authPayuId used for status/modify/pre-debit/SI transaction",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_mandate_status",
    name="UPI Autopay - Mandate Status",
    description="Check current status of a UPI Autopay mandate.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upi", "standinginstruction"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="upi_mandate_status"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        'var1 is JSON string {"authPayuId":"...","requestId":"..."}',
        "Returns mandate status (Active/Paused/Revoked) and details",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_mandate_modify",
    name="UPI Autopay - Modify Mandate",
    description="Modify an existing UPI Autopay mandate (amount, end date).",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upi", "standinginstruction"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="upi_mandate_modify"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 JSON contains authPayuId, requestId, and optional amount / endDate",
        "Customer must approve modification on UPI app",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_otm_preauth",
    name="UPI OTM - Pre-Authorize",
    description="UPI One-Time Mandate: pre-authorize (block) a future debit.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay", "UPI"],
    required_banking_codes=["upiotm", "upi"],
    required_modes=["upiotm", "upi"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="UPI"),
        _f("bankcode", "UPI app", fixed="INTENT"),
        _f("pre_authorize", "Pre-authorize flag", fixed="1"),
        _f("api_version", "API version", fixed="7"),
        _f("si_details", "OTM JSON with paymentStartDate/paymentEndDate; add multiCapture:Y for multi capture"),
    ],
    hash_formula=HASH_PAYMENT_SI,
    corrective_checks=[
        "UPI Autopay product Fully Ready",
        "Banking code 'upiotm' enabled",
    ],
    notes=[
        "pre_authorize=1, bankcode=INTENT, txn_s2s_flow=4, api_version=7",
        "Test sandbox: amount > ₹5,000 for success; max prod ₹5,00,000",
        "Amount is blocked then captured later via capture_transaction",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_otm_capture",
    name="UPI OTM - Capture Transaction",
    description="Capture funds from a previously pre-authorized UPI OTM transaction.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upiotm"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="capture_transaction"),
        _f("var2", "Unique capture order ID"),
        _f("var3", "Capture amount"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1=mihpayid of auth txn, var2=unique capture order id, var3=capture amount",
        "Partial and multiple captures supported when multiCapture=Y on auth",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_otm_verify",
    name="UPI OTM - Verify Payment",
    description="Verify a UPI OTM transaction (auth or capture).",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upiotm"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="verify_payment"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "Call after auth to retrieve mihpayid for capture/cancel",
        "Always verify — do not trust callback only",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_otm_cancel_refund",
    name="UPI OTM - Cancel / Refund",
    description="Cancel an uncaptured UPI OTM auth, or refund a captured one.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay", "UPI"],
    required_banking_codes=["upi", "upiotm"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="cancel_refund_transaction"),
        _f("var2", "Unique cancel/refund token"),
        _f("var3", "Amount"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1=mihpayid, var2=unique cancel/refund token, var3=amount",
        "For OTM auth cancel use command=cancel_transaction (releases blocked amount)",
        "Captured txns can only be refunded, not cancelled",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_check_action_status",
    name="Check Action Status",
    description="Check status of a cancel/refund request.",
    integration_type="Merchant Hosted",
    required_products=["UPI", "UPI Autopay", "Netbanking"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="check_action_status"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 = PayU mihpayid or request_id of the cancel/refund",
        "Returns whether refund/cancel is processed, pending, or failed",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_otm_status_check",
    name="UPI OTM - Status Check API",
    description="GET API to check UPI OTM status (uses HMAC-SHA256, not SHA-512).",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upiotm"],
    api_endpoint="https://apitest.payu.in/v1/transaction/upi_otm_status_check?payuId={payuId}",
    prod_endpoint="https://api.payu.in/v1/transaction/upi_otm_status_check?payuId={payuId}",
    http_method="GET",
    required_fields=[
        _f("payuId", "PayU ID from auth"),
        _f("Date", "UTC date header"),
        _f("Digest", "SHA-256 base64 digest of body"),
        _f("Authorization", "HMAC signature header"),
    ],
    hash_formula="HMAC-SHA256: base64(hmac_sha256(salt, 'date: {utcDate}\\ndigest: {sha256_base64_body}'))",
    notes=[
        "Uses HMAC-SHA256 signature (not SHA-512 hash)",
        "Digest = base64(sha256('')) for empty GET body",
        'Authorization header: hmac username="key", algorithm="hmac-sha256", headers="date digest", signature="..."',
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_otm_verify_auth",
    name="UPI OTM - Verify Payment Auth",
    description="Verify only the auth portion of a UPI OTM transaction.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upiotm"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="verify_payment"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 = original txnid from OTM auth request",
        "Used to retrieve mihpayid needed for capture",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_otm_verify_capture",
    name="UPI OTM - Verify Payment Capture",
    description="Verify a captured UPI OTM transaction.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upiotm"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="verify_payment"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 = capture_order_id (var2 used in capture_transaction)",
        "Confirms captured amount was debited",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_pre_debit",
    name="UPI Autopay - Pre-Debit Notification",
    description="Send NPCI-mandated 24h advance notification before a scheduled UPI Autopay debit.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upi", "standinginstruction"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="pre_debit_SI"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 JSON: {authPayuId, requestId, debitDate (YYYY-MM-DD), amount}",
        "NPCI mandates this be sent at least 24h before scheduled debit",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_si_transaction",
    name="UPI Autopay - SI Transaction (Recurring)",
    description="Execute a recurring debit against a registered UPI Autopay mandate.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upi", "standinginstruction"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="si_transaction"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 JSON includes authpayuid, amount, txnid, firstname, email, phone, udf1 (PAN||DOB), udf3 (InvoiceID||MerchantName)",
        "Executes the recurring debit against the registered mandate",
        "Debit amount must be ≤ billingAmount from mandate",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_upi_si_verify",
    name="UPI Autopay - Verify SI Payment",
    description="Verify a UPI Autopay recurring debit.",
    integration_type="Merchant Hosted",
    required_products=["UPI Autopay"],
    required_banking_codes=["upi", "standinginstruction"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="verify_payment"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 = SI txnid used in si_transaction",
        "Confirms recurring debit status (success/failure)",
    ],
))

# -------------------------- Cards Flows --------------------------

_add(PaymentFlow(
    flow_id="merchant_hosted_card_s2s",
    name="Normal S2S Card Payment",
    description="Server-to-server card payment where merchant captures raw card data (PCI DSS required).",
    integration_type="Merchant Hosted",
    required_products=["Credit Card", "Debit Card"],
    required_banking_codes=["creditcard", "debitcard"],
    required_modes=["creditcard", "debitcard"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway (CC/DC)"),
        _f("bankcode", "Bank code (CC/DC/AMEX)"),
        _f("ccnum", "Card number (PCI)"),
        _f("ccname", "Name on card"),
        _f("ccvv", "CVV (PCI)"),
        _f("ccexpmon", "Card expiry month (MM)"),
        _f("ccexpyr", "Card expiry year (YYYY)"),
    ],
    hash_formula=HASH_PAYMENT,
    corrective_checks=[
        "Credit Card / Debit Card product must be Fully Ready",
        "PCI DSS compliance required for raw card data",
        "Merchant must have S2S card flow enabled",
    ],
    notes=[
        "pg=CC (credit) or DC (debit); txn_s2s_flow=4",
        "Pre-step: getBinInfo (hash sha512(key|command|var1|salt)) and optional check_isDomestic",
        "Response includes acsTemplate (base64 HTML) for 3DS",
        "If binData.pureS2SSupported, submit OTP to https://test.payu.in/ResponseHandler.php",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_card_preauth",
    name="Card Pre-Auth (S2S)",
    description="Server-to-server card pre-authorization — hold funds without capturing.",
    integration_type="Merchant Hosted",
    required_products=["Credit Card"],
    required_banking_codes=["creditcard"],
    required_modes=["creditcard"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="CC"),
        _f("bankcode", "Bank code (CC/AMEX)"),
        _f("ccnum", "Card number"),
        _f("ccname", "Name on card"),
        _f("ccvv", "CVV"),
        _f("ccexpmon", "Expiry month"),
        _f("ccexpyr", "Expiry year"),
        _f("pre_authorize", "Pre-authorize flag", fixed="1"),
    ],
    hash_formula=HASH_PAYMENT,
    corrective_checks=[
        "Credit Card product Fully Ready with PreAuth enabled",
        "PreAuth activation requires PayU KAM approval",
    ],
    notes=[
        "pre_authorize=1 holds funds (auth state); use capture_transaction later",
        "Cancel (uncaptured) via cancel_transaction; captured txns can only be refunded",
        "Auto capture on day 7; supported on Visa, Mastercard, Amex CC only",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_card_tokenization",
    name="Card Tokenization (S2S)",
    description="Tokenize card details for saved-card flows (PayU/Network/Issuer tokens).",
    integration_type="Merchant Hosted",
    required_products=["Tokenisation", "Credit Card", "Debit Card"],
    required_banking_codes=["creditcard", "debitcard"],
    required_modes=["creditcard", "debitcard"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="CC"),
        _f("bankcode", "Bank code"),
        _f("user_credentials", "Encrypted user credential (format: merchantKey:userId)"),
        _f("store_card_or_store_card_token", "store_card=1 (first time) or store_card_token=<token> (repeat)"),
    ],
    hash_formula=HASH_PAYMENT,
    corrective_checks=[
        "Tokenisation product Fully Ready",
        "Credit Card or Debit Card product Fully Ready",
    ],
    notes=[
        "Model 2: first-time sends ccnum+ccvv+store_card=1+user_credentials; repeat uses store_card_token (cvv optional)",
        "Model 3: first-time plain payment, then save_payment_instrument; repeat uses get_payment_instrument + Get Cryptogram",
        "storecard_token_type: 0=PayU, 1=Network, 2=Issuer (DINR)",
        "Related postservice cmds: get_user_cards, get_payment_instrument, save_payment_instrument, delete_payment_instrument, get_payment_details",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_acs_template_decoder",
    name="ACS Template Decoder",
    description="Utility to decode base64 acsTemplate returned by _payment for 3DS flows.",
    integration_type="Merchant Hosted",
    required_products=["Credit Card", "Debit Card", "Netbanking", "UPI Autopay", "Enach"],
    api_endpoint="",
    http_method="",
    required_fields=[_f("acsTemplate", "Base64-encoded HTML from _payment response")],
    hash_formula="",
    notes=[
        "Utility — no API call; decodes base64 acsTemplate returned by _payment",
        "Decoded HTML is an auto-submitting form redirecting to bank's 3DS page",
        "Render in a new window (window.open) — do NOT use iframe (X-Frame-Options: DENY)",
        "Bank redirects back to merchant surl/furl after authentication",
    ],
))

# -------------------------- Net Banking Flows --------------------------

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_bank_selection",
    name="NB - getNetbankingStatus",
    description="Fetch list of active net banking banks with their real-time up status.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="getNetbankingStatus"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1='default' returns all banks; or pass a specific ibibo_code",
        "Response array: ibibo_code, bank_name, mode, up_status (1=Up, 0=Down)",
        "Filter by mode='NB' to get only Net Banking options",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_initiate",
    name="NB - Initiate Payment",
    description="Initiate a Net Banking payment via S2S.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    required_modes=["netbanking"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="NB"),
        _f("bankcode", "Bank ibibo code from getNetbankingStatus (e.g. AXIB/HDFB/ICIB/SBIB/TESTPGNB)"),
    ],
    hash_formula=HASH_PAYMENT,
    corrective_checks=[
        "Netbanking product Fully Ready",
        "Banking code 'netbanking' enabled",
    ],
    notes=[
        "pg=NB, txn_s2s_flow=4; bankcode must come from getNetbankingStatus",
        "Response returns base64 acsTemplate → redirect customer to bank login",
        "After bank auth, customer redirected to surl/furl",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_handle_response",
    name="NB - Handle Response / Redirect",
    description="Utility to decode acsTemplate and verify reverse hash from callback.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    api_endpoint="",
    http_method="",
    required_fields=[_f("acsTemplate", "Base64-encoded HTML from _payment response")],
    hash_formula="",
    notes=[
        "Base64-decode result.acsTemplate and render in new window",
        "Auto-submit form redirects customer to bank site",
        "Callback (surl/furl) returns status, mihpayid, mode, txnid, amount, bankcode, bank_ref_num, unmappedstatus, field9",
        "Verify reverse hash: sha512(SALT|status||||||udf5|udf4|udf3|udf2|udf1|email|firstname|productinfo|amount|txnid|key)",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_verify",
    name="NB - Verify Payment",
    description="Verify a Net Banking transaction by txnid.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="verify_payment"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 = txnid (multiple txnids pipe-separated allowed)",
        "Response returns transaction_details with mihpayid, status, unmappedstatus=captured for success",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_refund",
    name="NB - Normal Refund",
    description="Initiate a refund (full or partial) for a Net Banking transaction.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="cancel_refund_transaction"),
        _f("var2", "Unique refund token ID"),
        _f("var3", "Refund amount"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1=mihpayid, var2=unique refund token id, var3=refund amount (partial supported)",
        "Track refund progress via check_action_status API",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_split_refund",
    name="NB - Split Refund",
    description="Refund a split payment across child merchants.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking", "Split Settlements"],
    required_banking_codes=["netbanking", "SPLITPAY"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="cancel_refund_transaction"),
        _f("var2", "Unique refund token"),
        _f("var3", "Total refund amount"),
        _f("var5", "JSON: {splitInfo:[{merchantId, amount}]}"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var5 is JSON {splitInfo:[{merchantId, amount}]} matching original split",
        "Total across splits cannot exceed original transaction amount",
        "Use check_action_status to track split refund status",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_tpv",
    name="NB - TPV (Third Party Verification)",
    description="Net Banking payment with beneficiary account validation (TPV).",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    required_modes=["netbanking"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="NB"),
        _f("bankcode", "TPV-enabled bankcode (AXNBTPV/SBINBTPV/IKIBTPV/HABOROTPV)"),
        _f("api_version", "API version", fixed="6"),
        _f("beneficiarydetail", "JSON {beneficiaryAccountNumber, ifscCode}"),
    ],
    hash_formula=HASH_NB_TPV,
    corrective_checks=[
        "Netbanking product Fully Ready",
        "TPV-enabled bankcode must be configured for merchant (e.g. AXNBTPV)",
    ],
    notes=[
        "api_version=6; beneficiarydetail JSON included in hash",
        "Hash has 11 pipes between email and beneficiarydetail, then salt",
        "Up to 4 beneficiary accounts supported (pipe-separated)",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_pacb",
    name="NB - PACB (Pre-Authorize)",
    description="Net Banking Pre-Authorize: block customer funds for later capture.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    required_modes=["netbanking"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="NB"),
        _f("bankcode", "NB bankcode"),
        _f("pre_authorize", "Pre-authorize flag", fixed="1"),
        _f("api_version", "API version", fixed="6"),
    ],
    hash_formula=HASH_PAYMENT,
    corrective_checks=[
        "Netbanking product Fully Ready",
        "PACB activation required — contact PayU KAM to enable",
    ],
    notes=[
        "pre_authorize=1, api_version=6, pg=NB",
        "Successful auth → unmappedstatus='auth' (funds blocked); 'captured' means PACB NOT enabled",
        "Subscription variant uses si=1 + si_details (billingCycle, multiCapture:Y) with api_version=7",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_pacb_capture",
    name="NB - Capture PACB Funds",
    description="Capture previously pre-authorized NB funds.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="capture_transaction"),
        _f("var2", "Unique capture request id"),
        _f("var3", "Capture amount (partial allowed)"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1=mihpayid from PACB, var2=unique capture request id, var3=amount",
        "Only valid when original unmappedstatus='auth' — else 'Delayed capture not allowed'",
        "Partial capture releases remaining hold; 7-14 day hold window typical",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_enach_register",
    name="NB eNACH - Register Mandate",
    description="Register a Net Banking eNACH mandate for recurring debits.",
    integration_type="Merchant Hosted",
    required_products=["Enach", "Netbanking"],
    required_banking_codes=["enach", "standinginstruction"],
    required_modes=["enach", "netbanking"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="ENACH"),
        _f("bankcode", "eNACH bankcode (ICICENCC/HABORENCC/SBIENCC)"),
        _f("si", "Stored instrument flag", fixed="1"),
        _f("api_version", "API version", fixed="7"),
        _f("si_details", "JSON with billingAmount, billingCurrency, billingCycle, billingInterval, paymentStartDate, paymentEndDate"),
        _f("beneficiarydetail", "JSON {beneficiaryName, beneficiaryAccountNumber, beneficiaryAccountType, beneficiaryIfscCode}"),
    ],
    hash_formula=HASH_PAYMENT_SI,
    corrective_checks=[
        "Enach product Fully Ready",
        "Banking codes 'enach' AND 'standinginstruction' enabled",
        "eNACH-enabled bankcode configured (ICICENCC/HABORENCC/SBIENCC)",
    ],
    notes=[
        "pg=ENACH (not NB), si=1, api_version=7, txn_s2s_flow=4",
        "beneficiarydetail mandatory — needs account type (SAVINGS/CURRENT) + IFSC",
        "For eNACH, amount typically ₹1.00; mihpayid from callback is the authpayuid",
    ],
    required_callbacks=["siUpdateCallback"],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_enach_status",
    name="NB eNACH - Mandate Status",
    description="Check eNACH mandate status.",
    integration_type="Merchant Hosted",
    required_products=["Enach"],
    required_banking_codes=["enach"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="NB_mandate_status"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 JSON string {authpayuid, requestId}",
        "Status: INITIATED/SUCCESS/FAILED/CANCEL_*",
        "SUCCESS = mandate active and ready for recurring debits",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_enach_execute",
    name="NB eNACH - Execute Recurring Debit",
    description="Execute a recurring debit against an active eNACH mandate.",
    integration_type="Merchant Hosted",
    required_products=["Enach", "Cards SI"],
    required_banking_codes=["enach", "standinginstruction"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="si_transaction"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 JSON: {authpayuid, invoiceDisplayNumber, amount, txnid, phone, email, udf2-5}",
        "Only works 24h+ after mandate registration (PayU policy)",
        "Debit amount must not exceed billingAmount in mandate",
        "No customer 2FA required for subsequent debits",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_bank_list",
    name="NB - Get Active Bank List",
    description="Alias of getNetbankingStatus — returns active NB banks.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking"],
    required_banking_codes=["netbanking"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="getNetbankingStatus"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1='default' returns all; or pass a specific ibibo_code",
        "Response returns ibibo_code, bank_name, mode, up_status (1=Up, 0=Down)",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_split_payment",
    name="NB - Split Payment",
    description="Split an NB payment across multiple child merchants.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking", "Split Settlements"],
    required_banking_codes=["netbanking", "SPLITPAY"],
    required_modes=["netbanking", "SPLITPAY"],
    api_endpoint=PAYMENT_URL,
    prod_endpoint=PAYMENT_PROD,
    required_fields=BASE_S2S_FIELDS + [
        _f("pg", "Payment gateway", fixed="NB"),
        _f("bankcode", "NB bankcode"),
        _f("split_request", "JSON {split_info:[{merchant_id, amount}]}"),
    ],
    hash_formula=HASH_NB_SPLIT,
    corrective_checks=[
        "Netbanking product Fully Ready",
        "Split Settlements product Fully Ready",
        "Child merchant IDs must be configured on PayU",
    ],
    notes=[
        "split_request JSON: {split_info:[{merchant_id, amount}]}",
        "split_request JSON appended AFTER salt in hash string (unique placement!)",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_split_verify",
    name="NB - Verify Split Payment",
    description="Verify a split NB payment.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking", "Split Settlements"],
    required_banking_codes=["netbanking"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="verify_payment"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "Response includes split_status and split_info distribution",
        "Check split was applied among all merchants correctly",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_nb_offers",
    name="NB - Offers / SKU-Level Offers",
    description="Check and apply NB offers (bank/card/SKU-level discounts).",
    integration_type="Merchant Hosted",
    required_products=["Netbanking", "Offer engine"],
    required_banking_codes=["netbanking"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="check_offer"),
        _f("var2", "Payment mode (e.g. NB)"),
        _f("var3", "BANKCODE"),
    ],
    hash_formula=HASH_POSTSERVICE,
    corrective_checks=[
        "Offer engine product must be Fully Ready",
        "Netbanking product Fully Ready",
    ],
    notes=[
        "var1=amount, var2=payment mode (NB), var3=BANKCODE",
        "Apply returned offer_key in _payment; use offer_auto_apply=1 for best offer",
        "SKU offers use cart_details JSON {items:[{sku, category, brand, amount, quantity}], total}",
    ],
))

_add(PaymentFlow(
    flow_id="merchant_hosted_settlement",
    name="Settlement Details",
    description="Fetch settlement details for transactions.",
    integration_type="Merchant Hosted",
    required_products=["Netbanking", "UPI", "Credit Card", "Debit Card"],
    api_endpoint=POSTSERVICE_URL,
    prod_endpoint=POSTSERVICE_PROD,
    required_fields=POSTSERVICE_FIELDS + [
        _f("command", "API command", fixed="get_settlement_details"),
    ],
    hash_formula=HASH_POSTSERVICE,
    notes=[
        "var1 = settlement_id or date range",
        "Standard T+2; Express T+0/T+1 if enabled",
        "Refunds deducted from next settlement; split settlements distributed per split config",
    ],
))
