"""Flujo de conversación para inicio de sesión (/login)."""

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
    normalize_username,
    perform_login,
)
from src.moodle.instances import registry
from src.bot.handlers.general import cancel
from src.bot.keyboards import instances_keyboard, menu_keyboard

LOGIN_INSTANCE, LOGIN_USERNAME, LOGIN_PASSWORD = range(3)


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is not None:
        await update.message.reply_text(
            "🔐 Cole, ya tienes cuenta conectada:\n"
            f"   Usuario: <code>{info['username']}</code>\n"
            f"   Facultad: <b>{info['instance_name']}</b>\n\n"
            "Si quieres cambiar de facultad usa /cambiar_facultad.\n"
            "Si quieres salir, /logout.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🏛️ <b>¿En qué facultad estás, cole?</b>\n\n"
        "Elige la tuya para conectarte a Moodle:",
        parse_mode="HTML",
        reply_markup=instances_keyboard(),
    )
    return LOGIN_INSTANCE


async def login_instance_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    instance_id = query.data.split(":", 1)[1]
    instance = registry.get(instance_id)
    if instance is None:
        await query.edit_message_text("❌ Instancia desconocida. Envía /login de nuevo.")
        return ConversationHandler.END

    context.user_data["login_instance_id"] = instance_id
    context.user_data.pop("login_username", None)
    await query.edit_message_text(
        "✅ <b>Facultad escogida:</b>\n\n"
        f"🏫 <b>{instance.name}</b>\n"
        f"🌐 <code>{instance.base_url}</code>\n\n"
        "👤 Ahora escribe tu <b>usuario de Akumaja</b>.\n\n"
        "Es el mismo que usas en tu correo institucional: "
        "la parte antes de <code>@uniguajira.edu.co</code>.\n\n"
        "Ejemplo:\n"
        "Correo: <code>nombre.apellido@uniguajira.edu.co</code>\n"
        "Usuario: <code>nombre.apellido</code>\n\n"
        "No necesitas escribir el <code>@uniguajira.edu.co</code>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔄 ¿Te equivocaste? Cambiar facultad",
                callback_data="login_change_faculty",
            )],
        ]),
    )
    return LOGIN_USERNAME


async def login_change_faculty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Vuelve a la selección de facultad desde el paso del usuario (/login)."""
    query = update.callback_query
    await query.answer()

    context.user_data.pop("login_instance_id", None)
    context.user_data.pop("login_username", None)
    await query.edit_message_text(
        "🏛️ <b>¿En qué facultad estás, cole?</b>\n\n"
        "Elige la tuya para conectarte a Moodle:",
        parse_mode="HTML",
        reply_markup=instances_keyboard(),
    )
    return LOGIN_INSTANCE


async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text
    username = normalize_username(raw)
    if not username or len(username) > 100:
        await update.message.reply_text("⚠️ Escribe un usuario válido, cole.")
        return LOGIN_USERNAME

    context.user_data["login_username"] = username
    if username != raw.strip():
        await update.message.reply_text(
            f"✅ Va, usaré el usuario: <code>{username}</code>\n\n"
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
    return LOGIN_PASSWORD


async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    password = update.message.text

    # Borrar el mensaje de la contraseña (best-effort)
    try:
        await update.message.delete()
    except Exception:
        pass

    if not password:
        await update.message.reply_text("⚠️ Escribe una contraseña válida, cole.")
        return LOGIN_PASSWORD

    instance_id = context.user_data.get("login_instance_id")
    username = context.user_data.get("login_username")
    if not instance_id or not username:
        await update.message.reply_text("❌ Se venció el tiempo. Manda /login de nuevo.")
        return ConversationHandler.END

    try:
        instance = perform_login(chat_id, instance_id, username, password)
    except TooManyAttempts:
        await update.message.reply_text(
            "🚫 ¡Mucho intento fallido! Dale una pausa y vuelve con /login en unos minutos."
        )
        return ConversationHandler.END
    except LoginError:
        await update.message.reply_text(
            "❌ No pude conectarme a Moodle, cole.\n"
            "Revisa tu user y clave e intenta de nuevo "
            "(o manda /cancel si quieres salir)."
        )
        return LOGIN_PASSWORD

    context.user_data.clear()
    await update.message.reply_text(
        f"✅ <b>¡Listo, conectado!</b>\n\n"
        f"Usuario: <code>{username}</code>\n"
        f"Facultad: <b>{instance.name}</b>\n\n"
        "Ya puedes ver tus cursos, tareas y todo lo que necesites.",
        parse_mode="HTML",
        reply_markup=menu_keyboard(True),
    )
    return ConversationHandler.END


def get_login_handler() -> ConversationHandler:
    """Retorna el ConversationHandler configurado para /login."""
    return ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_INSTANCE: [CallbackQueryHandler(login_instance_selected, pattern=r"^inst:")],
            LOGIN_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_username),
                CallbackQueryHandler(login_change_faculty, pattern=r"^login_change_faculty$"),
            ],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
