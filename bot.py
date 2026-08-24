import os
import logging
from datetime import datetime

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from accounts import (
    LoginError,
    TooManyAttempts,
    account_status,
    apply_faculty_change,
    get_client_for,
    logout_user,
    normalize_username,
    perform_login,
    run_legacy_migration,
    validate_login,
)
from moodle_instances import registry
from monitor import collect_notifications_for_users, legacy_check

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Configuración de monitoreo
MONITOR_START_HOUR = 6
MONITOR_END_HOUR = 24
MONITOR_INTERVAL_MINUTES = 180

# Estados del flujo de login
LOGIN_INSTANCE, LOGIN_USERNAME, LOGIN_PASSWORD = range(3)

# Estados del flujo de cambiar facultad
CF_INSTANCE, CF_CONFIRM, CF_USERNAME, CF_PASSWORD = range(10, 14)


def _instances_keyboard():
    buttons = [
        [InlineKeyboardButton(instance.name, callback_data=f"inst:{instance_id}")]
        for instance_id, instance in registry.all()
    ]
    return InlineKeyboardMarkup(buttons)


def _menu_keyboard(logged_in):
    """Barra de botones persistente, adaptada al estado de login."""
    if logged_in:
        rows = [
            ["/start", "/ayuda"],
            ["/cursos", "/tareas"],
            ["/notificaciones", "/cuenta"],
            ["/cambiar_facultad", "/logout"],
        ]
    else:
        rows = [
            ["/start", "/login", "/ayuda"],
        ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ---------------------------------------------------------------------------
# Comandos generales
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    logged_in = info is not None

    if logged_in:
        header = (
            "🎓 <b>¡Bienvenido a Akumaja Bot!</b>\n\n"
            f"👤 <b>Conectado:</b> <code>{info['username']}</code>\n"
            f"🏫 <b>Facultad:</b> {info['instance_name']}\n"
            f"🌐 <b>Servidor:</b> <code>{info['instance_base_url']}</code>\n"
            f"🔄 <b>Última sync:</b> {info['last_sync_at'] or 'Nunca'}\n"
        )
    else:
        header = (
            "🎓 <b>¡Bienvenido a Akumaja Bot!</b>\n\n"
            "🔐 <b>No tienes cuenta conectada.</b>\n"
            "Pulsa <b>/login</b> para empezar.\n"
        )

    body = (
        "\n📋 <b>Comandos principales</b>\n"
        "├─ /cursos — Lista tus cursos\n"
        "├─ /tareas — Entregas próximas (30 días)\n"
        "├─ /notificaciones — Resumen completo\n"
        "├─ /cuenta — Tu info y botones\n"
        "├─ /cambiar_facultad — Cambia de facultad\n"
        "├─ /logout — Desconectar\n"
        "└─ /estado — Info del bot\n"
        "\n💡 <b>Monitoreo automático:</b> cada 3 h (6:00–23:59)\n"
        "   Entregas próximas · Vencidas · Contenido nuevo"
    )

    await update.message.reply_text(
        header + body,
        parse_mode="HTML",
        reply_markup=_menu_keyboard(logged_in),
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logged_in = account_status(chat_id) is not None

    await update.message.reply_text(
        "🤖 <b>Bot de Akumaja</b>\n\n"
        "<b>Primera vez:</b> envía /login, elige tu facultad, "
        "y escribe tu usuario y contraseña de Moodle.\n\n"
        "<b>Comandos:</b>\n"
        "/login - Conectar tu cuenta Moodle\n"
        "/cursos - Lista tus cursos inscritos\n"
        "/tareas - Actividades y entregas próximas (30 días)\n"
        "/notificaciones - Resumen de vencimientos y actividad reciente\n"
        "/cuenta - Ver qué cuenta tienes conectada\n"
        "/cambiar_facultad - Cambiar de facultad sin desconectarte\n"
        "/logout - Desconectar tu cuenta (elimina tus datos del bot)\n"
        "/estado - Información del bot\n"
        "/cancel - Cancelar un proceso de login en curso\n\n"
        "💡 <b>Notificaciones automáticas:</b> el bot te avisa "
        "cada 3 horas (6:00 - 23:59) sobre entregas próximas, "
        "vencimientos y contenido nuevo de tus cursos.",
        parse_mode="HTML",
        reply_markup=_menu_keyboard(logged_in),
    )


async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.list_active_users()
    end_display = f"{MONITOR_END_HOUR - 1}:59" if MONITOR_END_HOUR == 24 else f"{MONITOR_END_HOUR}:59"
    lines = [
        "🤖 <b>Estado del bot</b>",
        "",
        f"👥 Usuarios conectados: <b>{len(users)}</b>",
        f"🌐 Instancias Moodle: <b>{len(registry.all())}</b>",
        "",
        f"⏰ Monitoreo: cada {MONITOR_INTERVAL_MINUTES} min "
        f"({MONITOR_START_HOUR}:00 - {end_display})",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("❌ Proceso cancelado.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Comandos que requieren cuenta
# ---------------------------------------------------------------------------

async def _require_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper: devuelve el cliente del usuario o envía aviso de login."""
    chat_id = update.effective_chat.id
    client = get_client_for(chat_id)
    if client is None:
        await update.message.reply_text(
            "🔐 Aún no tienes una cuenta conectada.\n"
            "Envía /login para conectar tu cuenta de Moodle."
        )
        return None
    return client


async def cursos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Obteniendo tus cursos...")

    client = await _require_client(update, context)
    if client is None:
        return

    try:
        courses = client.get_courses()
    except Exception as exc:
        logger.exception("Error obteniendo cursos")
        await update.message.reply_text(
            "❌ Ocurrió un error al obtener tus cursos. "
            "Intenta de nuevo en unos minutos."
        )
        return
    finally:
        client.logout()

    if not courses:
        await update.message.reply_text("⚠️ No se encontraron cursos inscritos.")
        return

    lines = [f"📚 <b>Tus cursos ({len(courses)})</b>:", ""]
    for i, course in enumerate(courses, 1):
        lines.append(f"{i}. <b>{course['name']}</b>")
        lines.append(f"   🆔 ID: <code>{course['id']}</code>")
        lines.append(f"   🔗 <a href='{course['url']}'>Abrir en Moodle</a>")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def tareas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Consultando actividades próximas...")

    client = await _require_client(update, context)
    if client is None:
        return

    try:
        events = client.get_upcoming_events(days_ahead=30)
    except Exception as exc:
        logger.exception("Error obteniendo actividades")
        await update.message.reply_text(
            "❌ Ocurrió un error al obtener tus actividades. "
            "Intenta de nuevo en unos minutos."
        )
        return
    finally:
        client.logout()

    if not events:
        await update.message.reply_text("✅ No hay actividades próximas en los próximos 30 días.")
        return

    def _fmt_desc(desc: str, limit: int = 350) -> str:
        """Trunca descripción si es muy larga, limpia HTML crudo."""
        if not desc:
            return ""
        # quita tags HTML crudos que vengan de Moodle
        from html import unescape
        import re
        text = re.sub(r"<[^>]+>", "", unescape(desc))
        text = text.strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0] + "…"

    lines = [f"📅 <b>Próximas actividades ({len(events)})</b>:", ""]
    for e in events:
        lines.append(f"📌 <b>{e['name']}</b>")
        lines.append(f"   📚 Curso: {e['course_name']}")
        lines.append(f"   ⏰ Vence: {e['formatted_time']}")
        desc = _fmt_desc(e.get("description", ""))
        if desc:
            lines.append(f"   📝 <i>{desc}</i>")
        if e['url']:
            lines.append(f"   🔗 <a href='{e['url']}'>Ver en Moodle</a>")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def notificaciones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Obteniendo resumen de notificaciones...")

    client = await _require_client(update, context)
    if client is None:
        return

    try:
        summary = client.get_notifications_summary()
    except Exception as exc:
        logger.exception("Error obteniendo notificaciones")
        await update.message.reply_text(
            "❌ Ocurrió un error al obtener tus notificaciones. "
            "Intenta de nuevo en unos minutos."
        )
        return
    finally:
        client.logout()

    events = summary["upcoming_events"]
    activity = summary["recent_activity"]

    lines = ["🔔 <b>Resumen de Notificaciones</b>", ""]

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
        lines.append("✅ No hay notificaciones pendientes ni actividad reciente.")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is None:
        await update.message.reply_text(
            "🔐 No tienes una cuenta conectada.\nEnvía /login para conectar tu cuenta."
        )
        return

    # Conteo de cursos (best-effort: si Moodle no responde no bloquea /cuenta)
    cursos_count = "—"
    client = get_client_for(chat_id)
    if client is not None:
        try:
            cursos_count = len(client.get_courses())
        except Exception:
            cursos_count = "No disponible"
        finally:
            client.logout()

    text = (
        "👤 <b>Tu cuenta conectada</b>\n\n"
        f"Usuario: <code>{info['username']}</code>\n"
        f"Facultad: <b>{info['instance_name']}</b>\n"
        f"Servidor: <code>{info['instance_base_url']}</code>\n"
        f"Cursos: <b>{cursos_count}</b>\n"
        f"Estado: 🟢 Conectada\n"
        f"Última sincronización: {info['last_sync_at'] or 'Nunca'}"
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
        "👋 Cuenta desconectada. Tus datos fueron eliminados del bot."
    )
    await query.message.reply_text(
        "Si quieres conectar otra cuenta, envía /login o pulsa el botón.",
        reply_markup=_menu_keyboard(False),
    )


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logout_user(chat_id)
    await update.message.reply_text(
        "👋 Cuenta desconectada. Tus datos fueron eliminados del bot.\n"
        "Si quieres volver a conectar otra cuenta, envía /login.",
        reply_markup=_menu_keyboard(False),
    )


# ---------------------------------------------------------------------------
# Flujo de login (ConversationHandler)
# ---------------------------------------------------------------------------

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is not None:
        await update.message.reply_text(
            "🔐 Ya tienes una cuenta conectada:\n"
            f"   Usuario: <code>{info['username']}</code>\n"
            f"   Facultad: <b>{info['instance_name']}</b>\n\n"
            "Para cambiar de facultad usa /cambiar_facultad.\n"
            "Para desconectarte usa /logout.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🏛️ <b>¿A qué facultad perteneces?</b>\n\n"
        "Elige tu facultad para conectarte a tu instancia Moodle:",
        parse_mode="HTML",
        reply_markup=_instances_keyboard(),
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
        "✅ Facultad seleccionada:\n\n"
        f"🏫 <b>{instance.name}</b>\n"
        f"🌐 <code>{instance.base_url}</code>\n\n"
        "👤 Escribe tu <b>usuario de Akumaja</b>.\n\n"
        "Es el mismo usuario de tu correo institucional, "
        "es decir, la parte que aparece antes de:\n"
        "<code>@uniguajira.edu.co</code>\n\n"
        "Ejemplo:\n"
        "Correo: <code>nombre.apellido@uniguajira.edu.co</code>\n"
        "Usuario: <code>nombre.apellido</code>\n\n"
        "No necesitas escribir <code>@uniguajira.edu.co</code>.",
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
        "🏛️ <b>¿A qué facultad perteneces?</b>\n\n"
        "Elige tu facultad para conectarte a tu instancia Moodle:",
        parse_mode="HTML",
        reply_markup=_instances_keyboard(),
    )
    return LOGIN_INSTANCE


async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text
    username = normalize_username(raw)
    if not username or len(username) > 100:
        await update.message.reply_text("⚠️ Escribe un usuario válido.")
        return LOGIN_USERNAME

    context.user_data["login_username"] = username
    if username != raw.strip():
        await update.message.reply_text(
            f"✅ Usaré el usuario: <code>{username}</code>\n\n"
            "🔑 Ahora escribe tu <b>contraseña de Moodle</b>.\n"
            "⚠️ <i>Se eliminará este mensaje del chat al terminar.</i>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "🔑 Ahora escribe tu <b>contraseña de Moodle</b>.\n"
            "⚠️ <i>Se eliminará este mensaje del chat al terminar.</i>",
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
        await update.message.reply_text("⚠️ Escribe una contraseña válida.")
        return LOGIN_PASSWORD

    instance_id = context.user_data.get("login_instance_id")
    username = context.user_data.get("login_username")
    if not instance_id or not username:
        await update.message.reply_text("❌ El flujo expiró. Envía /login de nuevo.")
        return ConversationHandler.END

    try:
        instance = perform_login(chat_id, instance_id, username, password)
    except TooManyAttempts:
        await update.message.reply_text(
            "🚫 Demasiados intentos fallidos. Espera unos minutos y envía /login."
        )
        return ConversationHandler.END
    except LoginError:
        await update.message.reply_text(
            "❌ No se pudo iniciar sesión en Akumaja.\n"
            "Revisa tu usuario y contraseña e intenta de nuevo "
            "(o escribe /cancel para salir)."
        )
        return LOGIN_PASSWORD

    context.user_data.clear()
    await update.message.reply_text(
        f"✅ <b>¡Cuenta conectada!</b>\n\n"
        f"Usuario: <code>{username}</code>\n"
        f"Facultad: <b>{instance.name}</b>\n\n"
        "Ahora puedes usar:\n"
        "/cursos - ver tus cursos\n"
        "/tareas - actividades próximas\n"
        "/notificaciones - resumen de notificaciones",
        parse_mode="HTML",
        reply_markup=_menu_keyboard(True),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Flujo de cambiar facultad (ConversationHandler)
# ---------------------------------------------------------------------------

def _build_faculty_selection(current_instance_id=None):
    """Devuelve los botones del listado de facultades (marca la actual)."""
    buttons = []
    for instance_id, instance in registry.all():
        label = instance.name
        if instance_id == current_instance_id:
            label = f"✅ {label} (actual)"
        buttons.append(
            [InlineKeyboardButton(label, callback_data=f"cf_inst:{instance_id}")]
        )
    buttons.append([InlineKeyboardButton("❌ Cancelar", callback_data="cf_cancel")])
    return buttons


async def change_facultad_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is None:
        msg = (
            "🔐 No tienes una cuenta conectada.\n"
            "Envía /login para conectar tu cuenta primero."
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END

    text = (
        "🏫 Tu facultad actual:\n"
        f"<b>{info['instance_name']}</b>\n\n"
        "Selecciona la nueva facultad o dependencia:"
    )
    markup = InlineKeyboardMarkup(_build_faculty_selection(info["instance_id"]))

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
    """Selección de facultad: muestra confirmación (Mejora 5)."""
    query = update.callback_query
    await query.answer()

    instance_id = query.data.split(":", 1)[1]
    instance = registry.get(instance_id)
    if instance is None:
        await query.edit_message_text("❌ Instancia desconocida. Intenta de nuevo.")
        return ConversationHandler.END

    context.user_data["cf_instance_id"] = instance_id
    await query.edit_message_text(
        "Has seleccionado:\n\n"
        f"🏫 <b>{instance.name}</b>\n"
        f"🌐 <code>{instance.base_url}</code>\n\n"
        "¿Quieres intentar conectar tu cuenta en esta instancia?",
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
        await query.edit_message_text("👍 De acuerdo. Tu cuenta no cambió.")
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
        "👤 Escribe tu <b>usuario de Akumaja</b>.\n\n"
        "Es el mismo usuario de tu correo institucional, "
        "la parte antes de <code>@uniguajira.edu.co</code>.\n"
        "Ejemplo: <code>nombre.apellido</code>",
        parse_mode="HTML",
    )
    return CF_USERNAME


async def cf_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text
    username = normalize_username(raw)
    if not username or len(username) > 100:
        await update.message.reply_text("⚠️ Escribe un usuario válido.")
        return CF_USERNAME

    context.user_data["cf_username"] = username
    if username != raw.strip():
        await update.message.reply_text(
            f"✅ Usaré el usuario: <code>{username}</code>\n\n"
            "🔑 Ahora escribe tu <b>contraseña de Moodle</b>.\n"
            "⚠️ <i>Se eliminará este mensaje del chat al terminar.</i>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "🔑 Ahora escribe tu <b>contraseña de Moodle</b>.\n"
            "⚠️ <i>Se eliminará este mensaje del chat al terminar.</i>",
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
        await update.message.reply_text("⚠️ Escribe una contraseña válida.")
        return CF_PASSWORD

    instance_id = context.user_data.get("cf_instance_id")
    username = context.user_data.get("cf_username")
    if not instance_id or not username:
        await update.message.reply_text(
            "❌ El flujo expiró. Envía /cambiar_facultad de nuevo."
        )
        return ConversationHandler.END

    instance = registry.get(instance_id)
    try:
        # Validación contra la NUEVA instancia: no toca la cuenta actual
        _, course_count = validate_login(chat_id, instance_id, username, password)
    except TooManyAttempts:
        await update.message.reply_text(
            "🚫 Demasiados intentos fallidos. Espera unos minutos y envía /cambiar_facultad."
        )
        return ConversationHandler.END
    except LoginError:
        await update.message.reply_text(
            f"❌ No se pudo iniciar sesión en {instance.name}.\n"
            "Tu cuenta actual <b>NO se modificó</b>.\n"
            "Revisa tu usuario y contraseña e intenta de nuevo "
            "(o escribe /cancel para salir).",
            parse_mode="HTML",
        )
        return CF_PASSWORD

    # Solo aquí, tras autenticación exitosa, se aplica el cambio
    apply_faculty_change(chat_id, instance_id, username, password)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ <b>Facultad cambiada con éxito.</b>\n\n"
        f"🏫 {instance.name}\n"
        f"🌐 <code>{instance.base_url}</code>\n"
        f"Cursos detectados: <b>{course_count}</b>\n\n"
        "Tus notificaciones comenzarán a monitorearse en la nueva instancia.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Monitoreo automático
# ---------------------------------------------------------------------------

async def monitor_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job que se ejecuta cada 3 horas para verificar notificaciones nuevas"""
    now = datetime.now()
    current_hour = now.hour

    # Solo ejecutar entre 6:00 y 23:59
    if current_hour < MONITOR_START_HOUR or current_hour >= MONITOR_END_HOUR:
        return

    if db.count_users() > 0:
        await collect_notifications_for_users(context.bot)
    else:
        # Modo legacy: cuenta única de .env
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not chat_id:
            logger.warning("TELEGRAM_CHAT_ID no configurado, saltando monitoreo")
            return
        await legacy_check(context.bot, chat_id)


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------

def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "No se encontró TELEGRAM_BOT_TOKEN en .env"
        )

    db.init_db()
    run_legacy_migration()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("estado", estado))
    app.add_handler(CommandHandler("cursos", cursos))
    app.add_handler(CommandHandler("tareas", tareas))
    app.add_handler(CommandHandler("notificaciones", notificaciones))
    app.add_handler(CommandHandler("cuenta", cuenta))
    app.add_handler(CommandHandler("logout", logout))

    # Flujo /cambiar_facultad (también se entra desde el botón de /cuenta)
    change_faculty_conv = ConversationHandler(
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
    app.add_handler(change_faculty_conv)

    # Botón "Desconectar" de /cuenta
    app.add_handler(CallbackQueryHandler(cuenta_logout_cb, pattern=r"^cuenta_logout$"))

    # Flujo /login
    login_conv = ConversationHandler(
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
    app.add_handler(login_conv)

    # Job de monitoreo automático cada 30 minutos
    job_queue = app.job_queue
    job_queue.run_repeating(
        monitor_job,
        interval=MONITOR_INTERVAL_MINUTES * 60,  # en segundos
        first=10,  # primera ejecución a los 10 segundos
        name="monitor_notifications",
    )

    print("🤖 Bot iniciado. Esperando mensajes...")
    print(f"📅 Monitoreo automático: {MONITOR_START_HOUR}:00 - {MONITOR_END_HOUR - 1}:59 cada {MONITOR_INTERVAL_MINUTES} min")

    app.run_polling()


if __name__ == "__main__":
    main()