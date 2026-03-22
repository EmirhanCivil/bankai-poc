# app_main.py
from __future__ import annotations

import os
import re
import json
import time
import uuid
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# .env dosyasını otomatik yükle (path explicit — working dir fark etmesin)
from pathlib import Path as _P
from dotenv import load_dotenv
load_dotenv(_P(__file__).resolve().parent / ".env", override=True)

import requests
import jwt as pyjwt
from jwt import PyJWKClient
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# ------------------------------------------------------------
# Logging — her şeyi gör
# ------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bankai")

# ------------------------------------------------------------
# Konfig (ENV)
# ------------------------------------------------------------

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

OLLAMA_URL = os.getenv("OLLAMA_URL", f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/chat")
BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = Path(os.getenv("DOCS_DIR", str(BASE_DIR / "docs")))

AUDIT_DIR = Path(os.getenv("AUDIT_DIR", str(BASE_DIR / "audit")))
AUDIT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_FILE = AUDIT_DIR / "events.jsonl"

OPA_URL = os.getenv("OPA_URL", "http://127.0.0.1:8181/v1/data/rag/authz/allow")

QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")

# Embed model (multilingual — Türkçe retrieval kalitesi için kritik)
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# Chunking
CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "900"))

# Keycloak / JWT
KEYCLOAK_JWKS_URL = os.getenv("KEYCLOAK_JWKS_URL", "http://localhost:8443/realms/bankai/protocol/openid-connect/certs")
KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER", "http://localhost:8443/realms/bankai")

# JWKS client (lazy init, caches keys)
_jwks_client: Optional[PyJWKClient] = None

def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(KEYCLOAK_JWKS_URL, cache_keys=True)
    return _jwks_client

def _validate_jwt(token: str) -> Optional[Dict[str, Any]]:
    """Validate a Keycloak JWT and return decoded claims, or None on failure."""
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        claims = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_ISSUER,
            options={"verify_aud": False},
        )
        return claims
    except Exception as e:
        log.debug("JWT validation failed: %s", repr(e))
        return None

# Roller artik sadece Keycloak JWT'den geliyor, statik mapping yok


# ------------------------------------------------------------
# Grounding system prompt — çok daha güçlü
# ------------------------------------------------------------

GROUNDING_SYSTEM_PROMPT = """Sen bir banka içi bilgi asistanısın.

KURALLAR:
1. Sorunun cevabı kaynaklarda varsa: sadece o bilgiyi kullanarak Türkçe cevap ver ve sonuna "Kaynak: [1]" gibi referans ekle.
2. Sorunun cevabı kaynaklarda yoksa: SADECE şunu yaz: "Bu bilgi mevcut kaynaklarda bulunmamaktadır." Başka hiçbir şey ekleme, kaynaklardan alıntı yapma, yorum yapma.

Cevabı Türkçe ver. Kısa ve net ol."""


# ------------------------------------------------------------
# FastAPI app
# ------------------------------------------------------------

app = FastAPI(title="bankai-poc-gateway")


# ------------------------------------------------------------
# Modeller (schemas)
# ------------------------------------------------------------

class AskReq(BaseModel):
    tenant: str
    question: str


# OpenAI minimal schemas
class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False
    user: Optional[str] = None


# ------------------------------------------------------------
# Util: audit
# ------------------------------------------------------------

def audit(event: Dict[str, Any]) -> None:
    try:
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ------------------------------------------------------------
# Guardrail: DLP (Data Loss Prevention)
# ------------------------------------------------------------

DLP_PATTERNS = [
    ("TCKN",        re.compile(r"\b\d{11}\b"),                          "***TCKN***"),
    ("IBAN",        re.compile(r"\bTR\d{24}\b", re.IGNORECASE),        "***IBAN***"),
    ("KREDI_KARTI", re.compile(r"\b(?:\d[ -]*?){13,16}\b"),            "***KART***"),
    ("TELEFON",     re.compile(r"\b(?:\+90|0)[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b"), "***TEL***"),
    ("EMAIL",       re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "***EMAIL***"),
]

