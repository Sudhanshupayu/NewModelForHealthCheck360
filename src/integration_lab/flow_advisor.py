"""Flow advisor: analyzes merchant configuration against flow requirements.

Takes a merchant's HealthCheck360 data and compares it with an Integration Lab
payment flow's requirements to produce a gap analysis and corrective steps.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .knowledge_base import PaymentFlow, get_flow

logger = logging.getLogger(__name__)


@dataclass
class IntegrationGap:
    """Represents a gap between merchant config and flow requirements."""
    severity: str  # "critical", "warning", "info"
    category: str  # "product", "banking_code", "mode", "callback", "technical"
    item: str
    current_status: str
    required_status: str
    corrective_action: str


@dataclass
class IntegrationAnalysis:
    """Complete analysis of merchant readiness for a payment flow."""
    merchant_id: str
    merchant_name: str
    flow_id: str
    flow_name: str
    
    # Overall readiness
    ready_to_integrate: bool = False
    readiness_level: str = "not_ready"  # "ready", "partially_ready", "not_ready"
    
    # Detailed findings
    gaps: List[IntegrationGap] = field(default_factory=list)
    
    # Passing checks
    verified_items: List[str] = field(default_factory=list)
    
    # Corrective steps (prioritized)
    corrective_steps: List[str] = field(default_factory=list)
    
    # Flow-specific notes
    integration_notes: List[str] = field(default_factory=list)


def _check_product_readiness(
    flow: PaymentFlow,
    product_status_response: Dict[str, Any],
) -> tuple[List[IntegrationGap], List[str]]:
    """Check if required products are ready for the flow."""
    gaps = []
    verified = []
    
    products = product_status_response.get("product_status", {})
    
    for required_product in flow.required_products:
        product_data = products.get(required_product)
        
        if not product_data:
            gaps.append(IntegrationGap(
                severity="critical",
                category="product",
                item=required_product,
                current_status="Not found in merchant configuration",
                required_status="Must be enabled and fully configured",
                corrective_action=(
                    f"Contact PayU support to enable '{required_product}' "
                    f"product for this merchant"
                ),
            ))
            continue
        
        flags = product_data.get("flags", "No").lower()
        modes = product_data.get("modes", "No").lower()
        status = product_data.get("status", "No").lower()
        
        yes_count = sum(1 for v in [flags, modes, status] if v == "yes")
        
        missing = []
        if flags != "yes":
            missing.append("flags")
        if modes != "yes":
            missing.append("modes")
        if status != "yes":
            missing.append("status")
        
        if yes_count == 3:
            verified.append(f"✓ {required_product} is Fully Ready")
        elif yes_count == 2:
            gaps.append(IntegrationGap(
                severity="warning",
                category="product",
                item=required_product,
                current_status=f"Partially configured - {yes_count}/3 set (missing: {', '.join(missing)})",
                required_status="Fully Ready (flags=Yes, modes=Yes, status=Yes)",
                corrective_action=(
                    f"Configure {', '.join(missing)} for '{required_product}' "
                    f"in the merchant dashboard"
                ),
            ))
        elif yes_count == 1:
            gaps.append(IntegrationGap(
                severity="critical",
                category="product",
                item=required_product,
                current_status=f"Minimally configured - only {yes_count}/3 set (missing: {', '.join(missing)})",
                required_status="Fully Ready (flags=Yes, modes=Yes, status=Yes)",
                corrective_action=(
                    f"Configure {', '.join(missing)} for '{required_product}' "
                    f"in the merchant dashboard. Product is registered but not production-ready."
                ),
            ))
        else:
            gaps.append(IntegrationGap(
                severity="critical",
                category="product",
                item=required_product,
                current_status="Not configured (0/3 set)",
                required_status="Fully Ready",
                corrective_action=(
                    f"Enable and configure '{required_product}' product "
                    f"(flags, modes, and status must all be 'Yes')"
                ),
            ))
    
    return gaps, verified


def _check_banking_codes(
    flow: PaymentFlow,
    overview_response: Dict[str, Any],
) -> tuple[List[IntegrationGap], List[str]]:
    """Check if required banking codes are enabled."""
    gaps = []
    verified = []
    
    if not flow.required_banking_codes:
        return gaps, verified
    
    banking = overview_response.get("bankingCodesStatus", {})
    modes_enabled = banking.get("modesEnabled", "").lower()
    bank_codes = banking.get("bankCodes", "").lower()
    
    for code in flow.required_banking_codes:
        code_lower = code.lower()
        if code_lower in modes_enabled or code_lower in bank_codes:
            verified.append(f"✓ Banking code '{code}' is enabled")
        else:
            gaps.append(IntegrationGap(
                severity="critical",
                category="banking_code",
                item=code,
                current_status="Not enabled in banking codes",
                required_status=f"'{code}' must be in merchant's enabled modes",
                corrective_action=(
                    f"Contact PayU support to enable banking code '{code}' "
                    f"for this merchant"
                ),
            ))
    
    return gaps, verified


def _check_modes(
    flow: PaymentFlow,
    overview_response: Dict[str, Any],
) -> tuple[List[IntegrationGap], List[str]]:
    """Check if required payment modes are enabled."""
    gaps = []
    verified = []
    
    if not flow.required_modes:
        return gaps, verified
    
    banking = overview_response.get("bankingCodesStatus", {})
    modes_enabled = banking.get("modesEnabled", "").lower()
    
    for mode in flow.required_modes:
        mode_lower = mode.lower()
        if mode_lower in modes_enabled:
            verified.append(f"✓ Payment mode '{mode}' is enabled")
        else:
            gaps.append(IntegrationGap(
                severity="warning",
                category="mode",
                item=mode,
                current_status="Not in enabled modes",
                required_status=f"'{mode}' should be enabled",
                corrective_action=(
                    f"Enable payment mode '{mode}' in merchant configuration"
                ),
            ))
    
    return gaps, verified


def _check_callbacks(
    flow: PaymentFlow,
    overview_response: Dict[str, Any],
) -> tuple[List[IntegrationGap], List[str]]:
    """Check if required callback events are configured."""
    gaps = []
    verified = []
    
    if not flow.required_callbacks:
        return gaps, verified
    
    callbacks = overview_response.get("callbackEvents", {})
    payment_cb = callbacks.get("paymentCallbackEvents", "").lower()
    si_cb = callbacks.get("siUpdateCallbackEvents", "").lower()
    refund_cb = callbacks.get("refundCallbackEvents", "").lower()
    all_callbacks = payment_cb + si_cb + refund_cb
    
    for cb in flow.required_callbacks:
        cb_lower = cb.lower()
        if cb_lower in all_callbacks:
            verified.append(f"✓ Callback event '{cb}' is configured")
        elif cb_lower == "siupdatecallback" and si_cb:
            verified.append(f"✓ SI Update callback is configured")
        else:
            severity = "critical" if "si" in cb_lower else "warning"
            gaps.append(IntegrationGap(
                severity=severity,
                category="callback",
                item=cb,
                current_status="Not configured",
                required_status=f"'{cb}' callback URL must be configured",
                corrective_action=(
                    f"Configure '{cb}' callback URL in the merchant dashboard. "
                    f"This is required to receive payment lifecycle events."
                ),
            ))
    
    return gaps, verified


def _check_technical_config(
    flow: PaymentFlow,
    overview_response: Dict[str, Any],
) -> tuple[List[IntegrationGap], List[str]]:
    """Check technical configurations like refund flags, rate limits."""
    gaps = []
    verified = []
    
    tech = overview_response.get("technicalConfigurations", {})
    refund_flags = tech.get("refundFlags", "").lower()
    
    # Check auto refund for flows that may need it
    if flow.flow_id in ("payu_hosted_preauth", "payu_hosted_subscription"):
        if "not configured" in refund_flags:
            gaps.append(IntegrationGap(
                severity="warning",
                category="technical",
                item="Auto refund",
                current_status="Not configured",
                required_status="Auto refund should be enabled",
                corrective_action=(
                    "Enable auto refund and refund webhooks in the merchant "
                    "dashboard for better refund handling"
                ),
            ))
        else:
            verified.append("✓ Refund configuration is set up")
    
    return gaps, verified


def analyze_merchant_for_flow(
    flow_id: str,
    product_status_response: Dict[str, Any],
    overview_response: Dict[str, Any],
) -> IntegrationAnalysis:
    """Analyze merchant readiness for a specific payment flow.
    
    Args:
        flow_id: Payment flow identifier
        product_status_response: Response from /api/getProductStatus
        overview_response: Response from /api/overview
        
    Returns:
        IntegrationAnalysis with gaps, corrective steps, and recommendations
    """
    flow = get_flow(flow_id)
    if not flow:
        raise ValueError(
            f"Unknown flow '{flow_id}'. Available flows: "
            f"{', '.join(f.flow_id for f in [get_flow(k) for k in [flow_id]] if f)}"
        )
    
    mid = product_status_response.get("mid", "Unknown")
    merchant_info = overview_response.get("merchantInfo", {})
    merchant_name = merchant_info.get("name", "Unknown Merchant")
    
    analysis = IntegrationAnalysis(
        merchant_id=mid,
        merchant_name=merchant_name,
        flow_id=flow.flow_id,
        flow_name=flow.name,
    )
    
    # Run all checks
    all_gaps: List[IntegrationGap] = []
    all_verified: List[str] = []
    
    for check_fn in [
        _check_product_readiness,
        _check_banking_codes,
        _check_modes,
        _check_callbacks,
        _check_technical_config,
    ]:
        if check_fn == _check_product_readiness:
            gaps, verified = check_fn(flow, product_status_response)
        else:
            gaps, verified = check_fn(flow, overview_response)
        all_gaps.extend(gaps)
        all_verified.extend(verified)
    
    analysis.gaps = all_gaps
    analysis.verified_items = all_verified
    
    # Determine readiness level
    critical_gaps = [g for g in all_gaps if g.severity == "critical"]
    warning_gaps = [g for g in all_gaps if g.severity == "warning"]
    
    if not critical_gaps and not warning_gaps:
        analysis.readiness_level = "ready"
        analysis.ready_to_integrate = True
    elif not critical_gaps:
        analysis.readiness_level = "partially_ready"
        analysis.ready_to_integrate = True
    else:
        analysis.readiness_level = "not_ready"
        analysis.ready_to_integrate = False
    
    # Build prioritized corrective steps
    steps = []
    
    # Critical first
    for i, gap in enumerate(critical_gaps, 1):
        steps.append(f"[CRITICAL] {gap.corrective_action}")
    
    # Then warnings
    for gap in warning_gaps:
        steps.append(f"[WARNING] {gap.corrective_action}")
    
    # Flow-specific notes
    steps.extend([f"[NOTE] {note}" for note in flow.notes])
    
    # Flow-specific corrective checks (from KB)
    for check in flow.corrective_checks:
        if check not in steps:
            steps.append(f"[CHECK] {check}")
    
    analysis.corrective_steps = steps
    analysis.integration_notes = flow.notes
    
    return analysis


def format_analysis_report(analysis: IntegrationAnalysis) -> str:
    """Format analysis into a human-readable report.
    
    Args:
        analysis: IntegrationAnalysis object
        
    Returns:
        Formatted markdown-style report
    """
    lines = []
    
    # Header
    lines.append(f"🔍 **Integration Analysis: {analysis.flow_name}**")
    lines.append(f"   Merchant ID: {analysis.merchant_id}")
    lines.append(f"   Merchant: {analysis.merchant_name}")
    lines.append("")
    
    # Readiness status
    status_emoji = {
        "ready": "✅",
        "partially_ready": "⚠️",
        "not_ready": "❌",
    }
    emoji = status_emoji.get(analysis.readiness_level, "❓")
    status_text = analysis.readiness_level.replace("_", " ").title()
    
    lines.append(f"{emoji} **Overall Status: {status_text}**")
    
    if analysis.ready_to_integrate:
        lines.append("   This merchant can proceed with the integration.")
    else:
        lines.append("   Critical gaps must be resolved before integrating.")
    lines.append("")
    
    # Verified items
    if analysis.verified_items:
        lines.append(f"**✓ Verified ({len(analysis.verified_items)}):**")
        for item in analysis.verified_items[:10]:
            lines.append(f"   {item}")
        if len(analysis.verified_items) > 10:
            lines.append(f"   ... and {len(analysis.verified_items) - 10} more")
        lines.append("")
    
    # Critical gaps
    critical_gaps = [g for g in analysis.gaps if g.severity == "critical"]
    if critical_gaps:
        lines.append(f"**🚨 Critical Issues ({len(critical_gaps)}):**")
        for gap in critical_gaps:
            lines.append(f"   • **{gap.item}**: {gap.current_status}")
            lines.append(f"     → {gap.corrective_action}")
        lines.append("")
    
    # Warnings
    warning_gaps = [g for g in analysis.gaps if g.severity == "warning"]
    if warning_gaps:
        lines.append(f"**⚠️ Warnings ({len(warning_gaps)}):**")
        for gap in warning_gaps:
            lines.append(f"   • **{gap.item}**: {gap.current_status}")
            lines.append(f"     → {gap.corrective_action}")
        lines.append("")
    
    # Integration notes
    if analysis.integration_notes:
        lines.append("**📝 Integration Notes:**")
        for note in analysis.integration_notes:
            lines.append(f"   • {note}")
        lines.append("")
    
    return "\n".join(lines)
