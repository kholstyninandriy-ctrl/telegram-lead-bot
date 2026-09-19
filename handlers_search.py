"""Пошук бізнесів: діалог /find_leads, картки лідів і кнопки під ними."""

from __future__ import annotations

import asyncio
import io
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, \
    ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction
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
import apify
import db
import places as places_api
from enrich import enrich_many
import handlers_common as common
from handlers_common import MAIN_KEYBOARD
from phones import digits_only, validate_phone
from reviews import analyze_reviews, score_lead
from ui import esc, code, lead_card, lead_keyboard, send_html

logger = logging.getLogger(__name__)

COUNTRY, NICHE, CITY, COUNT = range(4)

EMOJI_RE = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U00002190-\U000027BF" "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF" "️‍⃣" "]+"
)

COUNTRY_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🇺🇦 Ukraine", "🇹🇷 Turkey", "🇵🇹 Portugal"],
        ["🇩🇪 Germany", "🇵🇱 Poland", "🇦🇪 UAE"],
        ["🇪🇸 Spain", "🇮🇹 Italy", "🇬🇧 UK"],
        ["🇺🇸 USA", "🇨🇿 Czech Republic", "🇷🇴 Romania"],
    ],
    one_time_keyboard=True, resize_keyboard=True,
    input_field_placeholder="Або введи свою країну...",
)

NICHE_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🍕 Restaurant", "☕ Cafe", "🍺 Bar"],
        ["💆 Beauty salon", "💅 Nail salon", "💇 Barbershop"],
        ["🏋️ Gym", "🧘 Yoga studio", "🏊 Swimming pool"],
        ["🦷 Dentist", "👁 Optician", "💊 Pharmacy"],
        ["🏨 Hotel", "🏠 Real estate", "🏗 Construction"],
        ["🚗 Car service", "🔧 Auto repair", "🚕 Taxi"],
        ["👗 Clothing store", "📱 Electronics", "🌸 Flower shop"],
        ["🐶 Vet clinic", "🎓 Language school", "🖨 Print shop"],
    ],
    one_time_keyboard=True, resize_keyboard=True,
    input_field_placeholder="Або введи свою нішу...",
)

CITY_SUGGESTIONS = {
    "ukraine": ["Kyiv", "Lviv", "Odesa", "Kharkiv", "Dnipro", "Vinnytsia"],
    "turkey": ["Istanbul", "Antalya", "Ankara", "Izmir", "Bursa", "Alanya"],
    "portugal": ["Lisbon", "Porto", "Faro", "Braga", "Coimbra", "Cascais"],
    "germany": ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne", "Stuttgart"],
    "poland": ["Warsaw", "Krakow", "Wroclaw", "Gdansk", "Poznan", "Lodz"],
    "uae": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Al Ain", "Fujairah"],
    "spain": ["Madrid", "Barcelona", "Valencia", "Seville", "Malaga", "Bilbao"],
    "italy": ["Rome", "Milan", "Naples", "Turin", "Florence", "Bologna"],
    "uk": ["London", "Manchester", "Birmingham", "Liverpool", "Leeds", "Bristol"],
    "usa": ["New York", "Los Angeles", "Chicago", "Miami", "Houston", "Dallas"],
    "czech republic": ["Prague", "Brno", "Ostrava", "Plzen", "Liberec", "Olomouc"],
    "romania": ["Bucharest", "Cluj-Napoca", "Timisoara", "Iasi", "Constanta", "Brasov"],
}


def strip_emoji(text: str) -> str:
    """Прибирає емодзі з тексту кнопки: '🇹🇷 Turkey' → 'Turkey'."""
    cleaned = EMOJI_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text.strip()


# ─── Діалог ───────────────────────────────────────────────────────────────────

async def find_leads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not config.has_google():
        await send_html(
            update.message,
            "⚠️ <b>GOOGLE_API_KEY не налаштовано</b> — пошук недоступний.\n\n"
            "Додай ключ у змінні оточення і перезапусти бота.",
        )
        return ConversationHandler.END

    await send_html(
        update.message,
        "🌍 <b>Крок 1/4 — Країна</b>\n\n"
        "Обери країну або введи свою:\n"
        "<i>(можна англійською: France, Brazil, Japan…)</i>",
        reply_markup=COUNTRY_KEYBOARD,
    )
    return COUNTRY


