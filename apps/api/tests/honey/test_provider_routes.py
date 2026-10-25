import uuid


def test_provider_shaped_honey_routes_use_the_session_workspace(client, merchant_auth_headers):
    session_id = str(uuid.uuid4())
    identity_id = str(uuid.uuid4())
    scope = f"session_id={session_id}&identity_id={identity_id}"

    profile = client.get(
        f"/v1/merchant/merchant-info?{scope}",
        headers=merchant_auth_headers,
    )
    invoices = client.get(
        f"/v2/invoicing/invoices?{scope}",
        headers=merchant_auth_headers,
    )
    transactions = client.get(
        f"/v1/reporting/transactions?{scope}",
        headers=merchant_auth_headers,
    )
    payouts = client.post(
        f"/v1/payments/payouts?{scope}",
        json={"amount": 125, "recipient_email": "provider-route@example.in"},
        headers={**merchant_auth_headers, "PayPal-Request-Id": str(uuid.uuid4())},
    )
    payout_list = client.get(
        f"/v1/payments/payouts?{scope}",
        headers=merchant_auth_headers,
    )

    assert profile.status_code == 200
    assert "merchant" in profile.json()
    assert invoices.status_code == 200
    assert invoices.json()["total"] > 0
    assert transactions.status_code == 200
    assert transactions.json()["total"] > 0
    assert payouts.status_code == 200
    assert payout_list.status_code == 200
    assert payout_list.json()["total"] == 1
