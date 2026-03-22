# Bankai - Kurumsal RAG Gateway

Keycloak SSO, grup bazli erisim kontrolu (RBAC), veri sizinti onleme (DLP), guvenlik katmanlari (guardrail) ve merkezi loglama ile donatiilmis, banka/kurumsal seviye bir RAG (Retrieval-Augmented Generation) gateway.

> **Not:** Bu proje kurumsal seviye RAG mimarisini gosteren bir PoC (Proof of Concept) uygulamasidir. Production kullanimi icin ek guvenlik sertlestirmesi gereklidir.

[English version below](#english)

---

## Mimari

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TARAYICI                                     │
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
│  │ JWT      │  │ Guvenlik │  │   OPA   │  │ Vektör    │  │  LLM   │ │
│  │ Dogrulama│─►│ Katmani  │─►│ Politika│─►│ Arama     │─►│ Ollama │ │
│  │ Keycloak │  │ DLP      │  │ Kontrol │  │ Qdrant    │  │        │ │
│  │ Gruplar  │  │ Enjeksiyn│  │         │  │           │  │        │ │
│  │          │  │ Toxic    │  │         │  │           │  │        │ │
│  │          │  │ Rate Lim │  │         │  │           │  │        │ │
│  └─────────┘  └──────────┘  └─────────┘  └───────────┘  └────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                  DENETIM KAYDI (JSONL)                        │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
           │                    │                          │
           ▼                    ▼                          ▼
┌──────────────┐    ┌──────────────┐            ┌──────────────────┐
│   Qdrant     │    │     OPA      │            │     Ollama       │
│   :6333      │    │    :8181     │            │    :11434        │
│  Vektör DB   │    │  Politika    │            │   LLM Backend    │
└──────────────┘    └──────────────┘            └──────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                      IZLEME (MONITORING)                             │
│                                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐                   │
│  │ Promtail │───►│   Loki   │◄───│   Grafana    │                   │
│  │ Toplayici │    │  :3100   │    │   :3001      │                   │
│  └──────────┘    └──────────┘    └──────────────┘                   │
└──────────────────────────────────────────────────────────────────────┘
```

## Istek Akisi

```
Kullanici Sorusu
     │
     ▼
[1]  JWT Dogrulama ────── Gecersiz? ──► 401 Yetkisiz
     │
     ▼
[2]  Rate Limit ─────── Asildi? ────► 429 Cok Fazla Istek
     │
     ▼
[3]  Girdi Uzunlugu ──── Uzun? ─────► 400 Girdi Cok Uzun
     │
     ▼
[4]  Toxic Filtre ────── Tespit? ───► 400 Uygunsuz Icerik
     │
     ▼
[5]  Enjeksiyon Kontrol ─ Tespit? ──► 400 Guvenlik Ihlali
     │
     ▼
[6]  DLP Maskeleme (girdi) ── TCKN, IBAN, Kart, Tel, E-posta
     │
     ▼
[7]  OPA Politika Kontrol ── Red? ──► 403 Erisim Engeli
     │
     ▼
[8]  Qdrant Vektör Arama ── Sonuc yok? ► "Bilgi bulunamadi"
     │
     ▼
[9]  LLM Uretimi (Ollama)
     │
     ▼
[10] Cikti Uzunlugu ──── Kesildi mi?
     │
     ▼
[11] Toxic Filtre (cikti)
     │
     ▼
[12] Halusinasyon Kontrol ── Dusuk ortusme? ► Uyari eklendi
     │
     ▼
[13] DLP Maskeleme (cikti)
     │
     ▼
[14] Denetim Kaydi ──► Loki ──► Grafana Dashboard
     │
     ▼
  Cevap
```

## Ozellikler

### Kimlik Dogrulama ve Yetkilendirme
- **Keycloak SSO** — Tek Oturum Acma, e-posta/sifre ile giris yok
- **Grup bazli RBAC** — Kullanicilar Keycloak gruplarina aittir (IK, Finans, BT vb.)
- **JWT dogrulama** — Gateway Keycloak JWT'sini dogrular, kullanici adi ve grup bilgisi cikarir
- **OPA politikalari** — Dokuman koleksiyonu bazinda ince taneli erisim kontrolu

### Guvenlik Katmanlari (Guardrails)
| Katman | Aciklama |
|--------|----------|
| **DLP** | TCKN, IBAN, kredi karti (Luhn), telefon, e-posta maskeleme — girdi ve ciktida |
| **Prompt Enjeksiyon** | "Talimatlari unut", "system prompt goster" gibi saldirilari tespit (TR/EN) |
| **Toxic Icerik** | Kufur ve uygunsuz dil engelleme (TR/EN) |
| **Rate Limiting** | Kullanici basi istek siniri (varsayilan: 15/dk, 100/saat) |
| **Girdi/Cikti Siniri** | Maksimum karakter siniri (varsayilan: 4K girdi, 8K cikti) |
| **Halusinasyon Tespiti** | Cevap kaynak dokumanlarla ortusmuyor ise uyari |

### Izleme (Monitoring)
- **Grafana dashboard** — Istek oranlari, OPA redleri, DLP olaylari, Keycloak olaylari, hatalar
- **Loki** — Etiket bazli sorgulama ile log toplama
- **Promtail** — Otomatik Docker + dosya log toplama

### Arayuz
- **LibreChat** — Lacivert "Bankai AI" temasi, sadece Keycloak SSO ile giris
- Kullanici basi JWT gateway'e iletilir

## Hizli Kurulum

### On Kosullar
- Docker Desktop (Windows'ta WSL2 ile)
- [Ollama](https://ollama.com/) kurulu ve calisiyor
- Model indirilmis:
  ```bash
  ollama pull qwen2.5:7b-instruct
  ```
- Python 3.10+

### 1. Klonla ve yapilandir

```bash
git clone https://github.com/EmirhanCivil/bankai-poc.git
cd bankai-poc

# Gateway yapilandirmasi
cp .env.example .env
# .env dosyasini duzenle — OLLAMA_HOST'u Ollama IP'niz ile degistirin
# WSL2 kullanicilari: ip route show default | awk '{print $3}'

# LibreChat yapilandirmasi
cp librechat/.env.example librechat/.env
# librechat/.env dosyasindaki tum CHANGE_ME degerlerini degistirin
```

### 2. Altyapiyi baslat

```bash
# Temel servisler (Qdrant, OPA, Keycloak, Loki, Grafana, Promtail)
docker compose up -d

# LibreChat
cd librechat && docker compose up -d && cd ..
```

### 3. Keycloak Kurulumu

Keycloak'in baslamasini bekleyin (~30sn), ardindan http://localhost:8443 adresini acin (`admin`/`admin`).

**Realm, client ve gruplari olusturun:**

```bash
# Admin token al
TOKEN=$(curl -s -X POST "http://localhost:8443/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli" -d "username=admin" -d "password=admin" \
  -d "grant_type=password" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# bankai realm olustur
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms" -d '{"realm":"bankai","enabled":true}'

# librechat client olustur (secret'i librechat/.env'deki ile ayni yapın)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms/bankai/clients" \
  -d '{
    "clientId":"librechat","enabled":true,"protocol":"openid-connect",
    "publicClient":false,"secret":"LIBRECHAT_ENV_DEKI_SECRET",
    "redirectUris":["http://localhost:3080/*"],"webOrigins":["*"],
    "directAccessGrantsEnabled":true
  }'

# Is birimi gruplarini olustur
for G in HR Compliance Finance BT Risk Hukuk; do
  curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    "http://localhost:8443/admin/realms/bankai/groups" -d "{\"name\":\"$G\"}"
done

# JWT'ye grup bilgisi ekleyen mapper olustur
CLIENT_UUID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8443/admin/realms/bankai/clients?clientId=librechat" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms/bankai/clients/$CLIENT_UUID/protocol-mappers/models" \
  -d '{"name":"groups","protocol":"openid-connect","protocolMapper":"oidc-group-membership-mapper",
       "config":{"full.path":"false","id.token.claim":"true","access.token.claim":"true",
                 "claim.name":"groups","userinfo.token.claim":"true"}}'
