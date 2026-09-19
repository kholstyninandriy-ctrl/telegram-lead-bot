"""Конфігурація бота: змінні оточення, константи, логування."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Видно в /start і в логах — щоб одразу бачити, яка версія реально запущена.
BOT_VERSION = "2.2"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# ─── Ключі ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = _env("GOOGLE_API_KEY") or _env("GOOGLE_MAPS_API_KEY")
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")

# ─── Файли ────────────────────────────────────────────────────────────────────
DB_PATH = _env("DB_PATH") or str(BASE_DIR / "notes.db")

# ─── Доступ ───────────────────────────────────────────────────────────────────
# Бот витрачає твої платні API-ключі, тому за замовчуванням варто обмежити коло
# користувачів: ALLOWED_USER_IDS="123456789,987654321".
# Порожнє значення = доступ відкритий для всіх (як було раніше).
ALLOWED_USER_IDS = frozenset(
    int(part)
    for part in re.split(r"[,\s;]+", _env("ALLOWED_USER_IDS"))
    if part.isdigit()
)

# ─── Ліміти та таймаути ───────────────────────────────────────────────────────
MAX_RESULTS = max(1, min(60, _env_int("MAX_RESULTS", 60)))   # стеля для /find_leads
PAGE_SIZE = 20                                               # ліміт Google на сторінку
HTTP_TIMEOUT = _env_int("HTTP_TIMEOUT", 15)                  # Google Places
SITE_TIMEOUT = _env_int("SITE_TIMEOUT", 10)                   # сайти бізнесів
ENRICH_CONCURRENCY = max(1, _env_int("ENRICH_CONCURRENCY", 6))
SEARCH_CACHE_TTL_MIN = _env_int("SEARCH_CACHE_TTL_MIN", 180)  # 0 = кеш вимкнено
try:
    SEND_DELAY = max(0.0, float(_env("SEND_DELAY", "0.35")))  # пауза між картками
except ValueError:
    SEND_DELAY = 0.35
AI_TIMEOUT = _env_int("AI_TIMEOUT", 60)

# ─── Apify (платне збагачення контактів) ─────────────────────────────────────
# Власний парсер безкоштовний, але безсилий проти Cloudflare-челенджів і
# сайтів, які малюються JavaScript-ом. Apify заходить справжнім браузером
# через проксі — тому використовуємо його ДОБИРАЛЬНИКОМ: лише для тих лідів,
# у яких є сайт, але email не знайшовся. Так платимо центи, а не за кожен лід.
APIFY_TOKEN = _env("APIFY_TOKEN")
APIFY_CONTACT_ACTOR = _env("APIFY_CONTACT_ACTOR", "vdrmota~contact-info-scraper")
APIFY_TIMEOUT = _env_int("APIFY_TIMEOUT", 180)        # скільки чекати на прогін, с
APIFY_MAX_SITES = _env_int("APIFY_MAX_SITES", 30)     # стеля сайтів на один пошук
APIFY_PAGES_PER_SITE = _env_int("APIFY_PAGES_PER_SITE", 10)
APIFY_MAX_DEPTH = _env_int("APIFY_MAX_DEPTH", 1)
APIFY_MEMORY_MB = _env_int("APIFY_MEMORY_MB", 2048)


def has_apify() -> bool:
    return bool(APIFY_TOKEN)

LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()


def setup_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, LOG_LEVEL, logging.INFO),
    )
    # httpx логує кожен запит до Telegram на INFO — це засмічує логи
    logging.getLogger("httpx").setLevel(logging.WARNING)


def has_google() -> bool:
    return bool(GOOGLE_API_KEY)


def has_ai() -> bool:
    return bool(OPENAI_API_KEY)


def is_allowed(user_id: int | None) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id is not None and user_id in ALLOWED_USER_IDS
