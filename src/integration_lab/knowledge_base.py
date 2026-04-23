"""Knowledge base for PayU Integration Lab payment flows.

This module provides structured information about each payment flow available
in PayU's Integration Lab, including required fields, banking codes, products,
and corrective checks needed for successful integration.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FlowField:
    """Represents a field required for a payment flow."""
    name: str
    description: str
    mandatory: bool = True
    fixed_value: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class PaymentFlow:
    """Represents a PayU payment integration flow."""
    flow_id: str
    name: str
    description: str
    integration_type: str  # "PayU Hosted" or "Merchant Hosted"
    
    # Product requirements on HealthCheck360
    required_products: List[str] = field(default_factory=list)
    required_banking_codes: List[str] = field(default_factory=list)
    required_modes: List[str] = field(default_factory=list)
    
    # API specifics
    api_endpoint: str = "https://test.payu.in/_payment"
    prod_endpoint: str = "https://secure.payu.in/_payment"
    http_method: str = "POST"
    
    # Field requirements
    required_fields: List[FlowField] = field(default_factory=list)
    optional_fields: List[FlowField] = field(default_factory=list)
    
    # Hash formula (pipe-separated)
    hash_formula: str = "key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||salt"
    
    # Corrective checks on merchant config
    corrective_checks: List[str] = field(default_factory=list)
    
    # Special notes / warnings
    notes: List[str] = field(default_factory=list)
    
    # Related callback events required
    required_callbacks: List[str] = field(default_factory=list)


# =============================================================================
# Common fields used across flows
# =============================================================================

COMMON_PAYMENT_FIELDS = [
    FlowField("key", "Merchant key from PayU dashboard", mandatory=True),
    FlowField("txnid", "Unique transaction ID (auto-generated)", mandatory=True),
    FlowField("amount", "Transaction amount", mandatory=True),
    FlowField("productinfo", "Product description (max 100 chars)", mandatory=True),
    FlowField("firstname", "Customer first name (max 60 chars)", mandatory=True),
    FlowField("email", "Customer email (max 50 chars)", mandatory=True),
    FlowField("phone", "Customer phone (10 digits)", mandatory=True),
    FlowField("surl", "Success redirect URL", mandatory=True),
    FlowField("furl", "Failure redirect URL", mandatory=True),
    FlowField("hash", "SHA-512 hash of required fields", mandatory=True),
]

COMMON_UDF_FIELDS = [
    FlowField("udf1", "User defined field 1", mandatory=False),
    FlowField("udf2", "User defined field 2", mandatory=False),
    FlowField("udf3", "User defined field 3", mandatory=False),
    FlowField("udf4", "User defined field 4", mandatory=False),
    FlowField("udf5", "User defined field 5", mandatory=False),
]

COMMON_ADDRESS_FIELDS = [
    FlowField("address1", "Address line 1", mandatory=False),
    FlowField("address2", "Address line 2", mandatory=False),
    FlowField("city", "City", mandatory=False),
    FlowField("state", "State", mandatory=False),
    FlowField("country", "Country", mandatory=False),
    FlowField("zipcode", "ZIP code", mandatory=False),
]


# =============================================================================
# Payment Flow Definitions
# =============================================================================

FLOWS: Dict[str, PaymentFlow] = {
    "payu_hosted_checkout": PaymentFlow(
        flow_id="payu_hosted_checkout",
        name="PayU Hosted Checkout",
        description="PayU's standard hosted checkout page with redirect-based payment flow. Customer is redirected to PayU to complete payment.",
        integration_type="PayU Hosted",
        required_products=["PayU Hosted Checkout"],
        required_fields=COMMON_PAYMENT_FIELDS,
        optional_fields=COMMON_UDF_FIELDS + COMMON_ADDRESS_FIELDS,
        hash_formula="key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||salt",
        corrective_checks=[
            "Ensure 'PayU Hosted Checkout' product is Fully Ready (flags=Yes, modes=Yes, status=Yes)",
            "Verify Success and Failure callback URLs are configured",
            "Ensure at least one payment mode is enabled (CC/DC/UPI/NB)",
        ],
        required_callbacks=["success", "failed"],
    ),

    "payu_hosted_subscription": PaymentFlow(
        flow_id="payu_hosted_subscription",
        name="PayU Hosted Subscription",
        description="Recurring payments with eNACH and card subscriptions via PayU's hosted checkout.",
        integration_type="PayU Hosted",
        required_products=["Cards SI", "Enach", "UPI Autopay"],
        required_banking_codes=["standinginstruction", "enach"],
        required_modes=["standinginstruction", "enach", "upi"],
        required_fields=COMMON_PAYMENT_FIELDS + [
            FlowField("si", "Stored Instrument flag", mandatory=True, fixed_value="1"),
            FlowField("api_version", "API version", mandatory=True, fixed_value="7"),
            FlowField("si_details", "JSON with billingAmount, billingCurrency, billingCycle, billingInterval, paymentStartDate, paymentEndDate", mandatory=True),
        ],
        optional_fields=COMMON_UDF_FIELDS + COMMON_ADDRESS_FIELDS,
        hash_formula="key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||si_details|salt",
        corrective_checks=[
            "Ensure Cards SI / Enach / UPI Autopay product is Fully Ready based on desired SI type",
            "Banking codes: 'standinginstruction' or 'enach' must be enabled",
            "SI Update callback URL must be configured for lifecycle updates",
            "For eNACH, payment_start_date must be at least tomorrow",
        ],
        required_callbacks=["siUpdateCallback"],
        notes=[
            "si=1 and api_version=7 are mandatory for subscription payments",
            "For eNACH: use transaction amount as 1, select tomorrow's date minimum",
            "si_details is JSON stringified and included in hash",
        ],
    ),

    "payu_hosted_tpv": PaymentFlow(
        flow_id="payu_hosted_tpv",
        name="PayU Hosted TPV (Third Party Verification)",
        description="Third Party Verification flow where the customer's bank account is validated before payment is processed.",
        integration_type="PayU Hosted",
        required_products=["Netbanking"],
        required_banking_codes=["netbanking"],
        required_modes=["netbanking"],
        required_fields=COMMON_PAYMENT_FIELDS + [
            FlowField("beneficiarydetail", "JSON with beneficiaryAccountNumber, beneficiaryIFSC, beneficiaryName, beneficiaryAccountType", mandatory=True),
            FlowField("txn_s2s_flow", "Server-to-server flow flag", mandatory=True, fixed_value="4"),
        ],
        optional_fields=COMMON_UDF_FIELDS + COMMON_ADDRESS_FIELDS,
        corrective_checks=[
            "Ensure Netbanking product is Fully Ready",
            "Verify TPV is enabled for the merchant in bank codes",
            "Beneficiary details must be valid and match customer's bank record",
        ],
        notes=[
            "TPV is used for stock trading, mutual funds, and similar regulated use cases",
            "Beneficiary account must be registered with PayU in advance",
        ],
    ),

    "payu_hosted_upi_otm": PaymentFlow(
        flow_id="payu_hosted_upi_otm",
        name="PayU Hosted UPI OTM (One Time Mandate)",
        description="UPI One Time Mandate for authorizing a future deduction with customer's explicit approval.",
        integration_type="PayU Hosted",
        required_products=["UPI Autopay"],
        required_banking_codes=["upiotm"],
        required_modes=["upiotm", "upi"],
        required_fields=COMMON_PAYMENT_FIELDS + [
            FlowField("si", "Stored Instrument flag", mandatory=True, fixed_value="1"),
            FlowField("api_version", "API version", mandatory=True, fixed_value="7"),
            FlowField("si_details", "JSON with mandate details: billingAmount, billingCurrency, paymentStartDate, paymentEndDate, remarks", mandatory=True),
            FlowField("enforce_paymethod", "Force UPI payment method", mandatory=True, fixed_value="upi"),
        ],
        optional_fields=COMMON_UDF_FIELDS + COMMON_ADDRESS_FIELDS,
        hash_formula="key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||si_details|salt",
        corrective_checks=[
            "Ensure UPI Autopay product is Fully Ready (flags=Yes, modes=Yes, status=Yes)",
            "Banking code 'upiotm' must be enabled in bank codes",
            "SI Update callback URL for UPI SI must be configured",
            "Mandate start date must be tomorrow or later",
        ],
        required_callbacks=["siUpdateCallback"],
        notes=[
            "UPI OTM holds amount for future deduction; not an immediate charge",
            "Maximum validity as per NPCI UPI mandate rules",
        ],
    ),

    "payu_hosted_preauth": PaymentFlow(
        flow_id="payu_hosted_preauth",
        name="PayU Hosted PreAuth Card Flow",
        description="Pre-authorization for card payments where funds are held but not charged until capture.",
        integration_type="PayU Hosted",
        required_products=["Credit Card", "Debit Card"],
        required_banking_codes=["creditcard", "debitcard"],
        required_modes=["creditcard", "debitcard"],
        required_fields=COMMON_PAYMENT_FIELDS + [
            FlowField("txn_s2s_flow", "Transaction flow type (PreAuth)", mandatory=True, fixed_value="4"),
        ],
        optional_fields=COMMON_UDF_FIELDS + COMMON_ADDRESS_FIELDS,
        corrective_checks=[
            "Credit Card / Debit Card product must be Fully Ready",
            "Merchant must be enabled for PreAuth (confirm with PayU support)",
            "Capture API must be called within validity period (typically 7 days)",
        ],
        notes=[
            "Funds are held (auth only), use Capture API to actually deduct",
            "If not captured within window, authorization expires",
            "Refund/void requires Cancel API",
        ],
    ),

    "checkout_plus": PaymentFlow(
        flow_id="checkout_plus",
        name="Checkout Plus",
        description="PayU's enhanced checkout experience with advanced features like EMI, offers, saved cards, and smart routing.",
        integration_type="PayU Hosted",
        required_products=["PayU Hosted Checkout", "Credit Card", "Debit Card", "UPI", "Netbanking"],
        required_fields=COMMON_PAYMENT_FIELDS,
        optional_fields=COMMON_UDF_FIELDS + COMMON_ADDRESS_FIELDS + [
            FlowField("enforce_paymethod", "Force specific payment methods", mandatory=False),
            FlowField("sdk", "Use Checkout Plus SDK", mandatory=False, fixed_value="1"),
        ],
        corrective_checks=[
            "Multiple payment products should be Fully Ready for best UX",
            "EMI product enabled if offering EMI options",
            "Offer engine enabled if using bank offers",
            "Tokenisation enabled if using saved cards",
        ],
        notes=[
            "Checkout Plus uses PayU's JavaScript SDK for embedded checkout",
            "Better conversion rates than redirect-based checkout",
        ],
    ),

    "payu_hosted_split_payment": PaymentFlow(
        flow_id="payu_hosted_split_payment",
        name="PayU Hosted Split Payment",
        description="Split a single payment across multiple merchant sub-accounts (marketplace model).",
        integration_type="PayU Hosted",
        required_products=["Split Settlements"],
        required_banking_codes=["SPLITPAY"],
        required_modes=["SPLITPAY"],
        required_fields=COMMON_PAYMENT_FIELDS + [
            FlowField("split_payment_details", "JSON with splitInfo array (merchant codes and amounts)", mandatory=True),
        ],
        optional_fields=COMMON_UDF_FIELDS + COMMON_ADDRESS_FIELDS,
        corrective_checks=[
            "Split Settlements product must be Fully Ready",
            "Banking code 'SPLITPAY' enabled",
            "Sub-merchant codes must be pre-registered with PayU",
            "Sum of split amounts must equal total transaction amount",
        ],
        notes=[
            "Useful for marketplaces, aggregators, booking platforms",
            "Each sub-merchant receives settlement as per configured split",
        ],
    ),

    "payu_hosted_bank_offers": PaymentFlow(
        flow_id="payu_hosted_bank_offers",
        name="PayU Hosted Bank Offers",
        description="Payments with automatic application of configured bank offers and discounts.",
        integration_type="PayU Hosted",
        required_products=["Credit Card", "Debit Card", "Netbanking", "Offer engine"],
        required_fields=COMMON_PAYMENT_FIELDS + [
            FlowField("offer_key", "Bank offer key identifier", mandatory=True),
        ],
        optional_fields=COMMON_UDF_FIELDS + COMMON_ADDRESS_FIELDS + [
            FlowField("sku_details", "JSON array of SKU-level offer items", mandatory=False),
        ],
        corrective_checks=[
            "Offer engine product must be Fully Ready",
            "Relevant payment products (CC/DC/NB) must be Ready",
            "Offers must be pre-configured in PayU dashboard",
            "Offer validity dates should cover transaction date",
        ],
        notes=[
            "Offers can be card-specific, bank-specific, or amount-based",
            "SKU-level offers require additional sku_details parameter",
        ],
    ),

    "payu_hosted_cross_border": PaymentFlow(
        flow_id="payu_hosted_cross_border",
        name="PayU Hosted Cross Border Payment",
        description="International payment transactions with multi-currency support (PACB - Payment Aggregator Cross Border).",
        integration_type="PayU Hosted",
        required_products=["Credit Card", "Debit Card"],
        required_fields=COMMON_PAYMENT_FIELDS + [
            FlowField("address1", "Billing address line 1", mandatory=True),
            FlowField("city", "Billing city", mandatory=True),
            FlowField("state", "Billing state", mandatory=True),
            FlowField("country", "Billing country", mandatory=True),
            FlowField("zipcode", "Billing ZIP code", mandatory=True),
            FlowField("udf5", "Invoice ID (mandatory for cross-border)", mandatory=True),
            FlowField("lrs_service_type", "LRS service type (for one-time only)", mandatory=False, notes="Required when LRS params enabled"),
            FlowField("tcs_amount", "TCS amount for LRS", mandatory=False),
        ],
        optional_fields=[
            FlowField("udf1", "PAN Number", mandatory=False),
            FlowField("udf3", "Buyer's DOB (Recommended)", mandatory=False),
            FlowField("udf4", "Seller Name", mandatory=False),
            FlowField("buyer_type", "Individual or Business", mandatory=False),
        ],
        corrective_checks=[
            "Merchant must be enabled for international transactions (RBI compliance)",
            "PACB (Payment Aggregator Cross Border) approval required from PayU",
            "Billing address fields are MANDATORY for cross-border",
            "Invoice ID (udf5) is mandatory",
            "Credit Card / Debit Card product must be Fully Ready with international enabled",
        ],
        notes=[
            "Subject to RBI guidelines for cross-border payments",
            "LRS (Liberalised Remittance Scheme) params required for certain transactions",
            "TCS (Tax Collected at Source) applicable above threshold",
        ],
    ),
}


def _load_seamless_flows() -> None:
    """Merge merchant-hosted (seamless) flows into the main FLOWS registry.
    
    Imports lazily to avoid circular imports.
    """
    try:
        from .seamless_flows import SEAMLESS_FLOWS
        for fid, flow in SEAMLESS_FLOWS.items():
            FLOWS[fid] = flow
    except ImportError:
        pass


_load_seamless_flows()


def get_flow(flow_id: str) -> Optional[PaymentFlow]:
    """Get a specific payment flow by ID.
    
    Args:
        flow_id: Flow identifier (e.g., "payu_hosted_checkout")
        
    Returns:
        PaymentFlow object or None if not found
    """
    # Support fuzzy matching on flow names
    flow_id_normalized = flow_id.lower().strip().replace(" ", "_").replace("-", "_")
    
    if flow_id_normalized in FLOWS:
        return FLOWS[flow_id_normalized]
    
    # Try partial matching on flow names
    for fid, flow in FLOWS.items():
        if flow_id_normalized in fid or flow_id_normalized in flow.name.lower().replace(" ", "_"):
            return flow
    
    # Merchant-hosted (seamless) keywords take priority if present
    seamless_keyword_map = {
        "seamless": None,
        "s2s": None,
        "merchant_hosted": None,
        "upi_intent": "merchant_hosted_upi_intent",
        "intent": "merchant_hosted_upi_intent",
        "upi_collect": "merchant_hosted_upi_collect",
        "collect": "merchant_hosted_upi_collect",
        "upi_autopay_register": "merchant_hosted_upi_mandate_register",
        "autopay_register": "merchant_hosted_upi_mandate_register",
        "mandate_register": "merchant_hosted_upi_mandate_register",
        "autopay": "merchant_hosted_upi_mandate_register",
        "upi_mandate_status": "merchant_hosted_upi_mandate_status",
        "mandate_status": "merchant_hosted_upi_mandate_status",
        "upi_mandate_modify": "merchant_hosted_upi_mandate_modify",
        "mandate_modify": "merchant_hosted_upi_mandate_modify",
        "upi_otm_preauth": "merchant_hosted_upi_otm_preauth",
        "otm_preauth": "merchant_hosted_upi_otm_preauth",
        "otm_capture": "merchant_hosted_upi_otm_capture",
        "capture_otm": "merchant_hosted_upi_otm_capture",
        "capture_transaction": "merchant_hosted_upi_otm_capture",
        "cancel_refund": "merchant_hosted_upi_otm_cancel_refund",
        "check_action_status": "merchant_hosted_check_action_status",
        "action_status": "merchant_hosted_check_action_status",
        "otm_status_check": "merchant_hosted_upi_otm_status_check",
        "pre_debit": "merchant_hosted_upi_pre_debit",
        "pre_debit_si": "merchant_hosted_upi_pre_debit",
        "si_transaction": "merchant_hosted_upi_si_transaction",
        "card_s2s": "merchant_hosted_card_s2s",
        "s2s_card": "merchant_hosted_card_s2s",
        "card_preauth": "merchant_hosted_card_preauth",
        "tokenization": "merchant_hosted_card_tokenization",
        "tokenisation": "merchant_hosted_card_tokenization",
        "tokenize": "merchant_hosted_card_tokenization",
        "saved_card": "merchant_hosted_card_tokenization",
        "acs_template": "merchant_hosted_acs_template_decoder",
        "acs_decoder": "merchant_hosted_acs_template_decoder",
        "nb_bank_selection": "merchant_hosted_nb_bank_selection",
        "getnetbankingstatus": "merchant_hosted_nb_bank_selection",
        "nb_initiate": "merchant_hosted_nb_initiate",
        "netbanking_initiate": "merchant_hosted_nb_initiate",
        "nb_verify": "merchant_hosted_nb_verify",
        "nb_refund": "merchant_hosted_nb_refund",
        "netbanking_refund": "merchant_hosted_nb_refund",
        "nb_split_refund": "merchant_hosted_nb_split_refund",
        "nb_tpv": "merchant_hosted_nb_tpv",
        "netbanking_tpv": "merchant_hosted_nb_tpv",
        "nb_pacb": "merchant_hosted_nb_pacb",
        "pacb_capture": "merchant_hosted_nb_pacb_capture",
        "nb_pacb_capture": "merchant_hosted_nb_pacb_capture",
        "nb_enach_register": "merchant_hosted_nb_enach_register",
        "enach_register": "merchant_hosted_nb_enach_register",
        "nb_enach_status": "merchant_hosted_nb_enach_status",
        "enach_status": "merchant_hosted_nb_enach_status",
        "nb_enach_execute": "merchant_hosted_nb_enach_execute",
        "enach_execute": "merchant_hosted_nb_enach_execute",
        "nb_bank_list": "merchant_hosted_nb_bank_list",
        "nb_split_payment": "merchant_hosted_nb_split_payment",
        "nb_split_verify": "merchant_hosted_nb_split_verify",
        "nb_offers": "merchant_hosted_nb_offers",
        "settlement": "merchant_hosted_settlement",
    }
    for kw, target in seamless_keyword_map.items():
        if target and kw in flow_id_normalized:
            return FLOWS.get(target)
    
    # PayU Hosted keywords (fallback)
    keyword_map = {
        "subscription": "payu_hosted_subscription",
        "recurring": "payu_hosted_subscription",
        "sip": "payu_hosted_subscription",
        "si": "payu_hosted_subscription",
        "enach": "payu_hosted_subscription",
        "tpv": "payu_hosted_tpv",
        "otm": "payu_hosted_upi_otm",
        "upi_otm": "payu_hosted_upi_otm",
        "preauth": "payu_hosted_preauth",
        "pre_auth": "payu_hosted_preauth",
        "hold": "payu_hosted_preauth",
        "split": "payu_hosted_split_payment",
        "marketplace": "payu_hosted_split_payment",
        "offer": "payu_hosted_bank_offers",
        "discount": "payu_hosted_bank_offers",
        "cross_border": "payu_hosted_cross_border",
        "international": "payu_hosted_cross_border",
        "pacb": "payu_hosted_cross_border",
        "checkout_plus": "checkout_plus",
        "plus": "checkout_plus",
        "hosted": "payu_hosted_checkout",
        "standard": "payu_hosted_checkout",
        "default": "payu_hosted_checkout",
    }
    
    for keyword, target_flow in keyword_map.items():
        if keyword in flow_id_normalized:
            return FLOWS[target_flow]
    
    return None


def list_flows() -> List[Dict[str, str]]:
    """List all available payment flows.
    
    Returns:
        List of dictionaries with flow_id, name, and description
    """
    return [
        {
            "flow_id": flow.flow_id,
            "name": flow.name,
            "description": flow.description,
            "type": flow.integration_type,
        }
        for flow in FLOWS.values()
    ]
