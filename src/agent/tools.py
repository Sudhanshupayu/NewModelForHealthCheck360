"""Tool definitions for the HealthCheck360 agent."""

import logging
from typing import List, Optional

from langchain_core.tools import Tool, StructuredTool
from pydantic import BaseModel, Field

from src.api_client import HealthCheckClient
from src.summarizer import (
    calculate_readiness_score,
    format_readiness_report,
    format_overview_summary,
)
from src.integration_lab import (
    get_flow,
    list_flows,
    analyze_merchant_for_flow,
    generate_curl,
    generate_python_code,
    generate_code,
    SUPPORTED_LANGUAGES,
)
from src.integration_lab.flow_advisor import format_analysis_report
from src.opensearch_client import (
    summarize_logs_for_payu_id,
    build_opensearch_discover_url,
)

logger = logging.getLogger(__name__)


class MerchantIDInput(BaseModel):
    """Input schema for merchant ID based tools."""
    mid: str = Field(description="The Merchant ID (MID) to query")


class FlowAnalysisInput(BaseModel):
    """Input schema for flow analysis tools."""
    mid: str = Field(description="The Merchant ID (MID) to analyze")
    flow_id: str = Field(
        description=(
            "Payment flow identifier. Valid values: payu_hosted_checkout, "
            "payu_hosted_subscription, payu_hosted_tpv, payu_hosted_upi_otm, "
            "payu_hosted_preauth, checkout_plus, payu_hosted_split_payment, "
            "payu_hosted_bank_offers, payu_hosted_cross_border. "
            "Can also use keywords like 'subscription', 'upi_otm', 'cross_border', etc."
        )
    )


class FlowRequirementsInput(BaseModel):
    """Input schema for flow requirements tool."""
    flow_id: str = Field(
        description=(
            "Payment flow identifier or keyword (e.g., 'subscription', 'upi_otm', "
            "'cross_border', 'tpv', 'preauth')"
        )
    )


class CodeGenerationInput(BaseModel):
    """Input schema for code generation tool."""
    mid: str = Field(description="The Merchant ID (MID)")
    flow_id: str = Field(description="Payment flow identifier or keyword")
    language: str = Field(
        default="curl",
        description=(
            "Output language. One of: 'curl', 'python', 'nodejs' (or 'node'/'js'), "
            "'php', 'java'. Defaults to 'curl'."
        ),
    )


class LogSummaryInput(BaseModel):
    """Input schema for OpenSearch log summarization."""
    payu_id: str = Field(
        description=(
            "PayU transaction id (a.k.a. mihpayid). Numeric string, e.g. "
            "'403993715537264905'."
        )
    )
    lookback_days: int = Field(
        default=7,
        description="How many days of logs to search. Defaults to 7.",
    )


def create_product_status_tool(client: HealthCheckClient) -> StructuredTool:
    """Create a tool for fetching product status.
    
    Args:
        client: HealthCheckClient instance
        
    Returns:
        Configured StructuredTool
    """
    def get_product_status(mid: str) -> str:
        """Fetch product status for a merchant and return formatted readiness report."""
        try:
            logger.info(f"Tool: Fetching product status for MID {mid}")
            
            # Fetch data from API
            response = client.get_product_status(mid)
            
            # Calculate readiness scores
            readiness_data = calculate_readiness_score(response)
            
            # Format the report
            report = format_readiness_report(readiness_data)
            
            return report
            
        except Exception as e:
            logger.error(f"Error fetching product status: {e}")
            return f"Error fetching product status for MID {mid}: {str(e)}"
    
    return StructuredTool.from_function(
        func=get_product_status,
        name="get_product_status",
        description=(
            "Fetches the status of all payment products for a merchant. "
            "Returns a readiness report showing which products are fully ready, "
            "partially ready, or not configured. Use this when the user asks about "
            "product status, what's active, or readiness for a merchant."
        ),
        args_schema=MerchantIDInput,
    )


