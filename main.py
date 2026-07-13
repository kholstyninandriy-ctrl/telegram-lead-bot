"""
LEAD FINDER BOT — повна версія:
- Пошук бізнесів через Google Places API v1
- Вибір кількості результатів
- Валідація телефонів
- Аналіз відгуків (актуальність, настрій, контекст)
- AI пакет підходу до бізнесу: скрипт дзвінка + WA повідомлення + поради
- CRM-нотатник: запис дзвінків, статусів, коментарів
- Експорт нотаток списком або CSV
"""

import csv
import io
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import quote

import phonenumbers
import requests
from openai import OpenAI
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

GOOGLE_API_KEY = os.environ.get(AIzaSyBAYg5x7vlNnxoyzqFk5lc1oiP54k1TS7U) or os.environ.get("GOOGLE_MAPS_API_KEY", "")
OPENAI_API_KEY = os.environ.get("sk-proj-N22i5_neUG3fueTR_z8HjRy6NE4", "")
DB_PATH = os.path.join(os.path.dirname(__file__), "notes.db")

# ─── OpenAI client ────────────────────────────────────────────────────────────

def get_openai_client() -> OpenAI | None:
    if not OPENAI_API_KEY:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)

# ─── Conversation states ───────────────────────────────────────────────────────
COUNTRY, NICHE, CITY, COUNT = range(4)
NOTE_NAME, NOTE_PHONE, NOTE_STATUS, NOTE_COMMENT = range(10, 14)
OUTREACH_NAME, OUTREACH_PHONE, OUTREACH_NICHE, OUTREACH_LANG = range(20, 24)

# ─── Database ─────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                biz_name    TEXT,
                phone       TEXT,
                status      TEXT,
                comment     TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        con.commit()


def save_note(user_id: int, biz_name: str, phone: str, status: str, comment: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO notes (user_id, biz_name, phone, status, comment, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, biz_name, phone, status, comment, ts),
        )
        con.commit()


def get_notes(user_id: int) -> list[dict]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM notes WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_note(note_id: int, user_id: int):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
        con.commit()


# ─── Google Places API v1 ─────────────────────────────────────────────────────

def search_places(query: str, max_count: int = 10) -> tuple[list[dict], str]:
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.rating,places.userRatingCount,places.businessStatus,"
            "places.nationalPhoneNumber,places.internationalPhoneNumber,"
            "places.websiteUri,places.googleMapsUri,places.reviews,places.photos"
        ),
    }
    body = {"textQuery": query, "languageCode": "uk", "maxResultCount": min(max_count, 20)}
    try:
        r = requests.post(url, json=body, headers=headers, timeout=15)
        logger.info("Places API v1 %s | query: %s", r.status_code, query)
        if r.status_code != 200:
            err = r.json().get("error", {})
            msg = err.get("message", r.text[:200])
            logger.error("Places API error %s: %s", r.status_code, msg)
            return [], f"HTTP {r.status_code}: {msg}"
        return r.json().get("places", []), ""
    except Exception as e:
        logger.error("search_places exception: %s", e)
        return [], str(e)


def get_photo_urls(place: dict, max_photos: int = 3) -> list[str]:
    """Реальні фото бізнесу з Google Maps (не згенеровані, а фактичні знімки)."""
    photos = place.get("photos") or []
    urls = []
    for photo in photos[:max_photos]:
        name = photo.get("name", "")
        if name:
            urls.append(
                f"https://places.googleapis.com/v1/{name}/media"
                f"?maxWidthPx=800&key={GOOGLE_API_KEY}"
            )
    return urls


# ─── Phone validation ─────────────────────────────────────────────────────────

def validate_phone(raw: str, country_hint: str = "") -> dict:
    if not raw:
        return {"valid": False, "formatted": "—", "status_emoji": "❌", "note": "відсутній"}
    try:
        parsed = phonenumbers.parse(raw, country_hint.upper() if country_hint else None)
        is_valid = phonenumbers.is_valid_number(parsed)
        is_possible = phonenumbers.is_possible_number(parsed)
        number_type = phonenumbers.number_type(parsed)
        type_map = {
            phonenumbers.PhoneNumberType.MOBILE: "мобільний",
            phonenumbers.PhoneNumberType.FIXED_LINE: "стаціонарний",
            phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "моб/стаціон",
            phonenumbers.PhoneNumberType.TOLL_FREE: "безкоштовний",
            phonenumbers.PhoneNumberType.VOIP: "VoIP",
        }
        type_label = type_map.get(number_type, "невідомий")
        fmt = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        region = phonenumbers.region_code_for_number(parsed)
        if is_valid:
            return {"valid": True, "formatted": fmt, "region": region,
                    "type": type_label, "status_emoji": "✅", "note": f"{type_label} · {region}"}
        elif is_possible:
            return {"valid": False, "formatted": fmt, "status_emoji": "⚠️",
                    "note": "можливий, але не підтверджений"}
        else:
            return {"valid": False, "formatted": raw, "status_emoji": "❌", "note": "невалідний формат"}
    except Exception:
        return {"valid": False, "formatted": raw, "status_emoji": "❌", "note": "помилка парсингу"}


# ─── Review analysis ──────────────────────────────────────────────────────────

POSITIVE_WORDS = {
    "відмінно", "чудово", "супер", "рекомендую", "якісно", "швидко",
    "excellent", "great", "amazing", "fantastic", "recommend", "best", "wonderful",
}
NEGATIVE_WORDS = {
    "погано", "жахливо", "грубо", "повільно", "bad", "terrible", "awful",
    "slow", "rude", "horrible", "worst",
}
CLOSED_SIGNALS = {"закрито", "не працює", "closed", "out of business", "fechado"}