def _luhn_check(num: str) -> bool:
    digits = [int(d) for d in num if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0

def dlp_mask(text: str) -> Dict[str, Any]:
    hits: List[Dict[str, str]] = []
    masked = text or ""
    for ptype, pattern, replacement in DLP_PATTERNS:
        def _repl(m: re.Match, _type=ptype, _repl=replacement) -> str:
            val = m.group(0)
            if _type == "KREDI_KARTI":
                clean = re.sub(r"[\s-]", "", val)
                if not _luhn_check(clean):
                    return val
            hits.append({"type": _type, "match": val[:4] + "..."})
            return _repl
        masked = pattern.sub(_repl, masked)
    return {"masked": masked, "hits": hits}


# ------------------------------------------------------------
# Guardrail: Prompt Injection Detection
# ------------------------------------------------------------

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"(?:show|reveal|print|display|output|give)\s+(?:me\s+)?(?:your\s+)?(?:system\s+)?(?:prompt|instructions|rules)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:a|an|in)\s+", re.IGNORECASE),
    re.compile(r"(?:act|behave|pretend|roleplay)\s+(?:as|like)\s+", re.IGNORECASE),
    re.compile(r"(?:new|override|replace|change)\s+(?:system\s+)?(?:prompt|instructions|role|persona)", re.IGNORECASE),
    re.compile(r"(?:do\s+not|don'?t)\s+(?:follow|obey|listen)", re.IGNORECASE),
    re.compile(r"\]\s*\}\s*(?:system|assistant)\s*:", re.IGNORECASE),
    # Türkçe
    re.compile(r"(?:önceki|yukarıdaki|mevcut)\s+(?:talimatları|kuralları|promptu)\s+(?:unut|yoksay|görmezden\s+gel)", re.IGNORECASE),
    re.compile(r"(?:sistem\s+)?(?:promptunu|talimatlarını|kurallarını)\s+(?:göster|yaz|ver)", re.IGNORECASE),
    re.compile(r"(?:artık|şimdi|bundan\s+sonra)\s+(?:sen\s+)?(?:bir|başka)\s+", re.IGNORECASE),
    re.compile(r"(?:gibi|olarak)\s+(?:davran|rol\s+yap|hareket\s+et)", re.IGNORECASE),
]

def detect_prompt_injection(text: str) -> Optional[str]:
    for pattern in PROMPT_INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


# ------------------------------------------------------------
# Guardrail: Toxic Content Filter
# ------------------------------------------------------------

TOXIC_KEYWORDS_TR = {
    "amk", "aq", "orospu", "piç", "siktir", "sikeyim", "siktiğimin",
    "gerizekalı", "aptal", "salak", "mal", "dangalak", "göt", "yavşak",
    "kahpe", "pezevenk", "hıyar", "kodumun", "hassiktir", "amına",
}

TOXIC_KEYWORDS_EN = {
    "fuck", "shit", "bitch", "asshole", "bastard", "dick", "pussy",
    "nigger", "faggot", "retard", "cunt", "whore", "slut", "motherfucker",
}

TOXIC_ALL = TOXIC_KEYWORDS_TR | TOXIC_KEYWORDS_EN

def detect_toxic_content(text: str) -> Optional[str]:
    words = set(re.findall(r"\b\w+\b", text.lower()))
    found = words & TOXIC_ALL
    if found:
        return ", ".join(sorted(found))
    return None


# ------------------------------------------------------------
# Guardrail: Rate Limiting (in-memory sliding window)
# ------------------------------------------------------------

from collections import defaultdict
import threading

RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "15"))
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "100"))

_rate_lock = threading.Lock()
_rate_store: Dict[str, List[float]] = defaultdict(list)

def _cleanup_timestamps(timestamps: List[float], window: float) -> List[float]:
    cutoff = time.time() - window
    return [t for t in timestamps if t > cutoff]

def check_rate_limit(user_id: str) -> Optional[str]:
    now = time.time()
    with _rate_lock:
        ts = _rate_store[user_id]
        ts = _cleanup_timestamps(ts, 3600)
        _rate_store[user_id] = ts

        recent_minute = [t for t in ts if t > now - 60]
        if len(recent_minute) >= RATE_LIMIT_PER_MINUTE:
            return f"Dakika limiti asildi ({RATE_LIMIT_PER_MINUTE}/dk)"

        if len(ts) >= RATE_LIMIT_PER_HOUR:
            return f"Saat limiti asildi ({RATE_LIMIT_PER_HOUR}/saat)"

        ts.append(now)
    return None


