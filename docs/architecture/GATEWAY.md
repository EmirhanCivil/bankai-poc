# Gateway Pipeline — Detayli Aciklama

Bankai Gateway, FastAPI uzerine insa edilmis OpenAI-uyumlu bir RAG gateway'dir. Tum istemler (OpenWebUI, LibreChat veya dogrudan API) bu gateway uzerinden gecer.

## Request Pipeline

Her `/v1/chat/completions` istegi asagidaki asamalardan gecer:

```
Istek Geldi
    |
    v
[1] Kullanici Cozumleme
    |  - Header (X-User, X-OpenWebUI-User-Name)
    |  - Body (req.user → LibreChat MongoDB ObjectID)
    |  - API Key (Authorization header → APIKEY_USER_MAP)
    |  - Fallback: "anonymous"
    |
    v
[2] Rol & Tenant Cikarsama
    |  - USER_ROLE_MAP'ten roller alinir
    |  - Tek rol varsa tenant = rol adi
    |
    v
[3] DLP Giris Kontrolu
    |  - Soru icerisindeki TCKN (11 haneli sayi) maskelenir
    |  - Ornek: "12345678901" → "***********"
    |
    v
[4] OPA Yetkilendirme
    |  - POST /v1/data/rag/authz/allow
    |  - input: {user: {username, roles}, resource: {collection}}
    |  - Reddedilirse: HTTP 403
    |
    v
[5] Vektor Arama (Retrieval)
    |  - Soru embed edilir (paraphrase-multilingual-MiniLM-L12-v2)
    |  - Qdrant'ta ilgili tenant koleksiyonunda arama
    |  - En yakin 4 chunk getirilir
    |
    v
[6] LLM Cagri (Generation)
    |  - System prompt + kaynaklar + soru → Ollama
    |  - Model: qwen2.5:7b-instruct
    |  - Grounding prompt: sadece kaynaklara dayanarak cevap ver
    |
    v
[7] DLP Cikis Kontrolu
    |  - LLM cevabindaki TCKN'ler maskelenir
    |
    v
[8] Audit Log
    |  - JSON satiri → audit/events.jsonl
    |  - Icerik: timestamp, user, tenant, izin durumu, kaynaklar, DLP bulgulari, latency
    |
    v
Cevap Donduruldu (stream veya non-stream)
```

## Kullanici Cozumleme Oncelik Sirasi

Gateway, kullanici kimligini birden fazla kaynaktan cozumleyebilir. Oncelik sirasi:

1. `X-User` header'i (Nginx tarafindan enjekte edilir)
2. `X-OpenWebUI-User-Name` header'i
3. `X-OpenWebUI-User-Email` header'i
4. `req.user` body alani — dogrudan bilinen kullanici adi mi?
5. `req.user` body alani — LibreChat MongoDB ObjectID → `LIBRECHAT_USERID_MAP`
6. `Authorization` header → `APIKEY_USER_MAP`
7. Fallback: `"anonymous"`

## OPA Policy Yapisi

OPA'da `policies/rag.rego` dosyasi kullanilir:

```rego
package rag.authz

default allow = false

allow {
  input.resource.collection == "hr"
  input.user.roles[_] == "hr"
}

allow {
  input.resource.collection == "compliance"
  input.user.roles[_] == "compliance"
}

allow {
  input.resource.collection == "finance"
  input.user.roles[_] == "finance"
}
```

**Kural:** Kullanicinin rollerinden biri, eristigi koleksiyonun adiyla eslesmelidir. Ornegin `ali` (rol: `hr`) sadece `hr` koleksiyonuna erisebilir.

## DLP Mekanizmasi

PoC'de yalnizca TCKN (Turkiye Cumhuriyeti Kimlik Numarasi) tespiti yapilir:

- **Pattern:** `\b\d{11}\b` (11 haneli ardisik rakam)
- **Uygulama:** Hem giris (soru) hem cikis (cevap) uzerinde
- **Maskeleme:** `***********`
- **Audit:** Tespit edilen degerler audit log'a kaydedilir

## Audit Log Formati

Her istek icin `audit/events.jsonl` dosyasina bir JSON satiri yazilir:

```json
{
  "ts": 1709337600.123,
  "user": {"username": "ali", "roles": ["hr"]},
  "tenant": "hr",
  "allowed": true,
  "sources": [{"doc_id": "hr_mevzuat.txt", "score": 0.82}],
  "dlp_in": [],
  "dlp_out": [],
  "latency_ms": 2340,
  "model": "qwen2.5:7b-instruct"
}
```

## Endpoint Listesi

| Method | Path | Aciklama |
|--------|------|----------|
| GET | `/__ping` | Health check |
| GET | `/__debug` | Konfigurasyonu goster |
| POST | `/admin/reindex/{tenant}` | Tenant dokumanlarini indeksle |
| POST | `/ask` | Dogrudan RAG sorgusu (header-based auth) |
| GET | `/v1/models` | OpenAI-uyumlu model listesi |
| GET | `/models` | OpenAI-uyumlu model listesi (alias) |
| POST | `/v1/chat/completions` | OpenAI-uyumlu chat endpoint (stream destekli) |

## Embedding Modeli

- **Model:** `paraphrase-multilingual-MiniLM-L12-v2`
- **Boyut:** 384 dimension
- **Secim nedeni:** Turkce retrieval kalitesi. Onceki model (`all-MiniLM-L6-v2`) yalnizca Ingilizce destekliyordu ve Turkce sorgularda dusuk skor uretiyordu.

## Chunking Stratejisi

- Dokumanlar paragraf sinirlarina gore bolunur
- Maksimum chunk boyutu: 900 karakter (`CHUNK_MAX_CHARS`)
- Paragraflar kucukse birlestilir, buyukse karakter bazinda bolunur
- Her chunk icin deterministik ID uretilir (SHA-256 hash)
