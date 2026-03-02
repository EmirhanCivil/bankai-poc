# LibreChat vs OpenWebUI — Karsilastirma

Bu dokuman, Bankai PoC'de kullanilan iki chat arayuzunun ortak ve farkli noktalarini karsilastirir.

## Ortak Noktalar

Her iki UI da:
- Ayni **Bankai Gateway**'e (`:8000`) baglanir (OpenWebUI Nginx uzerinden, LibreChat dogrudan)
- Ayni **Ollama LLM** backend'ini (`qwen2.5:7b-instruct`) kullanir
- Ayni **OPA RBAC** politikalarina tabi olur
- Ayni **DLP** kontrolunden gecer
- Ayni **audit log**'a yazilir
- **OpenAI-uyumlu** `/v1/chat/completions` endpoint'ini cagirir
- **Docker** container olarak calisir
- `host.docker.internal` ile host makineye erisir

## Farkli Noktalar

### Baglanti Yontemi

| | LibreChat | OpenWebUI |
|---|-----------|-----------|
| **Akis** | LibreChat → Gateway (:8000) | OpenWebUI → Nginx (:8080) → Gateway (:8000) |
| **Konfigürasyon** | `librechat.yaml` (custom endpoint) | Ortam degiskeni (`OPENAI_API_BASE_URL`) |
| **API Key** | `sk-bankai` | `dummy` (Nginx'e gecis icin, RBAC'ta kullanilmaz) |

### Kullanici Kimlik Cozumleme

| | LibreChat | OpenWebUI |
|---|-----------|-----------|
| **Mekanizma** | `req.user` alanindaki MongoDB ObjectID | Nginx header injection (`X-OpenWebUI-User-Name` → `X-User`) |
| **Map** | `LIBRECHAT_USERID_MAP` (gateway icinde) | `nginx.conf`'taki map kurallari |
| **Ornek** | `"69a491c78b6939fccb7a25b5"` → `"ali"` | `X-OpenWebUI-User-Name: ali` → `X-User: ali, X-Roles: hr` |
| **Coklu kullanici** | Her kullanici farkli ObjectID ile otomatik ayrilir | Her kullanici farkli header ile Nginx'te eslesir |
| **RBAC calisiyor mu?** | Evet | Evet (Nginx sayesinde) |
| **Dahili auth** | MongoDB'de kullanici/sifre | SQLite'da kullanici/sifre |

### UI Ozellikleri

| Ozellik | LibreChat | OpenWebUI |
|---------|-----------|-----------|
| **Arayuz dili** | Cok dilli | Cok dilli |
| **Sohbet gecmisi** | MongoDB'de | SQLite'da (webui.db) |
| **Model secimi** | Custom endpoint tanimi | OPENAI_API_BASE_URL |
| **Coklu endpoint** | Evet (custom endpoints) | Evet (connections) |
| **Filter/Plugin** | Hayir (ozel eklenti yok) | Evet (Filter Function) |
| **Admin paneli** | Sinirli | Kapsamli (model erisim kontrolu dahil) |
| **Kurulum** | Docker Compose (+ MongoDB) | Tek container (+ Nginx) |
| **Veri tabani** | MongoDB | SQLite |

## Karsilastirma Tablosu (Ozet)

| Kriter | LibreChat | OpenWebUI | Kazanan |
|--------|-----------|-----------|---------|
| Kurulum kolayligi | Docker Compose + MongoDB | Docker run + Nginx | Esit |
| Kullanici cozumleme | Otomatik (ObjectID) | Nginx map (statik) | LibreChat |
| RBAC calisiyor mu? | Evet | Evet (Nginx ile) | Esit |
| UI ozellikleri | Temel | Zengin (Filter, Admin) | OpenWebUI |
| Eklenti destegi | Yok | Filter Function | OpenWebUI |
| Kaynak tuketimi | Daha fazla (MongoDB ek) | Daha az | OpenWebUI |
| Yeni kullanici ekleme | Otomatik (kayit ol, ObjectID olusur) | nginx.conf'a elle ekle | LibreChat |

## Hangi Senaryo Icin Hangisi?

### LibreChat Tercih Edilmeli
- **Coklu kullanici / dinamik ortamda** — Yeni kullanici kayit oldugunda otomatik ObjectID olusur, gateway'e map eklenince RBAC calisir
- **Production'a yakin PoC'lerde** — MongoDB tabanli kullanici yonetimi daha olgun
- **Birden fazla LLM endpoint kullanilacaksa** — Custom endpoint destegi kapsamli

### OpenWebUI Tercih Edilmeli
- **Sabit kullanici listeli ortamlarda** — Nginx map'ine bir kez ekle, sonra degismez
- **Filter Function ile ozellestirme gerektiginde** — Request/response manipulasyonu mumkun
- **Admin panelinden model erisim kontrolu istendiginde** — GUI uzerinden yonetilebilir

## Sonuc

Bankai PoC'de her iki UI da calisir durumda tutulmustur ve **her ikisinde de RBAC calisir**:
- **LibreChat:** MongoDB ObjectID → `LIBRECHAT_USERID_MAP` → kullanici → rol → tenant
- **OpenWebUI:** `X-OpenWebUI-User-Name` → Nginx map → `X-User/X-Roles/X-Tenant` header injection → gateway