def create_merchant_overview_tool(client: HealthCheckClient) -> StructuredTool:
    """Create a tool for fetching merchant overview.
    
    Args:
        client: HealthCheckClient instance
        
    Returns:
        Configured StructuredTool
    """
    def get_merchant_overview(mid: str) -> str:
        """Fetch comprehensive merchant overview and return formatted summary."""
        try:
            logger.info(f"Tool: Fetching merchant overview for MID {mid}")
            
            # Fetch data from API
            response = client.get_merchant_overview(mid)
            
            # Format the summary
            summary = format_overview_summary(response)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error fetching merchant overview: {e}")
            return f"Error fetching overview for MID {mid}: {str(e)}"
    
    return StructuredTool.from_function(
        func=get_merchant_overview,
        name="get_merchant_overview",
        description=(
            "Fetches comprehensive merchant configuration including merchant info, "
            "KYC status, onboarding status, enabled products, banking codes, "
            "technical configurations, API rate limits, and callback settings. "
            "Use this when the user asks about merchant configuration, overview, "
            "settings, or detailed information."
        ),
        args_schema=MerchantIDInput,
    )


def create_analyze_integration_tool(client: HealthCheckClient) -> StructuredTool:
    """Create a tool for analyzing merchant readiness for a specific flow."""
    def analyze_integration(mid: str, flow_id: str) -> str:
        """Analyze merchant for specific payment flow integration."""
        try:
            logger.info(f"Tool: Analyzing MID {mid} for flow {flow_id}")
            
            flow = get_flow(flow_id)
            if not flow:
                available = ", ".join(f.flow_id for f in list_flows())
                return (
                    f"Unknown flow '{flow_id}'. Available flows:\n"
                    + "\n".join(f"• {f['name']} ({f['flow_id']})" for f in list_flows())
                )
            
            product_status = client.get_product_status(mid)
            overview = client.get_merchant_overview(mid)
            
            analysis = analyze_merchant_for_flow(
                flow_id=flow.flow_id,
                product_status_response=product_status,
                overview_response=overview,
            )
            
            report = format_analysis_report(analysis)
            
            if analysis.corrective_steps:
                report += "\n**📋 Corrective Steps (in order):**\n"
                for i, step in enumerate(analysis.corrective_steps[:10], 1):
                    report += f"   {i}. {step}\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Error analyzing integration: {e}", exc_info=True)
            return f"Error analyzing integration for MID {mid}, flow {flow_id}: {str(e)}"
    
    return StructuredTool.from_function(
        func=analyze_integration,
        name="analyze_integration",
        description=(
            "Analyzes if a merchant is ready to integrate a specific PayU payment flow. "
            "Combines merchant's current configuration with Integration Lab requirements "
            "to identify gaps and produce prioritized corrective steps. "
            "Use when the user asks about integrating a specific flow (subscription, "
            "UPI OTM, TPV, PreAuth, cross-border, split payment, bank offers, checkout plus), "
            "or asks 'can merchant X integrate Y', or wants corrective steps."
        ),
        args_schema=FlowAnalysisInput,
    )


def create_flow_requirements_tool() -> StructuredTool:
    """Create a tool for getting flow requirements."""
    def get_flow_requirements(flow_id: str) -> str:
        """Get requirements for a specific PayU payment flow."""
        try:
            logger.info(f"Tool: Getting requirements for flow {flow_id}")
            
            if flow_id.lower() in ("list", "all", "available"):
                flows = list_flows()
                lines = ["📋 **Available PayU Payment Flows:**\n"]
                for f in flows:
                    lines.append(f"• **{f['name']}** (`{f['flow_id']}`)")
                    lines.append(f"  {f['description']}")
                    lines.append(f"  Type: {f['type']}\n")
                return "\n".join(lines)
            
            flow = get_flow(flow_id)
            if not flow:
                available = ", ".join(f["flow_id"] for f in list_flows())
                return f"Unknown flow '{flow_id}'. Available: {available}"
            
            lines = []
            lines.append(f"📘 **{flow.name}**")
            lines.append(f"   {flow.description}")
            lines.append(f"   Integration Type: {flow.integration_type}")
            lines.append(f"   Endpoint: {flow.api_endpoint}")
            lines.append("")
            
            if flow.required_products:
                lines.append("**🎯 Required Products:**")
                for p in flow.required_products:
                    lines.append(f"   • {p}")
                lines.append("")
            
            if flow.required_banking_codes:
                lines.append("**🏦 Required Banking Codes:**")
                for c in flow.required_banking_codes:
                    lines.append(f"   • {c}")
                lines.append("")
            
            lines.append(f"**📝 Required Fields ({len(flow.required_fields)}):**")
            for f in flow.required_fields[:15]:
                fixed = f" (fixed: {f.fixed_value})" if f.fixed_value else ""
                lines.append(f"   • `{f.name}` - {f.description}{fixed}")
            if len(flow.required_fields) > 15:
                lines.append(f"   ... and {len(flow.required_fields) - 15} more")
            lines.append("")
            
            lines.append("**🔐 Hash Formula:**")
            lines.append(f"   `sha512({flow.hash_formula})`")
            lines.append("")
            
            if flow.corrective_checks:
                lines.append("**✅ Pre-Integration Checks:**")
                for c in flow.corrective_checks:
                    lines.append(f"   • {c}")
                lines.append("")
            
            if flow.notes:
                lines.append("**⚠️ Important Notes:**")
                for n in flow.notes:
                    lines.append(f"   • {n}")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Error getting flow requirements: {e}")
            return f"Error: {str(e)}"
    
    return StructuredTool.from_function(
        func=get_flow_requirements,
        name="get_flow_requirements",
        description=(
            "Gets the detailed requirements for a PayU payment flow including required "
            "products, banking codes, fields, hash formula, and pre-integration checks. "
            "Use when the user asks 'what is required for X flow', 'list all flows', "
            "'what are the requirements for subscription', etc. "
            "Pass 'list' or 'all' to get all available flows."
        ),
        args_schema=FlowRequirementsInput,
    )


