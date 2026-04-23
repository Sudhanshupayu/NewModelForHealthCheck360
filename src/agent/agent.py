"""HealthCheck360 LangChain Agent implementation."""

import logging
from typing import Optional, List, Dict, Any

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.language_models.base import BaseLanguageModel
from langgraph.prebuilt import create_react_agent

from src.models import get_llm
from src.api_client import HealthCheckClient
from src.agent.tools import get_tools
from src.agent.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Tools whose output must reach the user verbatim — small local LLMs
# (Llama 3.1 8B, etc.) tend to paraphrase long structured tool outputs and
# drop critical sections like raw logs, Jira blocks and Discover links.
# For these tools we bypass the LLM's final summarisation step entirely.
_VERBATIM_TOOLS = {
    "summarize_transaction_logs",
}

_TOOL_PREAMBLE_MARKER = "\n---\n\n"


def _strip_agent_preamble(tool_output: str) -> str:
    """Remove the ``_AGENT_INSTRUCTION:`` block we prepend to tool output.

    The preamble is intended for the LLM, not the end user. When we bypass
    the LLM and return the tool output directly we want the clean report.
    """
    if not tool_output:
        return tool_output
    text = tool_output.lstrip()
    if text.startswith("_AGENT_INSTRUCTION"):
        idx = text.find(_TOOL_PREAMBLE_MARKER)
        if idx >= 0:
            return text[idx + len(_TOOL_PREAMBLE_MARKER):].lstrip()
    return tool_output


def _extract_verbatim_tool_output(messages: List[Any]) -> Optional[str]:
    """Return the most recent verbatim-tool output from an agent run.

    Walks the messages in reverse order and returns the content of the last
    ``ToolMessage`` produced by a tool listed in :data:`_VERBATIM_TOOLS`.
    The ``_AGENT_INSTRUCTION`` preamble is stripped before returning.
    """
    for msg in reversed(messages or []):
        if isinstance(msg, ToolMessage) and getattr(msg, "name", "") in _VERBATIM_TOOLS:
            content = getattr(msg, "content", "") or ""
            if isinstance(content, list):  # some providers wrap content
                content = "".join(
                    (p.get("text", "") if isinstance(p, dict) else str(p))
                    for p in content
                )
            return _strip_agent_preamble(str(content))
    return None


class HealthCheckAgent:
    """Agent for handling HealthCheck360 queries."""
    
    def __init__(
        self,
        llm: Optional[BaseLanguageModel] = None,
        client: Optional[HealthCheckClient] = None,
        verbose: bool = True,
    ):
        """Initialize the agent.
        
        Args:
            llm: Language model instance (defaults to configured LLM)
            client: API client instance
            verbose: Whether to show agent reasoning
        """
        self.llm = llm or get_llm()
        self.client = client or HealthCheckClient()
        self.tools = get_tools(self.client, llm=self.llm)
        self.verbose = verbose
        
        # Create the agent using LangGraph
        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=SYSTEM_PROMPT,
        )
        
        # Conversation history
        self.chat_history: List[Dict[str, Any]] = []
    
    def invoke(self, user_input: str) -> str:
        """Process a user query and return the response.
        
        Args:
            user_input: User's message
            
        Returns:
            Agent's response
        """
        logger.info(f"Processing query: {user_input}")
        
        try:
            # Build messages with history
            messages = []
            for msg in self.chat_history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                else:
                    messages.append(AIMessage(content=msg["content"]))
            
            messages.append(HumanMessage(content=user_input))
            
            # Invoke the agent
            result = self.agent.invoke({"messages": messages})
            
            response = self._compose_final_response(result)
            
            # Update chat history
            self.chat_history.append({"role": "user", "content": user_input})
            self.chat_history.append({"role": "assistant", "content": response})
            
            # Keep history manageable (last 10 exchanges)
            if len(self.chat_history) > 20:
                self.chat_history = self.chat_history[-20:]
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return f"I encountered an error: {str(e)}. Please try again."

    def _compose_final_response(self, result: Dict[str, Any]) -> str:
        """Turn an agent-run result into the final string sent to the user.

        If the agent invoked a tool whose output must reach the user
        verbatim (see :data:`_VERBATIM_TOOLS`), we return that tool's
        output directly — the LLM's paraphrased summary is discarded.
        This is important for small local models (Llama 3.1 8B, etc.)
        that drop long structured sections when asked to pass content
        through. Otherwise we return the final ``AIMessage`` content.
        """
        messages = result.get("messages", []) if isinstance(result, dict) else []

        verbatim = _extract_verbatim_tool_output(messages)
        if verbatim:
            logger.info(
                "Returning verbatim tool output (len=%d) — bypassing LLM paraphrase.",
                len(verbatim),
            )
            # Try to salvage a one-line LLM intro if it exists — this adds a
            # natural greeting without risking dropped sections.
            intro = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    first_line = str(msg.content).strip().splitlines()[0].strip()
                    # Only use it if it looks like a short intro, not a full
                    # paraphrased report.
                    if 0 < len(first_line) <= 220 and first_line.count("\n") == 0:
                        intro = first_line
                    break
            if intro and not verbatim.lstrip().startswith(intro[:40]):
                return f"{intro}\n\n{verbatim}"
            return verbatim

        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                return str(msg.content)

        return "I couldn't process that request."

    async def ainvoke(self, user_input: str) -> str:
        """Async version of invoke.
        
        Args:
            user_input: User's message
            
        Returns:
            Agent's response
        """
        logger.info(f"Processing query (async): {user_input}")
        
        try:
            # Build messages with history
            messages = []
            for msg in self.chat_history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                else:
                    messages.append(AIMessage(content=msg["content"]))
            
            messages.append(HumanMessage(content=user_input))
            
            # Invoke the agent asynchronously
            result = await self.agent.ainvoke({"messages": messages})
            
            response = self._compose_final_response(result)
            
            # Update chat history
            self.chat_history.append({"role": "user", "content": user_input})
            self.chat_history.append({"role": "assistant", "content": response})
            
            # Keep history manageable
            if len(self.chat_history) > 20:
                self.chat_history = self.chat_history[-20:]
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return f"I encountered an error: {str(e)}. Please try again."
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self.chat_history = []
        logger.info("Chat history cleared")


def create_agent(
    llm: Optional[BaseLanguageModel] = None,
    verbose: bool = True
) -> HealthCheckAgent:
    """Factory function to create a HealthCheckAgent.
    
    Args:
        llm: Optional LLM instance
        verbose: Whether to show agent reasoning
        
    Returns:
        Configured HealthCheckAgent instance
    """
    return HealthCheckAgent(llm=llm, verbose=verbose)
