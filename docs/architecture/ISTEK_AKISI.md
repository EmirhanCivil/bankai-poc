# Bir Istegin Yolculugu — Bastan Sona

Bu dokuman, bir kullanicinin soru sordugu andan cevabi ekranda gordugu ana kadar her katmanda neler oldugunu en basit haliyle anlatir.

---

## Ornek Senaryo

**ali** isimli kullanici, LibreChat'e girip soruyor:

> "Yillik izin suresi kac gun?"

---

## 1. KULLANICI ARAYUZU (UI)

### Ne yapar?
Kullanicinin yazdigi soruyu alir, bir API istegine cevirir ve gateway'e gonderir.

### LibreChat'te olan:
ali, LibreChat'e email/sifre ile giris yapmistir. LibreChat bu kullaniciyi MongoDB'de tutar. ali'nin MongoDB'deki ID'si `aaa111bbb222ccc333ddd444`'dir.

ali soruyu yazip Enter'a bastiginda, LibreChat su HTTP istegini olusturur:

```
POST http://host.docker.internal:8000/v1/chat/completions
Authorization: Bearer sk-bankai
Content-Type: application/json

{
  "model": "qwen2.5:7b-instruct",
  "messages": [
    {"role": "user", "content": "Yillik izin suresi kac gun?"}
  ],
  "user": "aaa111bbb222ccc333ddd444",
  "stream": true
}
```

Dikkat edilecek noktalar:
- `user` alanina ali'nin adini degil, **MongoDB ObjectID**'sini yaziyor
- `Authorization` header'inda `sk-bankai` API key'i var
- `host.docker.internal` = Docker container'dan host makinedeki gateway'e erisim adresi
- `stream: true` = Cevabi kelime kelime gonder (canli yazma efekti)

### OpenWebUI'da olan:
ali, OpenWebUI'a email/sifre ile giris yapmistir. OpenWebUI bu kullaniciyi SQLite'da (`webui.db`) tutar.

ali soruyu yazip Enter'a bastiginda, OpenWebUI su HTTP istegini **dogrudan Gateway'e** gonderir:

```
POST http://host.docker.internal:8000/v1/chat/completions
Authorization: Bearer sk-dummy
Content-Type: application/json

{
  "model": "qwen2.5:7b-instruct",
  "messages": [
    {"role": "user", "content": "Yillik izin suresi kac gun?"}
  ],
  "stream": true
}
```

Dikkat edilecek noktalar:
- Dogrudan gateway'e gidiyor (`:8000`), Nginx'i **atliyor**
- OpenWebUI, OpenAI-uyumlu API'lere `X-OpenWebUI-User-Name` header'i **gondermez**
- Gateway, `Authorization: Bearer sk-dummy` header'indan API key'i cikarir
- `APIKEY_USER_MAP` tablosunda `sk-dummy` → `ali` olarak cozumlenir
- Bu sayede RBAC calisiyor — her API key bir kullaniciya baglidir

> **Not:** Nginx (:8080) opsiyonel olarak mevcuttur. UI'lar tarafindan kullanilmaz,
> yalnizca harici istemciler (curl, Postman vb.) icin header injection ile RBAC saglar.

### Bu asamada kullanilan veritabani:
| UI | Veritabani | Ne tutar? |
|---|---|---|
| LibreChat | **MongoDB** (:27017) | Kullanici hesaplari, sifre hash'leri, sohbet gecmisi, oturum bilgileri |
| OpenWebUI | **SQLite** (webui.db) | Ayni seyler ama dosya tabanli, ayri sunucu yok |

---

## 2. GATEWAY — Istegin Karsilandigi Yer

### Ne yapar?
Gelen istegin **kim**den geldigini anlar, **yetkisini** kontrol eder, **dokumanlari** bulur, **LLM'e** sorar, **cevabi** dondurur. Her seyin merkezi.

Gateway = FastAPI uygulamasi (`app_main.py`), port 8000'de calisiyor.

Istek geldiginde sirayla su adimlar islenir:

---

## 3. KULLANICI COZUMLEME (Gateway icinde)

### Ne yapar?
Gelen istekteki bilgilerden "bu kim?" sorusunu cevaplar.

### Nasil calisir?
Gateway birden fazla kaynaga bakar, ilk bulduguyla devam eder:

