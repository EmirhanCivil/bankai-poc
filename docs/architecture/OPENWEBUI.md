# OpenWebUI Entegrasyonu

## OpenWebUI Nedir?

OpenWebUI, acik kaynakli, modern bir chat arayuzudur. OpenAI-uyumlu API'lerle calismak uzere tasarlanmistir. Dahili kullanici yonetimi, sohbet gecmisi ve model yonetimi ozellikleri vardir.

## Neden OpenWebUI?

- Modern ve kullanici dostu arayuz
- OpenAI API uyumlulugu (dogrudan `/v1` endpoint'lerine baglanir)
- Filter Function destegi — request/response'u islemeden once/sonra degistirme imkani
- Model bazinda erisim kontrolu (admin panelinden)

## Baglanti Topolojisi (Mevcut Yapilandirma)

OpenWebUI, **dogrudan Gateway'e** baglanir. Nginx'i **atlar**.

```
+-------------+       HTTP/REST        +----------------+
|  OpenWebUI  | ---------------------> | Bankai Gateway |
|  (:3000)    |   host.docker.internal |    (:8000)     |
|             |        :8000/v1        |                |
+-------------+                        +----------------+
                                           |
                                      Kullanici Cozumleme:
                                      Authorization: Bearer sk-dummy
                                           ↓ APIKEY_USER_MAP
                                      user: ali
                                      roles: ["hr"]
                                      tenant: hr
```

**Neden Nginx kullanilmiyor?** OpenWebUI, OpenAI-uyumlu API'lere `X-OpenWebUI-User-Name` header'i **gondermez**. Bu nedenle Nginx'teki map kurallari tetiklenmez. Bunun yerine Gateway, `Authorization` header'indaki API key'i `APIKEY_USER_MAP` tablosunda arayarak kullaniciyi cozer.

> **Not:** Nginx (:8080) opsiyonel olarak mevcuttur. UI'lar tarafindan kullanilmaz,
> yalnizca harici istemciler (curl, Postman vb.) icin header injection ile RBAC saglar.

## RBAC Nasil Calisiyor?

### Adim adim akis:

1. **ali** OpenWebUI'da login olur (dahili auth, SQLite'da kayitli)
2. ali soru sorar
3. OpenWebUI istegi dogrudan Gateway'e gonderir: `Authorization: Bearer sk-dummy`
4. Gateway `APIKEY_USER_MAP`'te `sk-dummy` → `ali` olarak cozer
5. Gateway `USER_ROLE_MAP`'te `ali` → `["hr"]` → tenant: `hr`
6. OPA kontrolu: ali(hr) + hr koleksiyonu → **IZIN VERILDI**
7. Qdrant'ta `hr` koleksiyonunda arama yapilir

### ayse login olursa:
- OpenWebUI'da API key `sk-compliance` olarak ayarlanir
- Gateway: sk-compliance → ayse → compliance → compliance koleksiyonu

### veli login olursa:
- OpenWebUI'da API key `sk-finance` olarak ayarlanir
- Gateway: sk-finance → veli → finance → finance koleksiyonu

**Her API key bir kullaniciya baglidir, her kullanici sadece kendi ekibinin dokumanlarini gorebilir.**

## Nginx (Opsiyonel)

Nginx (:8080) OpenWebUI tarafindan kullanilmaz. Yalnizca harici istemciler (curl, Postman vb.) icin `X-OpenWebUI-User-Name` header'ini `X-User/X-Roles/X-Tenant` header'larina donusturup RBAC saglayan opsiyonel bir reverse proxy katmanidir.

Detaylar icin: `nginx/nginx.conf`

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
- `OPENAI_API_BASE_URL` — **Dogrudan Gateway adresi** (`:8000`)
- `OPENAI_API_KEY` — Gateway'in `APIKEY_USER_MAP`'inde kullanici cozumlemek icin kullanilir (`sk-dummy` → `ali`)
- `--add-host` — `host.docker.internal` cozumlemesi

## Model Erisim Kontrolu

OpenWebUI admin panelinden model bazinda erisim kontrolu uygulanabilir:

1. **Admin > Models** sayfasina git
2. Ilgili modeli sec
3. **Access Control** bolumunde izin verilen kullanicilari/gruplari belirle

Bu sayede farkli kullanicilar farkli model/endpoint'lere yonlendirilebilir.

## Bilinen Kisitlamalar

- `APIKEY_USER_MAP` statik — yeni kullanici icin yeni API key eklenmeli (`app_main.py` veya `APIKEY_USER_MAP` env)
- Tek API key ile tek kullanici eslesir — farkli kullanicilar farkli key kullanmali
- `webui.db` (SQLite) container icerisinde tutulur, kalicilik icin volume mount gerekir
