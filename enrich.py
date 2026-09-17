"""Збагачення ліда контактами із сайту бізнесу: email, Instagram, Facebook.

Google Places не віддає ні email, ні соцмережі — їх можна дістати лише з сайту.
Усі запити асинхронні й виконуються паралельно (з обмеженням одночасності),
тому збагачення 20 лідів займає секунди, а не хвилини.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote, urljoin, urlparse

import httpx

from config import ENRICH_CONCURRENCY, SITE_TIMEOUT
from http_client import client

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
MAILTO_RE = re.compile(r"mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", re.I)
INSTAGRAM_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})", re.I)
FACEBOOK_RE = re.compile(r"facebook\.com/([A-Za-z0-9_.\-]{2,50})", re.I)

_IGNORED_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")
_IGNORED_EMAIL_PARTS = (
    "example.com", "sentry.io", "wixpress.com", "domain.com", "email.com",
    "yourdomain", "squarespace", "godaddy", "@2x", "jquery", "schema.org",
)
_IGNORED_IG_HANDLES = {
    "p", "explore", "reel", "reels", "stories", "accounts", "about", "developer",
    "legal", "directory", "tv", "sharer", "share", "embed",
}
_IGNORED_FB_HANDLES = {
    "sharer", "share", "tr", "plugins", "dialog", "profile.php", "pages", "people",
}
CONTACT_PATHS = ("/contact", "/contacts", "/kontakt", "/contacto", "/iletisim", "/contato")


def _clean_email(candidate: str) -> str:
    email = candidate.strip().strip(".,;:").lower()
    if email.endswith(_IGNORED_EMAIL_SUFFIXES):
        return ""
    if any(part in email for part in _IGNORED_EMAIL_PARTS):
        return ""
    if len(email) > 100:
        return ""
    return email


def pick_email(html: str) -> str:
    """Спершу mailto: (найнадійніший сигнал), потім будь-який email у тексті."""
    for candidate in MAILTO_RE.findall(html):
        email = _clean_email(candidate)
        if email:
            return email
    for candidate in EMAIL_RE.findall(html):
        email = _clean_email(candidate)
        if email:
            return email
    return ""


def pick_instagram(html: str) -> str:
    for handle in INSTAGRAM_RE.findall(html):
        if handle.lower().rstrip(".") in _IGNORED_IG_HANDLES:
            continue
        return handle.rstrip(".")
    return ""


def pick_facebook(html: str) -> str:
    for handle in FACEBOOK_RE.findall(html):
        if handle.lower() in _IGNORED_FB_HANDLES:
            continue
        return handle
    return ""


def instagram_from_url(website: str) -> str:
    if website and "instagram.com" in website.lower():
        handle = website.rstrip("/").split("instagram.com/")[-1].split("?")[0].split("/")[0]
        if handle and handle.lower() not in _IGNORED_IG_HANDLES:
            return handle
    return ""


def instagram_search_url(name: str, city: str) -> str:
    """Чесний fallback: посилання на пошук, а не вигаданий акаунт."""
    query = f'site:instagram.com "{name}" {city}'.strip()
    return "https://www.google.com/search?q=" + quote(query)


async def _get_html(url: str) -> str:
    try:
        response = await client().get(url, timeout=SITE_TIMEOUT)
        content_type = response.headers.get("content-type", "")
        if response.status_code != 200 or "html" not in content_type.lower():
            return ""
        return response.text[:500_000]
    except (httpx.HTTPError, UnicodeDecodeError) as exc:
        logger.debug("site fetch failed %s: %s", url, exc)
        return ""


async def fetch_contacts(website: str, name: str = "", city: str = "") -> dict:
    """{'email','instagram','instagram_verified','instagram_url','facebook'}"""
    result = {
        "email": "",
        "instagram": instagram_from_url(website),
        "facebook": "",
    }

    if website and not website.lower().startswith(("http://", "https://")):
        website = "https://" + website

    if website and "instagram.com" not in website.lower():
        html = await _get_html(website)
        if html:
            result["email"] = pick_email(html)
            result["instagram"] = result["instagram"] or pick_instagram(html)
            result["facebook"] = pick_facebook(html)

            if not result["email"]:
                # email часто живе лише на сторінці контактів
                parsed = urlparse(website)
                base = f"{parsed.scheme}://{parsed.netloc}"
                for path in CONTACT_PATHS[:3]:
                    contact_html = await _get_html(urljoin(base, path))
                    if contact_html:
                        result["email"] = pick_email(contact_html)
                        result["instagram"] = result["instagram"] or pick_instagram(contact_html)
                        if result["email"]:
                            break

    verified = bool(result["instagram"])
    result["instagram_verified"] = verified
    result["instagram_url"] = (
        f"https://instagram.com/{result['instagram']}" if verified
        else instagram_search_url(name, city)
    )
    return result


async def enrich_many(leads: list[dict]) -> None:
    """Паралельно збагачує список лідів (мутує словники на місці)."""
    semaphore = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def worker(lead: dict) -> None:
        async with semaphore:
            try:
                contacts = await fetch_contacts(
                    lead.get("website", ""), lead.get("name", ""), lead.get("city", "")
                )
            except Exception as exc:  # збагачення не має ламати пошук
                logger.warning("enrich failed for %s: %s", lead.get("name"), exc)
                contacts = {
                    "email": "", "instagram": "", "facebook": "",
                    "instagram_verified": False,
                    "instagram_url": instagram_search_url(
                        lead.get("name", ""), lead.get("city", "")
                    ),
                }
            lead.update(contacts)

    await asyncio.gather(*(worker(lead) for lead in leads))
