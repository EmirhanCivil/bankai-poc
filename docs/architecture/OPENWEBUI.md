# OpenWebUI Entegrasyonu

## OpenWebUI Nedir?

OpenWebUI, acik kaynakli, modern bir chat arayuzudur. OpenAI-uyumlu API'lerle calismak uzere tasarlanmistir. Dahili kullanici yonetimi, sohbet gecmisi ve model yonetimi ozellikleri vardir.

## Neden OpenWebUI?

- Modern ve kullanici dostu arayuz
- OpenAI API uyumlulugu (dogrudan `/v1` endpoint'lerine baglanir)
- Filter Function destegi — request/response'u islemeden once/sonra degistirme imkani
- Model bazinda erisim kontrolu (admin panelinden)

## Baglanti Topolojisi

OpenWebUI iki farkli sekilde baglanabilir:

### Yontem 1: Dogrudan Gateway'e (Mevcut Yapilandirma)
```
+-------------+       HTTP/REST        +----------------+
|  OpenWebUI  | ---------------------> | Bankai Gateway |
|  (:3000)    |   host.docker.internal |    (:8000)     |
|             |        :8000/v1        |                |
+-------------+                        +----------------+
```

### Yontem 2: Nginx Proxy Uzerinden
```
+-------------+       HTTP/REST        +---------+       +----------------+
|  OpenWebUI  | ---------------------> |  Nginx  | ----> | Bankai Gateway |
|  (:3000)    |   host.docker.internal | (:8080) |       |    (:8000)     |
|             |        :8080/v1        |         |       |                |
+-------------+                        +---------+       +----------------+
```

**Mevcut durum:** OpenWebUI dogrudan gateway'e (8000) baglanir. Nginx proxy opsiyoneldir.

## Kullanici Kimlik Cozumleme

OpenWebUI, standart OpenAI API'sine uyumlu calisir ve **ek header gondermez**. Bu nedenle kullanici kimligi icin iki yontem vardir:

### Yontem A: API Key ile Cozumleme (Basit)

Gateway'deki `APIKEY_USER_MAP` kullanilir:

```python
APIKEY_USER_MAP = {
    "sk-dummy": "ali",       # OpenWebUI default key
    "sk-hr": "ali",
    "sk-compliance": "ayse",
    "sk-finance": "veli",
}
```

OpenWebUI `OPENAI_API_KEY=sk-dummy` ile baslatildiginda, tum istekler `ali` kullanicisi olarak cozumlenir.

### Yontem B: Nginx Header Injection

Nginx, OpenWebUI'nin gonderdigi `X-OpenWebUI-User-Name` header'ini okuyarak gateway'e `X-User`, `X-Roles`, `X-Tenant` header'lari enjekte eder:

```nginx
proxy_set_header X-User   $poc_user2;
proxy_set_header X-Roles  $poc_roles;
proxy_set_header X-Tenant $poc_tenant;
```

**Not:** OpenWebUI bu header'lari yalnizca bazi durumlarda gonderir. Bu nedenle API key yontemi daha guvenilirdir.

### Yontem C: Filter Function (Gelismis)

OpenWebUI'nin admin panelinden bir **Filter Function** tanimlanabilir. Bu fonksiyon, her istekten once calisarak `body["user"]` bilgisini enjekte eder:

```python
class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0)

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: dict) -> dict:
        # OpenWebUI'nin dahili user bilgisini body'ye ekle
        body["user"] = __user__.get("name", "anonymous")
        return body

    def outlet(self, body: dict, __user__: dict) -> dict:
        return body
```

Bu yontemde:
1. OpenWebUI kullanici giris yapar (dahili auth)
2. Filter Function, `__user__["name"]` degerini `body["user"]`'a yazar
3. Gateway, `body["user"]`'i `USER_ROLE_MAP`'te bulur
4. Roller ve tenant otomatik cikarilir

## Model Erisim Kontrolu

OpenWebUI admin panelinden model bazinda erisim kontrolu uygulanabilir:

1. **Admin > Models** sayfasina git
2. Ilgili modeli sec
3. **Access Control** bolumunde izin verilen kullanicilari/gruplari belirle

Bu sayede farkli kullanicilar farkli model/endpoint'lere yonlendirilebilir.

## Docker Yapilandirmasi

```bash
docker run -d --name openwebui \
  -p 3000:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8000/v1 \
  -e OPENAI_API_KEY=sk-dummy \
  --add-host host.docker.internal:host-gateway \
  ghcr.io/open-webui/open-webui:main
```

**Parametreler:**
- `-p 3000:8080` — Host'un 3000 portunu container'in 8080 portuna baglar
- `OPENAI_API_BASE_URL` — Gateway'in OpenAI-uyumlu endpoint'i
- `OPENAI_API_KEY` — `APIKEY_USER_MAP`'teki key
- `--add-host` — `host.docker.internal` cozumlemesi

## API Key

- **Varsayilan key:** `sk-dummy`
- `APIKEY_USER_MAP`'te `ali` kullanicisina eslenir
- Coklu kullanici icin farkli key'ler kullanilabilir (`sk-hr`, `sk-compliance`, `sk-finance`)
- PoC degerleridir, production'da degistirilmelidir

## Bilinen Kisitlamalar

- `X-OpenWebUI-User-Name` header'i her zaman gonderilmez — API key fallback gerekir
- Tek API key kullanildiginda tum kullanicilar ayni kisi olarak gorulur
- Filter Function kullanilmadan cok kullanicili RBAC mumkun degildir
- `webui.db` (SQLite) container icerisinde tutulur, kalicilik icin volume mount gerekir
- OpenWebUI kullanici kimligi ile bankai kullanici kimligi eslestirilmelidir