# ------------------------------------------------------------
# Guardrail: Input/Output Size Limits
# ------------------------------------------------------------

MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "4000"))
MAX_OUTPUT_CHARS = int(os.getenv("MAX_OUTPUT_CHARS", "8000"))


# ------------------------------------------------------------
# Guardrail: Hallucination Detection
# ------------------------------------------------------------

def detect_hallucination(answer: str, sources: List[Dict[str, Any]], ctx: List[Dict[str, Any]]) -> bool:
    if not ctx:
        return True
    source_text = " ".join(c.get("text", "") for c in ctx).lower()
    answer_words = set(re.findall(r"\b[a-züöşıçğ]{4,}\b", answer.lower()))
    if len(answer_words) < 3:
        return False
    source_words = set(re.findall(r"\b[a-züöşıçğ]{4,}\b", source_text))
    overlap = answer_words & source_words
    ratio = len(overlap) / len(answer_words) if answer_words else 0
    return ratio < 0.15


# ------------------------------------------------------------
# Util: groups parsing
# ------------------------------------------------------------

def parse_roles(x_roles: str) -> List[str]:
    if not x_roles:
        return []
    return [r.strip() for r in x_roles.split(",") if r.strip()]


def infer_roles_for_user(username: str) -> List[str]:
    """Artik roller sadece JWT'den geliyor. Fallback yok."""
    return []


def infer_tenant(explicit_tenant: Optional[str], groups: List[str]) -> str:
    if explicit_tenant and explicit_tenant.strip():
        return explicit_tenant.strip()
    if len(groups) == 1:
        return groups[0]
    return "default"


# ------------------------------------------------------------
# OPA allow
# ------------------------------------------------------------

def opa_allow(user: Dict[str, Any], resource: Dict[str, Any]) -> bool:
    try:
        r = requests.post(
            OPA_URL,
            json={"input": {"user": user, "resource": resource}},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        return bool(data.get("result", False))
    except Exception as e:
        audit({"ts": time.time(), "error": f"opa_error: {repr(e)}"})
        return False


# ------------------------------------------------------------
# Embedding (SentenceTransformer)
# ------------------------------------------------------------

_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBED_MODEL_NAME)
    return _embedder


def embed_text(text: str) -> List[float]:
    model = get_embedder()
    vec = model.encode([text], normalize_embeddings=True)[0]
    return vec.astype("float32").tolist()


# ------------------------------------------------------------
# Qdrant helpers (REST)
# ------------------------------------------------------------

def qdrant_ensure_collection(name: str, vector_size: int) -> None:
    r = requests.get(f"{QDRANT_URL}/collections/{name}", timeout=5)
    if r.status_code == 200:
        return
    payload = {
        "vectors": {"size": vector_size, "distance": "Cosine"},
    }
    r = requests.put(f"{QDRANT_URL}/collections/{name}", json=payload, timeout=10)
    r.raise_for_status()


def qdrant_upsert(name: str, points: List[Dict[str, Any]]) -> None:
    r = requests.put(f"{QDRANT_URL}/collections/{name}/points?wait=true", json={"points": points}, timeout=30)
    r.raise_for_status()


