"""HealthCheck360 LangChain Agent implementation."""

import logging
from typing import Optional, List, Dict, Any

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.language_models.base import BaseLanguageModel
from langgraph.prebuilt import create_react_agent

from src.models import get_llm
from src.api_client import HealthCheckClient
from src.agent.tools import get_tools
from src.agent.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


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
        self.tools = get_tools(self.client)
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
            
            # Extract the response
            response = ""
            if "messages" in result:
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage) and msg.content:
                        response = msg.content
                        break
            
            if not response:
                response = "I couldn't process that request."
            
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
            
            # Extract the response
            response = ""
            if "messages" in result:
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage) and msg.content:
                        response = msg.content
                        break
            
            if not response:
                response = "I couldn't process that request."
            
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
