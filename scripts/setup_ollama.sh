#!/bin/bash
# Setup script for Ollama with recommended models

set -e

echo "=========================================="
echo "  HealthCheck360 Bot - Ollama Setup"
echo "=========================================="

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "Ollama is not installed."
    echo ""
    echo "To install Ollama:"
    echo "  macOS:  brew install ollama"
    echo "  Linux:  curl -fsSL https://ollama.com/install.sh | sh"
    echo "  Or visit: https://ollama.com/download"
    echo ""
    exit 1
fi

echo "✓ Ollama is installed"

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo ""
    echo "Starting Ollama service..."
    ollama serve &
    sleep 3
fi

echo "✓ Ollama service is running"
echo ""

# Model selection
echo "Available models for HealthCheck360 Bot:"
echo "  1. llama3.1:8b    (Recommended - ~4.7GB)"
echo "  2. mistral:7b     (Lightweight - ~4.1GB)"
echo "  3. qwen2.5:7b     (Good function calling - ~4.4GB)"
echo ""

read -p "Enter model number to install [1]: " choice
choice=${choice:-1}

case $choice in
    1)
        MODEL="llama3.1:8b"
        ;;
    2)
        MODEL="mistral:7b"
        ;;
    3)
        MODEL="qwen2.5:7b"
        ;;
    *)
        MODEL="llama3.1:8b"
        ;;
esac

echo ""
echo "Pulling $MODEL..."
ollama pull $MODEL

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Model installed: $MODEL"
echo ""
echo "To use this model, set in your .env file:"
echo "  OLLAMA_MODEL=$MODEL"
echo ""
echo "Or run the bot with default settings:"
echo "  python main.py"
echo ""
