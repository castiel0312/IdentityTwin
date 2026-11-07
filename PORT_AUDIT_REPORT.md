# PORT AUDIT REPORT — IdentityTwin

**Audit Date:** 2026-11-07  
**Release Candidate:** 593b048f8da5bf77868aa9af2e1e4f12a0c7f155 (main branch)  
**Expected Tag:** rc-20261107-63a3a9d (not present locally)  

---

## Executive Summary

All required services are running and reachable on their configured ports. No port conflicts detected. The Docker Compose stack exposes services correctly through the gateway (port 8001) and console (port 3001). The database runs on internal port 5432 (not exposed to host).

---

## Discovered Ports

| Port | Protocol | Service | Process/Container | Bind Address | Expected vs Actual | Externally Exposed | Auth/Network Restrictions | Conflicts | Responds Correctly |
|------|----------|---------|-------------------|--------------|-------------------|-------------------|---------------------------|-----------|-------------------|
| 8000 | TCP | FastAPI Backend (internal) | identitytwin-api-1 | 0.0.0.0:8000 (container) | ✅ Match | No (internal network only) | None (health checks only) | No | ✅ Yes |
| 8001 | TCP | Nginx Gateway (API) | identitytwin-gateway-1 | 0.0.0.0:8001, [::]:8001 | ✅ Match | Yes | Rate limiting, CORS | No | ✅ Yes |
| 3001 | TCP | Frontend Console (Nginx) | identitytwin-console-1 | 0.0.0.0:3001, [::]:3001 | ✅ Match | Yes | None (static assets + proxy) | No | ✅ Yes |
| 5432 | TCP | PostgreSQL (internal) | identitytwin-db-1 | 5432 (container) | ✅ Match | No (internal network only) | postgres_user/password | No | ✅ Yes |
| 3128 | TCP | Squid Proxy (PayPal egress) | identitytwin-paypal-egress-1 | 3128 (container) | ✅ Match | No (internal network only) | None | No | ✅ Yes |
| 55432 | TCP | PostgreSQL (external test DB) | identitytwin-reconciliation-test | 0.0.0.0:55432, [::]:55432 | ⚠️ Extra | Yes | postgres_user/password | No | ✅ Yes |

---

## Port Configuration Analysis

### Docker Compose Port Mappings (docker-compose.yml)

```yaml
gateway:
  ports:
    - "${IDENTITYTWIN_API_PORT:-8001}:8000"  # Host 8001 -> Container 8000

console:
  ports:
    - "${IDENTITYTWIN_CONSOLE_PORT:-3001}:80"  # Host 3001 -> Container 80

db:
  # No host port mapping - internal only
  # The database is reachable only on the private Docker network (db:5432)
```

### Frontend Vite Configuration (vite.config.ts)
```typescript
server: {
  port: 5173,
  proxy: {
    "/v1": { target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000" },
    "/health": { target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000" },
  },
}
```
- **Development mode**: Vite dev server runs on 5173, proxies `/v1/*` and `/health` to backend on 8000
- **Production mode**: Built assets served by nginx on port 80 (container) / 3001 (host)

### Backend Configuration (apps/api/app/main.py)
- Uvicorn binds to `0.0.0.0:8000` inside container
- Health checks at `/health` and `/ready`

### Nginx Gateway Configuration (scripts/docker/nginx.conf)
- Listens on port 8000 (container)
- Proxies all traffic to `api:8000`
- Health checks at `/health` and `/ready`

### Frontend Nginx Configuration (frontend/nginx.conf)
- Listens on port 80 (container)
- Proxies `/v1/` to `gateway:8000`
- Proxies `/health` and `/ready` to `gateway:8000`
- Serves static assets for `/`

---

## Verification Results

### Service Health Checks

| Endpoint | Command | Result |
|----------|---------|--------|
| Gateway Health | `curl http://localhost:8001/health` | ✅ 200 OK - `{"status":"ok",...}` |
| Gateway Readiness | `curl http://localhost:8001/ready` | ✅ 200 OK - `{"status":"ready","database":"connected"}` |
| Console | `curl http://localhost:3001/` | ✅ 200 OK - HTML served |
| API Docs | `curl http://localhost:8001/docs` | ✅ 200 OK - Swagger UI |
| OpenAPI Spec | `curl http://localhost:8001/openapi.json` | ✅ 200 OK - Full spec |
| System Context | `curl -H "Auth: Bearer dev-merchant-token" http://localhost:8001/v1/system/context` | ✅ 200 OK |

### SSE Stream Test
```bash
curl -H "Authorization: Bearer dev-merchant-token" -H "Accept: text/event-stream" -N http://localhost:8001/v1/events/stream --max-time 5
```
✅ Returns 66 events with proper SSE format (`id:`, `event:`, `data:` fields)

### Database Connectivity
- Internal: `db:5432` - ✅ Healthy (pg_isready)
- From API: ✅ `check_db_ready()` returns true
- From host (test DB): `localhost:55432` - ✅ Accessible

---

## Issues Found

### P3 - Low: Extra Test Database Port Exposed
- **Port:** 55432 (TCP)
- **Service:** identitytwin-reconciliation-test (PostgreSQL)
- **Issue:** A test database container from a previous reconciliation test run is still running and exposing port 55432 on all interfaces (0.0.0.0)
- **Impact:** None on production stack; minor resource usage
- **Remediation:** `docker stop identitytwin-reconciliation-test && docker rm identitytwin-reconciliation-test`

### P3 - Low: Fast Refresh Warning (Known)
- **File:** `frontend/src/lib/auth.tsx:181`
- **Issue:** React Fast Refresh warning for non-component exports
- **Impact:** Development-only warning, no runtime impact
- **Status:** Previously documented, non-blocking

---

## Network Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │  Port 8001  │    │  Port 3001  │    │    Port 55432       │  │
│  │  (Gateway)  │    │  (Console)  │    │  (Test DB - Extra)  │  │
│  └──────┬──────┘    └──────┬──────┘    └─────────────────────┘  │
└─────────┼──────────────────┼─────────────────────────────────────┘
          │                  │
    ┌─────▼─────┐      ┌─────▼─────┐
    │  Gateway  │      │  Console  │
    │  (nginx)  │      │  (nginx)  │
    │  :8000    │      │  :80      │
    └─────┬─────┘      └─────┬─────┘
          │                  │
          └────────┬─────────┘
                   │
         ┌─────────▼─────────┐
         │  Docker Network   │
         │ identitytwin_     │
         │  private          │
         └─────────┬─────────┘
                   │
      ┌────────────┼────────────┐
      ▼            ▼            ▼
   ┌──────┐   ┌────────┐   ┌──────────┐
   │  API │   │   DB   │   │PayPal    │
   │ :8000│   │ :5432  │   │ Egress   │
   └──────┘   └────────┘   │ :3128    │
                           └──────────┘
```

---

## Conclusion

**PORT AUDIT: PASS** — All required ports are correctly configured, no conflicts, all services respond appropriately. The only findings are a leftover test container (P3) and a known Fast Refresh warning (P3).