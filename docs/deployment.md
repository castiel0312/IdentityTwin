# Local container deployment

The repository Compose stack is for local development and synthetic demos, not
production. It starts PostgreSQL, the API, the restricted honey database
connection, the API gateway and a built static console. The bundled database
credentials and development personas are intentionally local-only. Payment
execution defaults to the mock provider; the application only supports the
PayPal Sandbox adapter.

## Run the complete local stack

From the repository root in PowerShell:

```powershell
docker compose --env-file .env.example up --build -d
docker compose ps
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health
```

Open the console at <http://127.0.0.1:3000>. Sign in using a development
persona. API requests from the console are reverse-proxied by the static
frontend container to the API gateway; PostgreSQL is bound to the local
loopback interface only.

To load the deterministic synthetic demo records, run:

```powershell
docker compose exec api python /workspace/scripts/seed_demo.py
```

The seed script creates demo sessions, honey workspaces and canary metadata.
It does not execute real payments. The Honey Workspace remains empty until a
decoy interaction or this explicit seed operation provisions a synthetic
workspace.

Stop the stack with:

```powershell
docker compose down
```

The PostgreSQL volume persists across stops. To preserve data, do not remove
that volume.

## Production deployment status

The Compose file is a development/demo deployment and is not production-ready.
Production mode requires a real OIDC issuer, PostgreSQL, `ALLOW_DEV_AUTH=false`,
high-entropy `CANARY_HMAC_SECRET` and `EVIDENCE_HMAC_KEY` values, and explicitly
approved payment-provider configuration. When PayPal Sandbox is selected,
non-empty client credentials and `PAYPAL_WEBHOOK_ID` are required. The
application allows PayPal Sandbox only; it is not configured for real PayPal
production payouts.
Do not expose the bundled development persona tokens or sample database
credentials to an Internet-facing deployment.

Validate settings with deployment-owned secrets in the target environment.
Never put production credentials in a committed Compose file or frontend build
variables.