async def get_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    country = strip_emoji(update.message.text)
    context.user_data["search_country"] = country
    await send_html(
        update.message,
        f"✅ Країна: <b>{esc(country)}</b>\n\n"
        "🏷 <b>Крок 2/4 — Ніша бізнесу</b>\n\n"
        "Обери категорію або введи свою:\n"
        "<i>(photographer, lawyer, accountant, bakery…)</i>",
        reply_markup=NICHE_KEYBOARD,
    )
    return NICHE


async def get_niche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    niche = strip_emoji(update.message.text)
    context.user_data["search_niche"] = niche
    country = context.user_data.get("search_country", "")
    cities = CITY_SUGGESTIONS.get(country.lower(), [])

    if cities:
        rows = [cities[i:i + 3] for i in range(0, len(cities), 3)]
        keyboard = ReplyKeyboardMarkup(
            rows, one_time_keyboard=True, resize_keyboard=True,
            input_field_placeholder="Або введи своє місто...",
        )
        hint = f"Обери місто в <b>{esc(country)}</b> або введи своє:"
    else:
        keyboard = ReplyKeyboardRemove()
        hint = f"Введи назву міста в <b>{esc(country)}</b> англійською:"

    await send_html(
        update.message,
        f"✅ Ніша: <b>{esc(niche)}</b>\n\n🏙 <b>Крок 3/4 — Місто</b>\n\n{hint}",
        reply_markup=keyboard,
    )
    return CITY


async def get_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    city = strip_emoji(update.message.text)
    context.user_data["search_city"] = city
    keyboard = ReplyKeyboardMarkup(
        [["10", "20"], ["40", "60"]], one_time_keyboard=True, resize_keyboard=True,
    )
    await send_html(
        update.message,
        f"✅ Місто: <b>{esc(city)}</b>\n\n"
        "🔢 <b>Крок 4/4 — Кількість результатів</b>\n\n"
        f"Скільки бізнесів знайти? <i>(до {config.MAX_RESULTS})</i>\n"
        "<i>10 — швидко · 20 — стандарт · 40-60 — велика вибірка</i>",
        reply_markup=keyboard,
    )
    return COUNT


async def get_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = re.sub(r"\D", "", update.message.text or "")
    if not raw:
        await update.message.reply_text(f"Введи число від 1 до {config.MAX_RESULTS}:")
        return COUNT
    count = max(1, min(config.MAX_RESULTS, int(raw)))
    return await run_search(update, context, count)


# ─── Пошук ────────────────────────────────────────────────────────────────────

def build_lead(place: dict, niche: str, country: str, city: str) -> dict:
    display_name = place.get("displayName") or {}
    name = (display_name.get("text") if isinstance(display_name, dict) else None) \
        or place.get("name") or "Без назви"
    phone_raw = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or ""
    phone = validate_phone(phone_raw, country)
    analysis = analyze_reviews(place.get("reviews") or [])
    primary_type = place.get("primaryTypeDisplayName") or {}

    return {
        "place_id": place.get("id", ""),
        "name": name,
        "niche": niche,
        "type": primary_type.get("text", "") if isinstance(primary_type, dict) else "",
        "country": country,
        "city": city,
        "address": place.get("formattedAddress", ""),
        "phone": phone_raw,
        "phone_formatted": phone["formatted"] if phone_raw else "",
        "phone_e164": phone.get("e164", "") or digits_only(phone_raw),
        "phone_valid": phone["valid"],
        "phone_note": phone["note"],
        "phone_emoji": phone["emoji"],
        "rating": place.get("rating", ""),
        "review_count": place.get("userRatingCount") or 0,
        "business_status": place.get("businessStatus", ""),
        "website": place.get("websiteUri", ""),
        "maps_url": place.get("googleMapsUri", ""),
        "photo_names": places_api.photo_names(place, limit=5),
        "sentiment": analysis["sentiment"],
        "actuality_emoji": analysis["actuality_emoji"],
        "actuality_label": analysis["actuality_label"],
        "context_points": analysis["context_points"],
        "last_review_date": analysis["last_review_date"],
        "days_since_review": analysis["days_since_review"],
        "closed_signal": analysis["closed_signal"],
    }