_LANG_HUMAN_NAMES = {
    "curl": "cURL",
    "bash": "cURL",
    "python": "Python",
    "nodejs": "Node.js",
    "node": "Node.js",
    "js": "Node.js",
    "javascript": "Node.js",
    "php": "PHP",
    "java": "Java",
}


def create_code_generation_tool(client: HealthCheckClient) -> StructuredTool:
    """Create a tool for generating integration code."""
    def generate_integration_code(mid: str, flow_id: str, language: str = "curl") -> str:
        """Generate integration code for a payment flow in the chosen language."""
        try:
            lang = (language or "curl").lower().strip()
            logger.info(f"Tool: Generating {lang} code for MID {mid}, flow {flow_id}")

            flow = get_flow(flow_id)
            if not flow:
                available = ", ".join(f["flow_id"] for f in list_flows())
                return f"Unknown flow '{flow_id}'. Available flows: {available}"

            # Merchant info for context
            try:
                overview = client.get_merchant_overview(mid)
                merchant_info = overview.get("merchantInfo", {})
                merchant_key = merchant_info.get("key", "YOUR_MERCHANT_KEY")
                merchant_name = merchant_info.get("name", "Unknown")
            except Exception:
                merchant_key = "YOUR_MERCHANT_KEY"
                merchant_name = "Unknown"

            merchant_salt = "YOUR_MERCHANT_SALT"  # never expose real salt

            # If user requested "all", render a multi-language response
            if lang in ("all", "everything", "every"):
                sections = []
                for target in ("curl", "python", "nodejs", "php", "java"):
                    fence, code = generate_code(
                        flow_id=flow.flow_id,
                        language=target,
                        merchant_key=merchant_key,
                        merchant_salt=merchant_salt,
                    )
                    sections.append(
                        f"### {_LANG_HUMAN_NAMES.get(target, target.title())}\n\n"
                        f"```{fence}\n{code}\n```"
                    )
                result = (
                    f"**{flow.name}** — Merchant: {merchant_name} (MID: {mid}), "
                    f"Key: `{merchant_key}`\n\n"
                    + "\n\n".join(sections)
                    + "\n\n**⚠️ Security Note:** Replace `YOUR_MERCHANT_SALT` with "
                    f"your actual Salt v1 from the PayU dashboard before running. "
                    f"Never expose salt client-side."
                )
                return result

            # Single-language render via dispatcher
            fence, code = generate_code(
                flow_id=flow.flow_id,
                language=lang,
                merchant_key=merchant_key,
                merchant_salt=merchant_salt,
            )
            human = _LANG_HUMAN_NAMES.get(lang, lang.title())
            result = (
                f"📝 **{human} code for {flow.name}**\n"
                f"   Merchant: {merchant_name} (MID: {mid})\n"
                f"   Merchant Key: `{merchant_key}`\n\n"
                f"```{fence}\n{code}\n```\n\n"
                f"**⚠️ Security Note:** Replace `YOUR_MERCHANT_SALT` with your "
                f"actual Salt v1 from PayU dashboard. Never expose salt client-side."
            )
            return result

        except Exception as e:
            logger.error(f"Error generating code: {e}", exc_info=True)
            return f"Error generating code: {str(e)}"

    return StructuredTool.from_function(
        func=generate_integration_code,
        name="generate_integration_code",
        description=(
            "Generates ready-to-use integration code in the requested programming "
            "language for a specific PayU payment flow, with merchant's actual key "
            "pre-filled and the correct hash formula. "
            "Supported languages: 'curl', 'python', 'nodejs' (or 'node'/'js'), 'php', "
            "'java'. You can also pass 'all' to receive every language in one reply. "
            "Use when the user asks for 'sample code', 'curl command', 'python code', "
            "'node code', 'PHP example', 'java sample', 'generate code', 'how to integrate X', etc."
        ),
        args_schema=CodeGenerationInput,
    )