```
1. X-User header'i var mi?           → (Nginx veya harici istemci koyar — opsiyonel)
2. X-OpenWebUI-User-Name header'i?   → (OpenWebUI OpenAI API'ye gondermez, opsiyonel)
3. X-OpenWebUI-User-Email header'i?  → (opsiyonel)
4. body.user bilinen bir isim mi?    → "ali", "ayse", "veli" mi diye bakar
5. body.user bir ObjectID mi?        → "aaa111bbb222ccc333ddd444" → LIBRECHAT_USERID_MAP'te arar → "ali"
6. API key'den cikarilabilir mi?     → "sk-dummy" → APIKEY_USER_MAP'te arar → "ali" (OpenWebUI bu yolu kullanir)
7. Hicbiri bulunamadi                → "anonymous"
```

**Bizim ornekte:** body.user = `aaa111bbb222ccc333ddd444` → map'te aranir → **ali** bulunur.

### Sonra roller cikarilir:
```python
USER_ROLE_MAP = {"ali": ["hr"], "ayse": ["compliance"], "veli": ["finance"]}
```
ali → roller: `["hr"]` → tenant: `"hr"`

### Bu adimin sonucu:
```
kullanici = "ali"
roller    = ["hr"]
tenant    = "hr"    (hangi dokuman koleksiyonuna erisecek)
```

---

## 4. DLP GIRIS KONTROLU (Gateway icinde)

### Ne yapar?
Kullanicinin sorusunda **hassas veri** olup olmadigini kontrol eder. Varsa maskeler.

### DLP ne demek?
Data Loss Prevention = Veri Sizintisi Onleme. Hassas verilerin (kimlik numarasi, kredi karti vb.) disari cikmamasi icin bir filtre.

### Nasil calisir?
Simdilik sadece TCKN (Turkiye Cumhuriyeti Kimlik Numarasi) kontrol eder:

```
Soru: "12345678901 numarali calisanin izin hakki nedir?"
          ↓ DLP
Soru: "*********** numarali calisanin izin hakki nedir?"
```

11 haneli ardisik rakam gorurse `***********` ile degistirir.

**Bizim ornekte:** "Yillik izin suresi kac gun?" → Hassas veri yok, soru oldugu gibi kalir.

---

## 5. OPA — YETKILENDIRME KONTROLU

### Ne yapar?
"Bu kullanici bu bilgiye erisebilir mi?" sorusunu cevaplar. Izin verirse devam eder, vermezse **403 Yasak** dondurur.

### OPA ne demek?
Open Policy Agent. Yetkilendirme kurallarini kod olarak yazmani saglayan bir motor. Docker container olarak calisiyor (port 8181).

### Nasil calisir?
Gateway, OPA'ya su istegi gonderir:

```
POST http://127.0.0.1:8181/v1/data/rag/authz/allow

{
  "input": {
    "user": {
      "username": "ali",
      "roles": ["hr"]
    },
    "resource": {
      "collection": "hr"
    }
  }
}
```

OPA'daki kural (`policies/rag.rego`):

```
"hr rolune sahip kullanici hr koleksiyonuna erisebilir"
"compliance rolune sahip kullanici compliance koleksiyonuna erisebilir"
"finance rolune sahip kullanici finance koleksiyonuna erisebilir"
"baska her sey yasak"
```

**Bizim ornekte:** ali'nin rolu `hr`, eristigi koleksiyon `hr` → **Eslesme var → IZIN VERILDI**

Eger ali `finance` koleksiyonuna erismek isteseydi → rolu `hr`, koleksiyon `finance` → **Eslesme yok → REDDEDILDI (403)**

### Neden ayri bir servis?
Yetkilendirme kurallarini uygulamadan ayirmak icin. Kodu degistirmeden kurallari guncelleyebilirsin. Ornegin "ali artik finance'a da erissin" demek icin sadece policy dosyasini degistirirsin, gateway'e dokunmazsin.

---

## 6. QDRANT — DOKUMAN ARAMA (Retrieval)

### Ne yapar?
Kullanicinin sorusuyla en alakali dokuman parcalarini bulur.

