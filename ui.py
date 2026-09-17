"""Форматування повідомлень і клавіатури.

Весь текст іде в Telegram у режимі HTML, а всі динамічні значення (назви
бізнесів, коментарі, адреси) екрануються. Це прибирає цілий клас падінь
"Can't parse entities", які виникали з Markdown, коли в назві бізнесу
траплялись _ * [ ` — а таких назв на Google Maps дуже багато.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut

logger = logging.getLogger(__name__)

TG_LIMIT = 3800  # запас до ліміту 4096

STATUS_LABELS = {
    "called": "📞 Зателефонував",
    "interested": "🟢 Зацікавлений",
    "not_interested": "🔴 Не зацікавлений",
    "callback": "🔁 Передзвонить",
    "no_answer": "📵 Не відповів",
    "deal": "🤝 Угода",
}

BUSINESS_STATUS_LABELS = {
    "OPERATIONAL": "✅ Працює",
    "CLOSED_TEMPORARILY": "⏸ Тимчасово закрито",
    "CLOSED_PERMANENTLY": "🚫 Постійно закрито",
}


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def link(url: str, label: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{esc(label)}</a>'


def code(value: str) -> str:
    return f"<code>{esc(value)}</code>"


def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Ріже довгий текст по межах рядків, а не посеред HTML-тега."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


async def send_html(message: Message, text: str, reply_markup=None,
                    disable_preview: bool = True, **kwargs) -> Message | None:
    """Надсилає HTML-повідомлення: ріже на частини, переживає флуд-ліміт
    і, якщо розмітка раптом зламана, віддає користувачу чистий текст."""
    sent = None
    parts = split_message(text)
    for index, part in enumerate(parts):
        markup = reply_markup if index == len(parts) - 1 else None
        for attempt in range(3):
            try:
                sent = await message.reply_text(
                    part,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                    disable_web_page_preview=disable_preview,
                    **kwargs,
                )
                break
            except RetryAfter as exc:
                await asyncio.sleep(float(exc.retry_after) + 0.5)
            except TimedOut:
                await asyncio.sleep(1.5)
            except BadRequest as exc:
                logger.warning("HTML send failed (%s) — fallback to plain text", exc)
                sent = await message.reply_text(
                    html.unescape(_strip_tags(part)),
                    reply_markup=markup,
                    disable_web_page_preview=disable_preview,
                )
                break
    return sent


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


# ─── Картка ліда ──────────────────────────────────────────────────────────────

def lead_card(lead: dict, index: int, total: int) -> str:
    lines = [
        f"<b>{index}/{total}. {esc(lead.get('name', 'Без назви'))}</b>"
        f"  ·  {esc(lead.get('score_mark', ''))} {lead.get('score', 0)}/100",
    ]
    if lead.get("in_crm"):
        lines.append("🗂 <i>Цей бізнес уже є у твоїх нотатках</i>")
    lines.append(f"📍 {esc(lead.get('address', 'адреса невідома'))}")

    rating = lead.get("rating") or "—"
    status = BUSINESS_STATUS_LABELS.get(lead.get("business_status", ""), "❓ Статус невідомий")
    lines.append(f"⭐ {esc(rating)} ({lead.get('review_count', 0)} відгуків) · {status}")

    phone_display = lead.get("phone_formatted") or "—"
    lines += [
        "",
        f"📞 <b>Телефон:</b> {code(phone_display)} {lead.get('phone_emoji', '')}",
        f"   ↳ {esc(lead.get('phone_note', ''))}",
        "",
        f"🔍 <b>Актуальність:</b> {lead.get('actuality_emoji', '')} "
        f"{esc(lead.get('actuality_label', ''))}",
    ]

    points = lead.get("context_points") or []
    if points:
        lines += ["", "📋 <b>Контекст бізнесу:</b>"]
        lines += [f"  • {esc(point)}" for point in points]

    contacts = []
    if lead.get("website"):
        contacts.append(f"🌐 {link(lead['website'], lead['website'][:60])}")
    if lead.get("email"):
        contacts.append(f"✉️ {code(lead['email'])}")
    if lead.get("instagram_verified") and lead.get("instagram"):
        contacts.append(f"📸 {link(lead['instagram_url'], '@' + lead['instagram'])}")
    if lead.get("facebook"):
        contacts.append(f"👥 {link('https://facebook.com/' + lead['facebook'], 'Facebook')}")
    if lead.get("maps_url"):
        contacts.append(f"🗺 {link(lead['maps_url'], 'Відкрити в Maps')}")
    if contacts:
        lines += [""] + contacts
    return "\n".join(lines)


def lead_keyboard(lead_id: int, lead: dict, ai_enabled: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if ai_enabled:
        rows.append([InlineKeyboardButton("🎯 Як підійти до цього бізнесу",
                                          callback_data=f"ap:{lead_id}")])
        second = []
        if lead.get("phone_e164"):
            second.append(InlineKeyboardButton("💬 WhatsApp-текст", callback_data=f"wa:{lead_id}"))
        if lead.get("email"):
            second.append(InlineKeyboardButton("✉️ Лист на email", callback_data=f"em:{lead_id}"))
        if second:
            rows.append(second)

    third = []
    if len(lead.get("photo_names") or []) > 1:
        third.append(InlineKeyboardButton(
            f"📷 Ще фото ({len(lead['photo_names']) - 1})", callback_data=f"ph:{lead_id}"
        ))
    instagram_url = lead.get("instagram_url") or (
        "https://www.google.com/search?q=" + quote(
            f'site:instagram.com "{lead.get("name", "")}" {lead.get("city", "")}'.strip()
        )
    )
    if lead.get("instagram_verified"):
        if ai_enabled:
            third.append(InlineKeyboardButton("📸 Текст в Instagram",
                                              callback_data=f"ig:{lead_id}"))
        third.append(InlineKeyboardButton("🔗 Профіль", url=instagram_url))
    else:
        third.append(InlineKeyboardButton("🔍 Знайти Instagram", url=instagram_url))
    if third:
        rows.append(third)

    rows.append([InlineKeyboardButton("📝 Записати результат", callback_data=f"nt:{lead_id}")])
    return InlineKeyboardMarkup(rows)


def status_keyboard(prefix: str = "ns") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"{prefix}:{key}")]
        for key, label in STATUS_LABELS.items()
    ]
    return InlineKeyboardMarkup(rows)


def reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏰ Через 2 год", callback_data="rem:2h"),
            InlineKeyboardButton("📅 Завтра", callback_data="rem:1d"),
        ],
        [
            InlineKeyboardButton("🗓 Через 3 дні", callback_data="rem:3d"),
            InlineKeyboardButton("📆 Через тиждень", callback_data="rem:7d"),
        ],
        [InlineKeyboardButton("✖️ Без нагадування", callback_data="rem:no")],
    ])
