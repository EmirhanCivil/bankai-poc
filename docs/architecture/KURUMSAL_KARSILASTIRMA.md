# LibreChat vs OpenWebUI — Kurumsal Karsilastirma
## 500+ Kisilik On-Premise RAG Sistemi Icin Arayuz Secimi

> **Senaryo:** 500-600 calisanlik bir firma. Tamamen on-premise (cloud yok). Ekipler arasi veri izolasyonu zorunlu. Dahili dokumanlar uzerinde RAG sistemi kurulacak. Acik kaynak (open-source) kullanilacak.

---

## 1. GENEL BAKIS

| | LibreChat | OpenWebUI |
|---|---|---|
| **Lisans** | MIT (tamamen serbest) | Open WebUI License (BSD-3 + marka zorunlulugu) |
| **Marka kisiti** | Yok, istedigin gibi degistir | "Open WebUI" markasi kaldiramaz (50+ kullanici) |
| **Veritabani** | MongoDB (zorunlu) + Redis | SQLite (varsayilan) veya PostgreSQL |
| **Mimari** | Node.js (Express) + React | Python (FastAPI) + Svelte |
| **Container sayisi** | 3-6 (api + mongo + redis + opsiyonel) | 1-2 (tek container + Nginx veya reverse proxy) |
| **Aktif gelistirme** | ClickHouse satin aldi (Kasim 2025), aktif | Cok aktif, buyuk topluluk |

### Lisans Farki Neden Onemli?

**LibreChat (MIT):** Logoyu degistir, ismi degistir, "Banka AI Asistan" yap — hicbir kisit yok.

**OpenWebUI:** 50+ kullanicida "Open WebUI" markasini kaldirmak icin **Enterprise lisans** (ucretli) gerekir. Ic kullanim icin marka gorunur kalirsa ucretsiz. Beyaz etiketleme (white-label) istiyorsan ucretli.

---

## 2. KIMLIK DOGRULAMA (Authentication)

500+ kisilik firmada Active Directory / LDAP entegrasyonu sart.

| Ozellik | LibreChat | OpenWebUI |
|---|---|---|
| **Yerel kullanici/sifre** | Var | Var |
| **LDAP / Active Directory** | Var (.env ile yapilandirilir) | Var (.env ile yapilandirilir) |
| **OAuth2 / OIDC** | Var (Keycloak, Entra ID, Auth0, Cognito) | Var (Keycloak, Entra ID, Google, Authentik) |
| **SAML** | Var (ancak OIDC ile ayni anda kullanilamaz) | Yok |
| **Trusted Header Auth** | Yok (reverse proxy'den gelen header'a guvenme) | Var (X-Email header ile kimlik dogrulama) |
| **SCIM 2.0** | Yok | Var (Okta, Azure AD'den otomatik kullanici/grup sync) |
| **OAuth grup senkronizasyonu** | Sadece Microsoft Entra ID | Var (tum OIDC saglayicilar) |
| **LDAP grup filtresi** | Yok (tum LDAP kullanicilari girebilir) | Var |
| **Sadece SSO modu** | Yapilandirilabilir | `ENABLE_PASSWORD_AUTH=false` ile |

### Degerlendirme:

**OpenWebUI one cikar** cunku:
- SCIM 2.0 ile Active Directory'den otomatik kullanici ve grup provizyon yapabilir — 500 kisiyi elle tanimlamak gerekmez
- OAuth grup senkronizasyonu tum OIDC saglayicilarda calisir
- Trusted Header Auth ile mevcut kurumsal SSO proxy'nin arkasina koyabilirsin

**LibreChat'in eksigi:**
- LDAP grup filtresi yok — LDAP'taki tum kullanicilar girebilir, belirli gruplari kisitlayamazsin
- OAuth grup sync sadece Microsoft Entra ID'de calisir (Keycloak, Okta'da calismaz)
- SAML ve OIDC ayni anda kullanilamaz

---

## 3. YETKILENDIRME ve ERISIM KONTROLU (RBAC)

Ekipler arasi veri izolasyonu icin kritik bolum.