### Qdrant ne demek?
Vektor veritabani. Normal veritabanlari "ID=5 olan kaydi getir" der. Qdrant ise "bu cumleye en cok benzeyen kayitlari getir" der. Docker container olarak calisiyor (port 6333).

### Nasil calisir?

**Adim 1: Soruyu sayilara cevir (Embedding)**
```
"Yillik izin suresi kac gun?"
        ↓ SentenceTransformer modeli
[0.023, -0.118, 0.445, ..., 0.082]   (384 boyutlu sayi dizisi)
```

Bu islem gateway icinde yapilir. `paraphrase-multilingual-MiniLM-L12-v2` modeli kullanilir. Bu model cumlerin "anlamini" sayilara cevirir. Benzer anlamli cumleler benzer sayilar uretir.

**Adim 2: Qdrant'ta ara**
```
Gateway → Qdrant:
"hr koleksiyonunda, su vektore en yakin 4 chunk'i getir"
[0.023, -0.118, 0.445, ..., 0.082]
```

Qdrant, `hr` koleksiyonundaki tum dokuman parcalarinin vektorleriyle karsilastirir ve en benzer 4 taneyi dondurur:

```
Qdrant → Gateway:
[
  {skor: 0.87, doc: "hr_mevzuat.txt", metin: "Yillik ucretli izin suresi... 14 gun..."},
  {skor: 0.72, doc: "yan_haklar.txt", metin: "Calisanlara yillik izin haklari..."},
  {skor: 0.65, doc: "calisma_saatleri.txt", metin: "Haftalik calisma suresi..."},
  {skor: 0.41, doc: "hr_mevzuat.txt", metin: "Kidem tazminati hesaplama..."}
]
```

Skor 0-1 arasi. 1'e yakinsa cok benzer, 0'a yakinsa alakasiz.

### Dokumanlar Qdrant'a nasil girmis?
Onceden `/admin/reindex/hr` endpoint'i cagirilarak:
1. `docs/hr/` klasorundeki dosyalar okundu
2. Paragraflara bolundu (chunk)
3. Her chunk embed edildi (sayilara cevrildi)
4. Qdrant'a yazildi

---

## 7. OLLAMA — LLM CAGRISI (Generation)

### Ne yapar?
Bulunan dokuman parcalarini ve soruyu alip, insanin anlayacagi bir cevap uretir.

### Ollama ne demek?
Yerel (local) LLM calistirma araci. Bizim durumda Windows host uzerinde calisiyor (port 11434). Kullandigi model: `qwen2.5:7b-instruct` (7 milyar parametreli bir dil modeli).

### Nasil calisir?
Gateway, Ollama'ya su istegi gonderir:

```
POST http://<OLLAMA_HOST>:11434/api/chat

{
  "model": "qwen2.5:7b-instruct",
  "stream": false,
  "messages": [
    {
      "role": "system",
      "content": "Sen bir banka ici bilgi asistanisin.
                  Sorunun cevabi kaynaklarda varsa sadece o bilgiyi kullan.
                  Yoksa 'Bu bilgi mevcut kaynaklarda bulunmamaktadir.' yaz."
    },
    {
      "role": "user",
      "content": "Soru: Yillik izin suresi kac gun?

                  Kaynaklar:
                  [1] (hr_mevzuat.txt) Yillik ucretli izin suresi... 14 gun...
                  [2] (yan_haklar.txt) Calisanlara yillik izin haklari...
                  [3] (calisma_saatleri.txt) Haftalik calisma suresi...
                  [4] (hr_mevzuat.txt) Kidem tazminati hesaplama...

                  Cevap:"
    }
  ]
}
```

Dikkat: LLM internetten bir sey aramaz. Sadece **bizim verdigi kaynaklara** bakarak cevap uretir. Buna **grounding** denir — modeli kaynaga baglamak.

### Ollama'nin cevabi:
```
"Yillik ucretli izin suresi 14 gundur. Kaynak: [1]"
```

---

## 8. DLP CIKIS KONTROLU (Gateway icinde)

### Ne yapar?
LLM'in urettigi cevapta hassas veri olup olmadigini kontrol eder. Eger bir dokumanda TCKN varsa ve LLM bunu cevaba koymussa, maskeler.

