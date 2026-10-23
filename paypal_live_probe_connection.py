
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

BASE_URL = os.getenv(
    "PAYPAL_BASE_URL",
    "https://api-m.sandbox.paypal.com"
)
CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError(
        "Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env"
    )

response = requests.post(
    f"{BASE_URL}/v1/oauth2/token",
    auth=(CLIENT_ID, CLIENT_SECRET),
    headers={"Accept": "application/json"},
    data={"grant_type": "client_credentials"},
    timeout=20,
)

if not response.ok:
    print("PayPal authentication failed:", response.status_code)
    print(response.text[:500])
    raise SystemExit(1)

token_data = response.json()

if not token_data.get("access_token"):
    raise RuntimeError("PayPal returned no access token")

print("SUCCESS: PayPal Sandbox authentication works!")
print("Token type:", token_data.get("token_type"))
print("Expires in:", token_data.get("expires_in"), "seconds")
print("Access token intentionally hidden.")
