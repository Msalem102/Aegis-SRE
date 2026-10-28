"""
Meta Model API Diagnostic & Verification Tool.
Tests live connectivity to Meta Model API (or Baseten / Fireworks partner endpoints),
benchmarks roundtrip network latency, and verifies structured JSON reasoning capability.
"""

import sys
import os
import json
import time
import httpx
from dotenv import load_dotenv

# Ensure UTF-8 console output
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()


def test_meta_model_api():
    print("=" * 76)
    print("🔍 AEGIS SRE: Meta Model API Live Connectivity Test")
    print("=" * 76)

    api_key = os.getenv("META_API_KEY") or os.getenv("BASETEN_API_KEY")
    base_url = os.getenv("META_MODEL_API_URL", "https://api.meta.ai/v1")
    model_name = os.getenv("META_MODEL_NAME", "muse-spark")

    print(f"\n[Configuration]")
    print(f" -> Base URL:   {base_url}")
    print(f" -> Model Name: {model_name}")
    masked_key = f"{api_key[:6]}...{api_key[-4:]}" if api_key and len(api_key) > 10 else ("Configured" if api_key else "NOT SET")
    print(f" -> API Key:    {masked_key}")

    if not api_key or api_key == "your_meta_api_key_here":
        print("\n⚠️  No live Meta Model API key detected.")
        print("To connect live Meta models:")
        print("1. Open the '.env' file in your workspace root.")
        print("2. Set META_API_KEY to your Meta Model API key (from your $150 credit grant)")
        print("   or your Baseten API key.")
        print("3. Re-run this script: .\\.venv\\Scripts\\python.exe verify_meta_api.py")
        print("\n(Note: The Aegis SRE agent will continue using its local AST reasoning engine until a key is added).")
        print("=" * 76)
        return False

    print("\n[Sending Probe Request to Meta Model API...]")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    test_payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Aegis SRE diagnostic core. Respond strictly with JSON: "
                    '{"status": "ONLINE", "model_echo": "<model_name>", "capability": "SRE_REASONING_READY"}'
                )
            },
            {
                "role": "user",
                "content": "Verify system connectivity and reasoning latency."
            }
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    start_time = time.perf_counter()
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{base_url}/chat/completions", headers=headers, json=test_payload)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if resp.status_code == 200:
                data = resp.json()
                raw_content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})

                # Validate JSON parseability
                parsed = json.loads(raw_content)

                print("\n✅ Meta Model API Connection SUCCESSFUL!")
                print(f" -> HTTP Status:         200 OK")
                print(f" -> Roundtrip Latency:   {elapsed_ms:.2f}ms")
                print(f" -> Model Identity:      {data.get('model', model_name)}")
                print(f" -> Prompt Tokens:       {usage.get('prompt_tokens', 'N/A')}")
                print(f" -> Completion Tokens:   {usage.get('completion_tokens', 'N/A')}")
                print(f" -> Model Response JSON: {parsed}")
                print("=" * 76)
                return True
            else:
                print(f"\n❌ API Server Returned Error HTTP {resp.status_code}:")
                print(f" -> Response Body: {resp.text}")
                print("=" * 76)
                return False

    except httpx.ConnectError as e:
        print(f"\n❌ Network Connection Error: Could not connect to {base_url}.")
        print(f"   Details: {e}")
        print("=" * 76)
        return False
    except Exception as e:
        print(f"\n❌ Request Failed: {e}")
        print("=" * 76)
        return False


if __name__ == "__main__":
    test_meta_model_api()