def _crm_match(lead: dict, keys: set[str]) -> bool:
    if lead.get("place_id") and f"id:{lead['place_id']}" in keys:
        return True
    digits = digits_only(lead.get("phone", ""))
    if len(digits) >= 7 and f"tel:{digits}" in keys:
        return True
    return f"name:{lead.get('name', '').strip().lower()}" in keys


async def run_search(update: Update, context: ContextTypes.DEFAULT_TYPE, count: int) -> int:
    message = update.message
    user_id = update.effective_user.id
    country = context.user_data.get("search_country", "")
    niche = context.user_data.get("search_niche", "")
    city = context.user_data.get("search_city", "")
    query = f"{niche} in {city}, {country}"

    status = await message.reply_text(
        f"🔍 Шукаю {niche} у {city}, {country} — до {count} результатів…",
        reply_markup=ReplyKeyboardRemove(),
    )

    raw_places, error = await places_api.search_places(query, count)
    if not raw_places:
        await send_html(
            message,
            f"😔 Нічого не знайдено.\n{('⚠️ ' + esc(error)) if error else ''}\n\n"
            "Спробуй іншу нішу або місто: /find_leads",
        )
        return ConversationHandler.END

    await status.edit_text(
        f"✅ Знайдено {len(raw_places)} місць. Шукаю email та соцмережі…"
    )

    leads = [build_lead(place, niche, country, city) for place in raw_places]
    await enrich_many(leads)

    # Власний парсер безсилий проти Cloudflare-челенджів і JS-сайтів —
    # там, де він не дістав email, добираємо через Apify (справжній браузер).
    if config.has_apify():
        blind = [lead for lead in leads if lead.get("website") and not lead.get("email")]
        if blind:
            try:
                await status.edit_text(
                    f"🕵️ Email не знайшовся на {len(blind)} сайтах — "
                    "добираю через Apify (це до кількох хвилин)…"
                )
            except Exception:
                pass
            await apify.enrich_missing(leads)

    contacted = await db.acontacted_keys(user_id)
    for lead in leads:
        lead["score"], lead["score_mark"] = score_lead(lead)
        lead["in_crm"] = _crm_match(lead, contacted)

    # найтепліші ліди — першими, щоб дзвонити згори вниз
    leads.sort(key=lambda item: item["score"], reverse=True)

    lead_ids = await db.asave_leads(user_id, query, leads)
    await db.aprune_leads(user_id)
    context.user_data["last_search_query"] = query

    photos = await asyncio.gather(*[
        places_api.photo_bytes(lead["photo_names"][0]) if lead.get("photo_names") else _none()
        for lead in leads
    ])

    await status.edit_text(f"📇 Готую {len(leads)} карток…")

    ai_enabled = config.has_ai()
    for position, (lead, lead_id, photo) in enumerate(zip(leads, lead_ids, photos), 1):
        if photo:
            try:
                await message.reply_photo(io.BytesIO(photo))
            except Exception as exc:
                logger.warning("Фото для %s не надіслано: %s", lead["name"], exc)
        await send_html(
            message,
            lead_card(lead, position, len(leads)),
            reply_markup=lead_keyboard(lead_id, lead, ai_enabled),
        )
        await asyncio.sleep(config.SEND_DELAY)

    hot = sum(1 for lead in leads if lead["score"] >= 75)
    with_email = sum(1 for lead in leads if lead.get("email"))
    with_phone = sum(1 for lead in leads if lead.get("phone_valid"))
    with_instagram = sum(1 for lead in leads if lead.get("instagram_verified"))
    no_website = sum(1 for lead in leads if not lead.get("website"))
    in_crm = sum(1 for lead in leads if lead.get("in_crm"))

    via_apify = sum(1 for lead in leads if lead.get("email_source") == "apify")
    summary = [
        f"🏁 <b>Готово! Проаналізовано {len(leads)} лідів</b>",
        "",
        f"🔥 Гарячих (75+): <b>{hot}</b>",
        f"📞 З валідним телефоном: <b>{with_phone}</b>",
        f"✉️ З email: <b>{with_email}</b>"
        + (f" <i>(у {no_website} немає сайту — email там не існує)</i>" if no_website else ""),
    ]
    if via_apify:
        summary.append(f"    <i>↳ {via_apify} з них дістав Apify (браузером)</i>")
    summary.append(f"📸 З Instagram: <b>{with_instagram}</b>")
    if in_crm:
        summary.append(f"🗂 Вже у твоїй CRM: <b>{in_crm}</b>")
    blind_sites = sum(1 for lead in leads
                      if lead.get("website") and not lead.get("email"))
    if blind_sites and not config.has_apify():
        summary.append(
            f"\n💡 На {blind_sites} сайтах email захищений Cloudflare або малюється JS. "
            "Додай <code>APIFY_TOKEN</code> — бот дістане їх браузером."
        )
    summary += [
        "",
        "📤 /export_search — вивантажити ці ліди в CSV",
        "📝 /add_note — записати результат дзвінку",
        "🔄 /find_leads — новий пошук",
    ]
    try:
        await status.delete()
    except Exception:  # повідомлення могло бути видалене вручну
        pass
    await send_html(message, "\n".join(summary), reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def _none():
    return None


# ─── Кнопки під картками ──────────────────────────────────────────────────────

async def _load_lead(update: Update) -> dict | None:
    query = update.callback_query
    try:
        lead_id = int(query.data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None
    lead = await db.aget_lead(lead_id, update.effective_user.id)
    if lead is None:
        await query.message.reply_text(
            "⚠️ Дані ліда не знайдено — зроби новий пошук: /find_leads"
        )
    return lead


async def approach_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lead = await _load_lead(update)
    if not lead:
        return

    await query.message.chat.send_action(ChatAction.TYPING)
    placeholder = await query.message.reply_text(f"🤖 Аналізую {lead['name']}…")

    try:
        data = await ai.approach_package(lead)
    except ai.AIError as exc:
        await placeholder.edit_text(f"❌ {exc}")
        return

    lines = [f"🎯 <b>План підходу до {esc(lead['name'])}</b>"]
    if data.get("hook"):
        lines += ["", f"🪝 <b>Зачіпка:</b> {esc(data['hook'])}"]
    if data.get("call_script"):
        lines += ["", "📞 <b>Скрипт дзвінка:</b>", code(str(data["call_script"]))]
    whatsapp_text = str(data.get("whatsapp", "")).strip()
    if whatsapp_text:
        lines += ["", "💬 <b>Повідомлення WhatsApp:</b>", code(whatsapp_text)]
    strategy = data.get("strategy") or []
    if isinstance(strategy, str):
        strategy = [strategy]
    if strategy:
        lines += ["", "💡 <b>Стратегія:</b>"]
        lines += [f"  • {esc(item)}" for item in strategy]
    if data.get("objection"):
        lines += ["", f"🛡 <b>Заперечення:</b> {esc(data['objection'])}"]

    phone_digits = digits_only(lead.get("phone_e164") or lead.get("phone", ""))
    if phone_digits and whatsapp_text:
        url = ai.wa_link(phone_digits, whatsapp_text)
        lines += ["", f"📲 <a href=\"{url}\">Відкрити WhatsApp з цим текстом</a>"]

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Записати результат", callback_data=f"nt:{lead['lead_id']}")
    ]])
    await placeholder.delete()
    await send_html(query.message, "\n".join(lines), reply_markup=keyboard)