```
LLM cevabi: "Ali'nin TCKN'si 12345678901'dir"
        ↓ DLP
Maskelenmis: "Ali'nin TCKN'si ***********'dir"
```

**Bizim ornekte:** Cevapta TCKN yok, oldugu gibi kalir.

---

## 9. AUDIT LOG (Gateway icinde)

### Ne yapar?
Her istegin kaydini tutar. Kim, ne sordu, izin verildi mi, hangi dokumanlar kullanildi, ne kadar surdu — hepsini yazar.

### Nereye yazar?
`audit/events.jsonl` dosyasina. Her satir bir JSON kaydi:

```json
{
  "ts": 1709337600.123,
  "user": {"username": "ali", "roles": ["hr"]},
  "tenant": "hr",
  "allowed": true,
  "sources": [
    {"doc_id": "hr_mevzuat.txt", "score": 0.87},
    {"doc_id": "yan_haklar.txt", "score": 0.72}
  ],
  "dlp_in": [],
  "dlp_out": [],
  "latency_ms": 2340,
  "model": "qwen2.5:7b-instruct"
}
```

Bu dosya `.gitignore`'da cunku kisisel veri icerebilir.

---

## 10. CEVAP DONUSU (Gateway → UI)

### Ne yapar?
Hazirlanan cevabi kullaniciya gonderir.

### Iki mod var:

**Stream modu** (LibreChat ve OpenWebUI bunu kullanir):
Cevap kelime kelime gonderilir (SSE — Server-Sent Events). Kullanici cevabi canli olarak yazilirken gorur:

```
data: {"choices":[{"delta":{"content":"Yillik"}}]}
data: {"choices":[{"delta":{"content":" ucretli"}}]}
data: {"choices":[{"delta":{"content":" izin"}}]}
data: {"choices":[{"delta":{"content":" suresi"}}]}
data: {"choices":[{"delta":{"content":" 14"}}]}
data: {"choices":[{"delta":{"content":" gundur."}}]}
data: [DONE]
```