| Ozellik | LibreChat | OpenWebUI |
|---|---|---|
| **Roller** | admin, user | admin, user, pending |
| **Grup sistemi** | Planlanmis (2026 Q1-Q2 yol haritasinda) | **Var ve calisir** |
| **Grup bazli model erisimi** | Yok | **Var** (model X sadece Y grubuna gorunur) |
| **Grup bazli bilgi tabani erisimi** | Yok | **Var** (knowledge base Z sadece W grubuna) |
| **Kaynak gorunurlugu** | Herkese acik veya herkese kapali | **Private / Gruba ozel / Herkese acik** |
| **Yeni kullanici varsayilan grup** | Yok | `DEFAULT_GROUP_ID` ile otomatik atama |
| **Izin kategorileri** | Sinirli (endpoint erisimi, ajan olusturma) | **Genis** (workspace, paylasim, sohbet, ayarlar) |
| **Yonetim arayuzu** | Yok (YAML dosyasi ile) | **Var (GUI admin paneli)** |

### Ornek Senaryo: HR, Finans, Uyum Ekiplerinin Izolasyonu

**OpenWebUI'da nasil yapilir:**
```
1. Gruplar olustur: HR-Ekibi, Finans-Ekibi, Uyum-Ekibi
2. Bilgi tabanlari olustur: HR-Dokumanlari, Finans-Dokumanlari, Uyum-Dokumanlari
3. Her bilgi tabanini ilgili gruba ata
4. Model olustur: "HR Asistan" → HR-Dokumanlari bagla → HR-Ekibi'ne gorunur yap
5. Kullanicilari gruplara ata (veya SCIM/OAuth ile otomatik)
```

Sonuc: HR calisani sadece HR Asistan modelini gorur, sadece HR dokumanlarini sorgulayabilir. Finans dokumanlarini goremez bile.

**LibreChat'te nasil yapilir:**
```
1. Grup sistemi yok — her kullanicinin eristigi endpoint YAML'da tanimlanir
2. Veri izolasyonu icin her ekip icin ayri endpoint tanimlamak gerekir
3. Veya harici bir gateway (Bankai gibi) ile izolasyon saglanir
4. Elle yapilandirma, GUI yok
```

### Degerlendirme:

**OpenWebUI acik ara one cikar.** Grup bazli RBAC, bilgi tabani izolasyonu ve model erisim kontrolu **kutudan cikiyor**. LibreChat'te bu ozelliklerin cogu henuz yok veya 2026 yol haritasinda planlanmis.

---

## 4. VERI IZOLASYONU DETAYI

500+ kisilik firmada en kritik konu: "Finans ekibinin dokumanlarini HR gorebilir mi?"

| Katman | LibreChat | OpenWebUI |
|---|---|---|
| **Sohbet gecmisi** | Kullanici bazli izole (MongoDB) | Kullanici bazli izole (SQLite/PostgreSQL) |
| **Bilgi tabanlari (RAG)** | Kullanici bazli (dahili RAG) | **Grup bazli** (admin atamasi ile) |
| **Model erisimi** | Endpoint bazli (YAML) | **Grup bazli** (admin panelinden) |
| **Dosya yuklemeleri** | Kullanici bazli | Kullanici bazli |
| **Admin sohbet erisimi** | Admin tum sohbetleri gorebilir | `ENABLE_ADMIN_CHAT_ACCESS=false` ile kapatilabilir |
| **Vektor DB izolasyonu** | Uygulama katmaninda | Uygulama katmaninda (ACL bazli, DB seviyesinde degil) |

### Onemli Not — Vektor DB Izolasyonu:

Her iki sistemde de vektor veritabanindaki izolasyon **uygulama seviyesindedir** (application-level ACL). Yani veritabaninda fiziksel olarak ayri koleksiyonlar yok — erisim kontrolu yazilim katmaninda yapilir.

