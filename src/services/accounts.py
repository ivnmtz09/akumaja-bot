"""Lógica de cuentas: login, logout, estado y migración legacy.

Aislamiento: cada chat_id tiene su propia cuenta. Nunca se accede
a credenciales de otro usuario.
"""

import os
import sys
import time

from src.core import database as db
from src.core import security
from src.core.config import (
    TELEGRAM_CHAT_ID,
    MOODLE_URL,
    MOODLE_USERNAME,
    MOODLE_PASSWORD,
)
from src.moodle import api as moodle_api
from src.moodle.client import MoodleClient
from src.moodle.instances import registry
from src.services.notifications import (
    SENT_NOTIFICATIONS_FILE,
    get_sent_notifications_file,
    reset_sent_notifications,
)

MAX_LOGIN_ATTEMPTS = 5


class LoginError(Exception):
    """Error de login sin detalles sensibles."""


class TooManyAttempts(LoginError):
    pass


def normalize_username(raw):
    """Normaliza el usuario de Akumaja antes de enviarlo a Moodle.

    - Elimina espacios al inicio/final.
    - Si viene con correo (…@uniguajira.edu.co), conserva solo la parte
      anterior a '@'.
    - Convierte a minúsculas (los usuarios de Moodle son en minúsculas).

    La contraseña NUNCA se normaliza.
    """
    if not raw:
        return ""
    value = raw.strip()
    if "@" in value:
        value = value.split("@", 1)[0]
    return value.lower()


def _validate_credentials(instance_id, username, password):
    """Valida credenciales contra la instancia. NO toca la base de datos.

    Retorna (instance, cantidad_de_cursos). Lanza LoginError si falla.
    """
    instance = registry.get(instance_id)
    if not instance:
        raise LoginError("Instancia Moodle desconocida.")

    client = MoodleClient(instance.base_url, username, password)
    try:
        client.validate()
        courses = client.get_courses()
    except Exception:
        raise LoginError(
            f"No se pudo iniciar sesión en {instance.name}. "
            "Revisa tu usuario y contraseña e intenta de nuevo."
        )
    finally:
        client.logout()

    return instance, len(courses)


def validate_login(chat_id, instance_id, username, password):
    """Valida credenciales contra la instancia SIN guardar nada en la DB.

    Retorna (instance, cantidad_de_cursos). Lanza LoginError/TooManyAttempts.
    """
    _check_attempts(chat_id)
    try:
        result = _validate_credentials(instance_id, username, password)
    except LoginError:
        _register_failure(chat_id)
        raise
    _clear_attempts(chat_id)
    return result


def perform_login(chat_id, instance_id, username, password):
    """Valida las credenciales contra la instancia Moodle y guarda la cuenta

    cifrada en la base de datos. Lanza LoginError si falla.
    """
    instance, _ = validate_login(chat_id, instance_id, username, password)

    password_encrypted = security.encrypt(password)
    db.upsert_user(chat_id, instance_id, username, password_encrypted)
    return instance


def apply_faculty_change(chat_id, instance_id, username, password):
    """Guarda el cambio de facultad YA validado. No vuelve a validar.

    Actualiza la instancia, usuario, credencial cifrada y last_sync_at.
    También reinicia el dedup de notificaciones: los IDs de eventos y
    cursos son distintos en cada instancia.
    """
    password_encrypted = security.encrypt(password)
    db.update_user_faculty(chat_id, instance_id, username, password_encrypted)
    _reset_dedup(chat_id)


def _reset_dedup(chat_id):
    """Elimina el archivo de notificaciones ya enviadas del usuario."""
    path = moodle_api._sent_notifications_file(chat_id)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def logout_user(chat_id):
    """Elimina la cuenta del usuario (contraseña cifrada incluida)."""
    db.delete_user(chat_id)
    if chat_id in _client_cache:
        _client_cache[chat_id].logout()
        del _client_cache[chat_id]


