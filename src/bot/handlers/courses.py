"""Manejadores de comandos relacionados con cursos y cuenta:
/cursos, /tareas, /notificaciones, /cuenta, /logout y callback de desconexión.
"""

import logging
from html import escape, unescape

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.ext import ContextTypes

from src.services.accounts import (
    account_status,
    get_client_for,
    logout_user,
)
from src.moodle.api import _clean_event_name
from src.bot.keyboards import menu_keyboard
from src.bot.ui import (
    LINE_DOUBLE,
    LINE_LIGHT,
    account_keyboard,
    courses_keyboard,
    format_description,
    format_urgency,
    login_prompt_keyboard,
    notifications_keyboard,
    safe_escape,
    tasks_keyboard,
)

logger = logging.getLogger(__name__)


async def _send_or_edit(
    update: Update,
    text: str,
    reply_markup: InlineKeyboardMarkup = None,
    status_msg=None,
) -> None:
    """Envía un mensaje nuevo o edita el mensaje existente según el contexto."""
    query = update.callback_query
    link_opts = LinkPreviewOptions(is_disabled=True)

    if query:
        try:
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                link_preview_options=link_opts,
            )
        except Exception as exc:
            if "Message is not modified" not in str(exc):
                await query.message.reply_text(
                    text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    link_preview_options=link_opts,
                )
    elif status_msg:
        try:
            await status_msg.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                link_preview_options=link_opts,
            )
        except Exception:
            await update.message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                link_preview_options=link_opts,
            )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            link_preview_options=link_opts,
        )


async def _require_client(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status_msg=None,
):
    """Helper: devuelve el cliente del usuario o envía aviso estructurado de login."""
    chat_id = update.effective_chat.id
    client = get_client_for(chat_id)
    if client is None:
        text = (
            "🔐 <b>ACCESO NO AUTORIZADO</b>\n"
            f"{LINE_DOUBLE}\n"
            "Aún no has conectado tu cuenta institucional de Moodle.\n\n"
            "Conecta tu cuenta para acceder a tus materias, consultar entregas pendientes y recibir alertas automáticas.\n\n"
            "👉 Presiona el botón inferior o envía <b>/login</b> para comenzar."
        )
        markup = login_prompt_keyboard()
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text, parse_mode="HTML", reply_markup=markup
                )
            except Exception:
                await update.callback_query.message.reply_text(
                    text, parse_mode="HTML", reply_markup=markup
                )
        elif status_msg:
            try:
                await status_msg.edit_text(
                    text, parse_mode="HTML", reply_markup=markup
                )
            except Exception:
                await update.message.reply_text(
                    text, parse_mode="HTML", reply_markup=markup
                )
        else:
            await update.message.reply_text(
                text, parse_mode="HTML", reply_markup=markup
            )
        return None
    return client


async def cursos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    status_msg = None
    if query:
        await query.answer("Consultando materias...")
    else:
        status_msg = await update.message.reply_text(
            "🔄 <i>Consultando tus materias inscritas en Moodle...</i>",
            parse_mode="HTML",
        )

    client = await _require_client(update, context, status_msg=status_msg)
    if client is None:
        return

    try:
        course_list = client.get_courses()
    except Exception:
        logger.exception("Error obteniendo cursos")
        err_text = (
            "❌ <b>Error al consultar materias</b>\n"
            f"{LINE_DOUBLE}\n"
            "Ocurrió un inconveniente al consultar tus materias en el campus virtual.\n"
            "Por favor intenta de nuevo en unos momentos."
        )
        await _send_or_edit(
            update, err_text, reply_markup=courses_keyboard(), status_msg=status_msg
        )
        return

    if not course_list:
        empty_text = (
            "⚠️ <b>Sin materias encontradas</b>\n"
            f"{LINE_DOUBLE}\n"
            "No encontré cursos inscritos activos en tu cuenta.\n\n"
            "💡 <i>¿Estás matriculado en este período? Verifica si tu docente ya activó el aula o revisa tu facultad con /cuenta.</i>"
        )
        await _send_or_edit(
            update, empty_text, reply_markup=courses_keyboard(), status_msg=status_msg
        )
        return

    header = (
        "📚 <b>TUS MATERIAS MATRICULADAS</b>\n"
        f"{LINE_DOUBLE}\n"
        f"🎓 <b>Total matriculadas:</b> <code>{len(course_list)} materias</code>\n"
        f"{LINE_DOUBLE}\n"
    )

    cards = []
    for i, c in enumerate(course_list, 1):
        c_name = safe_escape(c.get("name", "Materia sin nombre"))
        c_url = c.get("url", "")
        c_id = c.get("id")
        id_part = f"   🆔 <b>Código:</b> <code>{c_id}</code>\n" if c_id else ""
        link_part = f"   🔗 <a href='{c_url}'><b>Entrar al aula virtual ➔</b></a>" if c_url else ""
        cards.append(f"📘 <b>{i:02d}. {c_name}</b>\n{id_part}{link_part}")

    courses_body = f"\n{LINE_LIGHT}\n".join(cards)
    footer = (
        f"\n{LINE_DOUBLE}\n"
        "💡 <i>Toca en «Entrar al aula virtual» para acceder directamente a los recursos de cada materia.</i>"
    )
    full_text = header + courses_body + footer

    await _send_or_edit(
        update, full_text, reply_markup=courses_keyboard(), status_msg=status_msg
    )


