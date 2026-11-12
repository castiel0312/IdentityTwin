# IdentityTwin — Demo & Judge Readiness Guide

IdentityTwin is a **Behavioral Identity & Trust Gateway** for merchant payment operations. It continuously assesses behavioral and transactional risk and routes sensitive operations through a centralized Trust Gateway with four enforced trust levels: NORMAL, RESTRICTED, DECOY, and ISOLATED.

This guide enables hackathon judges to clone, configure, launch, and interact with the actual IdentityTwin application locally.

---

## 1. Project Overview

IdentityTwin addresses account takeover, credential compromise, session hijacking, and unauthorized money movement in digital payment environments.

Unlike conventional authentication systems that verify identity primarily at login, IdentityTwin continuously evaluates behavioral and transactional signals throughout a session.

### Key Modules

- **FastAPI Backend:** REST APIs, OpenAPI 3.1 documentation, structured logging, and consistent error handling.
- **Centralized Trust Gateway:** Enforces four trust levels and controls protected payment operations.
- **Behavioral Risk Engine:** Evaluates eight deterministic risk signals.
- **Payment Provider Adapters:** Mock provider, PayPal Sandbox adapter, and Decoy Honey adapter.
- **PayPal Webhook Integration:** Receives and verifies payment-related notifications.
- **Incident Management:** Incident review, investigation, and role-based access control.
- **Honey Workspace:** Synthetic decoy environments with canary detection.
- **Evidence Chain:** Hash-chained, append-only security records.
- **Agentic Commerce:** Server-side authorization and controlled agent-initiated payout workflows.
- **Reconciliation Worker:** Background payout-state reconciliation.
- **Durable Domain Events:** Tenant-scoped Server-Sent Events with cursor replay.
- **React Operations Console:** 17 application routes.
- **AI Investigator:** Groq-powered, read-only incident investigation and contextual narrative generation.

---

## 2. System Requirements

The recommended judge workflow uses Docker Compose.

**Required:**

- Docker Desktop or Docker Engine.
- Docker Compose v2.
- Git.
- At least 4 GB RAM available to Docker.
- Ports 8001 and 3001 available on the host.

**Optional (local development without Docker):**

- Python 3.11+
- Node.js 22+

Judges do not need to install Python or Node.js separately when using the Docker workflow.

---

## 3. Installation Prerequisites

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and ensure Docker Engine is running before proceeding.

Verify installation:

```bash
docker --version
docker compose version
git --version
```

---

## 4. Repository Cloning

Clone the public repository:

```bash
git clone https://github.com/castiel0312/IdentityTwin.git
cd IdentityTwin
```

All application source code, Docker configuration, database migrations, documentation, and demo scripts are included in the repository.

---

## 5. Environment Setup

Create the local environment configuration:

```bash
cp .env.example .env
```

Review `.env` before starting the application.

### Configuration Variables

| Variable                    | Purpose                                |
| --------------------------- | -------------------------------------- |
| `ENVIRONMENT`               | Application environment                |
| `ALLOW_DEV_AUTH`            | Enables development authentication     |
| `DEV_AUTH_TOKEN`            | Development bearer token               |
| `PAYMENT_PROVIDER`          | Mock or PayPal Sandbox provider        |
| `PAYPAL_CLIENT_ID`          | PayPal Sandbox application client ID   |
| `PAYPAL_CLIENT_SECRET`      | PayPal Sandbox application secret      |
| `PAYPAL_WEBHOOK_ID`         | PayPal webhook identifier              |
| `AI_LLM_ENABLED`            | Enables Groq AI investigation          |
| `AI_LLM_BASE_URL`           | Groq OpenAI-compatible API endpoint    |
| `AI_LLM_EGRESS_HOST`        | Permitted outbound LLM host            |
| `AI_LLM_API_KEY`            | Groq API key                           |
| `AI_LLM_MODEL`              | Configured Groq model                  |
| `IDENTITYTWIN_API_PORT`     | Host API port                          |
| `IDENTITYTWIN_CONSOLE_PORT` | Host console port                      |

