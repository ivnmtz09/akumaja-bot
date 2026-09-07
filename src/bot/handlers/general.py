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
            "🌊 <b>¡Hola! Bienvenido a Akumaja Bot</b>\n\n"
            f"👤 <b>Usuario conectado:</b> <code>{info['username']}</code>\n"
            f"🏫 <b>Tu facultad:</b> {info['instance_name']}\n"
            f"🌐 <b>Servidor:</b> <code>{info['instance_base_url']}</code>\n"
            f"🔄 <b>Última sincronización:</b> {info['last_sync_at'] or 'Aún no'}\n"
        )
    else:
        header = (
            "🌊 <b>¡Hola! Bienvenido a Akumaja Bot (Uniguajira)</b>\n\n"
            "🔐 <b>Aún no has conectado tu cuenta Moodle.</b>\n"
            "Usa <b>/login</b> para comenzar y ponerte al día con tus materias.\n"
        )

    body = (
        "\n📋 <b>Comandos disponibles:</b>\n"
        "├─ /cursos — Consulta tus materias inscritas\n"
        "├─ /tareas — Próximas entregas y actividades (30 días)\n"
        "├─ /notificaciones — Resumen de novedades y vencimientos\n"
        "├─ /cuenta — Estado de tu cuenta y opciones\n"
        "├─ /cambiar_facultad — Cambiar de facultad o servidor\n"
        "├─ /logout — Cerrar sesión y desconectar cuenta\n"
        "└─ /estado — Estado del servicio\n"
        "\n💡 <b>Recordatorio:</b> Te aviso periódicamente (6am–11pm) sobre entregas "
        "próximas, fechas límite y nuevo material en tus cursos."
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
        "🌊 <b>Centro de ayuda — Akumaja Bot</b>\n\n"
        "<b>¿Primera vez por aquí?</b> Envía <b>/login</b>, selecciona tu facultad, "
        "ingresa tu usuario y contraseña de Moodle y listo.\n\n"
        "<b>Comandos disponibles:</b>\n"
        "/login — Conectar tu cuenta Moodle\n"
        "/cursos — Ver tus materias inscritas\n"
        "/tareas — Entregas y exámenes próximos (30 días)\n"
        "/notificaciones — Resumen completo de actividades\n"
        "/cuenta — Tu información y opciones de cuenta\n"
        "/cambiar_facultad — Cambiar de facultad sin desconectarte\n"
        "/logout — Cerrar sesión y borrar tus datos del bot\n"
        "/estado — Estado y estadísticas del servicio\n"
        "/cancel — Cancelar la operación en curso\n\n"
        "💡 <b>Monitoreo automático:</b> Te aviso periódicamente (6am–11pm) si tienes "
        "entregas próximas, tareas vencidas o nuevo contenido en tus cursos. "
        "¡Para que no se te pase ninguna entrega!",
        parse_mode="HTML",
        reply_markup=menu_keyboard(logged_in),
    )


async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.list_active_users()
    end_display = f"{MONITOR_END_HOUR - 1}:59" if MONITOR_END_HOUR == 24 else f"{MONITOR_END_HOUR}:59"
    lines = [
        "🤖 <b>Estado del servicio — Akumaja Bot</b>",
        "",
        f"👥 <b>Usuarios conectados:</b> {len(users)}",
        f"🌐 <b>Facultades disponibles:</b> {len(registry.all())}",
        "",
        f"⏰ <b>Monitoreo automático:</b> cada {MONITOR_INTERVAL_MINUTES // 60}h "
        f"({MONITOR_START_HOUR}:00 – {end_display})",
        "   Notificaciones de entregas, tareas vencidas y novedades.",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Operación cancelada. Todo permanece igual.")
    return ConversationHandler.END