def account_status(chat_id):
    """Retorna un dict con el estado de la cuenta o None."""
    user = db.get_user_by_chat_id(chat_id)
    if not user:
        return None

    instance = registry.get(user["moodle_instance_id"])
    return {
        "instance_id": user["moodle_instance_id"],
        "username": user["moodle_username"],
        "instance_name": instance.name if instance else "Desconocida",
        "instance_base_url": instance.base_url if instance else None,
        "last_sync_at": user["last_sync_at"],
        "created_at": user["created_at"],
    }


_client_cache = {}

def get_client_for(chat_id):
    """Construye o recupera un MoodleClient descifrando la credencial del usuario."""
    user = db.get_user_by_chat_id(chat_id)
    if not user:
        return None

    instance = registry.get(user["moodle_instance_id"])
    if not instance:
        return None

    cached = _client_cache.get(chat_id)
    if cached and cached.username == user["moodle_username"]:
        return cached

    try:
        password = security.decrypt(user["moodle_password_encrypted"])
    except RuntimeError:
        return None

    client = MoodleClient(
        instance.base_url, user["moodle_username"], password,
    )
    _client_cache[chat_id] = client
    return client


# ---------------------------------------------------------------------------
# Protección anti fuerza bruta (en memoria, por chat_id)
# ---------------------------------------------------------------------------

_attempts = {}


def _check_attempts(chat_id):
    if _attempts.get(chat_id, 0) >= MAX_LOGIN_ATTEMPTS:
        raise TooManyAttempts(
            "Demasiados intentos fallidos. Espera unos minutos e intenta de nuevo."
        )


def _register_failure(chat_id):
    _attempts[chat_id] = _attempts.get(chat_id, 0) + 1


def _clear_attempts(chat_id):
    _attempts.pop(chat_id, None)


# ---------------------------------------------------------------------------
# Migración legacy: cuenta única de .env -> primer usuario en la DB
# ---------------------------------------------------------------------------

def run_legacy_migration(force=False):
    """Si la DB está vacía y hay credenciales legacy en .env, migra esa cuenta

    al chat legacy configurado (TELEGRAM_CHAT_ID).

    No toca nada si la DB ya tiene usuarios (multi-usuario activo).
    """
    db.init_db()

    legacy_chat_id = TELEGRAM_CHAT_ID or os.getenv("TELEGRAM_CHAT_ID")
    legacy_url = MOODLE_URL or os.getenv("MOODLE_URL")
    legacy_user = MOODLE_USERNAME or os.getenv("MOODLE_USERNAME")
    legacy_pass = MOODLE_PASSWORD or os.getenv("MOODLE_PASSWORD")

    if not legacy_chat_id or not legacy_url or not legacy_user or not legacy_pass:
        print("⚠️  No hay cuenta legacy configurada (TELEGRAM_CHAT_ID/MOODLE_*).")
        return

    if db.count_users() > 0 and not force:
        print("ℹ️  DB con usuarios: se omite la migración legacy.")
        return

    instance_id = registry.match_base_url(legacy_url)
    if not instance_id:
        print(f"⚠️  MOODLE_URL legacy ({legacy_url}) no coincide con ninguna instancia.")
        return

    password_encrypted = security.encrypt(legacy_pass)
    db.upsert_user(legacy_chat_id, instance_id, legacy_user, password_encrypted)
    print(f"✅ Migración legacy: chat {legacy_chat_id} → {instance_id} ({legacy_user})")

    # Asegurar que el dedup legacy pase a ser por usuario
    _migrate_sent_notifications(legacy_chat_id)


def _migrate_sent_notifications(chat_id):
    legacy_file = SENT_NOTIFICATIONS_FILE
    user_file = get_sent_notifications_file(chat_id)
    if legacy_file.exists() and not user_file.exists():
        try:
            data = legacy_file.read_text(encoding="utf-8")
            user_file.write_text(data, encoding="utf-8")
            print(f"📁 Dedup legacy migrado a {user_file}")
        except Exception:
            pass


def require_login(chat_id):
    """Helper: retorna el MoodleClient si el usuario tiene cuenta, si no None."""
    return get_client_for(chat_id)


if __name__ == "__main__":
    run_legacy_migration()
