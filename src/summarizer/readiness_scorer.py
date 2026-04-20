"""Readiness score calculation and report formatting."""

from typing import Any, Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class ProductReadiness:
    """Readiness status for a single product."""
    name: str
    score: int
    flags: str
    modes: str
    status: str
    
    @property
    def category(self) -> str:
        """Get the readiness category."""
        if self.score == 100:
            return "fully_ready"
        elif self.score >= 66:
            return "partially_ready"
        elif self.score > 0:
            return "minimally_ready"
        return "not_configured"


def calculate_product_score(flags: str, modes: str, status: str) -> int:
    """Calculate readiness score for a single product.
    
    Scoring logic:
    - flags=Yes, modes=Yes, status=Yes → 100% (Fully Ready)
    - flags=Yes, modes=No, status=Yes  → 66% (Partially Ready - missing modes)
    - flags=Yes, modes=Yes, status=No  → 33% (Configured but inactive)
    - flags=No, modes=No, status=No    → 0% (Not configured)
    
    Args:
        flags: "Yes" or "No"
        modes: "Yes" or "No"
        status: "Yes" or "No"
        
    Returns:
        Readiness score (0-100)
    """
    yes_count = sum(1 for v in [flags, modes, status] if v.lower() == "yes")
    
    if yes_count == 3:
        return 100
    elif yes_count == 2:
        return 66
    elif yes_count == 1:
        return 33
    return 0


