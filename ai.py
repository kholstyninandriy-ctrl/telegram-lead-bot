"""AI-генерація: план підходу, WhatsApp, Instagram DM, холодний лист.

Модель відповідає у JSON (response_format=json_object), тому текст більше не
доводиться вирізати з відповіді за емодзі-заголовками — раніше саме через це
у WhatsApp-посилання інколи потрапляв шматок «СТРАТЕГІЯ ПІДХОДУ».
"""

from __future__ import annotations

import json
import logging
from urllib.parse import quote

from openai import APIError, AsyncOpenAI, RateLimitError

from config import AI_TIMEOUT, OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI | None:
    global _client
    if not OPENAI_API_KEY:
        return None
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=AI_TIMEOUT, max_retries=2)
    return _client


class AIError(RuntimeError):
    """Помилка генерації з текстом, який можна показати користувачу."""


async def _complete_json(system: str, user: str, max_tokens: int = 700) -> dict:
    api = client()
    if api is None:
        raise AIError("OPENAI_API_KEY не налаштовано — AI-функції вимкнені.")
    try:
        response = await api.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=max_tokens,
            temperature=0.7,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except RateLimitError:
        raise AIError("Ліміт OpenAI вичерпано — перевір баланс і спробуй за хвилину.")
    except APIError as exc:
        logger.error("OpenAI API error: %s", exc)
        raise AIError("OpenAI не відповів. Спробуй ще раз за хвилину.")
    except Exception as exc:  # мережа, таймаут тощо
        logger.error("OpenAI call failed: %s", exc)
        raise AIError("Не вдалося звернутись до OpenAI. Спробуй ще раз.")

    content = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.error("OpenAI returned non-JSON: %s", content[:200])
        raise AIError("AI повернув відповідь у несподіваному форматі. Спробуй ще раз.")
    if not isinstance(data, dict):
        raise AIError("AI повернув відповідь у несподіваному форматі. Спробуй ще раз.")
    return data


def _business_context(lead: dict) -> str:
    return "\n".join([
        f"Назва: {lead.get('name', '')}",
        f"Ніша: {lead.get('niche', '')}",
        f"Місто/країна: {lead.get('city', '')}, {lead.get('country', '')}",
        f"Адреса: {lead.get('address', '')}",
        f"Рейтинг: {lead.get('rating', '—')} ({lead.get('review_count', 0)} відгуків)",
        f"Настрій відгуків: {lead.get('sentiment', 'невідомо')}",
        f"Останній відгук: {lead.get('last_review_date', '—')}",
        f"Телефон: {lead.get('phone_formatted') or 'відсутній'}",
        f"Сайт: {lead.get('website') or 'ВІДСУТНІЙ'}",
        f"Instagram: {'@' + lead['instagram'] if lead.get('instagram_verified') else 'не знайдено'}",
        f"Email: {lead.get('email') or 'не знайдено'}",
        f"Оцінка ліда: {lead.get('score', 0)}/100 ({lead.get('score_mark', '')})",
    ])


APPROACH_SYSTEM = """Ти — досвідчений B2B sales-менеджер, який продає бізнесам цифрові послуги
(сайти, реклама, SMM, CRM, автоматизація, SEO). Аналізуй конкретні дані бізнесу
і давай персоналізований, практичний план — без води і без шаблонних фраз.

Поверни СТРОГО JSON такої структури:
{
  "hook": "одне речення — головна зачіпка саме для цього бізнесу",
  "call_script": "скрипт дзвінка: 2-4 речення, природньо, не продажно",
  "whatsapp": "повідомлення в WhatsApp: 3-5 речень, дружній тон, м'який CTA",
  "strategy": ["порада 1", "порада 2", "порада 3"],
  "objection": "найімовірніше заперечення + коротка відповідь на нього"
}
Усі тексти — українською мовою, якщо не вказано інше."""


async def approach_package(lead: dict) -> dict:
    return await _complete_json(
        APPROACH_SYSTEM,
        f"Дані бізнесу:\n{_business_context(lead)}\n\n"
        "Створи план підходу до цього бізнесу.",
        max_tokens=900,
    )


LANG_INSTRUCTIONS = {
    "uk": "Пиши українською мовою.",
    "en": "Write in English.",
    "auto": "Пиши мовою країни бізнесу (визнач її за країною/містом у даних). "
            "Якщо не впевнений — пиши англійською.",
}


async def whatsapp_message(lead: dict, language: str = "auto") -> str:
    instruction = LANG_INSTRUCTIONS.get(language, LANG_INSTRUCTIONS["auto"])
    data = await _complete_json(
        "Ти — спеціаліст з холодного аутріча. Напиши коротке персональне повідомлення "
        "в WhatsApp власнику бізнесу: коротке представлення, конкретна користь для його ніші, "
        "розмовний тон (не продажний), м'який заклик до дії. До 120 слів, максимум 2 емодзі. "
        f"{instruction}\n"
        'Поверни СТРОГО JSON: {"message": "текст повідомлення"}',
        f"Дані бізнесу:\n{_business_context(lead)}",
        max_tokens=400,
    )
    message = str(data.get("message", "")).strip()
    if not message:
        raise AIError("AI повернув порожнє повідомлення. Спробуй ще раз.")
    return message


async def instagram_dm(lead: dict) -> str:
    data = await _complete_json(
        "Ти пишеш дружнє повідомлення в Instagram Direct бізнесу від імені digital-спеціаліста. "
        "3-4 речення, неформальний тон як в Instagram, без канцеляриту і без 'Доброго дня'. "
        "Мета — запропонувати послуги з просування. Українською мовою.\n"
        'Поверни СТРОГО JSON: {"message": "текст"}',
        f"Дані бізнесу:\n{_business_context(lead)}",
        max_tokens=350,
    )
    message = str(data.get("message", "")).strip()
    if not message:
        raise AIError("AI повернув порожнє повідомлення. Спробуй ще раз.")
    return message


async def cold_email(lead: dict, language: str = "auto") -> dict:
    instruction = LANG_INSTRUCTIONS.get(language, LANG_INSTRUCTIONS["auto"])
    data = await _complete_json(
        "Ти пишеш холодний лист власнику бізнесу з пропозицією цифрових послуг. "
        "Тема — до 60 символів, конкретна, без клікбейту. Тіло — 4-6 речень: "
        "персональна зачіпка, користь, соціальний доказ одним рядком, м'який CTA. "
        f"Без води і без 'сподіваюсь, у вас все добре'. {instruction}\n"
        'Поверни СТРОГО JSON: {"subject": "тема", "body": "текст листа"}',
        f"Дані бізнесу:\n{_business_context(lead)}",
        max_tokens=600,
    )
    subject = str(data.get("subject", "")).strip()
    body = str(data.get("body", "")).strip()
    if not body:
        raise AIError("AI повернув порожній лист. Спробуй ще раз.")
    return {"subject": subject or "Пропозиція співпраці", "body": body}


# ─── Посилання ────────────────────────────────────────────────────────────────

def wa_link(phone_digits: str, message: str) -> str:
    return f"https://wa.me/{phone_digits}?text={quote(message)}"


def mailto_link(email: str, subject: str, body: str) -> str:
    return f"mailto:{email}?subject={quote(subject)}&body={quote(body)}"
