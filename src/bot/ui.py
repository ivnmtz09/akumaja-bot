"""Elementos visuales, separadores y formateadores de interfaz para Telegram.

Proporciona constantes de diseño (líneas dobles, separadores ligeros),
badges de urgencia, limpieza de textos y teclados inline interactivos
para que todos los mensajes tengan un diseño profesional, estructurado
y con excelente jerarquía visual.
"""

from datetime import datetime as _dt
from html import escape, unescape
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Líneas separadoras Unicode de alta compatibilidad visual
LINE_DOUBLE = "═══════════════════════════════════"
LINE_LIGHT = "───────────────────────────────────"
LINE_HEAVY = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def safe_escape(text: str) -> str:
    """Escapa caracteres HTML reservados (&, <, >) para Telegram."""
    if text is None:
        return ""
    return escape(str(text), quote=False)


def format_description(desc: str, limit: int = 220) -> str:
    """Limpia etiquetas HTML, normaliza espacios y trunca descripciones de tareas."""
    if not desc:
        return ""
    # Quitar etiquetas HTML previas que puedan venir de Moodle
    text = re.sub(r"<[^>]+>", " ", unescape(desc))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return safe_escape(text)


def format_urgency(timestart: float):
    """Calcula el estado de urgencia de una actividad según el tiempo restante.

    Retorna: (badge_html, tiempo_str, icono_status)
    """
    now = _dt.now().timestamp()
    diff_sec = timestart - now
    hours_left = diff_sec / 3600

    if hours_left < 0:
        hours_ago = abs(int(hours_left))
        badge = "🚨 <b>¡PLAZO VENCIDO!</b>"
        time_str = f"Venció hace {hours_ago}h"
        icon = "❌"
    elif hours_left < 6:
        h = int(hours_left)
        m = int((diff_sec % 3600) / 60)
        badge = "🔴 <b>¡URGENTE — VENCE HOY!</b>"
        time_str = f"Quedan {h}h {m}m"
        icon = "🔥"
    elif hours_left < 24:
        h = int(hours_left)
        badge = "🟡 <b>ATENCIÓN — MENOS DE 24H</b>"
        time_str = f"Quedan {h} horas"
        icon = "⏰"
    elif hours_left < 72:
        days = int(hours_left // 24)
        rem_h = int(hours_left % 24)
        badge = "🟠 <b>PRÓXIMO — EN 3 DÍAS</b>"
        time_str = f"Quedan {days}d {rem_h}h"
        icon = "⏳"
    else:
        days = int(hours_left // 24)
        badge = "🟢 <b>PROGRAMADA CON TIEMPO</b>"
        time_str = f"Faltan {days} días"
        icon = "📅"

    return badge, time_str, icon


def courses_keyboard():
    """Botones interactivos bajo el listado de materias."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Ver Tareas", callback_data="view_tareas"),
            InlineKeyboardButton("🔔 Novedades", callback_data="view_notif"),
        ],
        [
            InlineKeyboardButton("🔄 Actualizar", callback_data="view_cursos"),
            InlineKeyboardButton("👤 Mi Cuenta", callback_data="view_cuenta"),
        ],
    ])


def tasks_keyboard():
    """Botones interactivos bajo el listado de tareas."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Actualizar Tareas", callback_data="view_tareas"),
            InlineKeyboardButton("📚 Mis Materias", callback_data="view_cursos"),
        ],
        [
            InlineKeyboardButton("🔔 Novedades", callback_data="view_notif"),
            InlineKeyboardButton("👤 Mi Cuenta", callback_data="view_cuenta"),
        ],
    ])


def notifications_keyboard():
    """Botones interactivos bajo el centro de notificaciones."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Ver Tareas", callback_data="view_tareas"),
            InlineKeyboardButton("📚 Mis Materias", callback_data="view_cursos"),
        ],
        [
            InlineKeyboardButton("🔄 Actualizar", callback_data="view_notif"),
            InlineKeyboardButton("👤 Mi Cuenta", callback_data="view_cuenta"),
        ],
    ])


def account_keyboard():
    """Botones interactivos para el perfil de cuenta."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Cambiar facultad", callback_data="cuenta_cambiar_facultad"),
            InlineKeyboardButton("🚪 Desconectar", callback_data="cuenta_logout"),
        ],
        [
            InlineKeyboardButton("📚 Mis Materias", callback_data="view_cursos"),
            InlineKeyboardButton("📅 Mis Tareas", callback_data="view_tareas"),
        ],
    ])


def welcome_keyboard(logged_in: bool):
    """Botones interactivos en /start según el estado de sesión."""
    if logged_in:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📚 Mis Materias", callback_data="view_cursos"),
                InlineKeyboardButton("📅 Próximas Tareas", callback_data="view_tareas"),
            ],
            [
                InlineKeyboardButton("🔔 Novedades", callback_data="view_notif"),
                InlineKeyboardButton("👤 Mi Cuenta", callback_data="view_cuenta"),
            ],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Conectar Cuenta (/login)", callback_data="prompt_login")],
    ])


def login_prompt_keyboard():
    """Botón rápido para invocar /login."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Conectar Cuenta (/login)", callback_data="prompt_login")],
    ])