**Gercek fiziksel izolasyon** istiyorsan (farkli ekiplerin verileri farkli koleksiyonlarda):
- Harici bir gateway (Bankai PoC'deki gibi) ile her ekip icin ayri Qdrant koleksiyonu kullanmak gerekir
- Bu her iki UI icin de gecerli — ikisi de bunu yerel olarak yapamaz

---

## 5. ADMIN PANELI ve YONETIM

500+ kullaniciyi yonetmek icin GUI sart.

| Ozellik | LibreChat | OpenWebUI |
|---|---|---|
| **Kullanici yonetimi GUI** | **Yok** (2026 yol haritasinda) | **Var** (olustur, sil, aktif/pasif, rol degistir) |
| **Toplu kullanici aktarimi** | Yok | **CSV ile toplu import** |
| **Grup yonetimi GUI** | Yok | **Var** |
| **Model yonetimi GUI** | Yok (YAML dosyasi) | **Var** (toplu acma/kapama, araclari baglama) |
| **Kullanim analitigi** | MongoDB sorgulari ile | **Dashboard** (mesaj hacmi, token tuketimi, kullanici aktivitesi) |
| **Webhook** | Yok | **Var** (kayit olaylari icin) |
| **Bildirim banner'i** | Yok | **Var** (ozellestirilabilir) |
| **Yapilandirma yontemi** | `.env` + `librechat.yaml` dosyalari | `.env` + **admin paneli** |

### Degerlendirme:

**OpenWebUI acik ara one cikar.** 500 kisiyi YAML dosyasiyla yonetmek pratik degil. OpenWebUI'nin admin paneli kullanici yonetimi, grup yonetimi, model yonetimi ve analitik dashboard sunuyor. LibreChat'in admin paneli 2026 yol haritasinda var ama henuz mevcut degil.

---

## 6. EKLENTI / FONKSIYON SISTEMI

Kurumsal ihtiyaclara gore ozellestirme.

| Ozellik | LibreChat | OpenWebUI |
|---|---|---|
| **Plugin tipi** | MCP (Model Context Protocol) + Agents | **Filter + Pipe + Action** fonksiyonlari |
| **DLP (veri maskeleme)** | Yok (harici gateway ile) | **Filter fonksiyon ile yapilabilir** |
| **Prompt injection tespiti** | Yok | **LLM-Guard entegrasyonu** (Filter) |
| **Oran sinirlandirma** | `.env` ile | **Filter fonksiyon ile** (kullanici bazli) |
| **Toksisite filtresi** | Moderasyon sistemi (skor bazli) | **Detoxify entegrasyonu** (Filter) |
| **Ceviri** | Yok | **LibreTranslate entegrasyonu** (Filter) |
| **Izleme / monitoring** | Yok | **Langfuse entegrasyonu** (Filter) |
| **Ozel model pipeline** | Custom endpoint (YAML) | **Pipe fonksiyon** (Python kodu) |

### OpenWebUI Filter Fonksiyon Ornegi — DLP:

```python
class Filter:
    def inlet(self, body: dict, __user__: dict) -> dict:
        # Kullanicinin sorusundaki TCKN'leri maskele
        import re
        for msg in body.get("messages", []):
            if msg.get("content"):
                msg["content"] = re.sub(r'\b\d{11}\b', '***********', msg["content"])
        return body

    def outlet(self, body: dict, __user__: dict) -> dict:
        # LLM cevabindaki TCKN'leri maskele
        import re
        for msg in body.get("messages", []):
            if msg.get("content"):
                msg["content"] = re.sub(r'\b\d{11}\b', '***********', msg["content"])
        return body
```

### Degerlendirme:

**OpenWebUI one cikar.** Filter/Pipe/Action sistemi kurumsal ihtiyaclari (DLP, icerik filtreleme, izleme) dogrudan UI icerisinde cozmeye olanak tanir. LibreChat'te bunlar icin harici bir gateway veya servis gerekir.

---

## 7. DAHILI RAG (Bilgi Tabani)

Her iki sistem de dahili RAG destegi sunar.

| Ozellik | LibreChat | OpenWebUI |
|---|---|---|
| **RAG mimarisi** | Ayri mikro servis (Python FastAPI + pgvector) | Dahili (tek container icinde) |
| **Vektor DB** | PostgreSQL + pgvector | 9 secenk: Qdrant, ChromaDB, Milvus, pgvector, Elasticsearch, OpenSearch, Pinecone, S3Vector, Oracle |
| **Desteklenen formatlar** | PDF, txt, docx | PDF, Word, Excel, PowerPoint, txt (Apache Tika/Docling ile) |
| **Arama yontemi** | Vektor benzerlik | **Vektor + BM25 hibrit + CrossEncoder re-ranking** |
| **Bilgi tabani erisim kontrolu** | Kullanici bazli | **Grup bazli** |
| **Bilgi tabanini modele baglama** | Yok (dosyalar sohbete eklenir) | **Var** (model X'e Y bilgi tabanini bagla) |
| **Web arama RAG** | Yok | **15+ arama saglayicisi** (Searxng, Google, Bing) |
| **Toplu dokuman yukleme API** | Yok (sadece UI) | Var |
| **Satir ici kaynak referansi** | Var | **Var** (inline citation) |

### Degerlendirme:

**OpenWebUI acik ara one cikar.**
- 9 farkli vektor DB destegi (mevcut altyapiniza uyum)
- Hibrit arama (vektor + metin) daha iyi sonuclar
- Grup bazli bilgi tabani erisimi = ekip izolasyonu
- Model-bilgi tabani baglama = her ekibin kendi RAG asistani
- Excel/PowerPoint destegi kurumsal ortamda kritik

---

## 8. BACKEND ILETISIMI

RAG gateway'e kullanici bilgisini nasil iletirler?

| Ozellik | LibreChat | OpenWebUI |
|---|---|---|
| **Baglanti** | Dogrudan Gateway'e (:8000) | Nginx (:8080) uzerinden Gateway'e |
| **API key** | `librechat.yaml`'da tanimlanir (`sk-bankai`) | Ortam degiskeni ile (`dummy`) |
| **Kullanici bilgisi** | `req.body.user` = MongoDB ObjectID | `X-OpenWebUI-User-Name` header → Nginx → `X-User/X-Roles/X-Tenant` |
| **Kullanici cozumleme** | Gateway icinde (`LIBRECHAT_USERID_MAP`) | Nginx icinde (map kurallari) |
| **RBAC calisiyor mu?** | Evet | Evet (Nginx header injection ile) |

### Bankai PoC'deki Gercek Akis:

**LibreChat:**
```
LibreChat → Gateway (:8000)
  body.user: "69a491c78b6939fccb7a25b5"
  Gateway: LIBRECHAT_USERID_MAP → "ali" → roller: hr → tenant: hr
```

**OpenWebUI:**
```
OpenWebUI → Nginx (:8080) → Gateway (:8000)
  header: X-OpenWebUI-User-Name: ali
  Nginx map: ali → X-User: ali, X-Roles: hr, X-Tenant: hr
  Gateway: X-User header'ini okur → "ali"
```

### Degerlendirme:

**Her ikisi de calisir durumda.** LibreChat'te cozumleme gateway icinde yapilir (ObjectID map). OpenWebUI'da ise Nginx katmaninda yapilir (header injection). Her iki yaklasimin da avantaji var:

- **LibreChat:** Yeni kullanici kayit oldugunda ObjectID otomatik olusur, gateway map'ine eklenince RBAC calisir
- **OpenWebUI:** Nginx'teki map statik — yeni kullanici icin `nginx.conf` guncellenmeli

Kurumsal olcekte her iki durumda da **merkezi bir kimlik saglayici** (LDAP/SSO) kullanilmasi onerilen yaklasimdir.

---

## 9. DENETIM KAYDI (Audit Log)

Bankacillik ve finans sektorunde zorunlu.

| Ozellik | LibreChat | OpenWebUI |
|---|---|---|
| **Audit log** | Yok (uygulama loglari var) | **Var** (4 seviye: NONE, METADATA, REQUEST, REQUEST_RESPONSE) |
| **Dosyaya yazma** | Uygulama logu (Winston) | `ENABLE_AUDIT_LOGS_FILE=true` |
| **stdout'a yazma** | Var | `ENABLE_AUDIT_STDOUT=true` |
| **JSON formatli log** | Yapilandirilabilir | `LOG_FORMAT=json` |
| **Log rotasyonu** | 14 gun, 20MB | Boyut bazli rotasyon |
| **Token tuketimi takibi** | MongoDB'de (Transactions koleksiyonu) | Dashboard'da gorunur |
| **Oturum acma/kapama logu** | Yok | Kismi (bazi versiyonlarda eksik) |

### Degerlendirme:

**OpenWebUI one cikar.** Dort seviyeli audit log sistemi kutudan cikiyor. `REQUEST_RESPONSE` seviyesinde tam istek ve cevap kaydi tutulabilir. LibreChat'te audit log mevcut degil — sadece genel uygulama loglari var.

Ancak **ikisi de tam compliance-grade audit icin yeterli degil**. Bankacillik seviyesinde denetim kaydi icin harici bir gateway (Bankai gibi) veya log toplayici (ELK, Loki) gerekir.

---

## 10. ON-PREMISE KURULUM ve OLCEKLENDIRME

| Ozellik | LibreChat | OpenWebUI |
|---|---|---|
| **Minimum container** | 3 (api + mongo + redis) | **2** (OpenWebUI + Nginx/reverse proxy) |
| **Tam kurulum** | 6 (+ meilisearch + vectordb + rag_api) | 2-3 (+ vektor DB opsiyonel) |
| **Veritabani yonetimi** | MongoDB (ayri yedekleme, ayri guncelleme) | SQLite (dosya) veya PostgreSQL |
| **Kubernetes** | Topluluk destekli (resmi degil) | **Resmi Helm chart + Kustomize** |
| **Kaynak tuketimi** | Daha fazla (MongoDB + Redis + Node.js) | **Daha az** (tek Python process) |
| **Cevrimdisi calisma** | Tam destekli | Tam destekli |
| **Telefon etme (phone-home)** | Yok | Yok |
| **GPU destegi** | Yok (LLM harici) | Docker GPU varyantlari mevcut |
| **OpenTelemetry** | Yok | **Var** (mevcut izleme altyapisina entegrasyon) |

### 500 Kisi Icin Olceklendirme:

**LibreChat:**
- MongoDB replica set onerilen
- Redis zorunlu (oturum yonetimi)
- API birden fazla instance olarak calisabilir (load balancer arkasinda)
- Daha fazla operasyonel yuklenme

**OpenWebUI:**
- PostgreSQL'e gecis onerilen (SQLite 500 esanli kullanici icin dar bogazdir)
- Tek container birden fazla instance olarak calisabilir
- Daha az operasyonel karmasiklik

---

## 11. BUYUK KARSILASTIRMA TABLOSU

| Kriter | LibreChat | OpenWebUI | 500+ Kisi On-Prem Icin |
|---|---|---|---|
| **Lisans** | MIT (sinirsiz) | Marka kisitli | LibreChat |
| **LDAP/AD** | Var | Var | Esit |
| **SCIM (otomatik provizyon)** | Yok | Var | **OpenWebUI** |
| **OAuth grup sync** | Sadece Entra | Tum OIDC | **OpenWebUI** |
| **Grup bazli RBAC** | Yok (planlanmis) | Var | **OpenWebUI** |
| **Bilgi tabani izolasyonu** | Kullanici bazli | Grup bazli | **OpenWebUI** |
| **Model erisim kontrolu** | YAML ile | Grup bazli GUI | **OpenWebUI** |
| **Admin paneli** | Yok (planlanmis) | Var (kapsamli) | **OpenWebUI** |
| **Toplu kullanici import** | Yok | CSV ile | **OpenWebUI** |
| **Audit log** | Yok | Var (4 seviye) | **OpenWebUI** |
| **Eklenti sistemi** | MCP + Agents | Filter/Pipe/Action | **OpenWebUI** |
| **Dahili RAG** | pgvector | 9 vektor DB secenegi | **OpenWebUI** |
| **RAG arama kalitesi** | Vektor | Hibrit + re-ranking | **OpenWebUI** |
| **Desteklenen dosya formatlari** | PDF, txt, docx | PDF, Word, Excel, PPT, txt | **OpenWebUI** |
| **Kurulum basitligi** | 3-6 container | 2-3 container (+ Nginx) | **OpenWebUI** |
| **Kubernetes** | Topluluk | Resmi Helm | **OpenWebUI** |
| **Backend'e kullanici bilgisi** | body.user ObjectID (gateway cozumler) | Nginx header injection (X-User/X-Roles) | Esit |
| **Sohbet gecmisi** | MongoDB (olgun) | SQLite/PostgreSQL | Esit |
| **Coklu LLM endpoint** | Guclu (custom endpoints) | Var ama daha sinirli | LibreChat |
| **MCP destegi** | Tam | Sinirli | LibreChat |
| **Beyaz etiketleme** | Serbest (MIT) | Ucretli | LibreChat |
| **Analitik dashboard** | Yok | Var | **OpenWebUI** |

---

## 12. SONUC VE ONERI

### OpenWebUI Secilmeli — Eger:
- **Grup bazli veri izolasyonu** birincil oncelik ise (500 kisi, 10+ ekip)
- **Admin panelinden yonetim** isteniyor ise (GUI sart)
- **SCIM ile otomatik kullanici provizyon** gerekiyor ise (Active Directory sync)
- **Dahili RAG** yeterli ise (ekstra gateway'e gerek yok)
- **Audit log** zorunlu ise
- **Hizli kurulum** isteniyor ise (az container)
- Marka kisiti sorun degilse ("Open WebUI" yazisi kalabilir)

### LibreChat Secilmeli — Eger:
- **Beyaz etiketleme** (white-label) sart ise — kurumsal marka ile sunmak
- **Birden fazla LLM endpoint** yonetimi gerekiyor ise
- **MCP destegi** kritik ise (harici araclarla entegrasyon)
- **Harici bir RAG gateway** (Bankai gibi) zaten varsa veya planlaniyorsa
- Grup bazli RBAC'in 2026'da gelmesini bekleyebiliyorsaniz

### Bu Senaryo Icin (500+ Kisi, On-Prem, Veri Izolasyonu, RAG):

**Oneri: OpenWebUI**

Nedenleri:
1. Grup bazli RBAC ve bilgi tabani izolasyonu **bugun calisir durumda**
2. SCIM ile Active Directory'den 500 kullaniciyi otomatik senkronize edebilirsin
3. Admin panelinden her seyi yonetebilirsin (YAML dosyasi duzenlemek yerine)
4. Dahili RAG yeterli — her ekip icin ayri bilgi tabani, ayri model, ayri erisim
5. Az container (OpenWebUI + Nginx) — operasyonel yuklenme minimum
6. Audit log kutudan cikiyor

**Eger beyaz etiketleme ve harici RAG gateway sart ise:** OpenWebUI + Bankai Gateway kombinasyonu. UI olarak OpenWebUI, RAG ve RBAC icin Bankai Gateway.

**Eger markalama kritik ve gelecege yatirim yapilacaksa:** LibreChat. MIT lisansi tam ozgurluk verir. Admin paneli ve grup RBAC 2026'da gelecek.

---

## EK: HER IKI SISTEM ICIN ON-PREM KURULUM KARSILASTIRMASI

### OpenWebUI (Minimum Production)
```
1 x OpenWebUI container
1 x Nginx / Reverse Proxy (RBAC header injection icin)
1 x PostgreSQL (SQLite yerine)
1 x Qdrant veya ChromaDB (vektor DB)
1 x Ollama (LLM)
---
Toplam: 4-5 container
```

### LibreChat (Minimum Production)
```
1 x LibreChat API container
1 x MongoDB (zorunlu)
1 x Redis (zorunlu)
1 x PostgreSQL + pgvector (RAG icin)
1 x RAG API container (Python)
1 x Ollama (LLM)
---
Toplam: 5-6 container
```
