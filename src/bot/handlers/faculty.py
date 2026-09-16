"""Flujo de conversación para cambiar de facultad (/cambiar_facultad)."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.services.accounts import (
    LoginError,
    TooManyAttempts,
    account_status,
    apply_faculty_change,
    normalize_username,
    validate_login,
)
from src.moodle.instances import registry
from src.bot.handlers.general import cancel
from src.bot.keyboards import build_faculty_selection
from src.bot.ui import LINE_DOUBLE, LINE_LIGHT, safe_escape

CF_INSTANCE, CF_CONFIRM, CF_USERNAME, CF_PASSWORD = range(10, 14)


async def change_facultad_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is None:
        msg = (
            "🔐 <b>Acceso no autorizado</b>\n"
            f"{LINE_DOUBLE}\n"
            "No tienes una cuenta conectada.\n"
            "Envía <b>/login</b> primero para comenzar."
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return ConversationHandler.END

    text = (
        "🏫 <b>CAMBIAR DE FACULTAD</b>\n"
        f"{LINE_DOUBLE}\n"
        f"📍 <b>Tu facultad actual:</b>\n"
        f"<b>{safe_escape(info['instance_name'])}</b>\n\n"
        "👇 <b>¿A cuál facultad deseas cambiarte?</b>"
    )
    markup = InlineKeyboardMarkup(build_faculty_selection(info["instance_id"]))

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=markup
        )
    else:
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=markup
        )
    return CF_INSTANCE


async def cf_instance_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Selección de facultad: muestra confirmación."""
    query = update.callback_query
    await query.answer()

    instance_id = query.data.split(":", 1)[1]
    instance = registry.get(instance_id)
    if instance is None:
        await query.edit_message_text("❌ Instancia desconocida. Intenta de nuevo.")
        return ConversationHandler.END

    context.user_data["cf_instance_id"] = instance_id
    text = (
        "🏫 <b>CONFIRMAR CAMBIO DE FACULTAD</b>\n"
        f"{LINE_DOUBLE}\n"
        "Seleccionaste:\n\n"
        f"🏫 <b>{safe_escape(instance.name)}</b>\n"
        f"🌐 <code>{safe_escape(instance.base_url)}</code>\n\n"
        f"{LINE_DOUBLE}\n"
        "¿Deseas cambiarte a esta facultad?"
    )
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Continuar", callback_data="cf_confirm:yes")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cf_confirm:no")],
        ]),
    )
    return CF_CONFIRM


async def cf_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Botón 'Cancelar' del listado de facultades."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("❌ Cancelado. Tu cuenta no cambió.")
    return ConversationHandler.END


