# Bankai - Enterprise RAG Gateway

Banking-grade Retrieval-Augmented Generation (RAG) gateway with Keycloak SSO, group-based RBAC, DLP, guardrails, and centralized logging.

> **Note:** This is a PoC (Proof of Concept) demonstrating enterprise-grade RAG architecture. Not production-ready without additional hardening.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROWSER                                     │
│                                                                     │
│   ┌──────────────┐         ┌──────────────────┐                     │
│   │  LibreChat    │◄───────►│    Keycloak       │                    │
│   │  :3080        │  OAuth  │    :8443          │                    │
│   └──────┬───────┘  (OIDC) └──────────────────┘                    │
│          │ JWT                                                      │
└──────────┼──────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    BANKAI RAG GATEWAY (:8000)                        │
│                                                                      │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌───────────┐  ┌────────┐ │
│  │ JWT Auth │  │ Guardrails│  │   OPA   │  │ Retrieval │  │  LLM   │ │
│  │ Keycloak │─►│ DLP      │─►│ Policy  │─►│ Qdrant    │─►│ Ollama │ │
│  │ Groups   │  │ Injection│  │ Check   │  │ Search    │  │        │ │
│  │          │  │ Toxic    │  │         │  │           │  │        │ │
│  │          │  │ Rate Lim │  │         │  │           │  │        │ │
│  └─────────┘  └──────────┘  └─────────┘  └───────────┘  └────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                    AUDIT LOG (JSONL)                          │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
           │                    │                          │
           ▼                    ▼                          ▼
┌──────────────┐    ┌──────────────┐            ┌──────────────────┐
│   Qdrant     │    │     OPA      │            │     Ollama       │
│   :6333      │    │    :8181     │            │    :11434        │
│  Vector DB   │    │  Policy Eng  │            │   LLM Backend    │
└──────────────┘    └──────────────┘            └──────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                      MONITORING STACK                                 │
│                                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐                   │
│  │ Promtail │───►│   Loki   │◄───│   Grafana    │                   │
│  │ Collector │    │  :3100   │    │   :3001      │                   │
│  └──────────┘    └──────────┘    └──────────────┘                   │
└──────────────────────────────────────────────────────────────────────┘
```

## Request Flow

```
User Question
     │
     ▼
[1] JWT Validation ──── Invalid? ──► 401 Unauthorized
     │
     ▼
[2] Rate Limit Check ── Exceeded? ──► 429 Too Many Requests
     │
     ▼
[3] Input Size Check ── Too Long? ──► 400 Bad Request
     │
     ▼
[4] Toxic Filter ────── Detected? ──► 400 Inappropriate Content
     │
     ▼
[5] Injection Check ─── Detected? ──► 400 Security Violation
     │
     ▼
[6] DLP Masking (input) ── TCKN, IBAN, Card, Phone, Email masked
     │
     ▼
[7] OPA Policy Check ── Denied? ───► 403 Policy Deny
     │
     ▼
[8] Qdrant Retrieval ── No results? ► "Bilgi bulunamadı"
     │
     ▼
[9] LLM Generation (Ollama)
     │
     ▼
[10] Output Size Check ── Truncate if needed
     │
     ▼
[11] Toxic Filter (output)
     │
     ▼
[12] Hallucination Check ── Low overlap? ► Warning appended
     │
     ▼
[13] DLP Masking (output)
     │
     ▼
[14] Audit Log ──► Loki ──► Grafana Dashboard
     │
     ▼
  Response
```

## Features

### Authentication & Authorization
- **Keycloak SSO** — Single Sign-On, no email/password login
- **Group-based RBAC** — Users belong to Keycloak groups (HR, Finance, BT, etc.)
- **JWT validation** — Gateway validates Keycloak JWT, extracts username and groups
- **OPA policies** — Fine-grained access control per document collection

### Guardrails
| Guardrail | Description |
|-----------|-------------|
| **DLP** | Masks TCKN, IBAN, credit card (Luhn), phone, email in both input and output |
| **Prompt Injection** | Detects manipulation attempts in Turkish and English |
| **Toxic Content** | Blocks profanity and inappropriate language (TR/EN) |
| **Rate Limiting** | Per-user limits (default: 15/min, 100/hour) |
| **Input/Output Limits** | Max character limits (default: 4K input, 8K output) |
| **Hallucination Detection** | Warns when response doesn't align with source documents |

### Monitoring
- **Grafana dashboard** — Request rates, OPA denies, DLP events, Keycloak events, errors
- **Loki** — Log aggregation with label-based querying
- **Promtail** — Automatic Docker + file log collection

## Quick Start

### Prerequisites
- Docker Desktop (with WSL2 if on Windows)
- [Ollama](https://ollama.com/) with `qwen2.5:7b-instruct`:
  ```bash
  ollama pull qwen2.5:7b-instruct
  ```
- Python 3.10+

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/bankai-poc.git
cd bankai-poc

# Gateway config
cp .env.example .env
# Edit .env — set OLLAMA_HOST to your Ollama IP
# WSL2 users: ip route show default | awk '{print $3}'

# LibreChat config
cp librechat/.env.example librechat/.env
# Edit librechat/.env — change all CHANGE_ME values
```

### 2. Start infrastructure

```bash
# Core services (Qdrant, OPA, Keycloak, Loki, Grafana, Promtail)
docker compose up -d

# LibreChat
cd librechat && docker compose up -d && cd ..
```

### 3. Setup Keycloak

Wait for Keycloak to start (~30s), then open http://localhost:8443 and login with `admin`/`admin`.

**Create realm and clients:**

