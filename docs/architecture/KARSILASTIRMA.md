# LibreChat vs OpenWebUI — Karsilastirma

Bu dokuman, Bankai PoC'de kullanilan iki chat arayuzunun ortak ve farkli noktalarini karsilastirir.

## Ortak Noktalar

Her iki UI da:
- Ayni **Bankai Gateway**'e (`:8000`) baglanir
- Ayni **Ollama LLM** backend'ini (`qwen2.5:7b-instruct`) kullanir
- Ayni **OPA RBAC** politikalarina tabi olur
- Ayni **DLP** kontrolunden gecer
- Ayni **audit log**'a yazilir
- **OpenAI-uyumlu** `/v1/chat/completions` endpoint'ini cagirir
- **Docker** container olarak calisir
- `host.docker.internal` ile host makineye erisir

## Farkli Noktalar

### Kullanici Kimlik Cozumleme

| | LibreChat | OpenWebUI |
|---|-----------|-----------|
| **Mekanizma** | `req.user` alanindaki MongoDB ObjectID | API key / Filter Function / Nginx header |
| **Map** | `LIBRECHAT_USERID_MAP` | `APIKEY_USER_MAP` |
| **Ornek deger** | `"69a491c78b6939fccb7a25b5"` → `"ali"` | `"sk-dummy"` → `"ali"` |
| **Coklu kullanici** | Her kullanici farkli ObjectID ile otomatik ayrilir | Filter Function veya farkli API key gerekir |
| **Dahili auth** | MongoDB'de kullanici/sifre | SQLite'da kullanici/sifre |

### Baglanti Yontemi

| | LibreChat | OpenWebUI |
|---|-----------|-----------|
| **Hedef** | Dogrudan Gateway (:8000) | Dogrudan Gateway (:8000) veya Nginx (:8080) |
| **Konfigürasyon** | `librechat.yaml` (custom endpoint) | Ortam degiskenleri (`OPENAI_API_BASE_URL`) |
| **API Key** | `sk-bankai` | `sk-dummy` |

### UI Ozellikleri

| Ozellik | LibreChat | OpenWebUI |
|---------|-----------|-----------|
| **Arayuz dili** | Cok dilli | Cok dilli |
| **Sohbet gecmisi** | MongoDB'de | SQLite'da (webui.db) |
| **Model secimi** | Custom endpoint tanimi | OPENAI_API_BASE_URL |
| **Coklu endpoint** | Evet (custom endpoints) | Evet (connections) |
| **Filter/Plugin** | Hayir (ozel eklenti yok) | Evet (Filter Function) |
| **Admin paneli** | Sinirli | Kapsamli (model erisim kontrolu dahil) |
| **Kurulum** | Docker Compose (+ MongoDB) | Tek container |
| **Veri tabani** | MongoDB | SQLite |

## Karsilastirma Tablosu (Ozet)

| Kriter | LibreChat | OpenWebUI | Kazanan |
|--------|-----------|-----------|---------|
| Kurulum kolayligi | Docker Compose + MongoDB | Tek docker run | OpenWebUI |
| Kullanici cozumleme | Otomatik (ObjectID) | Manuel (API key/Filter) | LibreChat |
| RBAC uyumlulugu | Kolay (her kullanici ayri) | Zor (ek yapilandirma gerekli) | LibreChat |
| UI ozellikleri | Temel | Zengin (Filter, Admin) | OpenWebUI |
| Eklenti destegi | Yok | Filter Function | OpenWebUI |
| Kaynak tuketimi | Daha fazla (MongoDB ek) | Daha az (tek container) | OpenWebUI |

## Hangi Senaryo Icin Hangisi?

### LibreChat Tercih Edilmeli
- **Coklu kullanici / RBAC senaryolarinda** — Her kullanici otomatik olarak farkli ObjectID ile tanimlanir, ek yapilandirma gerekmez
- **Production'a yakin PoC'lerde** — MongoDB tabanli kullanici yonetimi daha olgun
- **Birden fazla LLM endpoint kullanilacaksa** — Custom endpoint destegi kapsamli

### OpenWebUI Tercih Edilmeli
- **Hizli demo/prototiplerde** — Tek container, dakikalar icerisinde hazir
- **Filter Function ile ozellestirme gerektiginde** — Request/response manipulasyonu mumkun
- **Admin panelinden model erisim kontrolu istendiginde** — GUI uzerinden yonetilebilir
- **Tek kullanicili senaryolarda** — API key ile basit cozumleme yeterli

## Sonuc

Bankai PoC'de her iki UI da calisir durumda tutulmustur. RBAC ve coklu kullanici senaryolari icin **LibreChat** daha uygun bir secimdir, cunku kullanici kimligi otomatik cozumlenir. **OpenWebUI** ise hizli demo ve tek kullanicili senaryolar icin idealdir.