def _review_ts(rv: dict) -> float:
    pt = rv.get("publishTime", "")
    if pt and "T" in pt:
        try:
            return datetime.fromisoformat(pt.replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
    return rv.get("time", 0) or 0.0


def _review_text(rv: dict) -> str:
    t = rv.get("text")
    return (t.get("text", "") if isinstance(t, dict) else t) or ""


def analyze_reviews(reviews: list[dict]) -> dict:
    if not reviews:
        return {"actuality_emoji": "⚫", "actuality_label": "відгуків немає",
                "sentiment": "невідомо", "context_points": [], "last_review_date": "—"}

    now_ts = datetime.now(timezone.utc).timestamp()
    sorted_rv = sorted(reviews, key=_review_ts, reverse=True)
    latest_ts = _review_ts(sorted_rv[0])
    days_ago = (now_ts - latest_ts) / 86400 if latest_ts else 9999

    if days_ago < 60:
        a_emoji, a_label = "🟢", f"активний ({int(days_ago)} дн. тому)"
    elif days_ago < 180:
        a_emoji, a_label = "🟡", f"помірна активність ({int(days_ago)} дн. тому)"
    else:
        a_emoji, a_label = "🔴", f"давно без відгуків ({int(days_ago // 30)} міс. тому)"

    last_date = (datetime.fromtimestamp(latest_ts, tz=timezone.utc).strftime("%d.%m.%Y")
                 if latest_ts else "—")

    pos = neg = 0
    all_text = ""
    for rv in reviews:
        txt = _review_text(rv).lower()
        all_text += " " + txt
        rating = rv.get("rating", 3)
        if rating >= 4:
            pos += 1
        elif rating <= 2:
            neg += 1
        for w in POSITIVE_WORDS:
            if w in txt:
                pos += 0.5
        for w in NEGATIVE_WORDS:
            if w in txt:
                neg += 0.5

    if pos > neg * 1.5:
        sentiment = "позитивний"
    elif neg > pos * 1.5:
        sentiment = "негативний"
    else:
        sentiment = "змішаний"

    closed = any(sig in all_text for sig in CLOSED_SIGNALS)
    if closed:
        a_emoji, a_label = "🔴", "можливо закрито (за відгуками)"

    ratings = [rv.get("rating", 0) for rv in reviews if rv.get("rating")]
    avg = sum(ratings) / len(ratings) if ratings else None

    context_points = [
        f"{a_emoji} Останній відгук: {last_date}",
        f"{'😊' if sentiment == 'позитивний' else '😐' if sentiment == 'змішаний' else '😞'} "
        f"Настрій відгуків: {sentiment} ({len(reviews)} відгуків)",
    ]
    if avg:
        context_points.append(f"⭐ Середня оцінка у відгуках: {avg:.1f}")
    context_points.append(
        "🚫 У відгуках згадується, що заклад закрито або не працює"
        if closed else "🏪 Жодних сигналів про закриття у відгуках"
    )

    return {"actuality_emoji": a_emoji, "actuality_label": a_label,
            "sentiment": sentiment, "context_points": context_points,
            "last_review_date": last_date}


def extract_instagram(website: str, name: str = "", city: str = "") -> dict:
    """Перевіряє, чи є в сайті бізнесу посилання на реальний Instagram.
    Google Places не віддає Instagram напряму — тому дивимось лише на website.
    Якщо немає — даємо посилання на Google-пошук (не вигадуємо акаунт!)."""
    if website and "instagram.com" in website.lower():
        handle = website.rstrip("/").split("instagram.com/")[-1].split("?")[0].split("/")[0]
        if handle:
            return {"verified": True, "url": f"https://instagram.com/{handle}", "handle": handle}
    query = f'site:instagram.com "{name}" {city}'.strip()
    search_url = "https://www.google.com/search?q=" + quote(query)
    return {"verified": False, "url": search_url, "handle": ""}


# ─── Lead card formatter ──────────────────────────────────────────────────────

def format_lead(place: dict, idx: int, country: str) -> str:
    dn = place.get("displayName") or {}
    name = (dn.get("text") if isinstance(dn, dict) else None) or place.get("name", "Без назви")
    address = place.get("formattedAddress") or place.get("formatted_address", "адреса невідома")
    rating = place.get("rating", "—")
    total = place.get("userRatingCount") or place.get("user_ratings_total", 0)
    biz_status = place.get("businessStatus") or place.get("business_status", "")
    phone_raw = (place.get("internationalPhoneNumber")
                 or place.get("nationalPhoneNumber", ""))
    phone_info = validate_phone(phone_raw, country)
    reviews = place.get("reviews") or []
    analysis = analyze_reviews(reviews)
    status_map = {"OPERATIONAL": "✅ Працює",
                  "CLOSED_TEMPORARILY": "⏸ Тимчасово закрито",
                  "CLOSED_PERMANENTLY": "🚫 Постійно закрито"}
    biz_label = status_map.get(biz_status, "❓ Статус невідомий")
    website = place.get("websiteUri", "")
    maps_url = place.get("googleMapsUri", "")

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━",
        f"*{idx}. {name}*",
        f"📍 {address}",
        f"⭐ {rating} ({total} відгуків) · {biz_label}",
        "",
        f"📞 *Телефон:* {phone_info['formatted']} {phone_info['status_emoji']}",
        f"   ↳ {phone_info['note']}",
        "",
        f"🔍 *Актуальність:* {analysis['actuality_emoji']} {analysis['actuality_label']}",
    ]
    if analysis["context_points"]:
        lines += ["", "📋 *Контекст бізнесу:*"]
        for pt in analysis["context_points"]:
            lines.append(f"  • {pt}")
    if website:
        lines.append(f"\n🌐 {website}")
    if maps_url:
        lines.append(f"🗺 [Відкрити в Maps]({maps_url})")
    return "\n".join(lines)


