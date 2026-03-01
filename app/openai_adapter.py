from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import time
import uuid
import httpx
import os

router = APIRouter()

ASK_URL = os.getenv("ASK_URL", "http://127.0.0.1:8000/ask")

# PoC role map (sonra LDAP/SSO'dan gelecek)
USER_ROLES = {
    "ali": ["hr"],
    "ayse": ["compliance"],
    "veli": ["finance"],
}

ROLE_TENANT = {
    "hr": "hr",
    "compliance": "compliance",
    "finance": "finance",
}

# -------------------------
# OpenAI minimal schemas
# -------------------------
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

def _last_user_message(messages: List[ChatMessage]) -> str:
    user_msgs = [m for m in messages if m.role == "user" and (m.content or "").strip()]
    if not user_msgs:
        raise HTTPException(status_code=400, detail="No user message found in messages[]")
    return user_msgs[-1].content.strip()

def _derive_user_roles_tenant(request: Request, fallback_user: str) -> tuple[str, List[str], str]:
    # OpenWebUI headers
    ow_name = request.headers.get("x-openwebui-user-name", "").strip()
    ow_email = request.headers.get("x-openwebui-user-email", "").strip()

    user_id = ow_name or ow_email or fallback_user or "anonymous"
    user_key = (ow_name or fallback_user or "anonymous").strip()

    roles = USER_ROLES.get(user_key, [])
    tenant = ""

    if roles:
        tenant = ROLE_TENANT.get(roles[0], "")
    return user_id, roles, tenant

@router.get("/v1/models")
async def list_models():
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": "qwen2.5:7b-instruct", "object": "model", "created": now, "owned_by": "local-ollama"}
        ],
    }

@router.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, request: Request):
    question = _last_user_message(req.messages)
    model = req.model or "qwen2.5:7b-instruct"
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    # OpenWebUI'dan user/role/tenant türet
    user_id, roles, tenant = _derive_user_roles_tenant(request, req.user or "demo_user")

    if not roles or not tenant:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "No roles/tenant resolved for this user (PoC role-map).",
                "user_id": user_id,
                "roles": roles,
                "tenant": tenant,
            },
        )

    payload = {"tenant": tenant, "question": question}

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(
                ASK_URL,
                json=payload,
                headers={
                    "x-user": user_id,
                    "x-roles": ",".join(roles),
                    "x-request-id": request_id,
                },
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ask_call_failed: {type(e).__name__}: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail={"ask_status": r.status_code, "ask_body": r.text})

    data = r.json()
    assistant_text = data.get("answer") or str(data)

    now = int(time.time())
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": assistant_text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "meta": {"request_id": request_id, "tenant": tenant, "user": user_id, "roles": roles},
    }