async def tareas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    status_msg = None
    if query:
        await query.answer("Revisando actividades...")
    else:
        status_msg = await update.message.reply_text(
            "🔄 <i>Revisando tus próximas actividades y entregas...</i>",
            parse_mode="HTML",
        )

    client = await _require_client(update, context, status_msg=status_msg)
    if client is None:
        return

    try:
        events = client.get_upcoming_events(days_ahead=30)
    except Exception:
        logger.exception("Error obteniendo actividades")
        err_text = (
            "❌ <b>Error al consultar actividades</b>\n"
            f"{LINE_DOUBLE}\n"
            "No pude conectar con el aula virtual en este momento.\n"
            "Por favor intenta de nuevo más tarde."
        )
        await _send_or_edit(
            update, err_text, reply_markup=tasks_keyboard(), status_msg=status_msg
        )
        return


    if not events:
        empty_text = (
            "🎉 <b>¡TODO AL DÍA!</b>\n"
            f"{LINE_DOUBLE}\n"
            "✅ No tienes actividades ni entregas pendientes en los próximos <b>30 días</b>.\n\n"
            "🌟 <i>¡Excelente trabajo manteniendo tus materias al día! Descansa o aprovecha para repasar tus apuntes.</i>"
        )
        await _send_or_edit(
            update, empty_text, reply_markup=tasks_keyboard(), status_msg=status_msg
        )
        return

    header = (
        "📅 <b>CALENDARIO DE ENTREGAS Y ACTIVIDADES</b>\n"
        f"{LINE_DOUBLE}\n"
        f"📌 <b>Pendientes en agenda:</b> <code>{len(events)} actividad(es)</code> (30 días)\n"
        f"{LINE_DOUBLE}\n"
    )

    max_display = 10
    display_events = events[:max_display]

    cards = []
    for e in display_events:
        badge, time_str, icon = format_urgency(e["timestart"])
        clean_name = safe_escape(_clean_event_name(e.get("name", "")))
        course_name = safe_escape(e.get("course_name", "Sin materia"))
        formatted_time = safe_escape(e.get("formatted_time", ""))

        card_lines = [
            f"{icon} <b>{clean_name}</b>",
            f"  📚 <i>{course_name}</i>",
            f"  ⏰ <code>{formatted_time}</code> ({time_str})",
            f"  {badge}",
        ]

        desc = format_description(e.get("description", ""))
        if desc:
            card_lines.append(f"   📝 <b>Detalle:</b>\n   <blockquote><i>{desc}</i></blockquote>")

        if e.get("url"):
            card_lines.append(f"   🔗 <a href='{e['url']}'><b>Ir a la entrega en Moodle ➔</b></a>")

        cards.append("\n".join(card_lines))

    task_body = f"\n{LINE_LIGHT}\n".join(cards)

    footer_notes = []
    if len(events) > max_display:
        footer_notes.append(
            f"⚠️ <i>... y {len(events) - max_display} actividades más visibles en tu calendario de Moodle.</i>"
        )
    footer_notes.append(
        "💡 <i>Consejo: Realiza tus entregas con anticipación para evitar saturación de red o de la plataforma.</i>"
    )

    footer = f"\n{LINE_DOUBLE}\n" + "\n".join(footer_notes)
    full_text = header + task_body + footer

    await _send_or_edit(
        update, full_text, reply_markup=tasks_keyboard(), status_msg=status_msg
    )


