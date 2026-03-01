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

# Basit user->role map (PoC)
DEFAULT_USER_ROLE_MAP = {"ali": ["hr"], "ayse": ["compliance"], "veli": ["finance"]}
try:
    USER_ROLE_MAP = json.loads(os.getenv("USER_ROLE_MAP", "")) if os.getenv("USER_ROLE_MAP") else DEFAULT_USER_ROLE_MAP
except Exception:
    USER_ROLE_MAP = DEFAULT_USER_ROLE_MAP

# API key -> user map (PoC: OpenWebUI kullanıcı header'ı göndermediği için)
DEFAULT_APIKEY_USER_MAP = {
    "sk-dummy": "ali",       # OpenWebUI default key
    "sk-hr": "ali",
    "sk-compliance": "ayse",
    "sk-finance": "veli",
    "sk-bankai": "ali",      # LibreChat tek endpoint default (fallback — asıl çözüm userid map)
}
try:
    APIKEY_USER_MAP = json.loads(os.getenv("APIKEY_USER_MAP", "")) if os.getenv("APIKEY_USER_MAP") else DEFAULT_APIKEY_USER_MAP
except Exception:
    APIKEY_USER_MAP = DEFAULT_APIKEY_USER_MAP

# LibreChat MongoDB ObjectID -> bankai username map
# LibreChat request body'de "user" alanına MongoDB _id gönderir
DEFAULT_LIBRECHAT_USERID_MAP = {
    "69a491c78b6939fccb7a25b5": "ali",
    "69a4b5200f1399f96c7803ed": "ayse",
    "69a4b5250f1399f96c7803f3": "veli",
}
try:
    LIBRECHAT_USERID_MAP = json.loads(os.getenv("LIBRECHAT_USERID_MAP", "")) if os.getenv("LIBRECHAT_USERID_MAP") else DEFAULT_LIBRECHAT_USERID_MAP
except Exception:
    LIBRECHAT_USERID_MAP = DEFAULT_LIBRECHAT_USERID_MAP


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
# Util: DLP (PoC)
# ------------------------------------------------------------

TCKN_RE = re.compile(r"\b\d{11}\b")

def dlp_mask(text: str) -> Dict[str, Any]:
    hits = []
    def repl(m: re.Match) -> str:
        hits.append({"type": "TCKN", "match": m.group(0)})
        return "***********"
    masked = TCKN_RE.sub(repl, text or "")
    return {"masked": masked, "hits": hits}


# ------------------------------------------------------------
# Util: roles parsing
# ------------------------------------------------------------

def parse_roles(x_roles: str) -> List[str]:
    if not x_roles:
        return []
    return [r.strip() for r in x_roles.split(",") if r.strip()]


def infer_roles_for_user(username: str) -> List[str]:
    roles = USER_ROLE_MAP.get(username, [])
    if isinstance(roles, str):
        roles = [roles]
    return [r for r in roles if r]


