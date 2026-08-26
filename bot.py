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
        reply_markup=_menu_keyboard(logged_in),
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
        reply_markup=_menu_keyboard(logged_in),
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
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("❌ Dale, cancelado. No pasa nada.")
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
    except Exception as exc:
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
    except Exception as exc:
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

    from datetime import datetime as _dt

    def _fmt_desc(desc: str, limit: int = 350) -> str:
        if not desc:
            return ""
        from html import unescape
        import re
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
    except Exception as exc:
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
        reply_markup=_menu_keyboard(False),
    )


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logout_user(chat_id)
    await update.message.reply_text(
        "👋 Dale, ya te desconecté y borré tus datos.\n"
        "Si quieres volver, manda /login.",
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
        reply_markup=_instances_keyboard(),
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