"""CRM-нотатник: /add_note, /notes, /stats-дані, експорт, нагадування."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
import handlers_common as common
from handlers_common import MAIN_KEYBOARD
from ui import STATUS_LABELS, esc, reminder_keyboard, send_html, status_keyboard

logger = logging.getLogger(__name__)

NOTE_NAME, NOTE_PHONE, NOTE_STATUS, NOTE_COMMENT, NOTE_REMIND = range(10, 15)

REMINDER_DELAYS = {
    "2h": (timedelta(hours=2), "через 2 години"),
    "1d": (timedelta(days=1), "завтра"),
    "3d": (timedelta(days=3), "через 3 дні"),
    "7d": (timedelta(days=7), "через тиждень"),
}


# ─── Створення нотатки ────────────────────────────────────────────────────────

async def add_note_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("note_place_id", None)
    await send_html(update.message, "📝 <b>Запис дзвінку</b>\n\nВведи назву бізнесу:")
    return NOTE_NAME


async def note_from_lead(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вхід у діалог одразу з картки ліда — назва й телефон уже відомі."""
    query = update.callback_query
    await query.answer()
    try:
        lead_id = int(query.data.split(":", 1)[1])
    except (IndexError, ValueError):
        return ConversationHandler.END

    lead = await db.aget_lead(lead_id, update.effective_user.id)
    if lead is None:
        await query.message.reply_text("⚠️ Лід не знайдено — зроби новий пошук: /find_leads")
        return ConversationHandler.END

    context.user_data["note_name"] = lead.get("name", "")
    context.user_data["note_phone"] = lead.get("phone_formatted") or lead.get("phone", "")
    context.user_data["note_place_id"] = lead.get("place_id", "")

    await send_html(
        query.message,
        f"📝 <b>{esc(lead.get('name', ''))}</b>\n"
        f"📞 {esc(context.user_data['note_phone'] or '—')}\n\n"
        "Обери статус дзвінку:",
        reply_markup=status_keyboard(),
    )
    return NOTE_STATUS


async def note_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["note_name"] = update.message.text.strip()
    await send_html(update.message, "📞 Введи телефон (або <code>-</code> якщо немає):")
    return NOTE_PHONE


async def note_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    context.user_data["note_phone"] = "" if phone == "-" else phone
    await send_html(update.message, "📊 Обери статус дзвінку:", reply_markup=status_keyboard())
    return NOTE_STATUS


async def note_status_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_key = query.data.split(":", 1)[1]
    context.user_data["note_status"] = status_key
    label = STATUS_LABELS.get(status_key, status_key)
    await query.edit_message_text(
        f"Статус: {label}\n\n✏️ Додай коментар (або «-» без коментаря):"
    )
    return NOTE_COMMENT


async def note_get_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    comment = update.message.text.strip()
    if comment == "-":
        comment = ""

    user_id = update.effective_user.id
    status_key = context.user_data.get("note_status", "")
    note_id = await db.aadd_note(
        user_id,
        context.user_data.get("note_name", ""),
        context.user_data.get("note_phone", ""),
        status_key,
        comment,
        context.user_data.get("note_place_id", ""),
    )
    context.user_data["note_id"] = note_id

    await send_html(
        update.message,
        "✅ <b>Записано!</b>\n\n"
        f"🏢 {esc(context.user_data.get('note_name', ''))}\n"
        f"📞 {esc(context.user_data.get('note_phone') or '—')}\n"
        f"📊 {esc(STATUS_LABELS.get(status_key, status_key))}\n"
        f"💬 {esc(comment or '—')}",
    )

    if status_key == "callback":
        await send_html(
            update.message,
            "⏰ Коли нагадати про цей бізнес?",
            reply_markup=reminder_keyboard(),
        )
        return NOTE_REMIND

    await _finish(update, context)
    return ConversationHandler.END


async def note_reminder_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    note_id = context.user_data.get("note_id")

    if choice == "no" or choice not in REMINDER_DELAYS or not note_id:
        await query.edit_message_text("Гаразд, без нагадування.")
    else:
        delay, human = REMINDER_DELAYS[choice]
        when = datetime.now(timezone.utc) + delay
        await db.aset_reminder(note_id, update.effective_user.id, when)
        schedule_reminder(
            context.application,
            note_id=note_id,
            chat_id=query.message.chat_id,
            name=context.user_data.get("note_name", ""),
            phone=context.user_data.get("note_phone", ""),
            when=when,
        )
        await query.edit_message_text(f"⏰ Нагадаю {human}.")

    await _finish(update, context)
    return ConversationHandler.END


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ("note_name", "note_phone", "note_status", "note_place_id", "note_id"):
        context.user_data.pop(key, None)
    message = update.effective_message
    if message:
        await message.reply_text(
            "📋 /notes — усі нотатки · 📈 /stats — статистика",
            reply_markup=MAIN_KEYBOARD,
        )


# ─── Нагадування ──────────────────────────────────────────────────────────────

async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    note_id = data.get("note_id")
    text = (
        "⏰ <b>Час передзвонити!</b>\n\n"
        f"🏢 {esc(data.get('name', ''))}\n"
        f"📞 {esc(data.get('phone') or '—')}\n\n"
        "📝 /add_note — записати результат"
    )
    try:
        await context.bot.send_message(
            chat_id=data["chat_id"], text=text, parse_mode="HTML"
        )
    except Exception as exc:
        logger.warning("Не вдалося надіслати нагадування %s: %s", note_id, exc)
    if note_id:
        await db.amark_reminded(note_id)