async def notificaciones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    status_msg = None
    if query:
        await query.answer("Consultando novedades...")
    else:
        status_msg = await update.message.reply_text(
            "🔄 <i>Consultando el resumen de novedades y vencimientos...</i>",
            parse_mode="HTML",
        )

    client = await _require_client(update, context, status_msg=status_msg)
    if client is None:
        return

    try:
        summary = client.get_notifications_summary()
    except Exception:
        logger.exception("Error obteniendo notificaciones")
        err_text = (
            "❌ <b>Error al consultar novedades</b>\n"
            f"{LINE_DOUBLE}\n"
            "No pude obtener el resumen de novedades en este momento.\n"
            "Por favor intenta de nuevo más tarde."
        )
        await _send_or_edit(
            update, err_text, reply_markup=notifications_keyboard(), status_msg=status_msg
        )
        return


    events = summary.get("upcoming_events", [])
    activity = summary.get("recent_activity", [])

    lines = [
        "🔔 <b>CENTRO DE NOVEDADES Y RECORDATORIOS</b>",
        LINE_DOUBLE,
    ]

    if events:
        lines.append(f"📅 <b>PRÓXIMOS VENCIMIENTOS ({len(events)})</b>")
        lines.append(LINE_LIGHT)
        for e in events[:6]:
            clean_name = safe_escape(_clean_event_name(e.get("name", "")))
            course_name = safe_escape(e.get("course_name", "Materia"))
            badge, time_str, icon = format_urgency(e["timestart"])
            lines.append(f"{icon} <b>{clean_name}</b>")
            lines.append(f"  📚 <i>{course_name}</i>")
            lines.append(f"  ⏰ <code>{e.get('formatted_time', '')}</code> ({time_str})")
            if e.get("url"):
                lines.append(f"   🔗 <a href='{e['url']}'>Ver entrega en Moodle ➔</a>")
            lines.append("")
        if len(events) > 6:
            lines.append(f"   <i>... y {len(events) - 6} vencimientos más</i>\n")

    if activity:
        if events:
            lines.append(LINE_DOUBLE)
        lines.append(f"📄 <b>ACTIVIDAD RECIENTE EN CURSOS (Últimos 7 días) ({len(activity)})</b>")
        lines.append(LINE_LIGHT)
        for a in activity[:6]:
            clean_name = safe_escape(_clean_event_name(a.get("name", "")))
            modname = safe_escape(a.get("modname", "").replace("mod_", ""))
            lines.append(f"📑 <b>{clean_name}</b> <code>[{modname}]</code>")
            lines.append(f"   🕐 <code>Publicado: {a.get('formatted_time', '')}</code>")
            if a.get("url"):
                lines.append(f"   🔗 <a href='{a['url']}'>Ver recurso en Moodle ➔</a>")
            lines.append("")
        if len(activity) > 6:
            lines.append(f"   <i>... y {len(activity) - 6} novedades más</i>\n")

    if not events and not activity:
        lines.append(
            "✨ <b>Todo despejado:</b> No tienes entregas pendientes ni nuevo material publicado en los últimos días.\n"
            "¡Tu semestre está completamente al día! 🎉"
        )
    else:
        lines.append(LINE_DOUBLE)
        lines.append("💡 <i>Usa los botones inferiores para ir directo a tus tareas o materias.</i>")

    full_text = "\n".join(lines)
    await _send_or_edit(
        update, full_text, reply_markup=notifications_keyboard(), status_msg=status_msg
    )


async def cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()

    chat_id = update.effective_chat.id
    info = account_status(chat_id)
    if info is None:
        text = (
            "🔐 <b>ACCESO RESTRINGIDO</b>\n"
            f"{LINE_DOUBLE}\n"
            "Aún no has conectado tu cuenta institucional de Moodle.\n\n"
            "👉 Usa <b>/login</b> o pulsa el botón inferior para comenzar."
        )
        await _send_or_edit(update, text, reply_markup=login_prompt_keyboard())
        return

    cursos_count = "—"
    client = get_client_for(chat_id)
    if client is not None:
        try:
            cursos_count = f"{len(client.get_courses())} asignaturas"
        except Exception:
            cursos_count = "No disponible"

    text = (
        "👤 <b>MI CUENTA AKUMAJA</b>\n"
        f"{LINE_DOUBLE}\n"
        f"🔹 <b>Usuario:</b> <code>{info['username']}</code>\n"
        f"🏛️ <b>Facultad:</b> <b>{info['instance_name']}</b>\n"
        f"🌐 <b>Servidor:</b> <code>{info['instance_base_url']}</code>\n"
        f"📚 <b>Materias activas:</b> <b>{cursos_count}</b>\n"
        f"🟢 <b>Estado del bot:</b> <code>Conectado y monitoreando</code>\n"
        f"🔄 <b>Última comprobación:</b> <code>{info['last_sync_at'] or 'Aún no'}</code>\n"
        f"{LINE_DOUBLE}\n"
        "🛡️ <i>Tus credenciales están protegidas localmente mediante cifrado AES-256.</i>\n\n"
        "⚙️ <i>Gestiona tu sesión o consulta tus materias con los botones inferiores:</i>"
    )
    await _send_or_edit(update, text, reply_markup=account_keyboard())


async def cuenta_logout_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Botón 'Desconectar' dentro de /cuenta."""
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    logout_user(chat_id)
    text = (
        "👋 <b>SESIÓN FINALIZADA</b>\n"
        f"{LINE_DOUBLE}\n"
        "Tu sesión se cerró exitosamente.\n"
        "Tus credenciales y datos fueron eliminados del bot de manera segura.\n\n"
        "Si deseas volver a conectarte, pulsa el botón inferior o escribe <b>/login</b>."
    )
    try:
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=login_prompt_keyboard(),
        )
    except Exception:
        await query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=login_prompt_keyboard(),
        )
    await query.message.reply_text(
        "¿Deseas conectar otra cuenta? Usa /login o presiona el botón del menú.",
        reply_markup=menu_keyboard(False),
    )


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logout_user(chat_id)
    text = (
        "👋 <b>SESIÓN FINALIZADA</b>\n"
        f"{LINE_DOUBLE}\n"
        "Has cerrado sesión exitosamente.\n"
        "Tus credenciales y datos fueron eliminados del bot de manera segura.\n\n"
        "Si deseas volver a conectarte, escribe <b>/login</b> o pulsa el botón del menú inferior."
    )
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=menu_keyboard(False),
    )
