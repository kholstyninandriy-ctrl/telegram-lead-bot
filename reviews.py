"""Аналіз відгуків Google + скоринг ліда."""

from __future__ import annotations

from datetime import datetime, timezone

POSITIVE_WORDS = {
    "відмінно", "чудово", "супер", "рекомендую", "якісно", "швидко", "ввічлив",
    "смачно", "приємно", "найкращ", "задоволен",
    "excellent", "great", "amazing", "fantastic", "recommend", "best", "wonderful",
    "friendly", "delicious", "perfect", "lovely", "harika", "mükemmel", "ótimo",
    "excelente", "muito bom", "sehr gut", "super",
}
NEGATIVE_WORDS = {
    "погано", "жахливо", "грубо", "повільно", "брудно", "обман", "хамств",
    "розчарув", "не рекомендую",
    "bad", "terrible", "awful", "slow", "rude", "horrible", "worst", "dirty",
    "overpriced", "disappointing", "kötü", "berbat", "péssimo", "ruim",
    "schlecht", "malo",
}
CLOSED_SIGNALS = {
    "закрито", "не працює", "закрылся", "permanently closed", "closed down",
    "out of business", "fechado", "kapali", "kapalı", "geschlossen", "cerrado",
}


def review_ts(review: dict) -> float:
    published = review.get("publishTime", "")
    if published and "T" in published:
        try:
            return datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    raw = review.get("time", 0)
    return float(raw) if isinstance(raw, (int, float)) else 0.0


def review_text(review: dict) -> str:
    text = review.get("text")
    if isinstance(text, dict):
        return text.get("text", "") or ""
    if isinstance(text, str):
        return text
    original = review.get("originalText")
    if isinstance(original, dict):
        return original.get("text", "") or ""
    return ""


def analyze_reviews(reviews: list[dict]) -> dict:
    """Повертає актуальність, настрій, контекстні пункти і вік останнього відгуку."""
    empty = {
        "actuality_emoji": "⚫", "actuality_label": "відгуків немає",
        "sentiment": "невідомо", "context_points": [], "last_review_date": "—",
        "days_since_review": None, "closed_signal": False,
    }
    if not reviews:
        return empty

    now_ts = datetime.now(timezone.utc).timestamp()
    latest_ts = max((review_ts(r) for r in reviews), default=0.0)
    days_ago = (now_ts - latest_ts) / 86400 if latest_ts else None

    if days_ago is None:
        emoji, label = "⚫", "дата відгуків невідома"
    elif days_ago < 60:
        emoji, label = "🟢", f"активний ({int(days_ago)} дн. тому)"
    elif days_ago < 180:
        emoji, label = "🟡", f"помірна активність ({int(days_ago)} дн. тому)"
    else:
        emoji, label = "🔴", f"давно без відгуків ({int(days_ago // 30)} міс. тому)"

    last_date = (datetime.fromtimestamp(latest_ts, tz=timezone.utc).strftime("%d.%m.%Y")
                 if latest_ts else "—")

    positive = negative = 0.0
    all_text = ""
    for review in reviews:
        text = review_text(review).lower()
        all_text += " " + text
        rating = review.get("rating") or 3
        if rating >= 4:
            positive += 1
        elif rating <= 2:
            negative += 1
        positive += 0.5 * sum(1 for w in POSITIVE_WORDS if w in text)
        negative += 0.5 * sum(1 for w in NEGATIVE_WORDS if w in text)

    if positive > negative * 1.5:
        sentiment = "позитивний"
    elif negative > positive * 1.5:
        sentiment = "негативний"
    else:
        sentiment = "змішаний"

    closed = any(signal in all_text for signal in CLOSED_SIGNALS)
    if closed:
        emoji, label = "🔴", "можливо закрито (за відгуками)"

    ratings = [r.get("rating") for r in reviews if r.get("rating")]
    avg = sum(ratings) / len(ratings) if ratings else None

    mood_emoji = {"позитивний": "😊", "змішаний": "😐"}.get(sentiment, "😞")
    points = [
        f"{emoji} Останній відгук: {last_date}",
        f"{mood_emoji} Настрій відгуків: {sentiment} ({len(reviews)} відгуків)",
    ]
    if avg:
        points.append(f"⭐ Середня оцінка у відгуках: {avg:.1f}")
    points.append(
        "🚫 У відгуках згадується, що заклад закрито або не працює"
        if closed else "🏪 Жодних сигналів про закриття у відгуках"
    )

    return {
        "actuality_emoji": emoji,
        "actuality_label": label,
        "sentiment": sentiment,
        "context_points": points,
        "last_review_date": last_date,
        "days_since_review": None if days_ago is None else int(days_ago),
        "closed_signal": closed,
    }


def score_lead(lead: dict) -> tuple[int, str]:
    """Оцінка привабливості ліда 0-100 + емодзі-мітка.

    Логіка «холодного продажу цифрових послуг»: бізнес цікавий, коли він живий
    (свіжі відгуки, статус OPERATIONAL), з ним є як зв'язатись (телефон/email),
    і в нього є куди рости (немає сайту, просілий рейтинг → є що продати).
    """
    score = 40

    if lead.get("phone_valid"):
        score += 15
    elif lead.get("phone"):
        score += 7
    if lead.get("email"):
        score += 8
    if lead.get("instagram_verified"):
        score += 5

    if not lead.get("website"):
        score += 12          # немає сайту — найочевидніша послуга на продаж

    days = lead.get("days_since_review")
    if days is not None:
        if days < 30:
            score += 15
        elif days < 90:
            score += 8
        elif days > 365:
            score -= 15

    try:
        rating = float(lead.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0.0
    reviews_count = lead.get("review_count") or 0
    if rating and reviews_count:
        if rating < 4.0:
            score += 8       # є проблема з репутацією → є що запропонувати
        if reviews_count < 20:
            score += 6       # мало відгуків → потрібне просування
        elif reviews_count > 300:
            score -= 5       # великий бренд, важче зайти

    if lead.get("closed_signal") or lead.get("business_status") in {
        "CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"
    }:
        score -= 45

    score = max(0, min(100, score))
    if score >= 75:
        mark = "🔥 гарячий"
    elif score >= 55:
        mark = "👍 перспективний"
    elif score >= 35:
        mark = "😐 середній"
    else:
        mark = "🧊 слабкий"
    return score, mark
