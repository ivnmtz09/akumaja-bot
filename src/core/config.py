"""Configuración centralizada y rutas del sistema.

Gestiona las rutas del proyecto (raíz, data, db, claves, notificaciones),
variables de entorno y parámetros de configuración general.
"""

import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Carga de variables de entorno desde .env
load_dotenv()

# Rutas principales del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("AKUMAJA_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("AKUMAJA_DB_PATH", str(DATA_DIR / "akumaja.db")))
KEY_FILE = Path(os.getenv("AKUMAJA_KEY_PATH", str(DATA_DIR / "akumaja.key")))
NOTIFICATIONS_DIR = Path(os.getenv("AKUMAJA_NOTIFICATIONS_DIR", str(DATA_DIR / "notifications")))

# Credenciales de Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Credenciales Legacy (para migración inicial)
MOODLE_URL = os.getenv("MOODLE_URL")
MOODLE_USERNAME = os.getenv("MOODLE_USERNAME")
MOODLE_PASSWORD = os.getenv("MOODLE_PASSWORD")

# Seguridad
AKUMAJA_ENCRYPTION_KEY = os.getenv("AKUMAJA_ENCRYPTION_KEY")

# Parámetros del monitor automático
MONITOR_START_HOUR = int(os.getenv("MONITOR_START_HOUR", "6"))
MONITOR_END_HOUR = int(os.getenv("MONITOR_END_HOUR", "24"))
MONITOR_INTERVAL_MINUTES = int(os.getenv("MONITOR_INTERVAL_MINUTES", "180"))


def ensure_directories():
    """Garantiza que los directorios de datos existan."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data_files():
    """Migra archivos de datos generados en la raíz antigua hacia data/."""
    ensure_directories()

    # 1. Migrar akumaja.db si está en la raíz y no en DATA_DIR
    root_db = BASE_DIR / "akumaja.db"
    if root_db.exists() and root_db != DB_PATH and not DB_PATH.exists():
        try:
            shutil.move(str(root_db), str(DB_PATH))
            print(f"📦 akumaja.db migrado a {DB_PATH}")
        except Exception as exc:
            print(f"⚠️ No se pudo mover akumaja.db a {DB_PATH}: {exc}")

    # 2. Migrar akumaja.key si está en la raíz y no en DATA_DIR
    root_key = BASE_DIR / "akumaja.key"
    if root_key.exists() and root_key != KEY_FILE and not KEY_FILE.exists():
        try:
            shutil.move(str(root_key), str(KEY_FILE))
            print(f"🔑 akumaja.key migrado a {KEY_FILE}")
        except Exception as exc:
            print(f"⚠️ No se pudo mover akumaja.key a {KEY_FILE}: {exc}")

    # 3. Migrar archivos de notificaciones .sent_notifications_*.json
    for root_file in BASE_DIR.glob(".sent_notifications_*.json"):
        dest = NOTIFICATIONS_DIR / root_file.name
        if not dest.exists():
            try:
                shutil.move(str(root_file), str(dest))
                print(f"📬 {root_file.name} migrado a {dest}")
            except Exception as exc:
                print(f"⚠️ Error migrando {root_file.name}: {exc}")

    # 4. Migrar .sent_notifications.json legacy si existe
    legacy_file = BASE_DIR / ".sent_notifications.json"
    if legacy_file.exists():
        dest = NOTIFICATIONS_DIR / ".sent_notifications.json"
        if not dest.exists():
            try:
                shutil.move(str(legacy_file), str(dest))
            except Exception:
                pass


# Ejecutar inicialización de directorios al importar
ensure_directories()
