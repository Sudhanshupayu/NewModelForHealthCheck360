# HealthCheck360 Bot

AI-powered assistant for checking merchant health status and configuration on PayU's payment platform.

## Features

- **Product Status Check**: View which payment products (Credit Card, UPI, Netbanking, etc.) are active for a merchant
- **Readiness Score**: Get an overall health percentage based on product configuration
- **Configuration Overview**: View merchant details, KYC status, API limits, and callback settings
- **Chat Interface**: Modern web UI with real-time WebSocket communication
- **Local LLM**: Runs entirely on your machine using Ollama

## Architecture

```
User Input → [Pattern Interpretation] → [API Call] → [JSON Summarization] → Response

Components:
├── LangChain Agent (Tool Calling)
├── HealthCheck360 API Client
├── Readiness Score Calculator
├── FastAPI + WebSocket Server
└── Modern Chat UI
```

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/download) installed and running

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Setup Ollama

```bash
# Install recommended model
chmod +x scripts/setup_ollama.sh
./scripts/setup_ollama.sh

# Or manually:
ollama pull llama3.1:8b
```

### 3. Configure Environment

```bash
# Copy example config
cp .env.example .env

# Edit if needed (defaults work for most setups)
```

### 4. Run the Bot

```bash
# Start web server
python main.py

# Or run in CLI mode for testing
python main.py --cli

# Test API connectivity first
python main.py --test-api
```

### 5. Open the Chat UI

Navigate to [http://localhost:8000](http://localhost:8000)

## Usage Examples

### Chat Queries

| Query | What it does |
|-------|--------------|
| "What products are active for merchant 2?" | Shows product status with readiness scores |
| "Show me the configuration for MID 2" | Shows full merchant configuration overview |
| "Give me a complete health check for merchant 5" | Runs both checks and provides comprehensive report |
| "What's the readiness score for MID 123?" | Calculates and displays readiness percentage |

### Sample Response

```
📊 Readiness Report for Merchant ID: 2
   Merchant: IBIBO GROUP PRIVATE LIMITED

Overall Readiness Score: 78%

✅ Fully Ready (12 products - 100%):
   Credit Card, Debit Card, UPI, Netbanking, EMI, BNPL,
   Cards SI, Enach, Tokenisation, UPI Autopay

⚠️ Partially Ready (4 products - 66%):
   • Merchant Hosted Checkout - modes not configured
   • PayU Hosted Checkout - modes not configured
   • S2S - modes not configured
   • Split Settlements - modes not configured

❌ Not Configured (2 products - 0%):
   Mealcards, Offer engine
```

## Project Structure

```
NewModelForHealthCheck360/
├── main.py                      # Entry point
├── requirements.txt             # Dependencies
├── config/
│   ├── settings.py              # Application configuration
│   └── cookies.py               # API authentication
├── src/
│   ├── models/
│   │   └── local_llm.py         # LLM provider (Ollama/HuggingFace)
│   ├── agent/
│   │   ├── agent.py             # LangChain agent
│   │   ├── tools.py             # API tools
│   │   └── prompts.py           # System prompts
│   ├── api_client/
│   │   └── healthcheck_client.py # HTTP client
│   └── summarizer/
│       └── readiness_scorer.py  # Score calculation
├── app/
│   ├── main.py                  # FastAPI app
│   ├── routes/
│   │   └── chat.py              # WebSocket chat
│   └── static/                  # Frontend UI
└── tests/                       # Test suite
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | LLM provider (`ollama` or `huggingface`) |
| `OLLAMA_MODEL` | `llama3.1:8b` | Ollama model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `API_BASE_URL` | `https://healthcheck360.payu.in` | HealthCheck360 API |
| `PORT` | `8000` | Web server port |

### Updating Cookies

The API uses cookie-based authentication. To update cookies:

1. Log into HealthCheck360 in your browser
2. Open DevTools → Network → Copy any request as cURL
3. Extract the cookie string
4. Set in `.env`: `HEALTHCHECK_COOKIES=your_cookie_string`

Or update `config/cookies.py` directly.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Chat UI |
| `/api/chat` | POST | HTTP chat endpoint |
| `/api/ws/{session_id}` | WebSocket | Real-time chat |
| `/api/clear/{session_id}` | POST | Clear chat history |
| `/api/health` | GET | Health check |
| `/docs` | GET | API documentation |

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Using HuggingFace Instead of Ollama

1. Uncomment HuggingFace dependencies in `requirements.txt`
2. Install: `pip install transformers torch accelerate`
3. Set in `.env`:
   ```
   LLM_PROVIDER=huggingface
   HUGGINGFACE_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
   ```

## Readiness Score Calculation

| Condition | Score |
|-----------|-------|
| flags=Yes, modes=Yes, status=Yes | 100% (Fully Ready) |
| Two of three = Yes | 66% (Partially Ready) |
| One of three = Yes | 33% (Minimally Ready) |
| All = No | 0% (Not Configured) |

**Overall Score** = Average of all product scores

## Troubleshooting

### "Connection refused" to Ollama

```bash
# Make sure Ollama is running
ollama serve
```

### Cookies expired

Update the cookies in `config/cookies.py` or set `HEALTHCHECK_COOKIES` env var.

### Model not responding

Try a smaller model:
```bash
ollama pull mistral:7b
# Update OLLAMA_MODEL in .env
```

## License

Internal use only - PayU.
