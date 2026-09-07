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

CF_INSTANCE, CF_CONFIRM, CF_USERNAME, CF_PASSWORD = range(10, 14)


async def change_facultad_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is None:
        msg = (
            "🔐 Cole, no tienes cuenta conectada.\n"
            "Manda /login primero."
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END

    text = (
        "🏫 <b>Tu facultad actual:</b>\n"
        f"<b>{info['instance_name']}</b>\n\n"
        "¿Cuál quieres cambiar, cole?"
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
    await query.edit_message_text(
        "Escogiste:\n\n"
        f"🏫 <b>{instance.name}</b>\n"
        f"🌐 <code>{instance.base_url}</code>\n\n"
        "¿Quieres conectarte a esta facultad, cole?",
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
        await query.edit_message_text("👍 Dale, todo como estaba. Tu cuenta no cambió.")
        return ConversationHandler.END

    instance_id = context.user_data.get("cf_instance_id")
    instance = registry.get(instance_id)
    if instance is None:
        await query.edit_message_text("❌ Instancia desconocida. Intenta de nuevo.")
        return ConversationHandler.END

    await query.edit_message_text(
        "✅ Has seleccionado:\n\n"
        f"🏫 <b>{instance.name}</b>\n"
        f"🌐 <code>{instance.base_url}</code>\n\n"
        "👤 Ahora escribe tu <b>usuario de Akumaja</b>.\n\n"
        "Es el mismo de tu correo institucional, "
        "la parte antes de <code>@uniguajira.edu.co</code>.\n"
        "Ejemplo: <code>nombre.apellido</code>",
        parse_mode="HTML",
    )
    return CF_USERNAME


async def cf_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text
    username = normalize_username(raw)
    if not username or len(username) > 100:
        await update.message.reply_text("⚠️ Escribe un usuario válido, cole.")
        return CF_USERNAME

    context.user_data["cf_username"] = username
    if username != raw.strip():
        await update.message.reply_text(
            f"✅ Va, usaré: <code>{username}</code>\n\n"
            "🔑 Ahora escribe tu <b>contraseña de Moodle</b>.\n"
            "⚠️ <i>La borro del chat cuando la escribas.</i>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "🔑 Ahora escribe tu <b>contraseña de Moodle</b>.\n"
            "⚠️ <i>La borro del chat cuando la escribas.</i>",
            parse_mode="HTML",
        )
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
        await update.message.reply_text("⚠️ Escribe una contraseña válida, cole.")
        return CF_PASSWORD

    instance_id = context.user_data.get("cf_instance_id")
    username = context.user_data.get("cf_username")
    if not instance_id or not username:
        await update.message.reply_text(
            "❌ Se venció el tiempo. Manda /cambiar_facultad de nuevo."
        )
        return ConversationHandler.END

    instance = registry.get(instance_id)
    try:
        _, course_count = validate_login(chat_id, instance_id, username, password)
    except TooManyAttempts:
        await update.message.reply_text(
            "🚫 ¡Mucho intento fallido! Dale una pausa y vuelve con /cambiar_facultad."
        )
        return ConversationHandler.END
    except LoginError:
        await update.message.reply_text(
            f"❌ No pude conectarme a {instance.name}, cole.\n"
            "Tu cuenta actual <b>NO se tocó</b>.\n"
            "Revisa tu user y clave e intenta de nuevo "
            "(o manda /cancel si quieres salir).",
            parse_mode="HTML",
        )
        return CF_PASSWORD

    apply_faculty_change(chat_id, instance_id, username, password)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ <b>¡Facultad cambiada, listo!</b>\n\n"
        f"🏫 {instance.name}\n"
        f"🌐 <code>{instance.base_url}</code>\n"
        f"Cursos encontrados: <b>{course_count}</b>\n\n"
        "De ahora en adelante te aviso de las cosas de esta facultad.",
        parse_mode="HTML",
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
        allow_reentry=True,
    )