```bash
# Get admin token
TOKEN=$(curl -s -X POST "http://localhost:8443/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli" -d "username=admin" -d "password=admin" \
  -d "grant_type=password" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Create bankai realm
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms" -d '{"realm":"bankai","enabled":true}'

# Create librechat client (use same secret as in librechat/.env)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms/bankai/clients" \
  -d '{
    "clientId":"librechat","enabled":true,"protocol":"openid-connect",
    "publicClient":false,"secret":"YOUR_CLIENT_SECRET_HERE",
    "redirectUris":["http://localhost:3080/*"],"webOrigins":["*"],
    "directAccessGrantsEnabled":true
  }'

# Create groups
for G in HR Compliance Finance BT Risk Hukuk; do
  curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    "http://localhost:8443/admin/realms/bankai/groups" -d "{\"name\":\"$G\"}"
done

# Add groups claim mapper to client
CLIENT_UUID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8443/admin/realms/bankai/clients?clientId=librechat" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms/bankai/clients/$CLIENT_UUID/protocol-mappers/models" \
  -d '{"name":"groups","protocol":"openid-connect","protocolMapper":"oidc-group-membership-mapper",
       "config":{"full.path":"false","id.token.claim":"true","access.token.claim":"true",
                 "claim.name":"groups","userinfo.token.claim":"true"}}'
```

**Create users** (repeat for each user/group):

```bash
# Create user
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms/bankai/users" \
  -d '{"username":"ali","firstName":"Ali","email":"ali@bankai.local","enabled":true}'

# Set password
USER_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8443/admin/realms/bankai/users?username=ali" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms/bankai/users/$USER_ID/reset-password" \
  -d '{"type":"password","value":"YourPassword123!","temporary":false}'

# Assign to group
GROUP_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8443/admin/realms/bankai/groups?search=HR" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8443/admin/realms/bankai/users/$USER_ID/groups/$GROUP_ID"
```

### 4. Start the gateway

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app_main:app --host 0.0.0.0 --port 8000
```

### 5. Index documents

```bash
for TENANT in hr compliance finance bt risk hukuk; do
  curl -X POST "http://localhost:8000/admin/reindex/$TENANT"
done
```

### 6. Access

| Service | URL | Credentials |
|---------|-----|-------------|
| **LibreChat** | http://localhost:3080 | Keycloak SSO |
| **Keycloak Admin** | http://localhost:8443 | admin / admin |
| **Grafana** | http://localhost:3001 | admin / bankai |
| **Gateway API** | http://localhost:8000 | JWT Bearer token |

## Project Structure

```
bankai-poc/
├── app_main.py                 # RAG Gateway (FastAPI) — auth, guardrails, pipeline
├── docker-compose.yml          # Qdrant + OPA + Keycloak + Monitoring stack
├── .env.example                # Gateway env template
├── requirements.txt            # Python dependencies
├── policies/
│   └── rag.rego                # OPA access control policies
├── docs/                       # Document collections (one dir per group)
│   ├── hr/                     # HR policies (Turkish)
│   ├── compliance/             # AML, KVKK, internal audit
│   ├── finance/                # Budget, treasury, credit
│   ├── bt/                     # IT security, dev standards, infra
│   ├── risk/                   # Operational, credit, market risk
│   └── hukuk/                  # Contracts, legal compliance, labor law
├── librechat/
│   ├── docker-compose.yml      # LibreChat + MongoDB
│   ├── .env.example            # LibreChat env template
│   ├── librechat.yaml          # Custom endpoint config
│   ├── openidStrategy.js       # Patched OIDC strategy (HTTP + URL rewrite)
│   ├── custom.css              # Navy blue theme
│   └── index.html              # Branded "Bankai AI" page
├── monitoring/
│   ├── loki-config.yml         # Loki log storage config
│   ├── promtail-config.yml     # Log collector config
│   └── grafana/
│       ├── dashboards/         # Pre-built Grafana dashboards
│       └── provisioning/       # Auto-provisioning (datasource + dashboards)
└── audit/                      # Runtime audit logs (gitignored)
```

## Adding New Groups

1. Create group in Keycloak admin panel
2. Create document directory: `mkdir docs/newgroup`
3. Add `.txt` or `.md` files
4. Add OPA policy rule in `policies/rag.rego`:
   ```rego
   allow {
     input.resource.collection == "newgroup"
     input.user.groups[_] == "newgroup"
   }
   ```
5. Restart OPA: `docker compose restart opa`
6. Index: `curl -X POST http://localhost:8000/admin/reindex/newgroup`
7. Assign users to group in Keycloak

## Configuration

### Guardrails (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_PER_MINUTE` | 15 | Max requests per user per minute |
| `RATE_LIMIT_PER_HOUR` | 100 | Max requests per user per hour |
| `MAX_INPUT_CHARS` | 4000 | Max input character length |
| `MAX_OUTPUT_CHARS` | 8000 | Max output character length |

### LLM (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | qwen2.5:7b-instruct | Ollama model name |
| `OLLAMA_URL` | http://localhost:11434/api/chat | Ollama API endpoint |

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Gateway | FastAPI (Python) | RAG pipeline, auth, guardrails |
| LLM | Ollama | Text generation (local, private) |
| Vector DB | Qdrant | Semantic search |
| Embeddings | sentence-transformers | Multilingual (Turkish optimized) |
| Identity | Keycloak | SSO, user/group management |
| Policy | OPA (Rego) | Fine-grained access control |
| UI | LibreChat | Chat interface with SSO |
| Logging | Loki + Grafana + Promtail | Centralized monitoring |

## License

MIT
