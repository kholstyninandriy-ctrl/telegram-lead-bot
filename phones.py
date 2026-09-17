"""Валідація телефонів + визначення ISO-коду країни за її назвою.

Раніше у phonenumbers.parse() передавалась назва країни ("Turkey"), а бібліотека
очікує ISO-код ("TR") — через це національні номери без "+" не парсились.
"""

from __future__ import annotations

import re

import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType

COUNTRY_TO_ISO: dict[str, str] = {
    "ukraine": "UA", "україна": "UA", "украина": "UA",
    "turkey": "TR", "türkiye": "TR", "turkiye": "TR", "туреччина": "TR",
    "portugal": "PT", "португалія": "PT",
    "germany": "DE", "deutschland": "DE", "німеччина": "DE",
    "poland": "PL", "polska": "PL", "польща": "PL",
    "uae": "AE", "united arab emirates": "AE", "оае": "AE", "dubai": "AE",
    "spain": "ES", "españa": "ES", "espana": "ES", "іспанія": "ES",
    "italy": "IT", "italia": "IT", "італія": "IT",
    "uk": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "британія": "GB", "англія": "GB",
    "usa": "US", "united states": "US", "us": "US", "сша": "US",
    "czech republic": "CZ", "czechia": "CZ", "чехія": "CZ",
    "romania": "RO", "румунія": "RO",
    "france": "FR", "франція": "FR",
    "netherlands": "NL", "holland": "NL", "нідерланди": "NL",
    "belgium": "BE", "austria": "AT", "switzerland": "CH", "sweden": "SE",
    "norway": "NO", "denmark": "DK", "finland": "FI", "ireland": "IE",
    "greece": "GR", "bulgaria": "BG", "hungary": "HU", "slovakia": "SK",
    "slovenia": "SI", "croatia": "HR", "serbia": "RS", "lithuania": "LT",
    "latvia": "LV", "estonia": "EE", "moldova": "MD", "georgia": "GE",
    "canada": "CA", "mexico": "MX", "brazil": "BR", "argentina": "AR",
    "chile": "CL", "colombia": "CO", "australia": "AU", "new zealand": "NZ",
    "japan": "JP", "china": "CN", "india": "IN", "indonesia": "ID",
    "thailand": "TH", "vietnam": "VN", "philippines": "PH", "malaysia": "MY",
    "singapore": "SG", "south korea": "KR", "korea": "KR", "israel": "IL",
    "egypt": "EG", "morocco": "MA", "tunisia": "TN", "south africa": "ZA",
    "saudi arabia": "SA", "qatar": "QA", "kuwait": "KW", "bahrain": "BH",
    "oman": "OM", "jordan": "JO", "cyprus": "CY", "malta": "MT",
    "montenegro": "ME", "albania": "AL", "north macedonia": "MK",
    "bosnia and herzegovina": "BA", "kazakhstan": "KZ", "uzbekistan": "UZ",
    "azerbaijan": "AZ", "armenia": "AM", "iceland": "IS", "luxembourg": "LU",
}

TYPE_LABELS = {
    PhoneNumberType.MOBILE: "мобільний",
    PhoneNumberType.FIXED_LINE: "стаціонарний",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "моб/стаціон",
    PhoneNumberType.TOLL_FREE: "безкоштовний",
    PhoneNumberType.VOIP: "VoIP",
    PhoneNumberType.PREMIUM_RATE: "платний",
}


def country_to_iso(country: str) -> str | None:
    """'Turkey' → 'TR', 'TR' → 'TR', невідома країна → None."""
    if not country:
        return None
    key = country.strip().lower()
    if key in COUNTRY_TO_ISO:
        return COUNTRY_TO_ISO[key]
    upper = country.strip().upper()
    if len(upper) == 2 and upper.isalpha():
        # перевіряємо, що це справді відомий регіон
        if upper in phonenumbers.SUPPORTED_REGIONS:
            return upper
    return None


def digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def validate_phone(raw: str, country_hint: str = "") -> dict:
    if not raw:
        return {"valid": False, "formatted": "—", "emoji": "❌",
                "note": "відсутній", "e164": "", "type": ""}

    region = country_to_iso(country_hint)
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return {"valid": False, "formatted": raw, "emoji": "❌",
                "note": "не вдалось розпізнати номер", "e164": "", "type": ""}

    type_label = TYPE_LABELS.get(phonenumbers.number_type(parsed), "невідомий тип")
    fmt = phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL)
    iso = phonenumbers.region_code_for_number(parsed) or (region or "")

    if phonenumbers.is_valid_number(parsed):
        return {
            "valid": True,
            "formatted": fmt,
            "e164": phonenumbers.format_number(parsed, PhoneNumberFormat.E164),
            "region": iso,
            "type": type_label,
            "emoji": "✅",
            "note": f"{type_label} · {iso}",
        }
    if phonenumbers.is_possible_number(parsed):
        return {"valid": False, "formatted": fmt, "emoji": "⚠️", "e164": "",
                "region": iso, "type": type_label,
                "note": "можливий, але не підтверджений"}
    return {"valid": False, "formatted": raw, "emoji": "❌", "e164": "",
            "type": type_label, "note": "невалідний формат"}