### Groq AI Configuration

To enable live AI-powered investigations, configure:

```dotenv
AI_LLM_ENABLED=true
AI_LLM_BASE_URL=https://api.groq.com/openai/v1
AI_LLM_EGRESS_HOST=api.groq.com
AI_LLM_API_KEY=<your_groq_api_key>
AI_LLM_MODEL=openai/gpt-oss-20b
```

Use a model currently available to your Groq account.

The application uses Groq's OpenAI-compatible inference API to generate structured investigation narratives. If AI is disabled or unavailable, the application uses its deterministic investigation fallback.

### PayPal Sandbox Configuration

To exercise PayPal Sandbox operations, configure:

```dotenv
PAYMENT_PROVIDER=paypal_sandbox
PAYPAL_CLIENT_ID=<your_sandbox_client_id>
PAYPAL_CLIENT_SECRET=<your_sandbox_client_secret>
PAYPAL_WEBHOOK_ID=<your_webhook_id>
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
```

Sandbox credentials can be obtained through the [PayPal Developer Platform](https://developer.paypal.com/). PayPal Sandbox allows payment workflows to be tested without using real money.

> **Security:** Never commit `.env`, API keys, or PayPal credentials. The repository includes `.env.example` for safe configuration.

---

## 6. Docker Startup

From the repository root, execute:

```bash
docker compose up --build
```

Docker Compose starts the following services:

1. **db:** PostgreSQL 16 database.
2. **paypal-egress:** Controlled outbound proxy for permitted external API calls.
3. **api:** FastAPI backend.
4. **gateway:** Nginx reverse proxy.
5. **console:** React operations console.

The API startup process performs database migrations and initializes demo data. The first startup may take approximately 30–60 seconds.

### Verify Startup

Check container status:

```bash
docker compose ps
```

Verify backend health:

```bash
curl -sf http://127.0.0.1:8001/health
```

Verify database readiness:

```bash
curl -sf http://127.0.0.1:8001/ready
```

Verify frontend accessibility:

```bash
curl -sf http://127.0.0.1:3001/
```

All required services should be healthy or running.

---

## 7. Database Migration and Demo Initialization

Database migrations are executed automatically when the API container starts. The migration command is:

```bash
alembic upgrade head
```

IdentityTwin includes 19 migration scripts, with the latest migration being `019_durable_domain_events`.

Demo data is initialized through:

```bash
python scripts/seed_demo.py
```

The seed script creates demonstration merchants, users, sessions, incidents, and other sample records. It is designed to be idempotent, so existing records are not unnecessarily duplicated when the application restarts.

---

## 8. Demo Login Instructions

The console supports development-only bearer-token authentication by default. Production OIDC configuration is separate.

Open **[http://127.0.0.1:3001](http://127.0.0.1:3001)**, select a demo persona, and authenticate using the corresponding token.

### Available Demo Personas

| Persona           | Development token          | Access                                |
| ----------------- | -------------------------- | ------------------------------------- |
| Merchant Operator | `dev-merchant-token`       | Merchant-scoped operations            |
| Risk Analyst      | `dev-analyst-token`        | Incident review and investigation     |
| Other Merchant    | `dev-other-merchant-token` | Separate tenant for isolation testing |

The analyst persona can review incidents, initiate investigations, and access analyst-specific workflows. The merchant persona is restricted by server-side role-based access controls.

### Demo Accounts

| Account       | Email                             | Role     |
| ------------- | --------------------------------- | -------- |
| Merchant User | `merchant-dev@identitytwin.local` | Merchant |
| Analyst User  | `analyst-dev@identitytwin.local`  | Analyst  |

Demo merchant ID: `00000000-0000-0000-0000-000000000001`

These are development-only demonstration credentials, not production accounts.

---

## 9. Frontend and Backend URLs

Once Docker Compose is running, use the following URLs:

| Service                  | URL                                                                  |
| ------------------------ | -------------------------------------------------------------------- |
| React Operations Console | [http://127.0.0.1:3001](http://127.0.0.1:3001)                       |
| Backend API              | [http://127.0.0.1:8001](http://127.0.0.1:8001)                       |
| Swagger API Documentation | [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)            |
| ReDoc                    | [http://127.0.0.1:8001/redoc](http://127.0.0.1:8001/redoc)           |
| OpenAPI JSON             | [http://127.0.0.1:8001/openapi.json](http://127.0.0.1:8001/openapi.json) |
| Health Check             | [http://127.0.0.1:8001/health](http://127.0.0.1:8001/health)         |
| Readiness Check          | [http://127.0.0.1:8001/ready](http://127.0.0.1:8001/ready)           |

---

## 10. API Documentation

IdentityTwin provides interactive API documentation through Swagger UI.

- **Swagger UI:** [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)
- **ReDoc:** [http://127.0.0.1:8001/redoc](http://127.0.0.1:8001/redoc)
- **OpenAPI Specification:** [http://127.0.0.1:8001/openapi.json](http://127.0.0.1:8001/openapi.json)

The exported API contract is also available at `packages/contracts/openapi.json`.

Protected `/v1/` endpoints use bearer-token authentication and the configured role and tenant context.

---

## 11. Testing Behavioral Risk Scenarios

IdentityTwin includes seeded sessions representing the four trust states.

### Sample Scenarios

| Session suffix | Trust level | Risk score | Scenario                                                           |
| -------------- | ----------- | ---------: | ------------------------------------------------------------------ |
| `...2222`      | NORMAL      |          0 | Confirmed device and routine payout                                |
| `...3333`      | RESTRICTED  |         55 | New device, new payee, and large payout                            |
| `...4444`      | DECOY       |         75 | Suspicious network fingerprint and canary interaction              |
| `...5555`      | ISOLATED    |         95 | Automation fingerprint, canary interaction, and high-value attempt |

### How to Explore

1. Log in using the merchant or analyst persona.
2. Navigate to the **Sessions** section.
3. Inspect the four seeded sessions.
4. Review their risk scores and trust levels.
5. Navigate to **Payouts** to explore the protected transaction workflow.
6. Navigate to **Risk / Risk Decisions** to inspect the individual risk signals.
7. Review the resulting policy decisions and security incidents.

### Expected Trust Gateway Behavior

| Trust level | Expected behavior                               |
| ----------- | ----------------------------------------------- |
| NORMAL      | `ALLOW` — configured payment provider           |
| RESTRICTED  | `REQUIRE_STEP_UP` — additional verification     |
| DECOY       | `DECOY_FORWARD` — synthetic honey environment   |
| ISOLATED    | `BLOCK` — session isolation and incident creation |

### Eight Risk Signals

- `NEW_DEVICE`
- `NEW_LOCATION`
- `UNUSUAL_TIME`
- `NEW_PAYEE`
- `LARGE_PAYOUT`
- `NEW_PAYEE_LARGE_PAYOUT`
- `PAYEE_ADD_THEN_PAYOUT`
- `CANARY_INTERACTION`

The risk engine combines these signals to calculate a risk score and determine the appropriate enforcement policy.

---

## 12. Triggering a Groq AI Investigation

IdentityTwin integrates Groq's LLM inference API to provide AI-assisted incident investigation.

### How to Test

1. Ensure the backend has `AI_LLM_ENABLED=true`.
2. Configure a valid Groq API key and supported model.
3. Restart the application after updating environment variables.
4. Sign in using the **Risk Analyst** persona.
5. Navigate to **Incidents**.
6. Open a suspicious incident.
7. Click **Run Investigation**.
8. Review the generated investigation narrative, findings, and recommendations.

### What Happens Behind the Scenes

1. The backend extracts structured, merchant-scoped security evidence.
2. Sensitive information is redacted.
3. The evidence is sent to Groq using its OpenAI-compatible API.
4. The LLM generates an investigation narrative.
5. The response is validated against a strict Pydantic schema.
6. The investigation is persisted in the database.
7. The frontend displays the resulting narrative and recommendations.

The database records whether AI was used and the model responsible through fields such as `ai_used` and `model_name`. If the LLM is unavailable, the deterministic fallback is used.

### AI Security Boundary

The AI Investigator is strictly advisory and read-only. It cannot:

- Execute payouts.
- Approve transactions.
- Modify risk scores.
- Change trust levels.
- Directly invoke payment providers.

All financial enforcement decisions remain within the deterministic Trust Gateway.

---

## 13. Testing PayPal Sandbox

IdentityTwin integrates the PayPal Developer Platform through its Sandbox environment.

### Capabilities

- OAuth 2.0 authentication.
- PayPal Sandbox REST API integration.
- Payout creation and retrieval.
- Request-level idempotency.
- Webhook signature verification.
- Transaction reconciliation.

### How to Test

1. Configure valid PayPal Sandbox application credentials.
2. Set `PAYMENT_PROVIDER=paypal_sandbox`.
3. Configure the Sandbox webhook ID.
4. Ensure the required Sandbox business and receiver accounts are available.
5. Restart the Docker stack.
6. Execute a payout through the protected transaction workflow.
7. Inspect the resulting transaction and provider response.
8. Test webhook verification and idempotency.

The integration uses a controlled outbound proxy to restrict permitted external payment-provider traffic.

### Important Distinction

IdentityTwin supports both mock-provider demonstrations and actual PayPal Sandbox operations.

The mock provider is intended for local testing without external payment calls. PayPal Sandbox exercises the actual developer platform using test credentials and test accounts. No real-money transactions are involved.

---

## 14. Troubleshooting

| Issue                            | Likely cause                                         | Resolution                                           |
| -------------------------------- | ---------------------------------------------------- | ---------------------------------------------------- |
| Database is not healthy          | PostgreSQL is still starting                         | Wait and inspect `docker compose logs db`            |
| API fails to start               | Migration or environment configuration issue         | Inspect `docker compose logs api`                    |
| Console is blank                 | Gateway or frontend startup issue                    | Check gateway and console health                     |
| PayPal requests fail             | Sandbox credentials or proxy configuration           | Verify Sandbox credentials and permitted egress      |
| Groq investigation uses fallback | AI disabled or invalid API key                       | Verify LLM environment configuration                 |
| 403 response                     | Incorrect role or development authentication context | Use the correct demo persona                         |
| Reconciliation tests fail        | PostgreSQL test dependency unavailable               | Start the dedicated PostgreSQL test environment      |

### View Logs

```bash
docker compose logs -f api
docker compose logs -f db
docker compose logs -f console
docker compose logs -f gateway
```

---

## 15. Shutdown Instructions

Stop the application (removes containers, preserves the PostgreSQL named volume):

```bash
docker compose down
```

Stop without removing containers:

```bash
docker compose stop
```

Resume:

```bash
docker compose start
```

Completely reset the demo database:

```bash
docker compose down -v
```

> **Warning:** The last command deletes the persisted database volume and all demo data.

---

## Related Documentation

| Document                                                                | Description                                      |
| ----------------------------------------------------------------------- | ------------------------------------------------ |
| [README.md](../README.md)                                               | Project overview, architecture, and quickstart   |
| [architecture.md](architecture.md)                                      | Technical architecture                           |
| [security-boundaries.md](security-boundaries.md)                        | Security boundaries and invariants               |
| [ai-investigator.md](ai-investigator.md)                                | AI Investigator architecture                     |
| [DEVPOST_PROJECT_DESCRIPTION.md](DEVPOST_PROJECT_DESCRIPTION.md)        | Hackathon project description                    |
| [openapi.json](../packages/contracts/openapi.json)                      | Exported OpenAPI 3.1 specification               |
| [PAYPAL_SANDBOX_VERIFICATION_REPORT.md](../PAYPAL_SANDBOX_VERIFICATION_REPORT.md) | PayPal integration verification evidence |

---

**Repository:** [https://github.com/castiel0312/IdentityTwin](https://github.com/castiel0312/IdentityTwin)

*Identity should be verified continuously. Trust should be earned with every transaction.*
