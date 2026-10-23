
"""
MANUAL LIVE PROBE - NOT AN AUTOMATED TEST.

This script performs a real OAuth call against PayPal Sandbox using the
credentials in .env. It is deliberately NOT named *_test.py so that pytest can
never collect and execute it. Never run it from CI or from an automated
workflow; the automated suite talks to PayPal only through httpx.MockTransport.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

base_url = os.getenv(
    "PAYPAL_BASE_URL",
    "https://api-m.sandbox.paypal.com"
)
client_id = os.getenv("PAYPAL_CLIENT_ID")
client_secret = os.getenv("PAYPAL_CLIENT_SECRET")

if not client_id or not client_secret:
    raise RuntimeError("Missing PayPal sandbox credentials")

token_response = requests.post(
    f"{base_url}/v1/oauth2/token",
    auth=(client_id, client_secret),
    headers={"Accept": "application/json"},
    data={"grant_type": "client_credentials"},
    timeout=20,
)
token_response.raise_for_status()

access_token = token_response.json()["access_token"]

response = requests.get(
    f"{base_url}/v1/identity/oauth2/userinfo",
    headers={"Authorization": f"Bearer {access_token}"},
    timeout=20,
)

print("HTTP status:", response.status_code)

if response.status_code == 200:
    print("API request succeeded.")
    print("Response received; sensitive fields omitted.")
else:
    print("This endpoint may require a different token scope.")
    print(response.text[:500])

