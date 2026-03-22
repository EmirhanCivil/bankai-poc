# LibreChat vs OpenWebUI — Karsilastirma

Bu dokuman, Bankai PoC'de kullanilan iki chat arayuzunun ortak ve farkli noktalarini karsilastirir.

## Ortak Noktalar

Her iki UI da:
- Ayni **Bankai Gateway**'e (`:8000`) **dogrudan** baglanir
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
| **Akis** | LibreChat → Gateway (:8000) | OpenWebUI → Gateway (:8000) |
| **Konfigürasyon** | `librechat.yaml` (custom endpoint) | Admin panelinden (SQLite config tablosu) |
| **API Key** | `sk-bankai` | `sk-dummy` (Gateway'de kullanici cozumlemek icin kullanilir) |

### Kullanici Kimlik Cozumleme

| | LibreChat | OpenWebUI |
|---|-----------|-----------|
| **Mekanizma** | `req.user` alanindaki MongoDB ObjectID | `Authorization` header'indaki API key |
| **Map** | `LIBRECHAT_USERID_MAP` (gateway icinde) | `APIKEY_USER_MAP` (gateway icinde) |
| **Ornek** | `"aaa111bbb222ccc333ddd444"` → `"ali"` | `sk-dummy` → `"ali"` |
| **Coklu kullanici** | Her kullanici farkli ObjectID ile otomatik ayrilir | Her kullanici farkli API key kullanmali |
| **RBAC calisiyor mu?** | Evet | Evet |
| **Dahili auth** | MongoDB'de kullanici/sifre | SQLite'da kullanici/sifre |

### UI Ozellikleri

| Ozellik | LibreChat | OpenWebUI |
|---------|-----------|-----------|
| **Arayuz dili** | Cok dilli | Cok dilli |
| **Sohbet gecmisi** | MongoDB'de | SQLite'da (webui.db) |
| **Model secimi** | Custom endpoint tanimi | Admin panelinden |
| **Coklu endpoint** | Evet (custom endpoints) | Evet (connections) |
| **Filter/Plugin** | Hayir (ozel eklenti yok) | Evet (Filter Function) |
| **Admin paneli** | Sinirli | Kapsamli (model erisim kontrolu dahil) |
| **Kurulum** | Docker Compose (+ MongoDB) | Tek container |
| **Veri tabani** | MongoDB | SQLite |

## Karsilastirma Tablosu (Ozet)

| Kriter | LibreChat | OpenWebUI | Kazanan |
|--------|-----------|-----------|---------|
| Kurulum kolayligi | Docker Compose + MongoDB | Docker run | OpenWebUI |
| Kullanici cozumleme | Otomatik (ObjectID) | API key bazli (statik) | LibreChat |
| RBAC calisiyor mu? | Evet | Evet | Esit |
| UI ozellikleri | Temel | Zengin (Filter, Admin) | OpenWebUI |
| Eklenti destegi | Yok | Filter Function | OpenWebUI |
| Kaynak tuketimi | Daha fazla (MongoDB ek) | Daha az | OpenWebUI |
| Yeni kullanici ekleme | Otomatik (kayit ol, ObjectID olusur) | `APIKEY_USER_MAP`'e yeni key ekle | LibreChat |

## Hangi Senaryo Icin Hangisi?

### LibreChat Tercih Edilmeli
- **Coklu kullanici / dinamik ortamda** — Yeni kullanici kayit oldugunda otomatik ObjectID olusur, gateway'e map eklenince RBAC calisir
- **Production'a yakin PoC'lerde** — MongoDB tabanli kullanici yonetimi daha olgun
- **Birden fazla LLM endpoint kullanilacaksa** — Custom endpoint destegi kapsamli

### OpenWebUI Tercih Edilmeli
- **Sabit kullanici listeli ortamlarda** — API key map'ine bir kez ekle, sonra degismez
- **Filter Function ile ozellestirme gerektiginde** — Request/response manipulasyonu mumkun
- **Admin panelinden model erisim kontrolu istendiginde** — GUI uzerinden yonetilebilir

## Nginx Nerede?

Nginx (:8080) **opsiyonel** bir bilesendir. Ne OpenWebUI ne de LibreChat Nginx'i kullanir. Her iki UI de dogrudan Gateway'e (:8000) baglanir. Nginx yalnizca harici istemciler (curl, Postman vb.) icin `X-OpenWebUI-User-Name` header'i uzerinden RBAC saglayan bir katmandir.

## Sonuc

Bankai PoC'de her iki UI da calisir durumda tutulmustur ve **her ikisinde de RBAC calisir**:
- **LibreChat:** MongoDB ObjectID → `LIBRECHAT_USERID_MAP` → kullanici → rol → tenant
- **OpenWebUI:** API key → `APIKEY_USER_MAP` → kullanici → `USER_ROLE_MAP` → rol → tenant
