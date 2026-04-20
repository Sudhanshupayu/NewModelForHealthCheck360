"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config.settings import settings
from src.utils import setup_logging
from app.routes import chat_router

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting HealthCheck360 Bot...")
    logger.info(f"LLM Provider: {settings.llm_provider}")
    logger.info(f"API Base URL: {settings.api_base_url}")
    
    yield
    
    logger.info("Shutting down HealthCheck360 Bot...")


# Create FastAPI app
app = FastAPI(
    title="HealthCheck360 Bot",
    description="AI-powered assistant for checking merchant health status on PayU platform",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(chat_router)

# Serve static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    """Serve the main chat interface."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "HealthCheck360 Bot API", "docs": "/docs"}


@app.get("/info")
async def info():
    """Get application information."""
    return {
        "name": "HealthCheck360 Bot",
        "version": "1.0.0",
        "llm_provider": settings.llm_provider,
        "llm_model": settings.ollama_model if settings.llm_provider == "ollama" else settings.huggingface_model,
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
