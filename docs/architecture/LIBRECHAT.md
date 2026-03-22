# LibreChat Entegrasyonu

## LibreChat Nedir?

LibreChat, acik kaynakli, coklu LLM destekleyen bir chat arayuzudur. OpenAI, Anthropic, Google ve ozel (custom) endpoint'leri destekler. Bankai PoC'de **custom endpoint** ozelligi kullanilarak gateway'e baglanir.

## Neden LibreChat?

- Kullanici yonetimi (kayit, oturum) dahili olarak MongoDB'de tutulur
- Ozel endpoint tanimlamasiyla herhangi bir OpenAI-uyumlu API'ye baglanabilir
- Request body'de `user` alani olarak MongoDB ObjectID gonderir — bu sayede kullanici bazli yetkilendirme mumkun olur
- Sohbet gecmisi ve basliklama ozellikleri yerlesiktir

## Baglanti Topolojisi

```
+-------------+       HTTP/REST        +----------------+
|  LibreChat  | ---------------------> | Bankai Gateway |
|  (:3080)    |   host.docker.internal |    (:8000)     |
|             |        :8000/v1        |                |
+------+------+                        +--------+-------+
       |                                        |
       v                                        v
+------+------+                        +---------+------+
|   MongoDB   |                        | Qdrant + OPA   |
|  (:27017)   |                        | + Ollama       |
+-------------+                        +----------------+
```

**Onemli:** LibreChat dogrudan gateway'e baglanir (port 8000). Nginx proxy'si (8080) kullanilmaz.

## Kullanici Kimlik Cozumleme

LibreChat, her API isteginin body'sindeki `user` alanina kullanicinin **MongoDB ObjectID**'sini yazar. Ornek:

```json
{
  "model": "qwen2.5:7b-instruct",
  "messages": [{"role": "user", "content": "Izin suresi kac gun?"}],
  "user": "aaa111bbb222ccc333ddd444"
}
```

Gateway bu ObjectID'yi `LIBRECHAT_USERID_MAP` ile bankai kullanici adina cevirir:

```python
LIBRECHAT_USERID_MAP = {
    "aaa111bbb222ccc333ddd444": "ali",
    "bbb222ccc333ddd444eee555": "ayse",
    "ccc333ddd444eee555fff666": "veli",
}
```

**Cozumleme akisi:**
1. `req.user` alinir (`"aaa111bbb222ccc333ddd444"`)
2. `USER_ROLE_MAP`'te dogrudan aranir — bulunamaz
3. `LIBRECHAT_USERID_MAP`'te aranir — `"ali"` bulunur
4. `ali` icin roller cikarilir: `["hr"]`
5. Tenant: `"hr"`

## librechat.yaml Konfigurasyonu

```yaml
version: 1.2.1
cache: true
registration:
  socialLogins: []

endpoints:
  custom:
    - name: "Bankai RAG"
      apiKey: "${LIBRECHAT_API_KEY}"
      baseURL: "http://host.docker.internal:8000/v1"
      models:
        default: ["qwen2.5:7b-instruct"]
        fetch: true
      titleConvo: true
      titleModel: "qwen2.5:7b-instruct"
      summarize: false
      dropParams:
        - "stop"
        - "frequency_penalty"
        - "presence_penalty"
        - "top_p"
```

**Aciklamalar:**
- `apiKey: "${LIBRECHAT_API_KEY}"` — Gateway'e gonderilen API key. `librechat/.env`'de tanimlanir. Fallback olarak `APIKEY_USER_MAP`'te eslenir, ancak asil cozumleme `user` alanindaki ObjectID uzerinden yapilir.
- `baseURL` — `host.docker.internal` sayesinde Docker icerisinden host makinedeki gateway'e erisilir.
- `dropParams` — Gateway'in desteklemedigi OpenAI parametreleri atilir.
- `summarize: false` — Ozet olusturma devre disi (gereksiz LLM cagrisi onlenir).

## Docker Compose Yapisi

```yaml
services:
  librechat:
    image: ghcr.io/danny-avila/librechat-dev:latest
    container_name: librechat
    ports:
      - "3080:3080"
    depends_on:
      - mongodb
    extra_hosts:
      - "host.docker.internal:host-gateway"
    env_file:
      - .env
    volumes:
      - ./librechat.yaml:/app/librechat.yaml:ro

  mongodb:
    image: mongo:8.0
    container_name: librechat-mongodb
    volumes:
      - librechat_mongo:/data/db
```

- `extra_hosts` — `host.docker.internal`'in container icerisinden cozumlenmesini saglar.
- `env_file` — `librechat/.env` dosyasindan ortam degiskenleri yuklenir.

## API Key

- **Kullanilan key:** `librechat/.env`'deki `LIBRECHAT_API_KEY` degeri
- Bu key `APIKEY_USER_MAP`'te ilgili kullaniciya eslenmelidir (fallback)
- **Asil kimlik cozumleme:** `user` alanindaki MongoDB ObjectID kullanilir
- PoC degeridir, production'da her kullanicinin kendi key'i olmalidir

## Bilinen Kisitlamalar

- `LIBRECHAT_USERID_MAP` statiktir — yeni kullanici eklendiginde gateway kodunda guncellenmeli
- LibreChat'in `user` alanina ObjectID yazmasi dokumante edilmemis bir davranistir
- Tek API key tum kullanicilar icin ortaktir (PoC)
- LibreChat sohbet gecmisi MongoDB'de tutulur, bu veri gateway tarafindan audit edilmez
