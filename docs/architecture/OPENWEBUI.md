# OpenWebUI Entegrasyonu

## OpenWebUI Nedir?

OpenWebUI, acik kaynakli, modern bir chat arayuzudur. OpenAI-uyumlu API'lerle calismak uzere tasarlanmistir. Dahili kullanici yonetimi, sohbet gecmisi ve model yonetimi ozellikleri vardir.

## Neden OpenWebUI?

- Modern ve kullanici dostu arayuz
- OpenAI API uyumlulugu (dogrudan `/v1` endpoint'lerine baglanir)
- Filter Function destegi — request/response'u islemeden once/sonra degistirme imkani
- Model bazinda erisim kontrolu (admin panelinden)

## Baglanti Topolojisi (Mevcut Yapilandirma)

OpenWebUI, **Nginx uzerinden** Gateway'e baglanir. Bu, RBAC'in calismasini saglayan yapidir.

```
+-------------+       HTTP/REST        +---------+       HTTP/REST        +----------------+
|  OpenWebUI  | ---------------------> |  Nginx  | ---------------------> | Bankai Gateway |
|  (:3000)    |   host.docker.internal | (:8080) |   host.docker.internal |    (:8000)     |
|             |        :8080/v1        |         |        :8000           |                |
+-------------+                        +---------+                        +----------------+
                                           |
                                      Header Injection:
                                      X-OpenWebUI-User-Name: ali
                                           ↓
                                      X-User: ali
                                      X-Roles: hr
                                      X-Tenant: hr
```

**Neden Nginx zorunlu?** OpenWebUI, backend'e sadece `X-OpenWebUI-User-Name` header'i gonderir. Gateway ise `X-User`, `X-Roles`, `X-Tenant` bekler. Nginx bu donusumu yapar ve kullaniciya gore rol/tenant atamasini gerceklestirir.

## RBAC Nasil Calisiyor?

### Adim adim akis:

1. **ali** OpenWebUI'da login olur (dahili auth, SQLite'da kayitli)
2. ali soru sorar
3. OpenWebUI istegi Nginx'e gonderir: `X-OpenWebUI-User-Name: ali`
4. Nginx `nginx.conf`'taki map kurallariyla:
   - `ali` → `poc_roles: "hr"` → `poc_tenant: "hr"`
5. Nginx gateway'e ilettigi istege su header'lari ekler:
   - `X-User: ali`
   - `X-Roles: hr`
   - `X-Tenant: hr`
6. Gateway `X-User` header'ini gorur → **ilk oncelikli kaynak** → `ali` olarak cozumler
7. OPA kontrolu: ali(hr) + hr koleksiyonu → **IZIN VERILDI**
8. Qdrant'ta `hr` koleksiyonunda arama yapilir

### ayse login olursa:
- Nginx: `ayse` → `compliance` → `compliance`
- Gateway: ayse(compliance) → compliance koleksiyonu

### veli login olursa:
- Nginx: `veli` → `finance` → `finance`
- Gateway: veli(finance) → finance koleksiyonu

**Her kullanici sadece kendi ekibinin dokumanlarini gorebilir.**

## Nginx Map Kurallari

`nginx/nginx.conf` dosyasindaki kullanici-rol eslemesi:

```nginx
# user -> roles (PoC)
map $poc_user2 $poc_roles {
    default "";
    "ali"  "hr";
    "ayse" "compliance";
    "veli" "finance";
}

# roles -> tenant
map $poc_roles $poc_tenant {
    default "";
    "hr"         "hr";
    "compliance" "compliance";
    "finance"    "finance";
}
```

Bilinmeyen kullanici (map'te olmayan) icin roller bos doner ve Nginx `403 Forbidden` dondurur:

```nginx
if ($poc_roles = "") { return 403; }
```

## Docker Yapilandirmasi

```bash
docker run -d --name openwebui \
  -p 3000:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1 \
  -e OPENAI_API_KEY=dummy \
  --add-host host.docker.internal:host-gateway \
  ghcr.io/open-webui/open-webui:main
```

**Parametreler:**
- `-p 3000:8080` — Host'un 3000 portunu container'in 8080 portuna baglar
- `OPENAI_API_BASE_URL` — **Nginx'in adresi** (`:8080`), dogrudan gateway degil
- `OPENAI_API_KEY` — Nginx'e gecmek icin gerekli (gateway'e kadar ulasmaz, Nginx kendi header'larini koyar)
- `--add-host` — `host.docker.internal` cozumlemesi

## Model Erisim Kontrolu

OpenWebUI admin panelinden model bazinda erisim kontrolu uygulanabilir:

1. **Admin > Models** sayfasina git
2. Ilgili modeli sec
3. **Access Control** bolumunde izin verilen kullanicilari/gruplari belirle

Bu sayede farkli kullanicilar farkli model/endpoint'lere yonlendirilebilir.

## Bilinen Kisitlamalar

- Nginx'teki kullanici-rol map'i statik — yeni kullanici eklendiginde `nginx.conf` guncellenmeli
- OpenWebUI'daki kullanici adi ile Nginx map'teki isim **birebir esmeli** (buyuk/kucuk harf dahil)
- `webui.db` (SQLite) container icerisinde tutulur, kalicilik icin volume mount gerekir
- Nginx'teki map'te olmayan kullanicilar 403 alir