# ─── /start ───────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "📖 *Інструкція — Lead Finder Bot*\n\n"

    "━━━━━━━━━━━━━━━━━\n"
    "🔍 *ПОШУК БІЗНЕСІВ*\n"
    "━━━━━━━━━━━━━━━━━\n"
    "/find\\_leads — почати пошук\n\n"
    "Бот запитає по черзі:\n"
    "1️⃣ *Країну* — де шукати _(напр. Turkey, Portugal, Germany)_\n"
    "2️⃣ *Нішу* — яку категорію бізнесу _(напр. restaurant, hotel, dentist, gym, beauty salon)_\n"
    "3️⃣ *Місто* — в якому місті _(напр. Antalya, Lisbon, Berlin)_\n"
    "4️⃣ *Кількість* — скільки результатів потрібно _(5 / 10 / 20 або своє число)_\n\n"
    "📌 Для кожного бізнесу бот покаже:\n"
    "• Назву, адресу, рейтинг\n"
    "• Телефон з перевіркою валідності ✅⚠️❌\n"
    "• Актуальність за датою останнього відгуку 🟢🟡🔴\n"
    "• Контекст: настрій відгуків, середня оцінка, статус роботи\n"
    "• Посилання на Google Maps\n\n"

    "━━━━━━━━━━━━━━━━━\n"
    "💬 *WHATSAPP OUTREACH*\n"
    "━━━━━━━━━━━━━━━━━\n"
    "/outreach — згенерувати AI-повідомлення для бізнесу\n\n"
    "Бот запитає:\n"
    "1️⃣ *Назву бізнесу*\n"
    "2️⃣ *Номер телефону* _(міжнародний формат, напр. +905321234567)_\n"
    "3️⃣ *Нішу* _(restaurant, hotel, beauty salon...)_\n"
    "4️⃣ *Мову* — 🇺🇦 Українська / 🇬🇧 English / 🌍 Мова країни\n\n"
    "✅ Результат:\n"
    "• Готовий персональний текст повідомлення\n"
    "• Посилання `wa.me` — клікаєш, WhatsApp відкривається з текстом\n"
    "• Залишається лише натиснути «Надіслати» 👆\n\n"

    "━━━━━━━━━━━━━━━━━\n"
    "📝 *CRM-НОТАТНИК*\n"
    "━━━━━━━━━━━━━━━━━\n"
    "/add\\_note — записати результат дзвінку\n\n"
    "Бот запитає:\n"
    "1️⃣ *Назву бізнесу*\n"
    "2️⃣ *Телефон* _(або `-` якщо не потрібен)_\n"
    "3️⃣ *Статус* — обери з кнопок:\n"
    "   📞 Зателефонував\n"
    "   🟢 Зацікавлений\n"
    "   🔴 Не зацікавлений\n"
    "   🔁 Передзвонить\n"
    "   📵 Не відповів\n"
    "4️⃣ *Коментар* — будь-яка нотатка _(або `-` без коментаря)_\n\n"

    "━━━━━━━━━━━━━━━━━\n"
    "📋 *ПЕРЕГЛЯД І ЕКСПОРТ*\n"
    "━━━━━━━━━━━━━━━━━\n"
    "/notes — показати всі нотатки списком\n"
    "/export — скачати всі нотатки у файл Excel/CSV\n"
    "/delete\\_note 5 — видалити нотатку з номером 5\n\n"

    "━━━━━━━━━━━━━━━━━\n"
    "⚙️ *ІНШЕ*\n"
    "━━━━━━━━━━━━━━━━━\n"
    "/start — головне меню\n"
    "/help — ця інструкція\n"
    "/cancel — скасувати поточну дію"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = user.first_name if user else "друже"

    await update.message.reply_text(
        f"👋 Привіт, *{name}*\\! Радий бачити тебе тут\\.\n\n"
        "🤖 Я — *Lead Finder Bot*\n"
        "Твій AI\\-помічник для пошуку клієнтів і виходу на бізнеси по всьому світу\\.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *ЩО Я ВМІЮ:*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 *Знаходжу бізнеси*\n"
        "Шукаю по будь\\-якій ніші та місту через Google Maps \\— з телефонами, адресами, рейтингом і аналізом відгуків\\.\n\n"
        "🎯 *Генерую план підходу \\(AI\\)*\n"
        "Для кожного бізнесу створюю персональний скрипт дзвінка, повідомлення для WhatsApp і стратегічні поради — враховуючи їхній рейтинг і нішу\\.\n\n"
        "💬 *Готую WA повідомлення*\n"
        "Натискаєш посилання → WhatsApp відкривається з готовим текстом → залишається лише надіслати\\.\n\n"
        "📝 *Веду CRM\\-нотатник*\n"
        "Записую результати дзвінків зі статусами: зацікавлений, передзвонить, не відповів та ін\\.\n\n"
        "📊 *Експортую в Excel*\n"
        "Всі нотатки одним файлом CSV для подальшої роботи\\.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 *З ЧОГО ПОЧАТИ:*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "/find\\_leads — 🔍 Знайти бізнеси\n"
        "/outreach — 💬 Написати в WhatsApp\n"
        "/add\\_note — 📝 Записати дзвінок\n"
        "/notes — 📋 Мої нотатки\n"
        "/help — 📖 Повна інструкція\n\n"
        "👇 *Натисни /find\\_leads щоб почати пошук*",
        parse_mode="MarkdownV2",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


# ─── /find_leads conversation ─────────────────────────────────────────────────

async def find_leads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    country_keyboard = ReplyKeyboardMarkup(
        [
            ["🇺🇦 Ukraine", "🇹🇷 Turkey", "🇵🇹 Portugal"],
            ["🇩🇪 Germany", "🇵🇱 Poland", "🇦🇪 UAE"],
            ["🇪🇸 Spain", "🇮🇹 Italy", "🇬🇧 UK"],
            ["🇺🇸 USA", "🇨🇿 Czech Republic", "🇷🇴 Romania"],
        ],
        one_time_keyboard=True,
        resize_keyboard=True,
        input_field_placeholder="Або введи свою країну...",
    )
    await update.message.reply_text(
        "🌍 *Крок 1/4 — Країна*\n\n"
        "Обери країну або введи свою:\n"
        "_(можна писати англійською: France, Brazil, Japan...)_",
        parse_mode="Markdown",
        reply_markup=country_keyboard,
    )
    return COUNTRY


async def get_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    # Прибираємо прапор і зайві пробіли якщо вибрали з кнопки
    country = raw.split(" ", 1)[-1] if raw.startswith(("🇺", "🇹", "🇵", "🇩", "🇦", "🇪", "🇮", "🇬", "🇺", "🇨", "🇷", "🇧", "🇯", "🇫")) else raw
    context.user_data["country"] = country.strip()

    niche_keyboard = ReplyKeyboardMarkup(
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
        one_time_keyboard=True,
        resize_keyboard=True,
        input_field_placeholder="Або введи свою нішу...",
    )
    await update.message.reply_text(
        f"✅ Країна: *{context.user_data['country']}*\n\n"
        "🏷 *Крок 2/4 — Ніша бізнесу*\n\n"
        "Обери категорію або введи свою:\n"
        "_(можна писати: photographer, lawyer, accountant, bakery...)_",
        parse_mode="Markdown",
        reply_markup=niche_keyboard,
    )
    return NICHE


CITY_SUGGESTIONS = {
    "ukraine": ["Kyiv", "Lviv", "Odessa", "Kharkiv", "Dnipro", "Vinnytsia"],
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


async def get_niche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    # Прибираємо емодзі якщо вибрали з кнопки
    niche = " ".join(w for w in raw.split() if not w.startswith(("🍕","☕","🍺","💆","💅","💇","🏋","🧘","🏊","🦷","👁","💊","🏨","🏠","🏗","🚗","🔧","🚕","👗","📱","🌸","🐶","🎓","🖨","️")))
    niche = niche.strip() or raw.strip()
    context.user_data["niche"] = niche

    country = context.user_data.get("country", "")
    cities = CITY_SUGGESTIONS.get(country.lower(), [])

    if cities:
        rows = [cities[i:i + 3] for i in range(0, len(cities), 3)]
        keyboard = ReplyKeyboardMarkup(
            rows,
            one_time_keyboard=True,
            resize_keyboard=True,
            input_field_placeholder="Або введи своє місто...",
        )
        hint = f"Обери місто в *{country}* або введи своє:"
    else:
        keyboard = ReplyKeyboardRemove()
        hint = f"Введи назву міста в *{country}* англійською:\n_(напр. столицю або велике місто)_"

    await update.message.reply_text(
        f"✅ Ніша: *{niche}*\n\n"
        "🏙 *Крок 3/4 — Місто*\n\n"
        f"{hint}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return CITY


async def get_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["city"] = update.message.text.strip()
    keyboard = ReplyKeyboardMarkup(
        [["5", "10", "20"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        f"✅ Місто: *{context.user_data['city']}*\n\n"
        "🔢 *Крок 4/4 — Кількість результатів*\n\n"
        "Скільки бізнесів знайти?\n"
        "_(5 — швидко переглянути · 10 — стандарт · 20 — максимум)_",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    return COUNT


async def count_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        count = max(1, min(20, int(text)))
    except ValueError:
        await update.message.reply_text(
            "Введи число від 1 до 20:",
            reply_markup=ReplyKeyboardMarkup([["5", "10", "20"]], one_time_keyboard=True, resize_keyboard=True),
        )
        return COUNT
    return await _do_search(update, context, count)


def _extract_lead_data(place: dict, niche: str, country: str, city: str = "") -> dict:
    """Витягує ключові дані ліда для збереження і AI-аналізу."""
    dn = place.get("displayName") or {}
    name = (dn.get("text") if isinstance(dn, dict) else None) or place.get("name", "Без назви")
    phone = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber", "")
    reviews = place.get("reviews") or []
    analysis = analyze_reviews(reviews)
    return {
        "name": name,
        "niche": niche,
        "phone": phone,
        "rating": place.get("rating", "—"),
        "review_count": place.get("userRatingCount") or 0,
        "sentiment": analysis.get("sentiment", "невідомо"),
        "address": place.get("formattedAddress", ""),
        "country": country,
        "website": place.get("websiteUri", ""),
        "city": city,
    }


async def _do_search(update, context, count: int) -> int:
    country = context.user_data.get("country", "")
    niche   = context.user_data.get("niche", "")
    city    = context.user_data.get("city", "")
    msg     = update.message

    await msg.reply_text(
        f"🔍 Шукаю *{niche}* у *{city}, {country}* — {count} результатів...\n"
        "Аналізую телефони та відгуки — зачекайте ⏳",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    if not GOOGLE_API_KEY:
        await msg.reply_text("⚠️ GOOGLE\\_API\\_KEY не налаштовано.", parse_mode="Markdown")
        return ConversationHandler.END

    places, api_error = search_places(f"{niche} in {city}, {country}", count)

    if not places:
        err = f"\n⚠️ `{api_error}`" if api_error else ""
        await msg.reply_text(
            f"😔 Нічого не знайдено.{err}\n\nСпробуй /find\\_leads знову.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await msg.reply_text(f"✅ Знайдено {len(places)} місць. Збираю деталі...")

    # Зберігаємо ліди для кнопки "Як підійти"
    last_leads = []
    for idx, place in enumerate(places, 1):
        lead_data = _extract_lead_data(place, niche, country, city)
        ig = extract_instagram(lead_data["website"], lead_data["name"], city)
        lead_data["instagram"] = ig
        last_leads.append(lead_data)
        card = format_lead(place, idx, country)

        # Реальні фото бізнесу з Google Maps (якщо є)
        photo_urls = get_photo_urls(place)
        if photo_urls:
            try:
                media = [InputMediaPhoto(u) for u in photo_urls]
                await msg.reply_media_group(media)
            except Exception as e:
                logger.warning("Не вдалося надіслати фото для %s: %s", lead_data["name"], e)

        # Кнопки під кожним лідом: AI-підхід + Instagram
        has_ai = bool(OPENAI_API_KEY)
        rows = []
        if has_ai:
            rows.append([InlineKeyboardButton(
                "🎯 Як підійти до цього бізнесу",
                callback_data=f"approach_{idx - 1}"
            )])
        if ig["verified"]:
            rows.append([
                InlineKeyboardButton("✉️ Текст для Instagram", callback_data=f"ig_{idx - 1}"),
                InlineKeyboardButton("📸 Відкрити профіль", url=ig["url"]),
            ])
        else:
            rows.append([InlineKeyboardButton("🔍 Знайти Instagram бізнесу", url=ig["url"])])
        keyboard = InlineKeyboardMarkup(rows)
        try:
            await msg.reply_text(
                card, parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
        except Exception:
            await msg.reply_text(card, disable_web_page_preview=True, reply_markup=keyboard)

    context.user_data["last_leads"] = last_leads

    ai_tip = "\n🎯 Натисни *«Як підійти»* під будь-яким лідом — AI дасть скрипт дзвінка і WA повідомлення!" if OPENAI_API_KEY else ""
    await msg.reply_text(
        f"🏁 Готово! Проаналізовано *{len(places)}* лідів.{ai_tip}\n\n"
        "📝 /add\\_note — записати результат дзвінку\n"
        "🔄 /find\\_leads — новий пошук",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─── /add_note conversation ───────────────────────────────────────────────────

STATUS_LABELS = {
    "called":         "📞 Зателефонував",
    "interested":     "🟢 Зацікавлений",
    "not_interested": "🔴 Не зацікавлений",
    "callback":       "🔁 Передзвонить",
    "no_answer":      "📵 Не відповів",
}


async def add_note_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📝 Запис дзвінку.\n\nВведи *назву бізнесу*:",
        parse_mode="Markdown",
    )
    return NOTE_NAME


async def note_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["note_name"] = update.message.text.strip()
    await update.message.reply_text("📞 Введи *телефон* (або `-` якщо немає):", parse_mode="Markdown")
    return NOTE_PHONE


async def note_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["note_phone"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"ns_{key}")]
        for key, label in STATUS_LABELS.items()
    ]
    await update.message.reply_text(
        "📊 Обери *статус* дзвінку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return NOTE_STATUS


async def note_status_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_key = query.data.replace("ns_", "")
    context.user_data["note_status"] = status_key
    label = STATUS_LABELS.get(status_key, status_key)
    await query.edit_message_text(f"Статус: {label}\n\n✏️ Додай *коментар* (або `-` без коментаря):",
                                  parse_mode="Markdown")
    return NOTE_COMMENT


async def note_get_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    comment = update.message.text.strip()
    if comment == "-":
        comment = ""
    uid = update.effective_user.id
    save_note(
        uid,
        context.user_data.get("note_name", ""),
        context.user_data.get("note_phone", ""),
        context.user_data.get("note_status", ""),
        comment,
    )
    status_label = STATUS_LABELS.get(context.user_data.get("note_status", ""), "")
    await update.message.reply_text(
        f"✅ Записано!\n\n"
        f"🏢 {context.user_data.get('note_name')}\n"
        f"📞 {context.user_data.get('note_phone')}\n"
        f"📊 {status_label}\n"
        f"💬 {comment or '—'}\n\n"
        "📋 /notes — переглянути всі нотатки",
    )
    context.user_data.pop("note_name", None)
    context.user_data.pop("note_phone", None)
    context.user_data.pop("note_status", None)
    return ConversationHandler.END


# ─── /notes — list ────────────────────────────────────────────────────────────

async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    notes = get_notes(uid)
    if not notes:
        await update.message.reply_text(
            "📭 Нотаток ще немає.\n\n📝 /add\\_note — додати перший запис.",
            parse_mode="Markdown",
        )
        return

    lines = [f"📋 *Твої нотатки* ({len(notes)}):\n"]
    for n in notes:
        status_label = STATUS_LABELS.get(n["status"], n["status"])
        lines.append(
            f"*#{n['id']}* | {n['created_at']}\n"
            f"🏢 {n['biz_name']}\n"
            f"📞 {n['phone'] or '—'} | {status_label}\n"
            f"💬 {n['comment'] or '—'}\n"
        )

    full_text = "\n".join(lines)
    # Telegram limit ~4096 chars — split if needed
    for i in range(0, len(full_text), 4000):
        await update.message.reply_text(full_text[i:i+4000], parse_mode="Markdown")

    await update.message.reply_text(
        "📤 /export — завантажити як CSV\n"
        "🗑 /delete\\_note \\<id\\> — видалити запис",
        parse_mode="Markdown",
    )


# ─── /export — CSV ────────────────────────────────────────────────────────────

async def export_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    notes = get_notes(uid)
    if not notes:
        await update.message.reply_text("📭 Нотаток немає — нічого експортувати.")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["#", "Дата", "Бізнес", "Телефон", "Статус", "Коментар"])
    for n in notes:
        writer.writerow([
            n["id"], n["created_at"], n["biz_name"],
            n["phone"], STATUS_LABELS.get(n["status"], n["status"]), n["comment"],
        ])

    file_bytes = buf.getvalue().encode("utf-8-sig")  # BOM for Excel
    filename = f"leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await update.message.reply_document(
        document=io.BytesIO(file_bytes),
        filename=filename,
        caption=f"📊 Експорт нотаток — {len(notes)} записів",
    )


# ─── /delete_note ─────────────────────────────────────────────────────────────

async def delete_note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Використання: /delete\\_note \\<id\\>", parse_mode="Markdown")
        return
    note_id = int(args[0])
    delete_note(note_id, uid)
    await update.message.reply_text(f"🗑 Нотатку #{note_id} видалено.")


# ─── AI: підхід до бізнесу ────────────────────────────────────────────────────

def generate_approach_package(
    name: str, niche: str, phone: str,
    rating: float | str, review_count: int,
    sentiment: str, address: str, country: str,
    website: str,
) -> dict:
    """Генерує повний пакет підходу до конкретного бізнесу через AI."""
    client = get_openai_client()
    if not client:
        return {}

    biz_context = (
        f"Назва: {name}\n"
        f"Ніша: {niche}\n"
        f"Адреса: {address}, {country}\n"
        f"Рейтинг: {rating} ({review_count} відгуків)\n"
        f"Настрій відгуків: {sentiment}\n"
        f"Телефон: {phone}\n"
        f"Сайт: {website or 'відсутній'}"
    )

    system_prompt = """Ти — досвідчений B2B sales менеджер. 
Твоє завдання — дати конкретний і практичний план підходу до бізнесу для продажу цифрових послуг (наприклад: сайт, реклама, CRM, SEO, соцмережі, автоматизація).
Аналізуй дані бізнесу і давай персоналізовані рекомендації.

Відповідай СТРОГО у форматі (3 блоки, без зайвого тексту):

📞 СКРИПТ ДЗВІНКА:
[2-4 речення. Привітання + конкретна проблема яку ти вирішуєш для САМЕ ЦЬОГО бізнесу + м'яке запитання. Природньо, не продажно.]

💬 ПОВІДОМЛЕННЯ WhatsApp:
[Короткий персональний текст 3-5 речень. Дружній тон. Конкретна цінність для цього бізнесу. Закінчити м'яким CTA.]

💡 СТРАТЕГІЯ ПІДХОДУ:
[3 пункти з конкретними порадами: що запропонувати, на що звернути увагу, найкращий час/спосіб контакту — на основі рейтингу, відгуків і ніші.]"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=600,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Дані бізнесу:\n{biz_context}\n\nСтвори план підходу до цього бізнесу українською мовою."},
            ],
        )
        return {"text": response.choices[0].message.content.strip()}
    except Exception as e:
        logger.error("OpenAI approach error: %s", e)
        return {}


async def approach_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє натискання кнопки 🎯 Як підійти."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    if len(parts) < 2:
        return
    lead_idx = int(parts[-1])

    leads = context.user_data.get("last_leads", [])
    if lead_idx >= len(leads):
        await query.message.reply_text("⚠️ Дані ліда не знайдено. Зроби новий пошук.")
        return

    lead = leads[lead_idx]
    name = lead.get("name", "")

    await query.message.reply_text(
        f"🤖 Аналізую *{name}*...\nГенерую стратегію підходу — зачекай кілька секунд ⏳",
        parse_mode="Markdown",
    )

    result = generate_approach_package(
        name=name,
        niche=lead.get("niche", ""),
        phone=lead.get("phone", ""),
        rating=lead.get("rating", "—"),
        review_count=lead.get("review_count", 0),
        sentiment=lead.get("sentiment", "невідомо"),
        address=lead.get("address", ""),
        country=lead.get("country", ""),
        website=lead.get("website", ""),
    )

    if not result:
        await query.message.reply_text(
            "❌ Не вдалося згенерувати план. Перевір OpenAI API ключ і баланс."
        )
        return

    approach_text = result["text"]
    phone_digits = re.sub(r"\D", "", lead.get("phone", ""))

    wa_block = ""
    if phone_digits and len(phone_digits) >= 7:
        wa_msg_start = approach_text.find("💬 ПОВІДОМЛЕННЯ WhatsApp:")
        wa_msg_end = approach_text.find("💡 СТРАТЕГІЯ")
        if wa_msg_start != -1 and wa_msg_end != -1:
            wa_text = approach_text[wa_msg_start + len("💬 ПОВІДОМЛЕННЯ WhatsApp:"):wa_msg_end].strip()
        else:
            wa_text = f"Привіт! Мене звати [Ім'я], бачив ваш бізнес {name}. Хочу обговорити співпрацю."
        wa_link = build_wa_link(phone_digits, wa_text)
        wa_block = f"\n\n📲 [Відкрити WhatsApp → {name}]({wa_link})"

    await query.message.reply_text(
        f"🎯 *План підходу до {name}*\n\n{approach_text}{wa_block}",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )

    keyboard = [[
        InlineKeyboardButton("📝 Записати нотатку", callback_data=f"quicknote_{lead_idx}"),
    ]]
    await query.message.reply_text(
        "Після контакту запиши результат:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def generate_instagram_message(name: str, niche: str, city: str, sentiment: str) -> str:
    """Генерує короткий DM-текст для Instagram (копіюється вручну — офіційного API для префілу DM немає)."""
    client = get_openai_client()
    if not client:
        return (
            f"Привіт! 👋 Побачив ваш профіль {name} тут, в {city}. "
            "Дуже подобається що ви робите! Хотів запропонувати співпрацю щодо просування — є хвилинка обговорити?"
        )
    prompt = (
        f"Бізнес: {name}\nНіша: {niche}\nМісто: {city}\nНастрій відгуків: {sentiment}\n\n"
        "Напиши коротке (3-4 речення) дружнє повідомлення в Instagram Direct для цього бізнесу "
        "українською мовою. Мета — запропонувати послуги з просування/цифрового маркетингу. "
        "Тон неформальний, як в Instagram, без канцеляриту. Без привітання типу 'Доброго дня' — простіше."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("OpenAI instagram message error: %s", e)
        return f"Привіт! 👋 Побачив ваш профіль {name}. Хотів запропонувати співпрацю — є хвилинка обговорити?"


async def instagram_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерує текст для Instagram DM (скопіювати вручну — Instagram не підтримує префіл повідомлень через лінк)."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 2:
        return
    lead_idx = int(parts[-1])

    leads = context.user_data.get("last_leads", [])
    if lead_idx >= len(leads):
        await query.message.reply_text("⚠️ Дані ліда не знайдено. Зроби новий пошук.")
        return

    lead = leads[lead_idx]
    name = lead.get("name", "")
    ig = lead.get("instagram", {})

    await query.message.reply_text(f"🤖 Генерую повідомлення для *{name}*...", parse_mode="Markdown")

    text = generate_instagram_message(
        name=name,
        niche=lead.get("niche", ""),
        city=lead.get("city", ""),
        sentiment=lead.get("sentiment", "невідомо"),
    )

    keyboard = None
    if ig.get("url"):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📸 Відкрити Instagram і вставити", url=ig["url"])
        ]])

    await query.message.reply_text(
        "✉️ *Готовий текст* (натисни і утримуй щоб скопіювати):\n\n"
        f"```\n{text}\n```\n\n"
        "⚠️ Instagram не дозволяє автоматично вставляти текст у чат через посилання "
        "(на відміну від WhatsApp) — потрібно скопіювати текст і вставити вручну після відкриття профілю.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def quicknote_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Швидкий запуск /add_note з даними ліда."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    lead_idx = int(parts[-1])
    leads = context.user_data.get("last_leads", [])
    if lead_idx < len(leads):
        lead = leads[lead_idx]
        context.user_data["note_name"] = lead.get("name", "")
        context.user_data["note_phone"] = lead.get("phone", "")
    await query.message.reply_text(
        "📝 Записую нотатку. Використай /add\\_note — назва і телефон вже збережені.",
        parse_mode="Markdown",
    )


# ─── WhatsApp outreach helpers ────────────────────────────────────────────────

def clean_phone_for_wa(phone: str) -> str:
    """Strip everything except digits."""
    return re.sub(r"\D", "", phone)


def build_wa_link(phone_digits: str, message: str) -> str:
    return f"https://wa.me/{phone_digits}?text={quote(message)}"


def generate_outreach_message(biz_name: str, niche: str, language: str) -> str:
    client = get_openai_client()
    if not client:
        return ""

    lang_instructions = {
        "uk": "Пиши українською мовою.",
        "en": "Write in English.",
        "auto": f"Write in the local language of a business called '{biz_name}' in the {niche} niche. Detect the country from the business name and respond in the appropriate language.",
    }
    lang_instr = lang_instructions.get(language, lang_instructions["auto"])

    system_prompt = (
        "You are a professional outreach specialist. "
        "Write a short, friendly, and personalized WhatsApp message for cold outreach to a business owner. "
        "The message should: introduce briefly, mention a specific value proposition related to their niche, "
        "be conversational (not salesy), end with a soft call to action. "
        "Keep it under 150 words. No emojis overload — max 2. "
        f"{lang_instr}"
    )
    user_prompt = (
        f"Business name: {biz_name}\n"
        f"Business niche: {niche}\n"
        "Write a personalized cold outreach WhatsApp message to this business owner."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=300,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("OpenAI error: %s", e)
        return ""


# ─── /outreach conversation ───────────────────────────────────────────────────

async def outreach_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not OPENAI_API_KEY:
        await update.message.reply_text(
            "⚠️ OpenAI API ключ не налаштовано.\n"
            "Додай *OPENAI\\_API\\_KEY* у секрети Replit.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "💬 *WhatsApp Outreach — генерація повідомлення*\n\n"
        "Введи *назву бізнесу* якому хочеш написати:",
        parse_mode="Markdown",
    )
    return OUTREACH_NAME


async def outreach_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["outreach_name"] = update.message.text.strip()
    await update.message.reply_text(
        "📞 Введи *номер телефону* бізнесу (міжнародний формат, напр. +905321234567):",
        parse_mode="Markdown",
    )
    return OUTREACH_PHONE


async def outreach_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone_raw = update.message.text.strip()
    phone_digits = clean_phone_for_wa(phone_raw)
    if len(phone_digits) < 7:
        await update.message.reply_text("❌ Невалідний номер. Введи ще раз (напр. +905321234567):")
        return OUTREACH_PHONE
    context.user_data["outreach_phone"] = phone_digits
    await update.message.reply_text(
        "🏷 В якій *ніші* працює цей бізнес?\n_(напр. restaurant, hotel, beauty salon, gym)_",
        parse_mode="Markdown",
    )
    return OUTREACH_NICHE


async def outreach_get_niche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["outreach_niche"] = update.message.text.strip()
    keyboard = [
        [
            InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        ],
        [InlineKeyboardButton("🌍 Мова країни (авто)", callback_data="lang_auto")],
    ]
    await update.message.reply_text(
        "🌐 Якою мовою писати повідомлення?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return OUTREACH_LANG


async def outreach_lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    language = query.data.replace("lang_", "")
    context.user_data["outreach_lang"] = language

    biz_name = context.user_data.get("outreach_name", "")
    niche = context.user_data.get("outreach_niche", "")
    phone_digits = context.user_data.get("outreach_phone", "")

    lang_labels = {"uk": "🇺🇦 Українська", "en": "🇬🇧 English", "auto": "🌍 Мова країни"}
    await query.edit_message_text(
        f"⏳ Генерую персональне повідомлення для *{biz_name}* ({lang_labels.get(language, language)})...\n"
        "Це займе декілька секунд...",
        parse_mode="Markdown",
    )

    message_text = generate_outreach_message(biz_name, niche, language)

    if not message_text:
        await query.message.reply_text(
            "❌ Не вдалося згенерувати повідомлення. Перевір OpenAI API ключ і спробуй ще раз.",
        )
        return ConversationHandler.END

    wa_link = build_wa_link(phone_digits, message_text)

    await query.message.reply_text(
        f"✅ *Повідомлення готове!*\n\n"
        f"📋 *Текст для відправки:*\n"
        f"```\n{message_text}\n```",
        parse_mode="Markdown",
    )

    await query.message.reply_text(
        f"👇 *Натисни посилання — WhatsApp відкриється з готовим текстом:*\n\n"
        f"[📲 Відкрити WhatsApp чат з {biz_name}]({wa_link})\n\n"
        f"_(тобі залишиться лише натиснути «Надіслати»)_\n\n"
        "🔄 Хочеш написати іншому бізнесу? /outreach\n"
        "✏️ Хочеш відредагувати текст? Просто скопіюй і зміни вручну.",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


# ─── /cancel ─────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Скасовано.")
    context.user_data.clear()
    return ConversationHandler.END


# ─── Fallback для довільного тексту ──────────────────────────────────────────

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    preview = text[:40] + ("…" if len(text) > 40 else "")

    keyboard = ReplyKeyboardMarkup(
        [
            ["/find_leads", "/outreach"],
            ["/add_note", "/notes"],
            ["/export", "/help"],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        f"🤖 Не розумію: «{preview}»\n\n"
        "Я працюю через команди — натисни кнопку нижче щоб почати:",
        reply_markup=keyboard,
    )


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не знайдено.")

    init_db()

    app = Application.builder().token(token).build()

    # /find_leads conversation
    search_conv = ConversationHandler(
        entry_points=[CommandHandler("find_leads", find_leads)],
        states={
            COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_country)],
            NICHE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_niche)],
            CITY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_city)],
            COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, count_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # /add_note conversation
    note_conv = ConversationHandler(
        entry_points=[CommandHandler("add_note", add_note_start)],
        states={
            NOTE_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, note_get_name)],
            NOTE_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, note_get_phone)],
            NOTE_STATUS:  [CallbackQueryHandler(note_status_button, pattern="^ns_")],
            NOTE_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, note_get_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # /outreach conversation
    outreach_conv = ConversationHandler(
        entry_points=[CommandHandler("outreach", outreach_start)],
        states={
            OUTREACH_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, outreach_get_name)],
            OUTREACH_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, outreach_get_phone)],
            OUTREACH_NICHE: [MessageHandler(filters.TEXT & ~filters.COMMAND, outreach_get_niche)],
            OUTREACH_LANG:  [CallbackQueryHandler(outreach_lang_button, pattern="^lang_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("notes", list_notes))
    app.add_handler(CommandHandler("export", export_notes))
    app.add_handler(CommandHandler("delete_note", delete_note_cmd))
    app.add_handler(search_conv)
    app.add_handler(note_conv)
    app.add_handler(outreach_conv)
    # Глобальні callback handlers (поза ConversationHandler)
    app.add_handler(CallbackQueryHandler(approach_handler, pattern="^approach_"))
    app.add_handler(CallbackQueryHandler(instagram_handler, pattern="^ig_"))
    app.add_handler(CallbackQueryHandler(quicknote_handler, pattern="^quicknote_"))
    # Fallback — будь-який інший текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    logger.info("Бот запущено.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