```

**Kullanici olusturun** (her kullanici/grup icin tekrarlayin):

```bash
# Kullanici olustur
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms/bankai/users" \
  -d '{"username":"ali","firstName":"Ali","email":"ali@bankai.local","enabled":true}'

# Sifre belirle
USER_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8443/admin/realms/bankai/users?username=ali" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "http://localhost:8443/admin/realms/bankai/users/$USER_ID/reset-password" \
  -d '{"type":"password","value":"SifreGirin123!","temporary":false}'

# Gruba ata
GROUP_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8443/admin/realms/bankai/groups?search=HR" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8443/admin/realms/bankai/users/$USER_ID/groups/$GROUP_ID"
```

### 4. Gateway'i baslat

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app_main:app --host 0.0.0.0 --port 8000
```

### 5. Dokumanlari indexle

```bash
for TENANT in hr compliance finance bt risk hukuk; do
  curl -X POST "http://localhost:8000/admin/reindex/$TENANT"
done
```

### 6. Erisim

| Servis | URL | Giris Bilgileri |
|--------|-----|-----------------|
| **LibreChat** | http://localhost:3080 | Keycloak SSO |
| **Keycloak Yonetim** | http://localhost:8443 | admin / admin |
| **Grafana** | http://localhost:3001 | admin / bankai |
| **Gateway API** | http://localhost:8000 | JWT Bearer token |

## Proje Yapisi

