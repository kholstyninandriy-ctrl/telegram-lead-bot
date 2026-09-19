"""
LEAD FINDER BOT — пошук бізнесів, AI-аутріч і CRM у Telegram.

Можливості:
  • пошук через Google Places API v1 (з пагінацією до 60 результатів і кешем)
  • валідація телефонів, аналіз відгуків, скоринг ліда 0-100
  • пошук email / Instagram / Facebook на сайті бізнесу
  • AI: план підходу, WhatsApp, Instagram DM, холодний лист
  • CRM-нотатки зі статусами, нагадуваннями та статистикою
  • експорт нотаток і результатів пошуку в CSV

Запуск:  python main.py
Змінні оточення: див. .env.example
"""

from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, MessageHandler, TypeHandler, filters

import config
import db
import handlers_common as common
import handlers_notes as notes
import handlers_outreach as outreach
import handlers_search as search
import http_client

config.setup_logging()
logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand("find_leads", "🔍 Знайти бізнеси"),
    BotCommand("outreach", "💬 AI-повідомлення в WhatsApp"),
    BotCommand("add_note", "📝 Записати результат дзвінку"),
    BotCommand("notes", "📋 Мої нотатки"),
    BotCommand("stats", "📈 Статистика"),
    BotCommand("export", "📤 Експорт нотаток у CSV"),
    BotCommand("export_search", "📊 Експорт останнього пошуку"),
    BotCommand("help", "📖 Інструкція"),
    BotCommand("diag", "🩺 Перевірити налаштування"),
    BotCommand("cancel", "❌ Скасувати дію"),
]


async def post_init(application: Application) -> None:
    await db.ainit_db()
    await application.bot.set_my_commands(BOT_COMMANDS)
    await notes.restore_reminders(application)
    logger.info(
        "Готово. Версія %s · Google: %s · OpenAI: %s · Apify: %s · доступ: %s",
        config.BOT_VERSION,
        "є" if config.has_google() else "НЕМАЄ",
        "є" if config.has_ai() else "НЕМАЄ",
        config.APIFY_CONTACT_ACTOR if config.has_apify() else "НЕМАЄ",
        f"{len(config.ALLOWED_USER_IDS)} користувач(ів)"
        if config.ALLOWED_USER_IDS else "відкритий",
    )


async def post_shutdown(application: Application) -> None:
    await http_client.aclose()


def build_application() -> Application:
    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    builder.post_init(post_init).post_shutdown(post_shutdown)

    try:  # плавне дотримання лімітів Telegram, якщо встановлено extras
        from telegram.ext import AIORateLimiter

        builder.rate_limiter(AIORateLimiter())
    except (ImportError, RuntimeError):
        logger.warning("AIORateLimiter недоступний — встанови "
                       "python-telegram-bot[rate-limiter] для захисту від флуд-лімітів.")

    application = builder.build()

    # Контроль доступу виконується раніше за будь-який інший хендлер
    application.add_handler(TypeHandler(Update, common.access_guard), group=-1)

    search_conversation, search_callbacks = search.build_handlers()
    application.add_handler(search_conversation)
    application.add_handler(notes.build_handlers())
    application.add_handler(outreach.build_handlers())

    application.add_handler(CommandHandler("start", common.start))
    application.add_handler(CommandHandler("help", common.help_cmd))
    application.add_handler(CommandHandler("stats", common.stats_cmd))
    application.add_handler(CommandHandler("notes", notes.list_notes))
    application.add_handler(CommandHandler("export", notes.export_notes))
    application.add_handler(CommandHandler("export_search", notes.export_search))
    application.add_handler(CommandHandler("delete_note", notes.delete_note_cmd))
    application.add_handler(CommandHandler("diag", common.diag_cmd))
    application.add_handler(CommandHandler("cancel", common.cancel))

    for handler in search_callbacks:
        application.add_handler(handler)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                           common.unknown_message))
    application.add_error_handler(common.error_handler)
    return application


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN не знайдено.\n"
            "Додай його у змінні оточення (Replit Secrets / .env) і запусти знову."
        )

    application = build_application()
    logger.info("Бот запущено.")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
