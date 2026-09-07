"""Manejadores de comandos relacionados con cursos y cuenta:
/cursos, /tareas, /notificaciones, /cuenta, /logout y callback de desconexión.
"""

import logging
import re
from datetime import datetime as _dt
from html import unescape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.services.accounts import (
    account_status,
    get_client_for,
    logout_user,
)
from src.bot.keyboards import menu_keyboard

logger = logging.getLogger(__name__)


async def _require_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper: devuelve el cliente del usuario o envía aviso de login."""
    chat_id = update.effective_chat.id
    client = get_client_for(chat_id)
    if client is None:
        await update.message.reply_text(
            "🔐 Cole, todavía no tienes cuenta conectada.\n"
            "Manda /login y nos ponemos al día."
        )
        return None
    return client


async def cursos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Dame un chance, trayendo tus materias...")

    client = await _require_client(update, context)
    if client is None:
        return

    try:
        courses = client.get_courses()
    except Exception:
        logger.exception("Error obteniendo cursos")
        await update.message.reply_text(
            "❌ Cole, se me travó algo buscando tus cursos. "
            "Paciencia y vuelve a intentar."
        )
        return
    finally:
        client.logout()

    if not courses:
        await update.message.reply_text("⚠️ No encontré cursos inscritos. ¿Estás matriculado?")
        return

    lines = [f"📚 <b>Tus materias ({len(courses)})</b>:", ""]
    for i, course in enumerate(courses, 1):
        lines.append(f"{i}. <b>{course['name']}</b>")
        lines.append(f"   🔗 <a href='{course['url']}'>Abrir en Moodle</a>")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def tareas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Dale, revisando qué se te viene...")

    client = await _require_client(update, context)
    if client is None:
        return

    try:
        events = client.get_upcoming_events(days_ahead=30)
    except Exception:
        logger.exception("Error obteniendo actividades")
        await update.message.reply_text(
            "❌ No pude traer las actividades, cole. "
            "Paciencia y vuelve a intentar."
        )
        return
    finally:
        client.logout()

    if not events:
        await update.message.reply_text("✅ ¡No tienes na' pendiente por 30 días! Relájate, cole.")
        return

    def _fmt_desc(desc: str, limit: int = 350) -> str:
        if not desc:
            return ""
        text = re.sub(r"<[^>]+>", "", unescape(desc))
        text = text.strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0] + "…"

    def _urgency_tag(timestart):
        now = _dt.now().timestamp()
        hours_left = (timestart - now) / 3600
        if hours_left < 0:
            return "🚨 <b>¡Eche, ya venció la mondá!</b>"
        if hours_left < 6:
            return "🔴 <b>¡Ponte pila en esa mondá! Queda menos de 6h</b>"
        if hours_left < 24:
            return "🟡 <b>Ojo con eso, que queda menos de 1 día</b>"
        if hours_left < 72:
            return "🟠 <b>Cule viaje, ya le quedan 3 días o menos</b>"
        return ""

    lines = [f"📅 <b>Tus actividades próximas ({len(events)}):</b>", ""]
    for e in events:
        tag = _urgency_tag(e["timestart"])
        lines.append(f"📌 <b>{e['name']}</b>")
        if tag:
            lines.append(f"   ⚠️ {tag}")
        lines.append(f"   📚 {e['course_name']}")
        lines.append(f"   ⏰ Vence: {e['formatted_time']}")
        desc = _fmt_desc(e.get("description", ""))
        if desc:
            lines.append(f"   📝 <i>{desc}</i>")
        if e["url"]:
            lines.append(f"   🔗 <a href='{e['url']}'>Ver en Moodle</a>")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def notificaciones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Dándole una revisada a todo...")

    client = await _require_client(update, context)
    if client is None:
        return

    try:
        summary = client.get_notifications_summary()
    except Exception:
        logger.exception("Error obteniendo notificaciones")
        await update.message.reply_text(
            "❌ No pude traer el resumen, cole. "
            "Paciencia y vuelve a intentar."
        )
        return
    finally:
        client.logout()

    events = summary["upcoming_events"]
    activity = summary["recent_activity"]

    lines = ["🔔 <b>Resumen de todo, cole</b>", ""]

    if events:
        lines.append(f"📅 <b>Próximos vencimientos ({len(events)})</b>:")
        for e in events[:10]:
            lines.append(f"  📌 {e['name']}")
            lines.append(f"     📚 {e['course_name']} | ⏰ {e['formatted_time']}")
        if len(events) > 10:
            lines.append(f"  ... y {len(events) - 10} más")
        lines.append("")

    if activity:
        lines.append(f"📄 <b>Actividad reciente (7 días) ({len(activity)})</b>:")
        for a in activity[:10]:
            modname = a["modname"].replace("mod_", "")
            lines.append(f"  📄 {a['name']} ({modname})")
            lines.append(f"     🕐 {a['formatted_time']}")
        if len(activity) > 10:
            lines.append(f"  ... y {len(activity) - 10} más")
        lines.append("")

    if not events and not activity:
        lines.append("✅ No tienes nada pendiente ni actividad reciente. ¡Dale down!")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is None:
        await update.message.reply_text(
            "🔐 Cole, no tienes cuenta conectada.\nManda /login y nos ponemos al día."
        )
        return

    cursos_count = "—"
    client = get_client_for(chat_id)
    if client is not None:
        try:
            cursos_count = len(client.get_courses())
        except Exception:
            cursos_count = "No pude traerlos"
        finally:
            client.logout()

    text = (
        "👤 <b>Tu cuenta, cole</b>\n\n"
        f"Usuario: <code>{info['username']}</code>\n"
        f"Facultad: <b>{info['instance_name']}</b>\n"
        f"Servidor: <code>{info['instance_base_url']}</code>\n"
        f"Cursos: <b>{cursos_count}</b>\n"
        f"Estado: 🟢 Conectado\n"
        f"Última vuelta: {info['last_sync_at'] or 'Aún no'}"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Cambiar facultad", callback_data="cuenta_cambiar_facultad")],
        [InlineKeyboardButton("🚪 Desconectar", callback_data="cuenta_logout")],
    ])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def cuenta_logout_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Botón 'Desconectar' dentro de /cuenta."""
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    logout_user(chat_id)
    await query.edit_message_text(
        "👋 Dale, desconectado. Tus datos se borraron del bot.\n"
        "Si quieres volver, manda /login."
    )
    await query.message.reply_text(
        "¿Quieres conectar otra cuenta? Dale a /login o usa el botón.",
        reply_markup=menu_keyboard(False),
    )


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logout_user(chat_id)
    await update.message.reply_text(
        "👋 Dale, ya te desconecté y borré tus datos.\n"
        "Si quieres volver, manda /login.",
        reply_markup=menu_keyboard(False),
    )