def calculate_readiness_score(product_status: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate readiness scores from product status response.
    
    Args:
        product_status: API response from /api/getProductStatus
        
    Returns:
        Dictionary with overall score and per-product breakdown
    """
    mid = product_status.get("mid", "Unknown")
    products = product_status.get("product_status", {})
    
    product_scores: List[ProductReadiness] = []
    
    for product_name, details in products.items():
        flags = details.get("flags", "No")
        modes = details.get("modes", "No")
        status = details.get("status", "No")
        
        score = calculate_product_score(flags, modes, status)
        product_scores.append(ProductReadiness(
            name=product_name,
            score=score,
            flags=flags,
            modes=modes,
            status=status,
        ))
    
    # Calculate overall score
    if product_scores:
        overall_score = sum(p.score for p in product_scores) // len(product_scores)
    else:
        overall_score = 0
    
    # Group by category
    fully_ready = [p for p in product_scores if p.category == "fully_ready"]
    partially_ready = [p for p in product_scores if p.category == "partially_ready"]
    minimally_ready = [p for p in product_scores if p.category == "minimally_ready"]
    not_configured = [p for p in product_scores if p.category == "not_configured"]
    
    return {
        "mid": mid,
        "overall_score": overall_score,
        "total_products": len(product_scores),
        "fully_ready": fully_ready,
        "partially_ready": partially_ready,
        "minimally_ready": minimally_ready,
        "not_configured": not_configured,
        "all_products": product_scores,
    }


def format_readiness_report(readiness_data: Dict[str, Any], merchant_name: str = None) -> str:
    """Format readiness data into a human-readable report.
    
    Args:
        readiness_data: Output from calculate_readiness_score
        merchant_name: Optional merchant name to include
        
    Returns:
        Formatted report string
    """
    mid = readiness_data["mid"]
    overall = readiness_data["overall_score"]
    total = readiness_data["total_products"]
    
    lines = []
    lines.append(f"📊 **Readiness Report for Merchant ID: {mid}**")
    if merchant_name:
        lines.append(f"   Merchant: {merchant_name}")
    lines.append("")
    lines.append(f"**Overall Readiness Score: {overall}%**")
    lines.append(f"Total Products Analyzed: {total}")
    lines.append("")
    
    # Fully Ready
    fully_ready = readiness_data["fully_ready"]
    if fully_ready:
        lines.append(f"✅ **Fully Ready ({len(fully_ready)} products - 100%):**")
        product_names = [p.name for p in fully_ready]
        lines.append(f"   {', '.join(product_names)}")
        lines.append("")
    
    # Partially Ready
    partially_ready = readiness_data["partially_ready"]
    if partially_ready:
        lines.append(f"⚠️ **Partially Ready ({len(partially_ready)} products - 66%):**")
        for p in partially_ready:
            missing = []
            if p.modes.lower() == "no":
                missing.append("modes not configured")
            if p.flags.lower() == "no":
                missing.append("flags not configured")
            if p.status.lower() == "no":
                missing.append("status inactive")
            lines.append(f"   • {p.name} - {', '.join(missing)}")
        lines.append("")
    
    # Minimally Ready
    minimally_ready = readiness_data["minimally_ready"]
    if minimally_ready:
        lines.append(f"🔶 **Minimally Ready ({len(minimally_ready)} products - 33%):**")
        for p in minimally_ready:
            lines.append(f"   • {p.name}")
        lines.append("")
    
    # Not Configured
    not_configured = readiness_data["not_configured"]
    if not_configured:
        lines.append(f"❌ **Not Configured ({len(not_configured)} products - 0%):**")
        product_names = [p.name for p in not_configured]
        lines.append(f"   {', '.join(product_names)}")
        lines.append("")
    
    return "\n".join(lines)


def format_overview_summary(overview_data: Dict[str, Any]) -> str:
    """Format merchant overview into a human-readable summary.
    
    Args:
        overview_data: API response from /api/overview
        
    Returns:
        Formatted summary string
    """
    lines = []
    
    # Merchant Info
    merchant_info = overview_data.get("merchantInfo", {})
    mid = merchant_info.get("mid", "Unknown")
    name = merchant_info.get("name", "Unknown")
    key = merchant_info.get("key", "N/A")
    approved = merchant_info.get("approved", "Unknown")
    active = merchant_info.get("active", "Unknown")
    
    lines.append(f"🏢 **Merchant Overview for MID: {mid}**")
    lines.append("")
    lines.append("**Merchant Info:**")
    lines.append(f"   • Name: {name}")
    lines.append(f"   • Key: {key}")
    lines.append(f"   • Approved: {approved}")
    lines.append(f"   • Active: {active}")
    lines.append("")
    
    # KYC Status
    kyc = overview_data.get("kycStatus", {})
    if kyc:
        lines.append("**KYC Status:**")
        lines.append(f"   • Approval Status: {kyc.get('merchantApprovalStatus', 'Unknown')}")
        lines.append("")
    
    # Onboarding Status
    onboarding = overview_data.get("onboardingStatus", {})
    if onboarding:
        lines.append("**Onboarding Status:**")
        lines.append(f"   • Status: {onboarding.get('onboardingStatus', 'Unknown')}")
        lines.append(f"   • MID Activation: {onboarding.get('midActivationStatus', 'Unknown')}")
        products = onboarding.get("productsEnabled", "None")
        lines.append(f"   • Products Enabled: {products}")
        lines.append("")
    
    # Banking Codes
    banking = overview_data.get("bankingCodesStatus", {})
    if banking:
        lines.append("**Banking Codes:**")
        modes = banking.get("modesEnabled", "None")
        lines.append(f"   • Modes: {modes[:100]}..." if len(modes) > 100 else f"   • Modes: {modes}")
        lines.append("")
    
    # Technical Configurations
    tech = overview_data.get("technicalConfigurations", {})
    if tech:
        lines.append("**Technical Configurations:**")
        lines.append(f"   • Refund Flags: {tech.get('refundFlags', 'N/A')}")
        lines.append(f"   • Callback Flags: {tech.get('paymentCallbackFlags', 'N/A')}")
        lines.append("")
    
    # API Limits
    payment_api = overview_data.get("paymentApi", {})
    info_api = overview_data.get("infoApi", {})
    if payment_api or info_api:
        lines.append("**API Rate Limits:**")
        if payment_api:
            lines.append(f"   • Payment API: {payment_api.get('apiRateLimits', 'N/A')}")
            lines.append(f"   • GMV Limits: {payment_api.get('gmvLimits', 'N/A')}")
        if info_api:
            lines.append(f"   • Info API: {info_api.get('apiRateLimits', 'N/A')}")
        lines.append("")
    
    # Callback Events
    callbacks = overview_data.get("callbackEvents", {})
    if callbacks:
        lines.append("**Callback Configuration:**")
        payment_cb = callbacks.get("paymentCallbackEvents", "")
        if payment_cb:
            # Extract just the key info
            if "Events enabled:" in payment_cb:
                events = payment_cb.split("Events enabled:")[-1].strip()
                lines.append(f"   • Payment Events: {events}")
        refund_cb = callbacks.get("refundCallbackEvents", "")
        if refund_cb:
            lines.append(f"   • Refund Callbacks: Configured")
        si_cb = callbacks.get("siUpdateCallbackEvents", "")
        if si_cb:
            lines.append(f"   • SI Update Callbacks: Configured")
    
    return "\n".join(lines)