async def whatsapp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lead = await _load_lead(update)
    if not lead:
        return

    phone_digits = digits_only(lead.get("phone_e164") or lead.get("phone", ""))
    if len(phone_digits) < 7:
        await query.message.reply_text("⚠️ У цього бізнесу немає придатного номера для WhatsApp.")
        return

    placeholder = await query.message.reply_text("🤖 Пишу повідомлення…")
    try:
        text = await ai.whatsapp_message(lead, "auto")
    except ai.AIError as exc:
        await placeholder.edit_text(f"❌ {exc}")
        return

    url = ai.wa_link(phone_digits, text)
    await placeholder.delete()
    await send_html(
        query.message,
        f"💬 <b>WhatsApp для {esc(lead['name'])}</b>\n\n{code(text)}\n\n"
        f"📲 <a href=\"{url}\">Відкрити WhatsApp з готовим текстом</a>",
    )


async def email_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lead = await _load_lead(update)
    if not lead:
        return
    if not lead.get("email"):
        await query.message.reply_text("⚠️ Email цього бізнесу не знайдено.")
        return

    placeholder = await query.message.reply_text("🤖 Пишу лист…")
    try:
        letter = await ai.cold_email(lead, "auto")
    except ai.AIError as exc:
        await placeholder.edit_text(f"❌ {exc}")
        return

    url = ai.mailto_link(lead["email"], letter["subject"], letter["body"])
    await placeholder.delete()
    await send_html(
        query.message,
        f"✉️ <b>Лист для {esc(lead['name'])}</b>\n"
        f"Кому: {code(lead['email'])}\n\n"
        f"<b>Тема:</b> {code(letter['subject'])}\n\n{code(letter['body'])}\n\n"
        f"📧 <a href=\"{url}\">Відкрити в поштовому клієнті</a>",
    )


