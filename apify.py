"""Apify як «важка артилерія» для пошуку контактів.

Власний парсер (enrich.py) безкоштовний, але його зупиняють:
  • Cloudflare-челендж (JS-перевірка браузера, а не просто заголовки),
  • сайти, де контакти малюються JavaScript-ом уже після завантаження,
  • блокування за IP дата-центру.

Apify-актор заходить справжнім браузером через проксі й обходить внутрішні
сторінки сайту, тому бере пошту там, де httpx безсилий. Щоб не палити гроші,
він викликається ДОБИРАЛЬНИКОМ — лише для лідів, у яких сайт є, а email не
знайшовся, і одним прогоном на весь пошук (актор приймає список URL).

Потрібен лише APIFY_TOKEN. Актор налаштовується через APIFY_CONTACT_ACTOR.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx

import config
from http_client import client

logger = logging.getLogger(__name__)

API_BASE = "https://api.apify.com/v2"
POLL_INTERVAL = 3.0
FINISHED_STATES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT", "TIMING-OUT"}

# Актори називають поля по-різному, тому читаємо всі відомі варіанти.
EMAIL_KEYS = ("emails", "email", "emailList", "contactEmails")
INSTAGRAM_KEYS = ("instagrams", "instagram", "instagramUrls", "instagramProfiles")
FACEBOOK_KEYS = ("facebooks", "facebook", "facebookUrls")
PHONE_KEYS = ("phones", "phone", "phoneNumbers")
URL_KEYS = ("url", "originalUrl", "pageUrl", "startUrl", "domain", "website", "loadedUrl")


class ApifyError(RuntimeError):
    """Помилка виклику Apify, придатна для показу користувачу."""


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.APIFY_TOKEN}",
            "Content-Type": "application/json"}


def domain_of(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _values(item: dict, keys: tuple[str, ...]) -> list[str]:
    """Дістає список рядків із поля, яке може бути рядком, списком або None."""
    for key in keys:
        if key not in item:
            continue
        value = item[key]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, (list, tuple)):
            found = [str(v).strip() for v in value if isinstance(v, (str, int)) and str(v).strip()]
            if found:
                return found
    return []


# ─── Низькорівневі виклики API ────────────────────────────────────────────────

async def start_run(actor: str, payload: dict) -> str:
    """Запускає актора і повертає runId."""
    url = f"{API_BASE}/acts/{actor}/runs"
    params = {"timeout": config.APIFY_TIMEOUT, "memory": config.APIFY_MEMORY_MB}
    try:
        response = await client().post(url, json=payload, params=params,
                                       headers=_headers(), timeout=30)
    except httpx.HTTPError as exc:
        raise ApifyError(f"Не вдалося звернутись до Apify: {exc}")

    if response.status_code == 401:
        raise ApifyError("APIFY_TOKEN недійсний.")
    if response.status_code == 404:
        raise ApifyError(f"Актор {actor} не знайдено — перевір APIFY_CONTACT_ACTOR.")
    if response.status_code >= 400:
        raise ApifyError(f"Apify відповів {response.status_code}: {response.text[:200]}")

    data = (response.json() or {}).get("data") or {}
    run_id = data.get("id")
    if not run_id:
        raise ApifyError("Apify не повернув id прогону.")
    return run_id


async def run_state(run_id: str) -> dict:
    response = await client().get(f"{API_BASE}/actor-runs/{run_id}",
                                  headers=_headers(), timeout=30)
    response.raise_for_status()
    return (response.json() or {}).get("data") or {}


async def dataset_items(dataset_id: str) -> list[dict]:
    if not dataset_id:
        return []
    response = await client().get(
        f"{API_BASE}/datasets/{dataset_id}/items",
        params={"clean": "true", "format": "json"},
        headers=_headers(), timeout=60,
    )
    response.raise_for_status()
    items = response.json()
    return items if isinstance(items, list) else []


async def abort_run(run_id: str) -> None:
    try:
        await client().post(f"{API_BASE}/actor-runs/{run_id}/abort",
                            headers=_headers(), timeout=20)
    except httpx.HTTPError:
        pass


async def run_actor(actor: str, payload: dict) -> list[dict]:
    """Запускає актора, чекає на завершення і віддає елементи датасету.

    Якщо час вичерпано — забирає те, що встигло назбиратись, і зупиняє прогін,
    щоб не витрачати кредити далі.
    """
    run_id = await start_run(actor, payload)
    deadline = asyncio.get_running_loop().time() + config.APIFY_TIMEOUT
    dataset_id = ""
    status = "READY"

    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            state = await run_state(run_id)
        except httpx.HTTPError as exc:
            logger.warning("Apify run state error: %s", exc)
            continue
        dataset_id = state.get("defaultDatasetId", dataset_id)
        status = state.get("status", status)
        if status in FINISHED_STATES:
            break

    if status not in FINISHED_STATES:
        logger.warning("Apify run %s не встиг за %s с — забираю часткові дані",
                       run_id, config.APIFY_TIMEOUT)
        await abort_run(run_id)

    try:
        items = await dataset_items(dataset_id)
    except httpx.HTTPError as exc:
        raise ApifyError(f"Не вдалося прочитати результат Apify: {exc}")

    logger.info("Apify %s: статус %s, елементів %s", actor, status, len(items))
    return items


# ─── Збагачення лідів ─────────────────────────────────────────────────────────

def _contact_payload(urls: list[str]) -> dict:
    return {
        "startUrls": [{"url": url} for url in urls],
        "maxDepth": config.APIFY_MAX_DEPTH,
        "maxRequestsPerStartUrl": config.APIFY_PAGES_PER_SITE,
        "considerChildFrames": True,
        "proxyConfig": {"useApifyProxy": True},
    }


def index_items(items: list[dict]) -> dict[str, dict]:
    """Групує результати актора за доменом (у датасеті — по сторінці на рядок)."""
    by_domain: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source = ""
        for key in URL_KEYS:
            if item.get(key):
                source = str(item[key])
                break
        domain = domain_of(source)
        if not domain:
            continue
        bucket = by_domain.setdefault(domain, {"emails": [], "instagrams": [],
                                               "facebooks": [], "phones": []})
        for field, keys in (("emails", EMAIL_KEYS), ("instagrams", INSTAGRAM_KEYS),
                            ("facebooks", FACEBOOK_KEYS), ("phones", PHONE_KEYS)):
            for value in _values(item, keys):
                if value not in bucket[field]:
                    bucket[field].append(value)
    return by_domain


def _handle_from_url(url: str, host: str) -> str:
    if host not in url.lower():
        return ""
    handle = url.rstrip("/").split(f"{host}/")[-1].split("?")[0].split("/")[0]
    return handle if handle and handle.lower() not in {"p", "explore", "reel", "sharer"} else ""


async def enrich_missing(leads: list[dict]) -> int:
    """Добирає контакти для лідів із сайтом, але без email. Повертає к-сть знахідок."""
    if not config.has_apify():
        return 0

    targets = [lead for lead in leads if lead.get("website") and not lead.get("email")]
    targets = targets[:config.APIFY_MAX_SITES]
    if not targets:
        return 0

    urls: list[str] = []
    for lead in targets:
        website = lead["website"]
        if "://" not in website:
            website = "https://" + website
        if website not in urls:
            urls.append(website)

    logger.info("Apify: добираю контакти для %s сайтів", len(urls))
    try:
        items = await run_actor(config.APIFY_CONTACT_ACTOR, _contact_payload(urls))
    except ApifyError as exc:
        logger.error("Apify enrichment failed: %s", exc)
        return 0

    by_domain = index_items(items)
    found = 0
    for lead in targets:
        bucket = by_domain.get(domain_of(lead["website"]))
        if not bucket:
            continue

        # enrich.choose_email імпортуємо тут, щоб не заводити циклічний імпорт
        from enrich import choose_email, _clean_email

        candidates = [email for email in (_clean_email(e) for e in bucket["emails"]) if email]
        if candidates and not lead.get("email"):
            lead["email"] = choose_email(candidates, lead["website"])
            lead["email_source"] = "apify"
            found += 1

        if not lead.get("instagram_verified"):
            for url in bucket["instagrams"]:
                handle = _handle_from_url(url, "instagram.com")
                if handle:
                    lead["instagram"] = handle
                    lead["instagram_verified"] = True
                    lead["instagram_url"] = f"https://instagram.com/{handle}"
                    break
        if not lead.get("facebook"):
            for url in bucket["facebooks"]:
                handle = _handle_from_url(url, "facebook.com")
                if handle:
                    lead["facebook"] = handle
                    break

    logger.info("Apify: додано email для %s лідів", found)
    return found