def create_log_summary_tool(llm=None) -> StructuredTool:
    """Create a tool that fetches + analyses logs into an Incident Report.

    Pass ``llm`` to have section 6 (Recommended next steps) narrated by the
    LLM instead of the deterministic fallback.
    """
    def summarize_transaction_logs(payu_id: str, lookback_days: int = 7) -> str:
        try:
            logger.info(
                f"Tool: Building Incident Report for payuId={payu_id} "
                f"(lookback={lookback_days}d)"
            )
            result = summarize_logs_for_payu_id(
                payu_id=payu_id, lookback_days=lookback_days, llm=llm,
            )

            markdown = result.get("markdown") or ""
            if not markdown:
                return (
                    f"No logs found for payuId `{payu_id}` in the last "
                    f"{lookback_days} days across `corepayment-php-app-logs-*`.\n"
                    f"Open manually: {result.get('opensearch_url','(VPC endpoint unreachable)')}"
                )

            # Hand the already-rendered report to the agent with a very
            # strict instruction: print it verbatim. No re-summarising.
            preamble = (
                "_AGENT_INSTRUCTION: The block below is a fully-rendered "
                "Incident Report (7 sections, including verdict, facts, "
                "per-processId timeline, findings, infra issues, next steps "
                "and the Jira evidence pack). PRINT IT VERBATIM in your "
                "reply to the user — do NOT paraphrase, condense, or drop "
                "sections. You may add a 1-line intro above it if useful, "
                "but the report itself must be passed through as-is._\n\n"
                "---\n\n"
            )
            return preamble + markdown

        except Exception as e:
            logger.error(f"Log summarization failed: {e}", exc_info=True)
            return (
                f"Error fetching logs for payuId `{payu_id}`: {e}\n\n"
                "If you are outside the VPC, the OpenSearch endpoint may be unreachable. "
                "Run this bot from within the UAT VPC or via VPN."
            )

    return StructuredTool.from_function(
        func=summarize_transaction_logs,
        name="summarize_transaction_logs",
        description=(
            "Fetches logs (index corepayment-php-app-logs-*) for a payuId, "
            "exhaustively walks every linked processId, and builds a full "
            "Incident Report with 7 sections: (1) Verdict "
            "(SUCCESS/DEGRADED/FAILURE/PENDING/UNKNOWN), (2) Transaction "
            "facts (merchant, amount, flow, PG, bank, final status, error "
            "code, bank_ref, merchant webhook outcome), (3) Per-processId "
            "timeline of key events, (4) Findings — every exception / error "
            "/ warning with a cause + fix, (5) Infra issues (gRPC / HTTP / "
            "DB), (6) Recommended next steps, (7) Evidence pack with "
            "OpenSearch Discover links and a Jira-ready text block. The "
            "report MUST be printed verbatim to the user. "
            "Use when the user provides a payuId and asks for 'what happened', "
            "'why did this fail', 'summarize logs', 'analyze transaction', etc."
        ),
        args_schema=LogSummaryInput,
    )


def get_tools(
    client: HealthCheckClient = None, llm=None
) -> List[StructuredTool]:
    """Get all available tools for the agent.

    Args:
        client: Optional HealthCheckClient instance.
        llm: Optional LangChain chat model used by the log analyser to
             narrate the "Recommended next steps" section of the Incident
             Report. If omitted, a deterministic fallback is used.

    Returns:
        List of configured tools
    """
    if client is None:
        client = HealthCheckClient()

    return [
        create_product_status_tool(client),
        create_merchant_overview_tool(client),
        create_analyze_integration_tool(client),
        create_flow_requirements_tool(),
        create_code_generation_tool(client),
        create_log_summary_tool(llm=llm),
    ]
