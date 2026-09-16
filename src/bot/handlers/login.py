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
from src.bot.ui import LINE_DOUBLE, LINE_LIGHT, safe_escape

LOGIN_INSTANCE, LOGIN_USERNAME, LOGIN_PASSWORD = range(3)


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is not None:
        text = (
            "🔐 <b>Cuenta ya conectada</b>\n"
            f"{LINE_DOUBLE}\n"
            f"👤 <b>Usuario:</b> <code>{safe_escape(info['username'])}</code>\n"
            f"🏫 <b>Facultad:</b> <b>{safe_escape(info['instance_name'])}</b>\n\n"
            "💡 Si deseas cambiar de facultad usa /cambiar_facultad.\n"
            "💡 Si deseas cerrar sesión, usa /logout."
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
        return ConversationHandler.END

    text = (
        "🏛️ <b>¿A qué facultad perteneces?</b>\n"
        f"{LINE_DOUBLE}\n"
        "Selecciona tu facultad para conectar tu cuenta de Moodle:"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=instances_keyboard(),
        )
    else:
        await update.message.reply_text(
            text,
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
    text = (
        "✅ <b>Facultad seleccionada:</b>\n"
        f"{LINE_DOUBLE}\n"
        f"🏫 <b>{safe_escape(instance.name)}</b>\n"
        f"🌐 <code>{safe_escape(instance.base_url)}</code>\n"
        f"{LINE_DOUBLE}\n\n"
        "👤 Ahora escribe tu <b>usuario de Akumaja</b>.\n\n"
        "Es el mismo que usas en tu correo institucional: "
        "la parte antes de <code>@uniguajira.edu.co</code>.\n\n"
        "Ejemplo:\n"
        "Correo: <code>nombre.apellido@uniguajira.edu.co</code>\n"
        "Usuario: <code>nombre.apellido</code>\n\n"
        "No necesitas escribir el <code>@uniguajira.edu.co</code>."
    )
    await query.edit_message_text(
        text,
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
    text = (
        "🏛️ <b>¿A qué facultad perteneces?</b>\n"
        f"{LINE_DOUBLE}\n"
        "Selecciona tu facultad para conectar tu cuenta de Moodle:"
    )
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=instances_keyboard(),
    )
    return LOGIN_INSTANCE


async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text
    username = normalize_username(raw)
    if not username or len(username) > 100:
        await update.message.reply_text(
            "⚠️ <b>Usuario no válido</b>\n"
            f"{LINE_DOUBLE}\n"
            "Por favor ingresa un usuario institucional válido (ej: <code>nombre.apellido</code>).",
            parse_mode="HTML",
        )
        return LOGIN_USERNAME

    context.user_data["login_username"] = username
    text = (
        f"✅ Usaré el usuario: <code>{safe_escape(username)}</code>\n"
        f"{LINE_DOUBLE}\n\n"
        "🔑 Ahora escribe tu <b>contraseña de Moodle</b>.\n"
        "<blockquote>⚠️ <i>Por seguridad, el mensaje se borrará de inmediato del chat en cuanto se reciba.</i></blockquote>"
    )
    await update.message.reply_text(text, parse_mode="HTML")
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
        await update.message.reply_text("⚠️ Por favor escribe una contraseña válida.")
        return LOGIN_PASSWORD

    instance_id = context.user_data.get("login_instance_id")
    username = context.user_data.get("login_username")
    if not instance_id or not username:
        await update.message.reply_text("❌ El tiempo de espera expiró. Envía /login nuevamente.")
        return ConversationHandler.END

    try:
        instance = perform_login(chat_id, instance_id, username, password)
    except TooManyAttempts:
        await update.message.reply_text(
            "🚫 <b>Demasiados intentos fallidos</b>\n"
            f"{LINE_DOUBLE}\n"
            "Por seguridad, espera unos minutos antes de volver a intentar con /login.",
            parse_mode="HTML",
        )
        return ConversationHandler.END
    except LoginError:
        await update.message.reply_text(
            "❌ <b>Error de autenticación</b>\n"
            f"{LINE_DOUBLE}\n"
            "No fue posible conectar con Moodle.\n"
            "Verifica tu usuario y contraseña e intenta nuevamente "
            "(o envía /cancel para cancelar).",
            parse_mode="HTML",
        )
        return LOGIN_PASSWORD

    context.user_data.clear()
    success_text = (
        "🎉 <b>¡CONEXIÓN EXITOSA!</b>\n"
        f"{LINE_DOUBLE}\n"
        f"👤 <b>Usuario:</b> <code>{safe_escape(username)}</code>\n"
        f"🏫 <b>Facultad:</b> <b>{safe_escape(instance.name)}</b>\n"
        f"🟢 <b>Estado:</b> <code>Conectado y listo</code>\n"
        f"{LINE_DOUBLE}\n\n"
        "🚀 Ya puedes consultar tus cursos, tareas y recibir alertas automáticas.\n"
        "Usa los botones del menú o explora con los accesos rápidos:"
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
    await update.message.reply_text(
        "✨ <i>Menú interactivo activado.</i>",
        parse_mode="HTML",
        reply_markup=menu_keyboard(True),
    )
    return ConversationHandler.END


def get_login_handler() -> ConversationHandler:
    """Retorna el ConversationHandler configurado para /login."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("login", login_start),
            CallbackQueryHandler(login_start, pattern=r"^prompt_login$"),
        ],
        states={
            LOGIN_INSTANCE: [CallbackQueryHandler(login_instance_selected, pattern=r"^inst:")],
            LOGIN_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_username),
                CallbackQueryHandler(login_change_faculty, pattern=r"^login_change_faculty$"),
            ],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True,
    )
