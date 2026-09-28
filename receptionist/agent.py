"""Мозок рецепціоніста: OpenAI tool-calling + інструменти бронювання.

Один і той самий execute_tool використовується і для чату (віджет),
і для голосу (Vapi webhook), тож поведінка однакова в обох каналах.
"""

import json
import logging
import os
from datetime import datetime

import phonenumbers
import requests
from openai import OpenAI

from calendar_backends import TZ, TZ_NAME, CalendarBackend
from niches import build_system_prompt
from storage import save_booking

logger = logging.getLogger(__name__)

MODEL = os.environ.get("RECEPTIONIST_MODEL", "gpt-4o-mini")
DEFAULT_REGION = os.environ.get("DEFAULT_PHONE_REGION", "UA")
NOTIFY_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")

WEEKDAYS_UA = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Повертає найближчі вільні слоти для запису.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "description": "На скільки днів вперед шукати (1–14)", "default": 3},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Створює запис у календарі. Викликати лише коли є слот, ім'я і телефон.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "ISO-час слоту з get_available_slots"},
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "notes": {"type": "string", "description": "Коротко потреба клієнта"},
                },
                "required": ["start", "name", "phone"],
            },
        },
    },
]


def human_slot(iso: str) -> str:
    dt = datetime.fromisoformat(iso).astimezone(TZ)
    return f"{WEEKDAYS_UA[dt.weekday()]} {dt:%d.%m} о {dt:%H:%M}"


def normalize_phone(raw: str) -> str | None:
    try:
        num = phonenumbers.parse(raw, None if raw.strip().startswith("+") else DEFAULT_REGION)
        if phonenumbers.is_possible_number(num):
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None


def notify_owner(text: str) -> None:
    if not (NOTIFY_BOT_TOKEN and NOTIFY_CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{NOTIFY_BOT_TOKEN}/sendMessage",
            json={"chat_id": NOTIFY_CHAT_ID, "text": text},
            timeout=5,
        )
    except requests.RequestException as e:
        logger.warning("Telegram notify failed: %s", e)


def execute_tool(name: str, args: dict, calendar: CalendarBackend, ctx: dict) -> dict:
    """ctx: channel, business, niche — для логування запису."""
    try:
        if name == "get_available_slots":
            days = max(1, min(int(args.get("days_ahead") or 3), 14))
            slots = calendar.get_available_slots(days_ahead=days)
            if not slots:
                return {"slots": [], "message": "Немає вільних слотів у цьому діапазоні"}
            return {"timezone": TZ_NAME, "slots": [{"start": s, "label": human_slot(s)} for s in slots]}

        if name == "book_appointment":
            phone = normalize_phone(args.get("phone", ""))
            if not phone:
                return {"ok": False, "error": "Некоректний номер телефону — попроси повторити"}
            client_name = (args.get("name") or "").strip()
            if not client_name:
                return {"ok": False, "error": "Потрібне ім'я клієнта"}
            res = calendar.book(
                args["start"], client_name, phone, args.get("email", ""), args.get("notes", "")
            )
            if not res.get("ok"):
                return res
            save_booking(
                channel=ctx.get("channel", "chat"),
                business=ctx.get("business"),
                niche=ctx.get("niche"),
                name=client_name,
                phone=phone,
                email=args.get("email", ""),
                start_at=res["start"],
                notes=args.get("notes", ""),
                calendar=calendar.name,
                external_id=res.get("id", ""),
            )
            notify_owner(
                f"📅 Новий запис від AI-рецепціоніста ({ctx.get('channel', 'chat')})\n"
                f"🏢 {ctx.get('business') or '-'}\n"
                f"👤 {client_name}\n📞 {phone}\n"
                f"🕐 {human_slot(res['start'])}\n"
                f"📝 {args.get('notes') or '-'}"
            )
            return {"ok": True, "confirmed": human_slot(res["start"]), "link": res.get("link", "")}

        return {"error": f"Невідомий інструмент {name}"}
    except Exception as e:  # інструмент не повинен валити діалог
        logger.exception("Tool %s failed", name)
        return {"ok": False, "error": f"Технічна помилка: {e.__class__.__name__}"}


class Receptionist:
    def __init__(self, calendar: CalendarBackend):
        self.calendar = calendar
        key = os.environ.get("OPENAI_API_KEY", "")
        self.client = OpenAI(api_key=key) if key else None

    def reply(self, history: list[dict], profile: dict, channel: str = "chat") -> tuple[str, list[dict]]:
        """history — повідомлення user/assistant/tool (без system). Повертає (текст, нова history)."""
        if not self.client:
            return "⚠️ OPENAI_API_KEY не налаштований на сервері.", history

        system = build_system_prompt(
            niche=profile.get("niche") or "real_estate",
            business_name=profile.get("business_name"),
            services=profile.get("services"),
            timezone=TZ_NAME,
            now_iso=datetime.now(TZ).strftime("%Y-%m-%d %H:%M, %A"),
            voice=channel == "voice",
        )
        ctx = {"channel": channel, "business": profile.get("business_name"), "niche": profile.get("niche")}
        msgs = list(history)

        for _ in range(4):  # максимум 4 кола інструментів
            resp = self.client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system}, *msgs],
                tools=TOOLS,
                temperature=0.4,
                max_tokens=300,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                text = (msg.content or "").strip()
                msgs.append({"role": "assistant", "content": text})
                return text, msgs

            msgs.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute_tool(tc.function.name, args, self.calendar, ctx)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})

        return "Вибачте, сталася затримка. Залиште, будь ласка, ім'я та телефон — ми передзвонимо.", msgs
