# Bankai PoC — Banking-Grade RAG Gateway

Banka içi dokümanlar uzerinde RBAC (Role-Based Access Control), DLP (Data Loss Prevention) ve audit trail ile korunan bir RAG (Retrieval-Augmented Generation) gateway PoC'si.

## Mimari Genel Bakis

```
  UI Katmani            Proxy             Gateway               Backend
+-----------+       +---------+       +------------+         +-----------+
| OpenWebUI | ----> |  Nginx  | ----> |            | ------> |  Qdrant   |
|  (:3000)  | :8080 | (:8080) | :8000 |   Bankai   |  embed  | (VectorDB)|
+-----------+       | header  |       |  Gateway   |         +-----------+
                    | inject  |       |  (:8000)   |
+-----------+       +---------+       |            |         +-----------+
| LibreChat | ---------------------> |  FastAPI   | ------> |    OPA    |
|  (:3080)  |        :8000           |            | policy  | (AuthZ)   |
+-----------+                         +-----+------+         +-----------+
                                            |
                                            |                +-----------+
                                       LLM ------> | Ollama   |
                                                             | (qwen2.5) |
                                                             +-----------+
```

> **Not:** OpenWebUI, Nginx (:8080) uzerinden Gateway'e baglanir. Nginx, kullanici
> header'larindan X-User/X-Roles/X-Tenant enjekte ederek RBAC saglar.
> LibreChat ise dogrudan Gateway'e (:8000) baglanir.

## Bilesenler

| Bilesen | Port | Container | Aciklama |
|---------|------|-----------|----------|
| **Bankai Gateway** | 8000 | - (host process) | FastAPI, RAG pipeline, DLP, audit |
| **Qdrant** | 6333 | `bankai-poc-qdrant-1` | Vektor veritabani (embedding storage) |
| **OPA** | 8181 | `bankai-poc-opa-1` | Open Policy Agent (RBAC policy engine) |
| **Ollama** | 11434 | - (Windows host) | LLM backend (qwen2.5:7b-instruct) |
| **Nginx** | 8080 | `bankai-nginx` | Reverse proxy — OpenWebUI RBAC icin header injection |
| **OpenWebUI** | 3000 | `openwebui` | Chat UI #1 |
| **LibreChat** | 3080 | `librechat` | Chat UI #2 |
| **MongoDB** | 27017 | `librechat-mongodb` | LibreChat kullanici/oturum veritabani |

## Hizli Kurulum

### 1. Onkoşullar
- Python 3.10+
- Docker & Docker Compose
- Ollama (Windows host uzerinde veya erisilebilir bir makinede)

### 2. Ortam Degiskenleri
```bash
cp .env.example .env
cp librechat/.env.example librechat/.env
# .env dosyalarini duzenleyin (Ollama IP, secret key'ler vb.)
```

### 3. Altyapi Servisleri (Qdrant + OPA)
```bash
docker compose up -d
```

### 4. Gateway
```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn requests python-dotenv sentence-transformers pydantic
uvicorn app_main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Dokuman Indeksleme
```bash
# Her tenant icin ayri koleksiyon
curl -X POST http://localhost:8000/admin/reindex/hr
curl -X POST http://localhost:8000/admin/reindex/compliance
curl -X POST http://localhost:8000/admin/reindex/finance
```

### 6. Nginx (OpenWebUI RBAC proxy)
```bash
docker run -d --name bankai-nginx \
  --add-host host.docker.internal:host-gateway \
  -p 8080:8080 \
  -v $(pwd)/nginx/nginx.conf:/etc/nginx/nginx.conf:ro \
  nginx:alpine
```

### 7. OpenWebUI
```bash
docker run -d --name openwebui \
  -p 3000:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1 \
  -e OPENAI_API_KEY=dummy \
  --add-host host.docker.internal:host-gateway \
  ghcr.io/open-webui/open-webui:main
```

### 8. LibreChat
```bash
cd librechat
docker compose up -d
```

## Kullanici / Rol / Tenant Eslemesi (PoC)

| Kullanici | Rol | Tenant (Koleksiyon) | API Key |
|-----------|-----|---------------------|---------|
| ali | hr | hr | `sk-dummy`, `sk-hr`, `sk-bankai` |
| ayse | compliance | compliance | `sk-compliance` |
| veli | finance | finance | `sk-finance` |

> **Not:** API key'ler PoC placeholder degerleridir. Production'da LDAP/SSO entegrasyonu kullanilmalidir.

## Hizli Test

```bash
# Ping
curl http://localhost:8000/__ping

# Dogrudan gateway (header ile)
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "X-User: ali" \
  -H "X-Roles: hr" \
  -d '{"tenant":"hr","question":"Calisma saatleri nedir?"}'

# OpenAI-uyumlu endpoint
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-hr" \
  -d '{
    "model": "qwen2.5:7b-instruct",
    "messages": [{"role":"user","content":"Yillik izin suresi kac gun?"}]
  }'

# Nginx uzerinden (OpenWebUI simulasyonu)
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-OpenWebUI-User-Name: ali" \
  -d '{
    "model": "qwen2.5:7b-instruct",
    "messages": [{"role":"user","content":"Yan haklar nelerdir?"}]
  }'
```

## Dokumantasyon

| Dosya | Icerik |
|-------|--------|
| [docs/architecture/GATEWAY.md](docs/architecture/GATEWAY.md) | Gateway pipeline detaylari |
| [docs/architecture/OPENWEBUI.md](docs/architecture/OPENWEBUI.md) | OpenWebUI entegrasyonu |
| [docs/architecture/LIBRECHAT.md](docs/architecture/LIBRECHAT.md) | LibreChat entegrasyonu |
| [docs/architecture/KARSILASTIRMA.md](docs/architecture/KARSILASTIRMA.md) | UI karsilastirmasi (PoC odakli) |
| [docs/architecture/KURUMSAL_KARSILASTIRMA.md](docs/architecture/KURUMSAL_KARSILASTIRMA.md) | Kurumsal olcekte UI karsilastirmasi (500+ kisi) |
| [docs/architecture/ISTEK_AKISI.md](docs/architecture/ISTEK_AKISI.md) | Bir istegin bastan sona yolculugu |
| [docs/architecture/topology.drawio](docs/architecture/topology.drawio) | Topoloji diyagrami (Draw.io) |

## Bilinen Kisitlamalar (PoC)

- DLP sadece TCKN (11 haneli sayi) tespit eder
- Kullanici/rol eslesmesi statik map ile yapilir (LDAP/SSO entegrasyonu yok)
- Ollama host IP'si WSL2'de dinamik degisebilir
- Test suite bulunmamaktadir
- Embedding modeli: `paraphrase-multilingual-MiniLM-L12-v2` (Turkce icin secildi)