def schedule_reminder(application, note_id: int, chat_id: int, name: str,
                      phone: str, when: datetime) -> None:
    job_queue = getattr(application, "job_queue", None)
    if job_queue is None:
        logger.warning("JobQueue недоступна — нагадування не заплановано "
                       "(встанови python-telegram-bot[job-queue]).")
        return
    delay = max(5.0, (when - datetime.now(timezone.utc)).total_seconds())
    job_queue.run_once(
        reminder_job,
        when=delay,
        data={"note_id": note_id, "chat_id": chat_id, "name": name, "phone": phone},
        name=f"reminder_{note_id}",
    )


async def restore_reminders(application) -> None:
    """Після перезапуску бота відновлює заплановані нагадування з бази."""
    pending = await db.apending_reminders()
    restored = 0
    for note in pending:
        try:
            when = datetime.strptime(note["remind_at"], db.TS_FMT).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        schedule_reminder(
            application,
            note_id=note["id"],
            chat_id=note["user_id"],
            name=note.get("biz_name", ""),
            phone=note.get("phone", ""),
            when=when,
        )
        restored += 1
    if restored:
        logger.info("Відновлено нагадувань: %s", restored)


# ─── Перегляд і експорт ───────────────────────────────────────────────────────

async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_filter = ""
    if context.args:
        candidate = context.args[0].strip().lower()
        if candidate in STATUS_LABELS:
            status_filter = candidate

    notes = await db.aget_notes(update.effective_user.id, status_filter)
    if not notes:
        await send_html(
            update.message,
            "📭 Нотаток ще немає.\n\n📝 /add_note — додати перший запис.",
        )
        return

    header = f"📋 <b>Твої нотатки</b> ({len(notes)})"
    if status_filter:
        header += f" · фільтр: {esc(STATUS_LABELS[status_filter])}"
    lines = [header, ""]
    for note in notes:
        lines.append(
            f"<b>#{note['id']}</b> | {esc(note['created_at'])}\n"
            f"🏢 {esc(note['biz_name'])}\n"
            f"📞 {esc(note['phone'] or '—')} | "
            f"{esc(STATUS_LABELS.get(note['status'], note['status']))}\n"
            f"💬 {esc(note['comment'] or '—')}\n"
        )
    await send_html(update.message, "\n".join(lines))
    await send_html(
        update.message,
        "📤 /export — завантажити як CSV\n"
        "🗑 /delete_note &lt;id&gt; — видалити запис\n"
        "🔎 /notes interested — фільтр за статусом "
        "<i>(called, interested, not_interested, callback, no_answer, deal)</i>",
    )


def _csv_document(rows: list[list], header: list[str]) -> io.BytesIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return io.BytesIO(buffer.getvalue().encode("utf-8-sig"))


async def export_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    notes = await db.aget_notes(update.effective_user.id)
    if not notes:
        await update.message.reply_text("📭 Нотаток немає — нічого експортувати.")
        return

    rows = [
        [n["id"], n["created_at"], n["biz_name"], n["phone"],
         STATUS_LABELS.get(n["status"], n["status"]), n["comment"],
         n.get("remind_at") or ""]
        for n in notes
    ]
    document = _csv_document(
        rows, ["#", "Дата", "Бізнес", "Телефон", "Статус", "Коментар", "Нагадування"]
    )
    await update.message.reply_document(
        document=document,
        filename=f"leads_crm_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        caption=f"📊 Експорт нотаток — {len(notes)} записів",
    )


async def export_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    leads = await db.alast_search_leads(update.effective_user.id)
    if not leads:
        await send_html(
            update.message,
            "📭 Немає результатів останнього пошуку.\n\n🔍 /find_leads — спершу знайди ліди.",
        )
        return

    rows = []
    for lead in leads:
        rows.append([
            lead.get("score", ""), lead.get("score_mark", ""), lead.get("name", ""),
            lead.get("niche", ""), lead.get("phone_formatted") or lead.get("phone", ""),
            "так" if lead.get("phone_valid") else "ні",
            lead.get("email", ""),
            lead.get("instagram_url", "") if lead.get("instagram_verified") else "",
            f"https://facebook.com/{lead['facebook']}" if lead.get("facebook") else "",
            lead.get("website", ""), lead.get("rating", ""), lead.get("review_count", ""),
            lead.get("sentiment", ""), lead.get("last_review_date", ""),
            lead.get("address", ""), lead.get("city", ""), lead.get("country", ""),
            lead.get("maps_url", ""),
        ])
    document = _csv_document(rows, [
        "Бал", "Оцінка", "Назва", "Ніша", "Телефон", "Телефон валідний", "Email",
        "Instagram", "Facebook", "Сайт", "Рейтинг", "К-сть відгуків", "Настрій",
        "Останній відгук", "Адреса", "Місто", "Країна", "Google Maps",
    ])
    await update.message.reply_document(
        document=document,
        filename=f"search_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        caption=f"📊 Експорт пошуку — {len(leads)} лідів",
    )


async def delete_note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await send_html(update.message, "Використання: <code>/delete_note 5</code>")
        return
    note_id = int(context.args[0])
    deleted = await db.adelete_note(note_id, update.effective_user.id)
    await update.message.reply_text(
        f"🗑 Нотатку #{note_id} видалено." if deleted
        else f"⚠️ Нотатки #{note_id} не знайдено серед твоїх записів."
    )


def build_handlers() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("add_note", add_note_start),
            CallbackQueryHandler(note_from_lead, pattern=r"^nt:\d+$"),
        ],
        states={
            NOTE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, note_get_name)],
            NOTE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, note_get_phone)],
            NOTE_STATUS: [CallbackQueryHandler(note_status_button, pattern=r"^ns:")],
            NOTE_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, note_get_comment)],
            NOTE_REMIND: [CallbackQueryHandler(note_reminder_button, pattern=r"^rem:")],
        },
        fallbacks=common.fallbacks("add_note", add_note_start),
        conversation_timeout=1800,
        per_message=False,
    )