def infer_tenant(explicit_tenant: Optional[str], roles: List[str]) -> str:
    if explicit_tenant and explicit_tenant.strip():
        return explicit_tenant.strip()
    if len(roles) == 1:
        return roles[0]
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

    log.info("=== PIPELINE START === tenant=%s user=%s question='%s'",
             tenant, user.get("username"), question[:200])

    dlp_in = dlp_mask(question)

    if not opa_allow(user, {"collection": tenant}):
        log.warning("OPA DENIED: user=%s tenant=%s", user, tenant)
        audit({"ts": time.time(), "user": user, "tenant": tenant, "allowed": False, "dlp_in": dlp_in["hits"]})
        raise HTTPException(status_code=403, detail="Policy deny")

    ctx = retrieve(tenant, dlp_in["masked"], k=4)
    if not ctx:
        log.warning("NO RETRIEVAL RESULTS: tenant=%s query='%s'", tenant, dlp_in["masked"][:200])
        audit({"ts": time.time(), "user": user, "tenant": tenant, "allowed": True, "sources": [], "dlp_in": dlp_in["hits"], "dlp_out": [], "latency_ms": int((time.time()-t0)*1000), "model": OLLAMA_MODEL})
        return {"answer": "İlgili kaynak bulamadım.", "sources": []}

    sources = [{"doc_id": c["doc_id"], "score": c["score"]} for c in ctx]
    context_text = "\n\n".join([f"[{i+1}] ({c['doc_id']}) {c['text']}" for i, c in enumerate(ctx)])

    log.info("RETRIEVED %d chunks: %s", len(ctx),
             [(c["doc_id"], round(c["score"], 3)) for c in ctx])

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

    dlp_out = dlp_mask(raw)

    log.info("=== PIPELINE DONE === latency=%dms answer_len=%d sources=%s",
             int((time.time()-t0)*1000), len(raw), [s["doc_id"] for s in sources])

    audit({
        "ts": time.time(),
        "user": user,
        "tenant": tenant,
        "allowed": True,
        "sources": sources,
        "dlp_in": dlp_in["hits"],
        "dlp_out": dlp_out["hits"],
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
    }


@app.post("/admin/reindex/{tenant}")
def reindex(tenant: str):
    n = index_docs(tenant)
    return {"tenant": tenant, "indexed_chunks": n}


@app.post("/ask")
def ask(req: AskReq, x_user: str = Header(default="anonymous"), x_roles: str = Header(default="")):
    roles = parse_roles(x_roles)
    user = {"username": x_user, "roles": roles}

    tenant = (req.tenant or "").strip()
    if not tenant:
        tenant = infer_tenant(None, roles)

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


def _resolve_user_from_apikey(auth_header: str) -> Optional[str]:
    """API key'den kullanıcı çözümle (PoC)."""
    if not auth_header:
        return None
    key = auth_header.removeprefix("Bearer ").strip()
    return APIKEY_USER_MAP.get(key)


def _resolve_user_from_librechat_id(body_user: str) -> Optional[str]:
    """LibreChat MongoDB ObjectID'den bankai kullanıcı adını çözümle."""
    if not body_user:
        return None
    return LIBRECHAT_USERID_MAP.get(body_user)


def _resolve_user_context(
    req: ChatCompletionRequest,
    x_user: str,
    x_roles: str,
    x_tenant: str,
    x_openwebui_user_name: str,
    x_openwebui_user_email: str,
    auth_header: str = "",
) -> Tuple[str, List[str], str]:
    """Resolve user_id, roles, tenant from all available sources."""
    user_id = (x_user or "").strip()
    if not user_id:
        body_user = (req.user or "").strip()
        # 1) Direkt bilinen kullanıcı adı mı?
        known_body_user = body_user if body_user in USER_ROLE_MAP else ""
        # 2) LibreChat MongoDB ObjectID mi?
        librechat_user = _resolve_user_from_librechat_id(body_user) if not known_body_user else None
        user_id = (
            (x_openwebui_user_name or "").strip()
            or (x_openwebui_user_email or "").strip()
            or known_body_user
            or librechat_user
            or _resolve_user_from_apikey(auth_header)
            or "anonymous"
        )

    roles = parse_roles(x_roles)
    if not roles:
        roles = infer_roles_for_user(user_id)

    tenant = infer_tenant(x_tenant, roles)
    return user_id, roles, tenant


def _build_non_streaming_response(
    model: str, assistant_text: str, request_id: str,
    tenant: str, user_id: str, roles: List[str],
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
            "roles": roles,
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
    user_id, roles, tenant = _resolve_user_context(
        req, x_user, x_roles, x_tenant,
        x_openwebui_user_name, x_openwebui_user_email,
        auth_header=auth_header,
    )

    log.info("RESOLVED: user_id=%s roles=%s tenant=%s", user_id, roles, tenant)

    question = _last_user_message(req.messages)
    model = req.model or OLLAMA_MODEL
    user = {"username": user_id, "roles": roles}

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
        tenant, user_id, roles, sources,
    )
