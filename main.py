#!/usr/bin/env python3
"""
HealthCheck360 Bot - Entry Point

Usage:
    python main.py                  # Start web server
    python main.py --cli            # Run in CLI mode
    python main.py --test-api       # Test API connectivity
"""

import argparse
import sys


def run_server():
    """Start the FastAPI web server."""
    import uvicorn
    from config.settings import settings
    
    print(f"""
    ╔═══════════════════════════════════════════════════════╗
    ║           HealthCheck360 Bot - Starting               ║
    ╠═══════════════════════════════════════════════════════╣
    ║  Web UI:     http://{settings.host}:{settings.port}                    ║
    ║  API Docs:   http://{settings.host}:{settings.port}/docs               ║
    ║  LLM:        {settings.llm_provider} ({settings.ollama_model if settings.llm_provider == 'ollama' else settings.huggingface_model})
    ╚═══════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


def run_cli():
    """Run the bot in CLI mode for testing."""
    from src.agent import HealthCheckAgent
    from src.utils import setup_logging
    
    setup_logging()
    
    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║           HealthCheck360 Bot - CLI Mode               ║
    ╠═══════════════════════════════════════════════════════╣
    ║  Type your questions and press Enter.                 ║
    ║  Type 'quit' or 'exit' to stop.                       ║
    ║  Type 'clear' to reset conversation.                  ║
    ╚═══════════════════════════════════════════════════════╝
    """)
    
    print("Initializing agent (this may take a moment)...")
    agent = HealthCheckAgent(verbose=True)
    print("Agent ready!\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ('quit', 'exit'):
                print("Goodbye!")
                break
            
            if user_input.lower() == 'clear':
                agent.clear_history()
                print("Conversation cleared.\n")
                continue
            
            print("\nAssistant: ", end="", flush=True)
            response = agent.invoke(user_input)
            print(response)
            print()
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


def test_api():
    """Test API connectivity."""
    from src.api_client import HealthCheckClient
    from src.summarizer import calculate_readiness_score, format_readiness_report
    
    print("Testing HealthCheck360 API connectivity...\n")
    
    client = HealthCheckClient()
    
    try:
        # Test product status API
        print("1. Testing /api/getProductStatus...")
        product_status = client.get_product_status("2")
        print(f"   ✓ Success! Found {len(product_status.get('product_status', {}))} products")
        
        # Test readiness calculation
        readiness = calculate_readiness_score(product_status)
        print(f"   ✓ Overall readiness score: {readiness['overall_score']}%")
        
        # Test overview API
        print("\n2. Testing /api/overview...")
        overview = client.get_merchant_overview("2")
        merchant_name = overview.get('merchantInfo', {}).get('name', 'Unknown')
        print(f"   ✓ Success! Merchant: {merchant_name}")
        
        print("\n" + "="*50)
        print("All API tests passed!")
        print("="*50)
        
        # Show sample report
        print("\nSample Readiness Report:")
        print("-"*50)
        print(format_readiness_report(readiness, merchant_name))
        
    except Exception as e:
        print(f"   ✗ Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="HealthCheck360 Bot - AI-powered merchant health checker"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode instead of web server"
    )
    parser.add_argument(
        "--test-api",
        action="store_true",
        help="Test API connectivity"
    )
    
    args = parser.parse_args()
    
    if args.test_api:
        test_api()
    elif args.cli:
        run_cli()
    else:
        run_server()


if __name__ == "__main__":
    main()