async def cf_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirmación: Continuar → pedir credenciales; Cancelar → no tocar nada."""
    query = update.callback_query
    await query.answer()

    choice = query.data.split(":", 1)[1]
    if choice == "no":
        context.user_data.clear()
        await query.edit_message_text("👍 Operación cancelada. Tu cuenta no cambió.")
        return ConversationHandler.END

    instance_id = context.user_data.get("cf_instance_id")
    instance = registry.get(instance_id)
    if instance is None:
        await query.edit_message_text("❌ Instancia desconocida. Intenta de nuevo.")
        return ConversationHandler.END

    text = (
        "✅ <b>Has seleccionado:</b>\n"
        f"{LINE_DOUBLE}\n"
        f"🏫 <b>{safe_escape(instance.name)}</b>\n"
        f"🌐 <code>{safe_escape(instance.base_url)}</code>\n"
        f"{LINE_DOUBLE}\n\n"
        "👤 Ahora escribe tu <b>usuario de Akumaja</b>.\n\n"
        "Es el mismo de tu correo institucional, "
        "la parte antes de <code>@uniguajira.edu.co</code>.\n"
        "Ejemplo: <code>nombre.apellido</code>"
    )
    await query.edit_message_text(text, parse_mode="HTML")
    return CF_USERNAME


async def cf_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text
    username = normalize_username(raw)
    if not username or len(username) > 100:
        await update.message.reply_text(
            "⚠️ <b>Usuario no válido</b>\n"
            f"{LINE_DOUBLE}\n"
            "Por favor ingresa un usuario institucional válido (ej: <code>nombre.apellido</code>).",
            parse_mode="HTML",
        )
        return CF_USERNAME

    context.user_data["cf_username"] = username
    text = (
        f"✅ Usaré: <code>{safe_escape(username)}</code>\n"
        f"{LINE_DOUBLE}\n\n"
        "🔑 Ahora escribe tu <b>contraseña de Moodle</b>.\n"
        "<blockquote>⚠️ <i>Por seguridad, el mensaje se borrará de inmediato del chat.</i></blockquote>"
    )
    await update.message.reply_text(text, parse_mode="HTML")
    return CF_PASSWORD


async def cf_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    password = update.message.text

    # Borrar el mensaje de la contraseña (best-effort)
    try:
        await update.message.delete()
    except Exception:
        pass

    if not password:
        await update.message.reply_text("⚠️ Por favor escribe una contraseña válida.")
        return CF_PASSWORD

    instance_id = context.user_data.get("cf_instance_id")
    username = context.user_data.get("cf_username")
    if not instance_id or not username:
        await update.message.reply_text(
            "❌ El tiempo de espera expiró. Envía /cambiar_facultad de nuevo."
        )
        return ConversationHandler.END

    instance = registry.get(instance_id)
    try:
        _, course_count = validate_login(chat_id, instance_id, username, password)
    except TooManyAttempts:
        await update.message.reply_text(
            "🚫 <b>Demasiados intentos fallidos</b>\n"
            f"{LINE_DOUBLE}\n"
            "Por seguridad, espera unos minutos antes de intentar con /cambiar_facultad.",
            parse_mode="HTML",
        )
        return ConversationHandler.END
    except LoginError:
        await update.message.reply_text(
            f"❌ <b>No fue posible conectar con {safe_escape(instance.name)}</b>.\n"
            f"{LINE_DOUBLE}\n"
            "Tu cuenta actual <b>no se modificó</b>.\n"
            "Verifica tu usuario y contraseña e intenta nuevamente "
            "(o envía /cancel para cancelar).",
            parse_mode="HTML",
        )
        return CF_PASSWORD

    apply_faculty_change(chat_id, instance_id, username, password)
    context.user_data.clear()
    success_text = (
        "🎉 <b>¡FACULTAD ACTUALIZADA CON ÉXITO!</b>\n"
        f"{LINE_DOUBLE}\n"
        f"🏫 <b>{safe_escape(instance.name)}</b>\n"
        f"🌐 <code>{safe_escape(instance.base_url)}</code>\n"
        f"📚 Cursos encontrados: <b>{course_count}</b>\n"
        f"{LINE_DOUBLE}\n\n"
        "A partir de ahora recibirás alertas y novedades de esta facultad."
    )
    quick_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📚 Mis Materias", callback_data="view_cursos"),
            InlineKeyboardButton("📅 Próximas Tareas", callback_data="view_tareas"),
        ],
    ])
    await update.message.reply_text(
        success_text,
        parse_mode="HTML",
        reply_markup=quick_markup,
    )
    return ConversationHandler.END


def get_faculty_handler() -> ConversationHandler:
    """Retorna el ConversationHandler configurado para /cambiar_facultad."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("cambiar_facultad", change_facultad_start),
            CallbackQueryHandler(change_facultad_start, pattern=r"^cuenta_cambiar_facultad$"),
        ],
        states={
            CF_INSTANCE: [
                CallbackQueryHandler(cf_instance_selected, pattern=r"^cf_inst:"),
                CallbackQueryHandler(cf_cancel, pattern=r"^cf_cancel$"),
            ],
            CF_CONFIRM: [CallbackQueryHandler(cf_confirm, pattern=r"^cf_confirm:")],
            CF_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cf_username)],
            CF_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, cf_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True, per_message=False,
    )
