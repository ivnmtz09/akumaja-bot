"""Gestión de notificaciones y deduplicación por usuario.

Almacena y recupera el historial de eventos ya notificados en data/notifications/
para evitar enviar notificaciones duplicadas al usuario.
"""

import json
from pathlib import Path

from src.core.config import NOTIFICATIONS_DIR

SENT_NOTIFICATIONS_FILE = NOTIFICATIONS_DIR / ".sent_notifications.json"


def get_sent_notifications_file(user_id=None):
    """Retorna la ruta del archivo de deduplicación para un usuario o legacy."""
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    if user_id is not None:
        return NOTIFICATIONS_DIR / f".sent_notifications_{user_id}.json"
    return SENT_NOTIFICATIONS_FILE


def load_sent_notifications(user_id=None):
    """Carga el diccionario de notificaciones enviadas."""
    path = get_sent_notifications_file(user_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_sent_notifications(data, user_id=None):
    """Guarda el diccionario de notificaciones enviadas."""
    path = get_sent_notifications_file(user_id)
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def reset_sent_notifications(user_id):
    """Elimina el archivo de deduplicación de un usuario (usado en cambio de facultad)."""
    path = get_sent_notifications_file(user_id)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
