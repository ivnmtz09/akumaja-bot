"""Manejadores de comandos generales: /start, /ayuda, /estado, /cancel."""

from telegram import LinkPreviewOptions, Update
from telegram.ext import ContextTypes, ConversationHandler

from src.core import database as db
from src.core.config import (
    MONITOR_END_HOUR,
    MONITOR_INTERVAL_MINUTES,
    MONITOR_START_HOUR,
)
from src.moodle.instances import registry
from src.services.accounts import account_status
from src.bot.keyboards import menu_keyboard
from src.bot.ui import LINE_DOUBLE, LINE_LIGHT, safe_escape, welcome_keyboard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    logged_in = info is not None
    link_opts = LinkPreviewOptions(is_disabled=True)

    if logged_in:
        text = (
            "🌊 <b>¡HOLA DE NUEVO! BIENVENIDO A AKUMAJA BOT</b>\n"
            "<i>Tu asistente académico para las plataformas Moodle de Uniguajira</i>\n"
            f"{LINE_DOUBLE}\n"
            f"👤 <b>Usuario conectado:</b> <code>{safe_escape(info['username'])}</code>\n"
            f"🏫 <b>Tu facultad:</b> <b>{safe_escape(info['instance_name'])}</b>\n"
            f"🌐 <b>Servidor:</b> <code>{safe_escape(info['instance_base_url'])}</code>\n"
            f"🟢 <b>Estado:</b> <code>Sesión activa y monitoreando</code>\n"
            f"🔄 <b>Última sincronización:</b> <code>{safe_escape(info['last_sync_at'] or 'Aún no')}</code>\n"
            f"{LINE_DOUBLE}\n\n"
            "📋 <b>Comandos disponibles:</b>\n"
            "├─ /cursos — Consulta tus materias inscritas\n"
            "├─ /tareas — Próximas entregas y actividades (30 días)\n"
            "├─ /notificaciones — Resumen de novedades y vencimientos\n"
            "├─ /cuenta — Estado de tu cuenta y opciones\n"
            "├─ /cambiar_facultad — Cambiar de facultad o servidor\n"
            "├─ /logout — Cerrar sesión y desconectar cuenta\n"
            "└─ /estado — Estado del servicio\n\n"
            f"{LINE_LIGHT}\n"
            "💡 <b>Recordatorio:</b> Te aviso periódicamente (6am–11pm) sobre entregas "
            "próximas, fechas límite y nuevo material en tus cursos."
        )
    else:
        text = (
            "🌊 <b>¡BIENVENIDO A AKUMAJA BOT!</b>\n"
            "<i>Tu asistente académico para las plataformas Moodle de Uniguajira</i>\n"
            f"{LINE_DOUBLE}\n\n"
            "🔐 <b>Aún no has conectado tu cuenta Moodle.</b>\n"
            "Usa <b>/login</b> para comenzar y ponerte al día con tus materias.\n\n"
            "🚀 <b>¿Cómo empezar?</b>\n"
            "1️⃣ Pulsa el botón inferior o escribe <b>/login</b>\n"
            "2️⃣ Selecciona tu <b>facultad</b> correspondiente\n"
            "3️⃣ Ingresa tu <b>usuario institucional</b> (sin el @uniguajira.edu.co)\n"
            "4️⃣ Ingresa tu contraseña (se borrará del chat al instante)\n\n"
            "📋 <b>Comandos disponibles:</b>\n"
            "├─ /cursos — Consulta tus materias inscritas\n"
            "├─ /tareas — Próximas entregas y actividades (30 días)\n"
            "├─ /notificaciones — Resumen de novedades y vencimientos\n"
            "├─ /cuenta — Estado de tu cuenta y opciones\n"
            "├─ /cambiar_facultad — Cambiar de facultad o servidor\n"
            "├─ /logout — Cerrar sesión y desconectar cuenta\n"
            "└─ /estado — Estado del servicio\n\n"
            f"{LINE_LIGHT}\n"
            "💡 <b>Recordatorio:</b> Te aviso periódicamente (6am–11pm) sobre entregas "
            "próximas, fechas límite y nuevo material en tus cursos."
        )

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=welcome_keyboard(logged_in),
            link_preview_options=link_opts,
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=welcome_keyboard(logged_in),
            link_preview_options=link_opts,
        )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logged_in = account_status(chat_id) is not None
    link_opts = LinkPreviewOptions(is_disabled=True)

    text = (
        "🌊 <b>CENTRO DE AYUDA — AKUMAJA BOT</b>\n"
        f"{LINE_DOUBLE}\n\n"
        "👋 <b>¿Primera vez por aquí?</b>\n"
        "<blockquote>Envía <b>/login</b>, selecciona tu facultad, ingresa tu usuario "
        "institucional (la parte antes de <code>@uniguajira.edu.co</code>) y tu "
        "contraseña de Moodle. ¡Listo en 30 segundos!</blockquote>\n\n"
        "📋 <b>Comandos disponibles:</b>\n"
        "/login — Conectar tu cuenta Moodle\n"
        "/cursos — Ver tus materias inscritas\n"
        "/tareas — Entregas y exámenes próximos (30 días)\n"
        "/notificaciones — Resumen completo de actividades\n"
        "/cuenta — Tu información y opciones de cuenta\n"
        "/cambiar_facultad — Cambiar de facultad sin desconectarte\n"
        "/logout — Cerrar sesión y borrar tus datos del bot\n"
        "/estado — Estado y estadísticas del servicio\n"
        "/cancel — Cancelar la operación en curso\n\n"
        f"{LINE_LIGHT}\n"
        "💡 <b>Monitoreo automático:</b>\n"
        "<blockquote>Te aviso periódicamente (6am–11pm) si tienes entregas próximas, "
        "tareas vencidas o nuevo contenido en tus cursos. ¡Para que no se te pase ninguna entrega!</blockquote>"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=menu_keyboard(logged_in),
        link_preview_options=link_opts,
    )


async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.list_active_users()
    end_display = (
        f"{MONITOR_END_HOUR - 1}:59"
        if MONITOR_END_HOUR == 24
        else f"{MONITOR_END_HOUR}:59"
    )
    interval_desc = (
        f"{MONITOR_INTERVAL_MINUTES} min"
        if MONITOR_INTERVAL_MINUTES < 60
        else f"{MONITOR_INTERVAL_MINUTES // 60}h"
    )

    lines = [
        "🤖 <b>Estado del servicio — Akumaja Bot</b>",
        LINE_DOUBLE,
        f"👥 <b>Usuarios conectados:</b> {len(users)}",
        f"🌐 <b>Facultades disponibles:</b> {len(registry.all())}",
        f"🟢 <b>Estado del sistema:</b> <code>Operativo y activo</code>",
        LINE_DOUBLE,
        f"⏰ <b>Monitoreo automático:</b> cada {interval_desc} "
        f"({MONITOR_START_HOUR}:00 – {end_display})",
        "   Notificaciones de entregas, tareas vencidas y novedades.",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    text = (
        "❌ <b>Operación cancelada</b>\n"
        f"{LINE_DOUBLE}\n"
        "Operación cancelada. Todo permanece igual."
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")
    return ConversationHandler.END
