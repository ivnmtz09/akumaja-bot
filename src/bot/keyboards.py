"""Constructores de teclados y botones para Telegram."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from src.moodle.instances import registry


def instances_keyboard():
    """Genera teclado inline con todas las facultades disponibles."""
    buttons = [
        [InlineKeyboardButton(instance.name, callback_data=f"inst:{instance_id}")]
        for instance_id, instance in registry.all()
    ]
    return InlineKeyboardMarkup(buttons)


def menu_keyboard(logged_in: bool):
    """Barra de botones persistente, adaptada al estado de login del usuario."""
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


def build_faculty_selection(current_instance_id=None):
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


# Alias con guion bajo para compatibilidad con código existente
_instances_keyboard = instances_keyboard
_menu_keyboard = menu_keyboard
_build_faculty_selection = build_faculty_selection
