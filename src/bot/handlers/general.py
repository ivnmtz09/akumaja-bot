"""Manejadores de comandos generales: /start, /ayuda, /estado, /cancel."""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from src.core import database as db
from src.core.config import (
    MONITOR_START_HOUR,
    MONITOR_END_HOUR,
    MONITOR_INTERVAL_MINUTES,
)
from src.moodle.instances import registry
from src.services.accounts import account_status
from src.bot.keyboards import menu_keyboard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    logged_in = info is not None

    if logged_in:
        header = (
            "🌊 <b>¡Qué más, cole! Bienvenido a Akumaja Bot</b>\n\n"
            f"👤 <b>Usuario conectado:</b> <code>{info['username']}</code>\n"
            f"🏫 <b>Tu facultad:</b> {info['instance_name']}\n"
            f"🌐 <b>Servidor:</b> <code>{info['instance_base_url']}</code>\n"
            f"🔄 <b>Última vuelta:</b> {info['last_sync_at'] or 'Aún no'}\n"
        )
    else:
        header = (
            "🌊 <b>¡Qué más, cole! Bienvenido a Akumaja Bot</b>\n\n"
            "🔐 <b>Todavía no te has conectado, mi valecita.</b>\n"
            "Dale a <b>/login</b> y nos ponemos al día.\n"
        )

    body = (
        "\n📋 <b>Lo que puedes hacer:</b>\n"
        "├─ /cursos — Tus materias al tiro\n"
        "├─ /tareas — Qué se viene (30 días)\n"
        "├─ /notificaciones — Resumen completico\n"
        "├─ /cuenta — Tu perfil y botones\n"
        "├─ /cambiar_facultad — Cambias de facultad sin drama\n"
        "├─ /logout — Te sales si quieres\n"
        "└─ /estado — Cómo va el bot\n"
        "\n💡 <b>Ojo:</b> te aviso cada 3h (6am–11pm) si se te vence algo, "
        "si ya pasó la fecha o si subieron cosa nueva. ¡Quedas pilas!"
    )

    await update.message.reply_text(
        header + body,
        parse_mode="HTML",
        reply_markup=menu_keyboard(logged_in),
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logged_in = account_status(chat_id) is not None

    await update.message.reply_text(
        "🌊 <b>Ayuda de Akumaja Bot, cole</b>\n\n"
        "<b>¿Primera vez?</b> Manda <b>/login</b>, elige tu facultad, "
        "mete tu user y clave de Moodle y listo.\n\n"
        "<b>Comandos pa' que te desenvuelvas:</b>\n"
        "/login — Conectas tu Moodle\n"
        "/cursos — Tus materias inscritas\n"
        "/tareas — Entregas y exams próx. (30 días)\n"
        "/notificaciones — Resumen completico\n"
        "/cuenta — Tu info + botones de acción\n"
        "/cambiar_facultad — Cambias facultad sin desconectarte\n"
        "/logout — Te desconectas y borro tus datos\n"
        "/estado — Cómo anda el bot\n"
        "/cancel — Cortas lo que estés haciendo\n\n"
        "💡 <b>El bot te avisa cada 3h (6am–11pm):</b> si se te vence algo, "
        "si ya pasó la fecha o si subieron contenido nuevo. "
        "¡No se te pasa nada, pim@!",
        parse_mode="HTML",
        reply_markup=menu_keyboard(logged_in),
    )


async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.list_active_users()
    end_display = f"{MONITOR_END_HOUR - 1}:59" if MONITOR_END_HOUR == 24 else f"{MONITOR_END_HOUR}:59"
    lines = [
        "🤖 <b>Estado del bot, cole</b>",
        "",
        f"👥 <b>Gente conectada:</b> {len(users)}",
        f"🌐 <b>Facultades disponibles:</b> {len(registry.all())}",
        "",
        f"⏰ <b>Monitoreo:</b> cada {MONITOR_INTERVAL_MINUTES // 60}h "
        f"({MONITOR_START_HOUR}:00 – {end_display})",
        "   Te aviso de entregas, vencidos y cosas nuevas.",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Dale, cancelado. No pasa nada.")
    return ConversationHandler.END
