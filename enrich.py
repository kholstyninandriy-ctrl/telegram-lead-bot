"""Збагачення ліда контактами із сайту бізнесу: email, Instagram, Facebook.

Google Places не віддає ні email, ні соцмережі — їх можна дістати лише з сайту.
Реальні сайти ховають пошту багатьма способами, тож тут кілька шарів:

  1. Cloudflare email protection (data-cfemail / cdn-cgi/l/email-protection)
     — адреса зашифрована XOR-ом; це найчастіша причина «email не знайдено».
  2. mailto: — найнадійніший прямий сигнал.
  3. JSON-LD і мікророзмітка ("email": "...") — є навіть на JS-сайтах.
  4. Обфускація виду  info (at) domain (dot) com  та HTML-сутності &#64;.
  5. Звичайний текст сторінки.

Якщо на головній пусто — бот знаходить на ній посилання на «Контакти»
(будь-якою мовою, включно з німецьким Impressum, де email обов'язковий за законом)
і дивиться туди. Усі запити асинхронні й паралельні.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
from urllib.parse import quote, urljoin, urlparse

import httpx

from config import ENRICH_CONCURRENCY, SITE_TIMEOUT
from http_client import client

logger = logging.getLogger(__name__)

# Звичайний браузерний User-Agent: сайти на Cloudflare/WAF віддають 403
# на все, що виглядає як бот, — саме тому раніше багато сайтів мовчали.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,uk;q=0.8,tr;q=0.7,de;q=0.7",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
MAILTO_RE = re.compile(r"mailto:\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", re.I)
JSONLD_EMAIL_RE = re.compile(
    r'"email"\s*:\s*"(?:mailto:)?([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})"', re.I
)
CFEMAIL_RE = re.compile(r'data-cfemail="([0-9a-fA-F]{6,})"')
CF_LINK_RE = re.compile(r'/cdn-cgi/l/email-protection#([0-9a-fA-F]{6,})')
OBFUSCATED_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*(?:\(at\)|\[at\]|\{at\}|\s+at\s+|&#64;|&commat;)\s*"
    r"([a-zA-Z0-9.\-]+)\s*(?:\(dot\)|\[dot\]|\s+dot\s+|\.)\s*"
    r"([a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)",
    re.I,
)
INSTAGRAM_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})", re.I)
FACEBOOK_RE = re.compile(r"facebook\.com/([A-Za-z0-9_.\-]{2,50})", re.I)
LINK_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.{0,120}?)</a>', re.I | re.S)

CONTACT_HINT_RE = re.compile(
    r"contact|kontakt|contato|contacto|iletisim|ileti%C5%9Fim|impressum|about[-_]?us|"
    r"reach[-_]?us|get[-_]?in[-_]?touch|контакт|зв.?яз|о\s*нас",
    re.I,
)
# Порядок = пріоритет: Impressum у Німеччині за законом мусить містити email,
# тому він стоїть високо.
CONTACT_PATHS = (
    "/contact", "/contact-us", "/kontakt", "/impressum", "/contacts",
    "/iletisim", "/contacto", "/contato", "/about-us", "/about",
)
MAX_CONTACT_PAGES = 6

_IGNORED_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
                           ".css", ".js", ".woff", ".woff2")
_IGNORED_EMAIL_PARTS = (
    "example.com", "example.org", "sentry.io", "wixpress.com", "domain.com",
    "email.com", "yourdomain", "squarespace", "godaddy", "@2x", "jquery",
    "schema.org", "sentry-next", "wordpress.org", "w3.org", "core.min",
    "your@", "name@", "user@", "test@test", "noreply@", "no-reply@",
    ".png@", "bootstrapcdn", "googleapis", "gstatic", "cloudflare",
)
_PREFERRED_PREFIXES = ("info", "contact", "hello", "office", "mail", "sales",
                       "kontakt", "reception", "booking", "team", "admin")
_IGNORED_IG_HANDLES = {
    "p", "explore", "reel", "reels", "stories", "accounts", "about", "developer",
    "legal", "directory", "tv", "sharer", "share", "embed",
}
_IGNORED_FB_HANDLES = {
    "sharer", "share", "tr", "plugins", "dialog", "profile.php", "pages", "people",
}


# ─── Декодування ──────────────────────────────────────────────────────────────

def decode_cfemail(encoded: str) -> str:
    """Cloudflare шифрує email XOR-ом: перший байт — ключ."""
    try:
        data = bytes.fromhex(encoded)
    except ValueError:
        return ""
    if len(data) < 3:
        return ""
    key = data[0]
    try:
        decoded = "".join(chr(byte ^ key) for byte in data[1:])
    except ValueError:
        return ""
    return decoded if EMAIL_RE.fullmatch(decoded) else ""


def _clean_email(candidate: str) -> str:
    email = html_lib.unescape(candidate).strip().strip(".,;:'\"()<>").lower()
    if not EMAIL_RE.fullmatch(email):
        return ""
    if email.endswith(_IGNORED_EMAIL_SUFFIXES):
        return ""
    if any(part in email for part in _IGNORED_EMAIL_PARTS):
        return ""
    local, _, domain = email.partition("@")
    if len(email) > 100 or len(local) > 64 or "." not in domain:
        return ""
    # у мінімізованих js/css трапляються «емейли» з хешів — вони довгі й без крапок
    if len(local) > 30 and local.isalnum():
        return ""
    return email


def extract_emails(page_html: str) -> list[str]:
    """Усі знайдені адреси, від найнадійнішого джерела до найменш надійного."""
    candidates: list[str] = []

    for encoded in CFEMAIL_RE.findall(page_html) + CF_LINK_RE.findall(page_html):
        decoded = decode_cfemail(encoded)
        if decoded:
            candidates.append(decoded)

    candidates += MAILTO_RE.findall(page_html)
    candidates += JSONLD_EMAIL_RE.findall(page_html)

    unescaped = html_lib.unescape(page_html)
    candidates += [f"{local}@{domain}.{tld}"
                   for local, domain, tld in OBFUSCATED_RE.findall(unescaped)]
    candidates += EMAIL_RE.findall(unescaped)

    result: list[str] = []
    for candidate in candidates:
        email = _clean_email(candidate)
        if email and email not in result:
            result.append(email)
    return result


def choose_email(candidates: list[str], website: str = "") -> str:
    """Обирає найкращу адресу: спершу на домені бізнесу, далі — info@/contact@."""
    if not candidates:
        return ""
    host = urlparse(website).netloc.lower().replace("www.", "")
    root = ".".join(host.split(".")[-2:]) if host else ""

    def rank(email: str) -> tuple:
        domain = email.split("@")[1]
        local = email.split("@")[0]
        same_domain = bool(root) and root in domain
        preferred = local.startswith(_PREFERRED_PREFIXES)
        return (not same_domain, not preferred, len(email))

    return sorted(candidates, key=rank)[0]


def pick_email(page_html: str, website: str = "") -> str:
    return choose_email(extract_emails(page_html), website)


def pick_instagram(page_html: str) -> str:
    for handle in INSTAGRAM_RE.findall(page_html):
        if handle.lower().rstrip(".") in _IGNORED_IG_HANDLES:
            continue
        return handle.rstrip(".")
    return ""


def pick_facebook(page_html: str) -> str:
    for handle in FACEBOOK_RE.findall(page_html):
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


def contact_urls(page_html: str, base_url: str, limit: int = 3) -> list[str]:
    """Знаходить на сторінці посилання на «Контакти» / Impressum / About."""
    host = urlparse(base_url).netloc.lower()
    found: list[str] = []
    for href, text in LINK_RE.findall(page_html):
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        label = re.sub(r"<[^>]+>", " ", text)
        if not (CONTACT_HINT_RE.search(href) or CONTACT_HINT_RE.search(label)):
            continue
        absolute = urljoin(base_url, html_lib.unescape(href)).split("#")[0]
        if urlparse(absolute).netloc.lower() != host:
            continue
        if absolute.rstrip("/") == base_url.rstrip("/") or absolute in found:
            continue
        found.append(absolute)
        if len(found) >= limit:
            break
    return found


# ─── Мережа ───────────────────────────────────────────────────────────────────

def normalize_website(website: str) -> str:
    if not website:
        return ""
    website = website.strip()
    if not website.lower().startswith(("http://", "https://")):
        website = "https://" + website
    return website


async def fetch_html(url: str) -> str:
    try:
        response = await client().get(url, timeout=SITE_TIMEOUT, headers=BROWSER_HEADERS)
    except (httpx.HTTPError, UnicodeDecodeError) as exc:
        logger.debug("site fetch failed %s: %s", url, exc)
        return ""
    if response.status_code != 200:
        logger.debug("site %s returned %s", url, response.status_code)
        return ""
    if "html" not in response.headers.get("content-type", "").lower():
        return ""
    return response.text[:800_000]


async def fetch_contacts(website: str, name: str = "", city: str = "") -> dict:
    """{'email','instagram','instagram_verified','instagram_url','facebook','contact_page'}"""
    result = {
        "email": "",
        "instagram": instagram_from_url(website),
        "facebook": "",
        "contact_page": "",
    }
    website = normalize_website(website)

    if website and "instagram.com" not in website.lower():
        page = await fetch_html(website)
        if page:
            result["email"] = pick_email(page, website)
            result["instagram"] = result["instagram"] or pick_instagram(page)
            result["facebook"] = pick_facebook(page)

            if not result["email"]:
                parsed = urlparse(website)
                base = f"{parsed.scheme}://{parsed.netloc}"
                # спершу — реальні посилання «Контакти» зі сторінки,
                # потім типові адреси на випадок, якщо меню зібране на JS
                candidates = contact_urls(page, website)
                candidates += [urljoin(base, path) for path in CONTACT_PATHS]

                targets: list[str] = []
                for candidate in candidates:
                    if candidate not in targets:
                        targets.append(candidate)
                targets = targets[:MAX_CONTACT_PAGES]

                # сторінки тягнемо паралельно — послідовно це до хвилини на лід
                pages = await asyncio.gather(*(fetch_html(url) for url in targets))
                for target, contact_html in zip(targets, pages):
                    if not contact_html:
                        continue
                    result["instagram"] = result["instagram"] or pick_instagram(contact_html)
                    result["facebook"] = result["facebook"] or pick_facebook(contact_html)
                    email = pick_email(contact_html, website)
                    if email and not result["email"]:
                        result["email"] = email
                        result["contact_page"] = target

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
                    "email": "", "instagram": "", "facebook": "", "contact_page": "",
                    "instagram_verified": False,
                    "instagram_url": instagram_search_url(
                        lead.get("name", ""), lead.get("city", "")
                    ),
                }
            if contacts.get("email"):
                contacts["email_source"] = "site"
            lead.update(contacts)

    await asyncio.gather(*(worker(lead) for lead in leads))


# ─── Діагностика (команда /diag) ──────────────────────────────────────────────

CLOUDFLARE_MARKERS = (
    "cf-browser-verification", "cdn-cgi/challenge-platform", "__cf_chl",
    "checking your browser", "attention required! | cloudflare",
)


async def probe_site(website: str) -> dict:
    """Показує, що саме бот бачить на сайті — щоб не гадати, чому немає email."""
    report = {
        "url": normalize_website(website), "status": None, "length": 0,
        "content_type": "", "error": "", "emails": [], "cf_protected": False,
        "cf_challenge": False, "instagram": "", "facebook": "", "contact_links": [],
    }
    if not report["url"]:
        report["error"] = "порожня адреса"
        return report

    try:
        response = await client().get(report["url"], timeout=SITE_TIMEOUT,
                                      headers=BROWSER_HEADERS)
    except httpx.HTTPError as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    page = response.text or ""
    report["status"] = response.status_code
    report["length"] = len(page)
    report["content_type"] = response.headers.get("content-type", "")[:40]
    lowered = page.lower()
    report["cf_protected"] = bool(CFEMAIL_RE.search(page) or CF_LINK_RE.search(page))
    report["cf_challenge"] = any(marker in lowered for marker in CLOUDFLARE_MARKERS)
    report["emails"] = extract_emails(page)[:5]
    report["instagram"] = pick_instagram(page)
    report["facebook"] = pick_facebook(page)
    report["contact_links"] = contact_urls(page, report["url"])
    return report
