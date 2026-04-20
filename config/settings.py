"""Application settings and configuration."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    """Application configuration settings."""
    
    # API Configuration
    api_base_url: str = "https://healthcheck360.payu.in"
    api_timeout: int = 30
    
    # Model Configuration
    llm_provider: str = "ollama"  # "ollama" or "huggingface"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    huggingface_model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    
    # Logging
    log_level: str = "INFO"
    
    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        return cls(
            api_base_url=os.getenv("API_BASE_URL", cls.api_base_url),
            api_timeout=int(os.getenv("API_TIMEOUT", cls.api_timeout)),
            llm_provider=os.getenv("LLM_PROVIDER", cls.llm_provider),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", cls.ollama_base_url),
            ollama_model=os.getenv("OLLAMA_MODEL", cls.ollama_model),
            huggingface_model=os.getenv("HUGGINGFACE_MODEL", cls.huggingface_model),
            host=os.getenv("HOST", cls.host),
            port=int(os.getenv("PORT", cls.port)),
            debug=os.getenv("DEBUG", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", cls.log_level),
        )


settings = Settings.from_env()
