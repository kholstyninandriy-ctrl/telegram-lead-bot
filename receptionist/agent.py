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
CLAUDE_MODEL = "claude-opus-5-5"
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


# Ті самі інструменти у форматі Anthropic
CLAUDE_TOOLS = [
    {"name": t["function"]["name"], "description": t["function"]["description"],
     "input_schema": t["function"]["parameters"]}
    for t in TOOLS
]

FALLBACK_TEXT = "Вибачте, сталася затримка. Залиште, будь ласка, ім'я та телефон — ми передзвонимо."


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
    """Провайдер обирається за ключем: ANTHROPIC_API_KEY → Claude, інакше OPENAI_API_KEY → OpenAI."""

    def __init__(self, calendar: CalendarBackend):
        self.calendar = calendar
        self.provider = None
        if os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic

            self.provider = "anthropic"
            self.model = os.environ.get("RECEPTIONIST_MODEL", CLAUDE_MODEL)
            self.client = anthropic.Anthropic()
        elif os.environ.get("OPENAI_API_KEY"):
            self.provider = "openai"
            self.model = MODEL
            self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        else:
            self.client = None

    @staticmethod
    def build_system(profile: dict, channel: str = "chat") -> str:
        """Будується ОДИН раз на сесію: Claude вимагає незмінний system між запитами діалогу."""
        return build_system_prompt(
            niche=profile.get("niche") or "real_estate",
            business_name=profile.get("business_name"),
            services=profile.get("services"),
            timezone=TZ_NAME,
            now_iso=datetime.now(TZ).strftime("%Y-%m-%d %H:%M, %A"),
            voice=channel == "voice",
        )

    def reply(self, history: list[dict], system: str, ctx: dict) -> tuple[str, list[dict]]:
        """history — повідомлення у форматі провайдера (тільки дописуються, ніколи не редагуються).
        Повертає (текст відповіді, нова history)."""
        if not self.client:
            return "⚠️ На сервері не задано ANTHROPIC_API_KEY або OPENAI_API_KEY.", history
        if self.provider == "anthropic":
            return self._reply_claude(history, system, ctx)
        return self._reply_openai(history, system, ctx)

    # ─── Claude ──────────────────────────────────────────────────────────────

    def _claude_params(self) -> dict:
        if self.model.startswith("claude-haiku"):
            # Haiku 4.5: без adaptive thinking / effort / server-side fallback
            return {"max_tokens": 1024}
        return {
            "max_tokens": 4000,
            # Мінімальний effort → швидкі відповіді в чаті
            "output_config": {"effort": "low"},
            # Історія лише дописується; drop_block — страховка, щоб діалог не падав з 400
            "thinking": {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
            # Якщо модель відмовить через класифікатор — API сам повторить на запасній моделі
            "fallbacks": "default",
            "betas": ["server-side-fallback-2026-07-01", "thinking-binding-controls-2026-08-01"],
        }

    def _reply_claude(self, history: list[dict], system: str, ctx: dict) -> tuple[str, list[dict]]:
        msgs = list(history)
        params = self._claude_params()
        for _ in range(4):  # максимум 4 кола інструментів
            resp = self.client.beta.messages.create(
                model=self.model,
                system=system,
                tools=CLAUDE_TOOLS,
                messages=msgs,
                **params,
            )
            if resp.stop_reason == "refusal":
                logger.warning("Claude refusal: %s", resp.stop_details)
                # не дописуємо відмову в історію — останнє повідомлення клієнта прибираємо
                return "Вибачте, з цим я не допоможу. Можу записати вас на консультацію?", history[:-1]

            # Дописуємо content повністю (разом з thinking-блоками) — без змін
            msgs.append({
                "role": "assistant",
                "content": [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in resp.content],
            })
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not tool_uses:
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                return text or "…", msgs

            results = []
            for tu in tool_uses:
                args = tu.input if isinstance(tu.input, dict) else {}
                result = execute_tool(tu.name, args, self.calendar, ctx)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, ensure_ascii=False),
                    **({"is_error": True} if result.get("ok") is False and "Технічна" in result.get("error", "") else {}),
                })
            # усі tool_result — в одному user-повідомленні
            msgs.append({"role": "user", "content": results})

        return FALLBACK_TEXT, msgs

    # ─── OpenAI ──────────────────────────────────────────────────────────────

    def _reply_openai(self, history: list[dict], system: str, ctx: dict) -> tuple[str, list[dict]]:
        msgs = list(history)
        for _ in range(4):
            resp = self.client.chat.completions.create(
                model=self.model,
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

        return FALLBACK_TEXT, msgs
