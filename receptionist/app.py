"""AI-Рецепціоніст — веб-сервіс.

Ендпоінти:
  GET  /                 — демо-сторінка з віджетом (кастомізація через ?business=&niche=&color=)
  GET  /widget.js        — вбудовуваний віджет для будь-якого сайту
  POST /api/chat         — чат з асистентом
  POST /api/vapi/tools   — webhook для інструментів Vapi (голосовий агент)
  GET  /api/vapi/assistant-config — готовий JSON асистента для Vapi
  GET  /api/bookings     — останні записи (потрібен ADMIN_TOKEN)
  GET  /health

Запуск локально:  cd receptionist && uvicorn app:app --reload
"""

import json
import logging
import os
import secrets
import time
from collections import OrderedDict
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from agent import TOOLS, Receptionist, execute_tool
from calendar_backends import TZ, TZ_NAME, get_calendar
from niches import NICHES, build_system_prompt
from storage import init_db, list_bookings

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("receptionist")

STATIC = os.path.join(os.path.dirname(__file__), "static")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
VAPI_SECRET = os.environ.get("VAPI_SECRET", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

init_db()
calendar = get_calendar()
receptionist = Receptionist(calendar)

app = FastAPI(title="AI Receptionist")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Сесії чату (в пам'яті, для демо достатньо) ───────────────────────────────
MAX_SESSIONS = 2000
SESSION_TTL = 60 * 60
sessions: "OrderedDict[str, dict]" = OrderedDict()


def _get_session(sid: str | None) -> tuple[str, dict]:
    now = time.time()
    for k in [k for k, v in sessions.items() if now - v["ts"] > SESSION_TTL]:
        sessions.pop(k, None)
    if not sid or sid not in sessions:
        sid = secrets.token_urlsafe(12)
        sessions[sid] = {"history": [], "ts": now}
    sessions.move_to_end(sid)
    while len(sessions) > MAX_SESSIONS:
        sessions.popitem(last=False)
    sessions[sid]["ts"] = now
    return sid, sessions[sid]


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    niche: str | None = None
    business_name: str | None = Field(None, max_length=100)
    services: str | None = Field(None, max_length=500)


@app.post("/api/chat")
def chat(body: ChatIn):
    sid, sess = _get_session(body.session_id)
    profile = {
        "niche": body.niche if body.niche in NICHES else "real_estate",
        "business_name": body.business_name,
        "services": body.services,
    }
    history = sess["history"] + [{"role": "user", "content": body.message}]
    t0 = time.time()
    text, new_history = receptionist.reply(history, profile, channel="chat")
    sess["history"] = new_history[-30:]
    # не залишаємо «осиротілі» tool-повідомлення на початку після обрізки
    while sess["history"] and sess["history"][0]["role"] != "user":
        sess["history"].pop(0)
    logger.info("chat %s: %.2fs", sid[:6], time.time() - t0)
    return {"session_id": sid, "reply": text}


# ─── Vapi (голос) ─────────────────────────────────────────────────────────────

@app.post("/api/vapi/tools")
async def vapi_tools(request: Request, x_vapi_secret: str | None = Header(None)):
    if VAPI_SECRET and x_vapi_secret != VAPI_SECRET:
        raise HTTPException(401, "bad secret")
    payload = await request.json()
    message = payload.get("message", {})
    if message.get("type") != "tool-calls":
        return {}
    call = message.get("call", {}) or {}
    ctx = {
        "channel": "voice",
        "business": (call.get("assistantOverrides") or {}).get("variableValues", {}).get("business_name"),
        "niche": None,
    }
    results = []
    for tc in message.get("toolCallList") or message.get("toolCalls") or []:
        fn = tc.get("function") or {}
        name = fn.get("name") or tc.get("name")
        args = fn.get("arguments") or tc.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        result = execute_tool(name, args, calendar, ctx)
        results.append({"toolCallId": tc.get("id"), "result": json.dumps(result, ensure_ascii=False)})
    return {"results": results}


@app.get("/api/vapi/assistant-config")
def vapi_assistant_config(niche: str = "real_estate", business_name: str | None = None):
    """JSON, який можна вставити в Vapi (Assistants → API) або відправити POST /assistant."""
    base = PUBLIC_URL or "https://YOUR-RENDER-URL"
    server = {"url": f"{base}/api/vapi/tools"}
    if VAPI_SECRET:
        server["secret"] = "<VAPI_SECRET>"
    name = business_name or NICHES.get(niche, NICHES["real_estate"])["business_name"]
    return {
        "name": f"{name} — AI Receptionist",
        "firstMessage": f"Добрий день! {name}, AI-адміністратор. Чим можу допомогти?",
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.4,
            "messages": [{
                "role": "system",
                "content": build_system_prompt(niche, business_name, voice=True,
                                               now_iso="{{now}}", timezone=TZ_NAME),
            }],
            "tools": [{**t, "server": server} for t in TOOLS],
        },
        "voice": {"provider": "11labs", "voiceId": "pNInz6obpgDQGcFmaJgB"},
        "transcriber": {"provider": "deepgram", "model": "nova-2", "language": "multi"},
        "endCallFunctionEnabled": True,
    }


# ─── Адмінка ─────────────────────────────────────────────────────────────────

@app.get("/api/bookings")
def bookings(authorization: str | None = Header(None)):
    if not ADMIN_TOKEN or authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(401, "unauthorized")
    return {"calendar": calendar.name, "bookings": list_bookings()}


@app.get("/health")
def health():
    return {
        "ok": True,
        "calendar": calendar.name,
        "openai": receptionist.client is not None,
        "time": datetime.now(TZ).isoformat(),
    }


# ─── Статика ─────────────────────────────────────────────────────────────────

@app.get("/")
def demo_page():
    return FileResponse(os.path.join(STATIC, "demo.html"))


@app.get("/widget.js")
def widget_js():
    return FileResponse(os.path.join(STATIC, "widget.js"), media_type="application/javascript")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse({"reply": "Технічна помилка, спробуйте ще раз."}, status_code=500)
