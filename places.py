"""Клієнт Google Places API v1 — асинхронний, з пагінацією, кешем і фото."""

from __future__ import annotations

import logging

import httpx

from config import GOOGLE_API_KEY, HTTP_TIMEOUT, PAGE_SIZE
from http_client import client
import db

logger = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.rating,places.userRatingCount,places.businessStatus,"
    "places.nationalPhoneNumber,places.internationalPhoneNumber,"
    "places.websiteUri,places.googleMapsUri,places.reviews,places.photos,"
    "places.primaryTypeDisplayName,nextPageToken"
)

ERROR_HINTS = {
    "API_KEY_INVALID": "Google API ключ недійсний — перевір значення GOOGLE_API_KEY.",
    "PERMISSION_DENIED": "Places API (New) не увімкнено або ключ обмежений. "
                         "Увімкни «Places API (New)» у Google Cloud Console.",
    "BILLING": "У проєкті Google Cloud не активований білінг.",
    "RESOURCE_EXHAUSTED": "Вичерпано квоту Google Places на сьогодні.",
}


def _hint(message: str, status: int) -> str:
    upper = message.upper()
    for key, hint in ERROR_HINTS.items():
        if key in upper:
            return hint
    if status == 403:
        return ERROR_HINTS["PERMISSION_DENIED"]
    if status == 429:
        return ERROR_HINTS["RESOURCE_EXHAUSTED"]
    return message


async def _search_page(query: str, page_size: int, page_token: str = "") -> tuple[list[dict], str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body: dict = {
        "textQuery": query,
        "languageCode": "uk",
        "maxResultCount": min(page_size, PAGE_SIZE),
    }
    if page_token:
        body["pageToken"] = page_token
    try:
        response = await client().post(SEARCH_URL, json=body, headers=headers,
                                       timeout=HTTP_TIMEOUT)
    except httpx.TimeoutException:
        return [], "", "Google Places не відповів вчасно — спробуй ще раз."
    except httpx.HTTPError as exc:
        logger.error("Places request failed: %s", exc)
        return [], "", f"Помилка мережі: {exc}"

    if response.status_code != 200:
        try:
            message = response.json().get("error", {}).get("message", "")
        except ValueError:
            message = response.text[:200]
        logger.error("Places API %s: %s", response.status_code, message)
        return [], "", _hint(message or f"HTTP {response.status_code}", response.status_code)

    data = response.json()
    return data.get("places", []), data.get("nextPageToken", ""), ""


async def search_places(query: str, max_count: int) -> tuple[list[dict], str]:
    """Текстовий пошук із пагінацією (Google віддає максимум 20 місць на сторінку).

    Результат кешується в SQLite — повторний однаковий запит не витрачає квоту.
    """
    if not GOOGLE_API_KEY:
        return [], "GOOGLE_API_KEY не налаштовано."

    cache_key = f"{query.strip().lower()}|{max_count}"
    cached = await db.acache_get(cache_key)
    if cached is not None:
        logger.info("Places cache hit: %s", cache_key)
        return cached, ""

    collected: list[dict] = []
    seen: set[str] = set()
    token = ""
    error = ""

    while len(collected) < max_count:
        page, token, error = await _search_page(query, max_count - len(collected), token)
        if error:
            break
        for place in page:
            place_id = place.get("id") or place.get("formattedAddress", "")
            if place_id in seen:
                continue
            seen.add(place_id)
            collected.append(place)
        if not token or not page:
            break

    collected = collected[:max_count]
    if collected and not error:
        await db.acache_put(cache_key, collected)
    return collected, error if not collected else ""


def photo_names(place: dict, limit: int = 3) -> list[str]:
    return [p["name"] for p in (place.get("photos") or [])[:limit] if p.get("name")]


async def photo_bytes(photo_name: str, max_width: int = 800) -> bytes | None:
    """Завантажує фото самостійно і повертає байти.

    Раніше в Telegram віддавався URL із API-ключем усередині — ключ потрапляв
    на сторонні сервери. Тепер ключ не залишає бота.
    """
    if not photo_name or not GOOGLE_API_KEY:
        return None
    url = f"https://places.googleapis.com/v1/{photo_name}/media"
    try:
        response = await client().get(
            url,
            params={"maxWidthPx": max_width, "key": GOOGLE_API_KEY},
            timeout=HTTP_TIMEOUT,
        )
        if response.status_code == 200 and response.content:
            return response.content
        logger.warning("Photo download failed %s: %s", photo_name, response.status_code)
    except httpx.HTTPError as exc:
        logger.warning("Photo download error %s: %s", photo_name, exc)
    return None
