"""Chat API routes with WebSocket support."""

import logging
from typing import Dict
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from src.agent import HealthCheckAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# Store agent instances per session (in production, use Redis or similar)
sessions: Dict[str, HealthCheckAgent] = {}


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    response: str
    session_id: str


def get_or_create_agent(session_id: str) -> HealthCheckAgent:
    """Get existing agent or create new one for session."""
    if session_id not in sessions:
        logger.info(f"Creating new agent for session: {session_id}")
        sessions[session_id] = HealthCheckAgent(verbose=False)
    return sessions[session_id]


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """HTTP endpoint for chat interactions.
    
    Args:
        request: Chat request with message and session_id
        
    Returns:
        Agent's response
    """
    logger.info(f"Chat request from session {request.session_id}: {request.message[:50]}...")
    
    try:
        agent = get_or_create_agent(request.session_id)
        response = await agent.ainvoke(request.message)
        
        return ChatResponse(
            response=response,
            session_id=request.session_id,
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time chat.
    
    Args:
        websocket: WebSocket connection
        session_id: Unique session identifier
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: {session_id}")
    
    agent = get_or_create_agent(session_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            logger.info(f"WS message from {session_id}: {data[:50]}...")
            
            # Send "thinking" indicator
            await websocket.send_json({
                "type": "thinking",
                "content": "Processing your request..."
            })
            
            # Process with agent
            try:
                response = await agent.ainvoke(data)
                
                # Send response
                await websocket.send_json({
                    "type": "response",
                    "content": response
                })
            except Exception as e:
                logger.error(f"Agent error: {e}")
                await websocket.send_json({
                    "type": "error",
                    "content": f"Error processing request: {str(e)}"
                })
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
        # Clean up session after disconnect (optional - keep for reconnection)
        # if session_id in sessions:
        #     del sessions[session_id]


@router.post("/clear/{session_id}")
async def clear_session(session_id: str) -> Dict[str, str]:
    """Clear chat history for a session.
    
    Args:
        session_id: Session to clear
        
    Returns:
        Confirmation message
    """
    if session_id in sessions:
        sessions[session_id].clear_history()
        logger.info(f"Cleared history for session: {session_id}")
        return {"status": "success", "message": "Chat history cleared"}
    
    return {"status": "success", "message": "Session not found (already clear)"}


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "healthcheck360-bot"}