def qdrant_search(name: str, vector: List[float], limit: int = 4) -> List[Dict[str, Any]]:
    payload = {"vector": vector, "limit": limit, "with_payload": True}
    r = requests.post(f"{QDRANT_URL}/collections/{name}/points/search", json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("result", [])


# ------------------------------------------------------------
# Docs indexing + chunking
# ------------------------------------------------------------

def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf = ""

    for p in paras:
        if not buf:
            buf = p
        elif len(buf) + 2 + len(p) <= max_chars:
            buf += "\n\n" + p
        else:
            chunks.append(buf)
            buf = p

    if buf:
        chunks.append(buf)

    fixed: List[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            fixed.append(c)
            continue
        for i in range(0, len(c), max_chars):
            fixed.append(c[i:i+max_chars])
    return fixed


def iter_tenant_files(tenant: str) -> List[Path]:
    tdir = DOCS_DIR / tenant
    files: List[Path] = []
    if tdir.exists() and tdir.is_dir():
        for p in sorted(tdir.glob("**/*")):
            if p.is_file() and p.suffix.lower() in (".txt", ".md"):
                files.append(p)
        return files

    for p in sorted(DOCS_DIR.glob("*")):
        if p.is_file() and p.suffix.lower() in (".txt", ".md"):
            files.append(p)
    return files


def stable_point_id(tenant: str, doc_id: str, chunk_idx: int, text: str) -> int:
    h = hashlib.sha256(f"{tenant}|{doc_id}|{chunk_idx}|{text}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def index_docs(tenant: str) -> int:
    files = iter_tenant_files(tenant)
    if not files:
        return 0

    vec0 = embed_text("hello")
    qdrant_ensure_collection(tenant, vector_size=len(vec0))

    points: List[Dict[str, Any]] = []
    total_chunks = 0

    for fp in files:
        doc_id = fp.name
        content = fp.read_text(encoding="utf-8", errors="ignore")
        chunks = chunk_text(content, max_chars=CHUNK_MAX_CHARS)

        for i, ch in enumerate(chunks):
            vec = embed_text(ch)
            pid = stable_point_id(tenant, doc_id, i, ch)
            points.append({
                "id": pid,
                "vector": vec,
                "payload": {
                    "tenant": tenant,
                    "doc_id": doc_id,
                    "chunk_idx": i,
                    "text": ch,
                },
            })
            total_chunks += 1

    if points:
        qdrant_upsert(tenant, points)

    return total_chunks


def retrieve(tenant: str, query: str, k: int = 4) -> List[Dict[str, Any]]:
    try:
        vec = embed_text(query)
        results = qdrant_search(tenant, vec, limit=k)
        ctx = []
        for r in results:
            payload = r.get("payload") or {}
            ctx.append({
                "doc_id": payload.get("doc_id", "unknown"),
                "text": payload.get("text", ""),
                "score": float(r.get("score", 0.0)),
            })
        return ctx
    except Exception as e:
        audit({"ts": time.time(), "error": f"retrieve_error: {repr(e)}", "tenant": tenant})
        return []


# ------------------------------------------------------------
# LLM (Ollama)
# ------------------------------------------------------------

def ollama_chat(system: str, user_msg: str, model: Optional[str] = None) -> str:
    payload = {
        "model": model or OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    }
    log.debug("OLLAMA REQUEST: model=%s, system_len=%d, user_msg_len=%d",
              payload["model"], len(system), len(user_msg))
    log.debug("OLLAMA SYSTEM PROMPT:\n%s", system[:500])
    log.debug("OLLAMA USER MSG:\n%s", user_msg[:1000])

    r = requests.post(OLLAMA_URL, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    msg = (data.get("message") or {})
    content = (msg.get("content") or "").strip()

    log.debug("OLLAMA RESPONSE (first 500 chars):\n%s", content[:500])
    return content


# ------------------------------------------------------------
# Core pipeline
# ------------------------------------------------------------

def answer_from_docs(tenant: str, question: str, user: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.time()
    username = user.get("username", "?")
    guardrail_flags: List[str] = []

    log.info("=== PIPELINE START === tenant=%s user=%s question='%s'",
             username, username, question[:200])

    # ── Guardrail: Rate Limiting ──
    rate_err = check_rate_limit(username)
    if rate_err:
        log.warning("RATE LIMIT: user=%s reason=%s", username, rate_err)
        audit({"ts": time.time(), "user": user, "tenant": tenant, "blocked": "rate_limit", "reason": rate_err})
        raise HTTPException(status_code=429, detail=rate_err)

    # ── Guardrail: Input Size Limit ──
    if len(question) > MAX_INPUT_CHARS:
        log.warning("INPUT TOO LONG: user=%s len=%d max=%d", username, len(question), MAX_INPUT_CHARS)
        audit({"ts": time.time(), "user": user, "tenant": tenant, "blocked": "input_too_long", "input_len": len(question)})
        raise HTTPException(status_code=400, detail=f"Girdi çok uzun (maks {MAX_INPUT_CHARS} karakter)")

    # ── Guardrail: Toxic Content (input) ──
    toxic = detect_toxic_content(question)
    if toxic:
        log.warning("TOXIC INPUT: user=%s words=%s", username, toxic)
        audit({"ts": time.time(), "user": user, "tenant": tenant, "blocked": "toxic_input", "toxic_words": toxic})
        raise HTTPException(status_code=400, detail="Uygunsuz içerik tespit edildi. Lütfen profesyonel bir dil kullanın.")

    # ── Guardrail: Prompt Injection (input) ──
    injection = detect_prompt_injection(question)
    if injection:
        log.warning("PROMPT INJECTION: user=%s match='%s'", username, injection)
        audit({"ts": time.time(), "user": user, "tenant": tenant, "blocked": "prompt_injection", "match": injection})
        raise HTTPException(status_code=400, detail="Güvenlik ihlali tespit edildi. Bu istek reddedildi.")

    # ── DLP: Input maskeleme ──
    dlp_in = dlp_mask(question)
    if dlp_in["hits"]:
        guardrail_flags.append("dlp_input")

    # ── OPA: Yetkilendirme ──
    if not opa_allow(user, {"collection": tenant}):
        log.warning("OPA DENIED: user=%s tenant=%s", user, tenant)
        audit({"ts": time.time(), "user": user, "tenant": tenant, "allowed": False, "dlp_in": dlp_in["hits"]})
        raise HTTPException(status_code=403, detail="Policy deny")

    # ── Retrieval ──
    ctx = retrieve(tenant, dlp_in["masked"], k=4)
    if not ctx:
        log.warning("NO RETRIEVAL RESULTS: tenant=%s query='%s'", tenant, dlp_in["masked"][:200])
        audit({"ts": time.time(), "user": user, "tenant": tenant, "allowed": True, "sources": [], "dlp_in": dlp_in["hits"], "dlp_out": [], "latency_ms": int((time.time()-t0)*1000), "model": OLLAMA_MODEL})
        return {"answer": "Bu bilgi mevcut kaynaklarda bulunmamaktadır.", "sources": []}

    sources = [{"doc_id": c["doc_id"], "score": c["score"]} for c in ctx]
    context_text = "\n\n".join([f"[{i+1}] ({c['doc_id']}) {c['text']}" for i, c in enumerate(ctx)])

    log.info("RETRIEVED %d chunks: %s", len(ctx),
             [(c["doc_id"], round(c["score"], 3)) for c in ctx])

    # ── LLM Call ──
    system = GROUNDING_SYSTEM_PROMPT
    user_msg = f"Soru: {dlp_in['masked']}\n\nKaynaklar:\n{context_text}\n\nCevap:"

    log.debug("FULL PROMPT TO LLM:\n--- SYSTEM ---\n%s\n--- USER ---\n%s\n--- END ---",
              system, user_msg[:2000])

    try:
        raw = ollama_chat(system, user_msg, model=OLLAMA_MODEL)
    except Exception as e:
        log.error("OLLAMA ERROR: %s", repr(e))
        audit({"ts": time.time(), "user": user, "tenant": tenant, "allowed": True, "sources": sources, "dlp_in": dlp_in["hits"], "dlp_out": [], "latency_ms": int((time.time()-t0)*1000), "model": OLLAMA_MODEL, "error": f"ollama_error: {repr(e)}"})
        raise HTTPException(status_code=502, detail="LLM backend error")

    # ── Guardrail: Output Size Limit ──
    if len(raw) > MAX_OUTPUT_CHARS:
        raw = raw[:MAX_OUTPUT_CHARS] + "\n\n[Cevap uzunluk sınırı nedeniyle kesildi]"
        guardrail_flags.append("output_truncated")

    # ── Guardrail: Toxic Content (output) ──
    toxic_out = detect_toxic_content(raw)
    if toxic_out:
        log.warning("TOXIC OUTPUT: user=%s words=%s", username, toxic_out)
        guardrail_flags.append("toxic_output")
        raw = "Üretilen cevapta uygunsuz içerik tespit edildi. Lütfen sorunuzu yeniden formüle edin."

    # ── Guardrail: Hallucination Detection ──
    is_hallucination = detect_hallucination(raw, sources, ctx)
    if is_hallucination:
        log.warning("HALLUCINATION DETECTED: user=%s tenant=%s", username, tenant)
        guardrail_flags.append("hallucination_warning")
        raw += "\n\n⚠ Bu cevap kaynaklarla tam olarak doğrulanamamıştır. Lütfen ilgili birime danışın."

    # ── DLP: Output maskeleme ──
    dlp_out = dlp_mask(raw)
    if dlp_out["hits"]:
        guardrail_flags.append("dlp_output")

    log.info("=== PIPELINE DONE === latency=%dms answer_len=%d sources=%s guardrails=%s",
             int((time.time()-t0)*1000), len(raw), [s["doc_id"] for s in sources], guardrail_flags)

    audit({
        "ts": time.time(),
        "user": user,
        "tenant": tenant,
        "allowed": True,
        "sources": sources,
        "dlp_in": dlp_in["hits"],
        "dlp_out": dlp_out["hits"],
        "guardrail_flags": guardrail_flags,
        "latency_ms": int((time.time()-t0)*1000),
        "model": OLLAMA_MODEL,
    })

    return {"answer": dlp_out["masked"], "sources": sources}


# ------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------

@app.get("/__ping")
def ping():
    return "pong\n"


@app.get("/__debug")
def debug_config():
    return {
        "OLLAMA_URL": OLLAMA_URL,
        "OLLAMA_HOST": OLLAMA_HOST,
        "OLLAMA_MODEL": OLLAMA_MODEL,
        "QDRANT_URL": QDRANT_URL,
        "OPA_URL": OPA_URL,
        "KEYCLOAK_ISSUER": KEYCLOAK_ISSUER,
        "KEYCLOAK_JWKS_URL": KEYCLOAK_JWKS_URL,
    }


@app.post("/admin/reindex/{tenant}")
def reindex(tenant: str):
    n = index_docs(tenant)
    return {"tenant": tenant, "indexed_chunks": n}


@app.post("/ask")
def ask(req: AskReq, x_user: str = Header(default="anonymous"), x_groups: str = Header(default="")):
    groups = [g.strip().lower() for g in x_groups.split(",") if g.strip()]
    user = {"username": x_user, "groups": groups}

    tenant = (req.tenant or "").strip()
    if not tenant:
        tenant = infer_tenant(None, groups)

    return answer_from_docs(tenant, req.question, user)


# -------------------------
# OpenAI adapter endpoints
# -------------------------

@app.get("/v1/models")
@app.get("/models")
def list_models():
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": OLLAMA_MODEL,
                "object": "model",
                "created": now,
                "owned_by": "local-ollama",
                "name": OLLAMA_MODEL,
                "permission": [],
                "root": OLLAMA_MODEL,
                "parent": None,
            },
        ],
    }


def _last_user_message(messages: List[ChatMessage]) -> str:
    user_msgs = [m for m in messages if m.role == "user" and (m.content or "").strip()]
    if not user_msgs:
        raise HTTPException(status_code=400, detail="No user message found in messages[]")
    return user_msgs[-1].content.strip()


def _resolve_user_from_jwt(auth_header: str) -> Optional[Tuple[str, List[str]]]:
    """Extract user_id and roles from a Keycloak JWT Bearer token."""
    if not auth_header:
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    if not token or token.count(".") != 2:
        return None
    claims = _validate_jwt(token)
    if not claims:
        return None
    user_id = claims.get("preferred_username", "")
    groups = [g.lower() for g in claims.get("groups", [])]
    log.info("JWT resolved: user=%s groups=%s", user_id, groups)
    return (user_id, groups) if user_id else None


def _resolve_user_context(
    req: ChatCompletionRequest,
    x_user: str,
    x_roles: str,
    x_tenant: str,
    x_openwebui_user_name: str,
    x_openwebui_user_email: str,
    auth_header: str = "",
) -> Tuple[str, List[str], str]:
    """Resolve user_id, groups, tenant from Keycloak JWT. No fallback."""
    jwt_result = _resolve_user_from_jwt(auth_header)
    if jwt_result:
        user_id, groups = jwt_result
        tenant = infer_tenant(x_tenant, groups)
        return user_id, groups, tenant

    raise HTTPException(status_code=401, detail="Valid Keycloak JWT required")


def _build_non_streaming_response(
    model: str, assistant_text: str, request_id: str,
    tenant: str, user_id: str, groups: List[str],
    sources: List[Dict[str, Any]],
) -> dict:
    """Build an OpenAI-compatible non-streaming chat completion response."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": assistant_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "meta": {
            "request_id": request_id,
            "tenant": tenant,
            "user": user_id,
            "groups": groups,
            "sources": sources,
        },
    }


def _sse_streaming_response(
    model: str, assistant_text: str, completion_id: str,
):
    """
    Generate SSE events that OpenWebUI can parse.
    Simulates token-by-token streaming of an already-complete answer.
    """
    created = int(time.time())

    # First chunk: role declaration
    first_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": ""},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(first_chunk)}\n\n"

    # Stream the content in small pieces to look natural
    # Use word-level chunks for better UX
    words = assistant_text.split(" ")
    for i, word in enumerate(words):
        token = word if i == 0 else " " + word
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": token},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

    # Final chunk: finish_reason = stop
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
def chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    # Bizim gateway header'ları:
    x_user: str = Header(default=""),
    x_roles: str = Header(default=""),
    x_tenant: str = Header(default=""),
    # OpenWebUI forward header'ları:
    x_openwebui_user_name: str = Header(default=""),
    x_openwebui_user_email: str = Header(default=""),
    x_request_id: str = Header(default=""),
):
    request_id = x_request_id.strip() or str(uuid.uuid4())

    # ── DEBUG: Log the FULL incoming request + ALL headers ──
    log.info("=" * 60)
    log.info(">>> /v1/chat/completions INCOMING REQUEST")
    log.info("  request_id  = %s", request_id)
    log.info("  stream      = %s", req.stream)
    log.info("  model       = %s", req.model)
    log.info("  user (body) = %s", req.user)
    log.info("  messages count = %d", len(req.messages))
    for i, m in enumerate(req.messages):
        content_preview = (m.content or "")[:200]
        log.info("  msg[%d] role=%s content='%s'", i, m.role, content_preview)
    log.info("  HEADERS: x-user=%s x-roles=%s x-tenant=%s",
             x_user, x_roles, x_tenant)
    log.info("  HEADERS: x-openwebui-user-name=%s x-openwebui-user-email=%s",
             x_openwebui_user_name, x_openwebui_user_email)
    # Log ALL raw headers for debugging
    log.info("  ALL HEADERS: %s", dict(request.headers))
    log.info("=" * 60)

    # ── Resolve user context (API key fallback dahil) ──
    auth_header = request.headers.get("authorization", "")
    user_id, groups, tenant = _resolve_user_context(
        req, x_user, x_roles, x_tenant,
        x_openwebui_user_name, x_openwebui_user_email,
        auth_header=auth_header,
    )

    log.info("RESOLVED: user_id=%s groups=%s tenant=%s", user_id, groups, tenant)

    question = _last_user_message(req.messages)
    model = req.model or OLLAMA_MODEL
    user = {"username": user_id, "groups": groups}

    # ── Core RAG pipeline — same for stream and non-stream ──
    out = answer_from_docs(tenant, question, user)
    assistant_text = out.get("answer", "")
    sources = out.get("sources", [])

    log.info("PIPELINE RESULT: answer_len=%d sources=%s stream_requested=%s",
             len(assistant_text), [s["doc_id"] for s in sources], req.stream)

    # ── STREAMING RESPONSE (critical for OpenWebUI) ──
    if req.stream:
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        log.info("STREAMING response via SSE, id=%s", completion_id)
        return StreamingResponse(
            _sse_streaming_response(model, assistant_text, completion_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Nginx'te buffering'i kapat
            },
        )

    # ── NON-STREAMING RESPONSE ──
    return _build_non_streaming_response(
        model, assistant_text, request_id,
        tenant, user_id, groups, sources,
    )