```
bankai-poc/
├── app_main.py                 # RAG Gateway (FastAPI) — kimlik, guvenlik, pipeline
├── docker-compose.yml          # Qdrant + OPA + Keycloak + Izleme
├── .env.example                # Gateway ortam degiskeni sablonu
├── requirements.txt            # Python bagimliliklari
├── policies/
│   └── rag.rego                # OPA erisim politikalari
├── docs/                       # Dokuman koleksiyonlari (grup basina dizin)
│   ├── hr/                     # IK politikalari (Turkce)
│   ├── compliance/             # AML, KVKK, ic denetim
│   ├── finance/                # Butce, hazine, kredi
│   ├── bt/                     # BT guvenlik, gelistirme, altyapi
│   ├── risk/                   # Operasyonel, kredi, piyasa riski
│   └── hukuk/                  # Sozlesme, yasal uyum, is hukuku
├── librechat/
│   ├── docker-compose.yml      # LibreChat + MongoDB
│   ├── .env.example            # LibreChat ortam degiskeni sablonu
│   ├── librechat.yaml          # Endpoint yapilandirmasi
│   ├── openidStrategy.js       # Yamali OIDC stratejisi (HTTP + URL yeniden yazma)
│   ├── custom.css              # Lacivert tema
│   └── index.html              # "Bankai AI" markali sayfa
├── monitoring/
│   ├── loki-config.yml         # Loki log depolama yapilandirmasi
│   ├── promtail-config.yml     # Log toplayici yapilandirmasi
│   └── grafana/
│       ├── dashboards/         # Hazir Grafana panolari
│       └── provisioning/       # Otomatik yapilandirma
└── audit/                      # Calisma zamani denetim kayitlari (git'e dahil degil)
```

## Dokuman Koleksiyonlari

Her grubun kendi dokuman koleksiyonu vardir. Kullanicilar yalnizca kendi gruplarina ait dokumanlari sorgulayabilir.

| Grup | Koleksiyon | Dokumanlar |
|------|-----------|------------|
| IK | `hr` | Izin politikasi, yan haklar, calisma saatleri |
| Uyum | `compliance` | AML politikasi, KVKK proseduru, ic denetim |
| Finans | `finance` | Butce yonetimi, hazine, kredi politikasi |
| BT | `bt` | Guvenlik politikasi, gelistirme standartlari, altyapi |
| Risk | `risk` | Operasyonel risk, kredi riski, piyasa riski |
| Hukuk | `hukuk` | Sozlesme yonetimi, yasal uyum, is hukuku |

## Yeni Grup Ekleme

1. Keycloak yonetim panelinden grup olusturun
2. Dokuman dizini olusturun: `mkdir docs/yenigrup`
3. `.txt` veya `.md` dosyalari ekleyin
4. `policies/rag.rego` dosyasina OPA politika kurali ekleyin:
   ```rego
   allow {
     input.resource.collection == "yenigrup"
     input.user.groups[_] == "yenigrup"
   }
   ```
5. OPA'yi yeniden baslatin: `docker compose restart opa`
6. Indexleyin: `curl -X POST http://localhost:8000/admin/reindex/yenigrup`
7. Keycloak'ta kullanicilari gruba atayin

## Yapilandirma

### Guvenlik Katmanlari (`.env`)

| Degisken | Varsayilan | Aciklama |
|----------|-----------|----------|
| `RATE_LIMIT_PER_MINUTE` | 15 | Kullanici basi dakika siniri |
| `RATE_LIMIT_PER_HOUR` | 100 | Kullanici basi saat siniri |
| `MAX_INPUT_CHARS` | 4000 | Maksimum girdi karakter uzunlugu |
| `MAX_OUTPUT_CHARS` | 8000 | Maksimum cikti karakter uzunlugu |

### LLM (`.env`)

| Degisken | Varsayilan | Aciklama |
|----------|-----------|----------|
| `OLLAMA_MODEL` | qwen2.5:7b-instruct | Ollama model adi |
| `OLLAMA_URL` | http://localhost:11434/api/chat | Ollama API adresi |

## Teknoloji Yigini

| Bilesen | Teknoloji | Amac |
|---------|-----------|------|
| Gateway | FastAPI (Python) | RAG pipeline, kimlik dogrulama, guvenlik katmanlari |
| LLM | Ollama | Metin uretimi (yerel, ozel) |
| Vektor DB | Qdrant | Anlamsal arama |
| Gomme (Embedding) | sentence-transformers | Cok dilli (Turkce optimize) |
| Kimlik | Keycloak | SSO, kullanici/grup yonetimi |
| Politika | OPA (Rego) | Ince taneli erisim kontrolu |
| Arayuz | LibreChat | Sohbet arayuzu (SSO entegreli) |
| Izleme | Loki + Grafana + Promtail | Merkezi loglama |

---

<a name="english"></a>

## English

Banking-grade RAG gateway with Keycloak SSO, group-based RBAC, DLP, guardrails, and centralized logging. See the Turkish section above for full documentation. Key points:

- **Auth:** Keycloak SSO with group-based access (no email/password)
- **Guardrails:** DLP (TCKN/IBAN/card/phone/email), prompt injection, toxic filter, rate limit, hallucination detection
- **Monitoring:** Loki + Grafana + Promtail with pre-built dashboards
- **UI:** LibreChat with custom navy theme, JWT forwarding to gateway
- **Policy:** OPA (Rego) per-collection access control
- **LLM:** Ollama (local, private) with Turkish-optimized embeddings

Quick start: `cp .env.example .env && cp librechat/.env.example librechat/.env` then `docker compose up -d`.

## Lisans

MIT