**Non-stream modu** (API'yi dogrudan curl ile cagirirsan):
Tum cevap tek seferde gelir.

### UI cevabi aldiginda:
- LibreChat: Cevabi sohbet gecmisine yazar (MongoDB)
- OpenWebUI: Cevabi sohbet gecmisine yazar (SQLite)

---

## BUYUK RESIM — Her Iki UI Icin Sema

### LibreChat Akisi:

```
ali "Yillik izin suresi kac gun?" yazar
    |
    v
[LIBRECHAT]  (:3080)
    | Kullanici bilgisi: MongoDB'den ObjectID alinir
    | HTTP istegi olusturulur (user: ObjectID, key: sk-bankai)
    |
    v
[GATEWAY]  (:8000)  ← app_main.py
    |
    |─ (1) Kullanici Cozumleme
    |      ObjectID → LIBRECHAT_USERID_MAP → "ali"
    |      ali → USER_ROLE_MAP → roller: ["hr"] → tenant: "hr"
    |
    |─ (2) DLP Giris
    |      Soruda TCKN var mi? → Yok, devam
    |
    |─ (3) OPA Sorgusu ──────────→ [OPA] (:8181)
    |      ali(hr) + hr koleksiyonu    Policy: "hr rolu hr'ye erisebilir"
    |      ← IZIN VERILDI             ← true
    |
    |─ (4) Embedding
    |      "Yillik izin suresi..." → [0.023, -0.118, ...]
    |
    |─ (5) Vektor Arama ─────────→ [QDRANT] (:6333)
    |      hr koleksiyonunda ara       En yakin 4 chunk
    |      ← 4 dokuman parcasi        ← skor + metin
    |
    |─ (6) LLM Cagrisi ──────────→ [OLLAMA] (:11434, Windows)
    |      System prompt +             qwen2.5:7b-instruct
    |      kaynaklar + soru            Cevap uret
    |      ← "Yillik izin 14 gundur"  ← metin
    |
    |─ (7) DLP Cikis
    |      Cevapta TCKN var mi? → Yok, devam
    |
    |─ (8) Audit Log
    |      → audit/events.jsonl'e yaz
    |
    |─ (9) Cevap Dondur (SSE stream)
    |
    v
[LIBRECHAT]
    | Cevabi ekranda gosterir
    | Sohbet gecmisini MongoDB'ye yazar
    |
    v
ali ekranda cevabi gorur: "Yillik ucretli izin suresi 14 gundur. Kaynak: [1]"
```

### OpenWebUI Akisi:

```
ali "Yillik izin suresi kac gun?" yazar
    |
    v
[OPENWEBUI]  (:3000)
    | Kullanici bilgisi: SQLite'dan alinir
    | HTTP istegi olusturulur (Authorization: Bearer sk-dummy)
    | NOT: Nginx'i atlar, dogrudan gateway'e gider
    |
    v
[GATEWAY]  (:8000)  ← app_main.py
    |
    |─ (1) Kullanici Cozumleme
    |      X-User yok, X-OpenWebUI-User-Name yok, body.user yok
    |      API key fallback: sk-dummy → APIKEY_USER_MAP → "ali"
    |      ali → USER_ROLE_MAP → roller: ["hr"] → tenant: "hr"
    |
    |─ (2) DLP Giris → (3) OPA → (4) Qdrant → (5) Ollama → (6) DLP Cikis → (7) Audit
    |      (LibreChat akisiyla ayni adimlar)
    |
    |─ (8) Cevap Dondur (SSE stream)
    |
    v
[OPENWEBUI]
    | Cevabi ekranda gosterir
    | Sohbet gecmisini SQLite'a yazar
    |
    v
ali ekranda cevabi gorur: "Yillik ucretli izin suresi 14 gundur. Kaynak: [1]"
```

---

## HER BILESENIN OZETI

| Bilesen | Tip | Port | Tek cumleyle ne yapar? |
|---------|-----|------|----------------------|
| **LibreChat** | Chat UI | 3080 | Kullanicinin yazdigi soruyu API istegine cevirir |
| **OpenWebUI** | Chat UI | 3000 | Ayni isi yapar, farkli arayuz |
| **MongoDB** | Veritabani | 27017 | LibreChat'in kullanici/sohbet verilerini tutar |
| **SQLite** | Veritabani | - | OpenWebUI'nin kullanici/sohbet verilerini tutar (dosya) |
| **Nginx** | Reverse Proxy (opsiyonel) | 8080 | Harici istemciler icin kullanici/rol/tenant header'i enjekte eder (UI'lar kullanmaz) |
| **Gateway** | API Sunucusu | 8000 | Her seyin merkezi: kimlik, yetki, arama, LLM, audit |
| **OPA** | Policy Engine | 8181 | "Bu kullanici buna erisebilir mi?" sorusunu cevaplar |
| **Qdrant** | Vektor DB | 6333 | Soruya en benzer dokuman parcalarini bulur |
| **Ollama** | LLM Runtime | 11434 | Kaynaklara bakarak insanin anlayacagi cevap uretir |
| **Audit Log** | Dosya | - | Her istegin kaydini tutar (kim, ne, ne zaman) |

---

## REDDETME SENARYOSU

Eger **ayse** (rolu: compliance) ayni soruyu sorarsa ne olur?

```
ayse "Yillik izin suresi kac gun?" yazar
    |
    v
[GATEWAY]
    |─ Kullanici: ayse, roller: ["compliance"], tenant: "compliance"
    |─ DLP Giris: OK
    |─ OPA Sorgusu: ayse(compliance) + compliance koleksiyonu
    |  ← IZIN VERILDI (compliance koleksiyonuna erisiyor)
    |─ Qdrant'ta "compliance" koleksiyonunda arama
    |─ Bulunan dokumanlar: aml_politikasi.txt, kvkk_proseduru.txt, ic_denetim.txt
    |─ Bu dokumanlarda "yillik izin" bilgisi yok
    |─ LLM cevabi: "Bu bilgi mevcut kaynaklarda bulunmamaktadir."
```

Eger ayse **hr** koleksiyonuna erismek isteseydi (ornegin tenant=hr ile):
```
    |─ OPA Sorgusu: ayse(compliance) + hr koleksiyonu
    |  ← REDDEDILDI (compliance rolu hr'ye erisemez)
    |─ HTTP 403 Forbidden dondu
```

Her kullanici sadece kendi rolunun dokumanlarini gorebilir. Bu **RBAC** (Role-Based Access Control) prensibinin temelidir.
