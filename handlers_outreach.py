"""/outreach — AI-повідомлення в WhatsApp для бізнесу, якого немає в пошуку."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import ai
import config
import handlers_common as common
from handlers_common import MAIN_KEYBOARD
from phones import digits_only, validate_phone
from ui import code, esc, send_html

logger = logging.getLogger(__name__)

OUTREACH_NAME, OUTREACH_PHONE, OUTREACH_NICHE, OUTREACH_LANG = range(20, 24)

LANG_LABELS = {"uk": "🇺🇦 Українська", "en": "🇬🇧 English", "auto": "🌍 Мова країни"}


async def outreach_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not config.has_ai():
        await send_html(
            update.message,
            "⚠️ <b>OPENAI_API_KEY не налаштовано</b> — AI-повідомлення недоступні.\n"
            "Додай ключ у змінні оточення і перезапусти бота.",
        )
        return ConversationHandler.END

    await send_html(
        update.message,
        "💬 <b>WhatsApp Outreach</b>\n\nВведи назву бізнесу, якому хочеш написати:",
    )
    return OUTREACH_NAME


async def outreach_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["outreach_name"] = update.message.text.strip()
    await send_html(
        update.message,
        "📞 Введи номер телефону в міжнародному форматі "
        "<i>(напр. +905321234567)</i>:",
    )
    return OUTREACH_PHONE


async def outreach_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    info = validate_phone(raw)
    digits = digits_only(info.get("e164") or raw)

    if len(digits) < 8:
        await update.message.reply_text(
            "❌ Схоже, це не номер. Введи ще раз у форматі +905321234567:"
        )
        return OUTREACH_PHONE

    context.user_data["outreach_phone"] = digits
    warning = "" if info["valid"] else "\n⚠️ <i>Номер не пройшов перевірку — можливо, є помилка.</i>"
    await send_html(
        update.message,
        f"✅ Номер: {code(info['formatted'])}{warning}\n\n"
        "🏷 В якій ніші працює цей бізнес?\n<i>(restaurant, hotel, beauty salon, gym…)</i>",
    )
    return OUTREACH_NICHE


async def outreach_get_niche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["outreach_niche"] = update.message.text.strip()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(LANG_LABELS["uk"], callback_data="olang:uk"),
            InlineKeyboardButton(LANG_LABELS["en"], callback_data="olang:en"),
        ],
        [InlineKeyboardButton("🌍 Мова країни (авто)", callback_data="olang:auto")],
    ])
    await send_html(update.message, "🌐 Якою мовою писати повідомлення?", reply_markup=keyboard)
    return OUTREACH_LANG


async def outreach_lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    language = query.data.split(":", 1)[1]

    name = context.user_data.get("outreach_name", "")
    niche = context.user_data.get("outreach_niche", "")
    digits = context.user_data.get("outreach_phone", "")

    await query.edit_message_text(
        f"⏳ Генерую повідомлення для {name} ({LANG_LABELS.get(language, language)})…"
    )

    lead = {"name": name, "niche": niche, "phone_formatted": "+" + digits}
    try:
        text = await ai.whatsapp_message(lead, language)
    except ai.AIError as exc:
        await query.message.reply_text(f"❌ {exc}")
        return ConversationHandler.END

    url = ai.wa_link(digits, text)
    await send_html(
        query.message,
        f"✅ <b>Повідомлення готове!</b>\n\n{code(text)}\n\n"
        f"📲 <a href=\"{url}\">Відкрити WhatsApp з цим текстом</a>\n"
        "<i>(залишиться лише натиснути «Надіслати»)</i>\n\n"
        "🔄 /outreach — написати іншому бізнесу",
        reply_markup=MAIN_KEYBOARD,
    )
    for key in ("outreach_name", "outreach_niche", "outreach_phone"):
        context.user_data.pop(key, None)
    return ConversationHandler.END


def build_handlers() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("outreach", outreach_start)],
        states={
            OUTREACH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, outreach_get_name)],
            OUTREACH_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, outreach_get_phone)],
            OUTREACH_NICHE: [MessageHandler(filters.TEXT & ~filters.COMMAND, outreach_get_niche)],
            OUTREACH_LANG: [CallbackQueryHandler(outreach_lang_button, pattern=r"^olang:")],
        },
        fallbacks=common.fallbacks("outreach", outreach_start),
        conversation_timeout=1800,
    )