async def instagram_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lead = await _load_lead(update)
    if not lead:
        return

    placeholder = await query.message.reply_text("🤖 Генерую текст для Instagram…")
    try:
        text = await ai.instagram_dm(lead)
    except ai.AIError as exc:
        await placeholder.edit_text(f"❌ {exc}")
        return

    keyboard = None
    if lead.get("instagram_url"):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📸 Відкрити профіль", url=lead["instagram_url"])
        ]])
    await placeholder.delete()
    await send_html(
        query.message,
        f"✉️ <b>Текст для Instagram Direct</b> <i>(натисни, щоб скопіювати)</i>\n\n"
        f"{code(text)}\n\n"
        "⚠️ Instagram, на відміну від WhatsApp, не вміє підставляти текст через посилання — "
        "скопіюй і встав вручну.",
        reply_markup=keyboard,
    )


async def photos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lead = await _load_lead(update)
    if not lead:
        return

    names = (lead.get("photo_names") or [])[1:5]
    if not names:
        await query.message.reply_text("Більше фото немає.")
        return

    await query.message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    downloaded = await asyncio.gather(*(places_api.photo_bytes(name) for name in names))
    media = [InputMediaPhoto(io.BytesIO(data)) for data in downloaded if data]
    if not media:
        await query.message.reply_text("⚠️ Не вдалося завантажити фото.")
        return
    try:
        await query.message.reply_media_group(media)
    except Exception as exc:
        logger.warning("media group failed: %s", exc)
        await query.message.reply_text("⚠️ Не вдалося надіслати фото.")


def build_handlers() -> tuple:
    conversation = ConversationHandler(
        entry_points=[CommandHandler("find_leads", find_leads)],
        states={
            COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_country)],
            NICHE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_niche)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_city)],
            COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_count)],
        },
        fallbacks=common.fallbacks("find_leads", find_leads),
        conversation_timeout=1800,
    )
    callbacks = (
        CallbackQueryHandler(approach_handler, pattern=r"^ap:\d+$"),
        CallbackQueryHandler(whatsapp_handler, pattern=r"^wa:\d+$"),
        CallbackQueryHandler(email_handler, pattern=r"^em:\d+$"),
        CallbackQueryHandler(instagram_handler, pattern=r"^ig:\d+$"),
        CallbackQueryHandler(photos_handler, pattern=r"^ph:\d+$"),
    )
    return conversation, callbacks
