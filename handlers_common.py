"""Загальні хендлери: /start, /help, /cancel, /stats, контроль доступу, помилки."""

from __future__ import annotations

import logging

from telegram import ReplyKeyboardMarkup, Update
from telegram.error import Forbidden, NetworkError, TimedOut
from telegram.ext import ApplicationHandlerStop, ContextTypes, ConversationHandler

import config
import db
import texts
from ui import STATUS_LABELS, esc, send_html

logger = logging.getLogger(__name__)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["/find_leads", "/outreach"],
        ["/add_note", "/notes"],
        ["/stats", "/help"],
    ],
    resize_keyboard=True,
)


async def access_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пропускає далі лише дозволених користувачів (якщо ALLOWED_USER_IDS задано).

    Бот витрачає платні Google/OpenAI ключі власника, тож відкритий доступ
    для будь-кого, хто знайде бота, — це прямі витрати.
    """
    user = update.effective_user
    if config.is_allowed(user.id if user else None):
        return
    logger.warning("Access denied for user_id=%s (%s)",
                   user.id if user else "?", user.username if user else "?")
    if update.callback_query:
        await update.callback_query.answer("Доступ до цього бота обмежений.", show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(
            "🔒 Доступ до цього бота обмежений.\n"
            f"Твій Telegram ID: {user.id if user else '—'}"
        )
    raise ApplicationHandlerStop


def _missing_keys_warning() -> str:
    missing = []
    if not config.has_google():
        missing.append("GOOGLE_API_KEY — пошук бізнесів не працюватиме")
    if not config.has_ai():
        missing.append("OPENAI_API_KEY — AI-тексти не працюватимуть")
    if not missing:
        return ""
    lines = "\n".join(f"  • {esc(item)}" for item in missing)
    return f"\n\n⚠️ <b>Не налаштовано:</b>\n{lines}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = esc(user.first_name if user else "друже")
    await send_html(
        update.message,
        texts.START_TEXT.format(name=name) + _missing_keys_warning(),
        reply_markup=MAIN_KEYBOARD,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_html(update.message, texts.HELP_TEXT)


def clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in list(context.user_data.keys()):
        if key.startswith(("note_", "outreach_", "search_")):
            context.user_data.pop(key, None)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    clear_flow(context)
    await update.message.reply_text("❌ Скасовано.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/start посеред діалогу: завершуємо діалог і показуємо головне меню."""
    clear_flow(context)
    await start(update, context)
    return ConversationHandler.END


# Команди, які «витягують» користувача з поточного діалогу.
# Раніше будь-яка команда всередині діалогу просто ігнорувалась, і бот виглядав
# зависшим — доводилось вручну шукати /cancel.
OTHER_COMMANDS = [
    "find_leads", "outreach", "add_note", "notes", "stats",
    "export", "export_search", "delete_note", "help",
]


async def leave_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    clear_flow(context)
    command = (update.message.text or "").split()[0]
    await update.message.reply_text(
        f"↩️ Попередню дію скасовано.\nНатисни {command} ще раз, щоб продовжити.",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


def fallbacks(own_command: str, own_handler) -> list:
    """Стандартний набір fallback-хендлерів для всіх діалогів бота."""
    from telegram.ext import CommandHandler

    others = [name for name in OTHER_COMMANDS if name != own_command]
    return [
        CommandHandler("cancel", cancel),
        CommandHandler("start", restart),
        CommandHandler(own_command, own_handler),
        CommandHandler(others, leave_conversation),
    ]


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    stats = await db.anotes_stats(update.effective_user.id)
    if not stats["total"]:
        await send_html(
            update.message,
            "📭 Нотаток ще немає — статистику нема з чого рахувати.\n\n"
            "📝 /add_note — записати перший дзвінок",
        )
        return

    by_status = stats["by_status"]
    called = stats["total"]
    interested = by_status.get("interested", 0)
    deals = by_status.get("deal", 0)

    lines = [
        "📈 <b>Твоя статистика</b>",
        "",
        f"📇 Знайдено лідів: <b>{stats['leads_total']}</b>",
        f"📝 Записів у CRM: <b>{called}</b> (за тиждень: {stats['week']})",
        "",
        "<b>За статусами:</b>",
    ]
    for key, label in STATUS_LABELS.items():
        count = by_status.get(key, 0)
        if count:
            share = count / called * 100
            lines.append(f"  {esc(label)}: <b>{count}</b> ({share:.0f}%)")

    lines += [
        "",
        f"🎯 Конверсія в зацікавлених: <b>{interested / called * 100:.1f}%</b>",
        f"🤝 Конверсія в угоди: <b>{deals / called * 100:.1f}%</b>",
    ]
    if interested and not deals:
        lines.append("\n💡 Є зацікавлені, але ще немає угод — варто пройтись по них повторно.")
    await send_html(update.message, "\n".join(lines))


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    preview = esc(text[:40] + ("…" if len(text) > 40 else ""))
    await send_html(
        update.message,
        f"🤖 Не розумію: «{preview}»\n\nЯ працюю через команди — обери дію нижче:",
        reply_markup=MAIN_KEYBOARD,
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальний обробник помилок: логує і чесно повідомляє користувача."""
    error = context.error
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning("Network error: %s", error)
        return
    if isinstance(error, Forbidden):
        logger.info("Bot blocked by user: %s", error)
        return

    logger.exception("Unhandled exception while processing update", exc_info=error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Щось пішло не так під час обробки запиту.\n"
                "Спробуй ще раз або почни спочатку: /start"
            )
        except Exception:
            pass
