"""Akumaja Bot — Punto de entrada principal (Telegram Bot).

Multiusuario y multi-instancia para la Plataforma Virtual Akumaja (Uniguajira).
Ejecución:
    python bot.py
"""

import logging
import os
from datetime import datetime

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from src.core import database as db
from src.core.config import (
    MONITOR_END_HOUR,
    MONITOR_INTERVAL_MINUTES,
    MONITOR_START_HOUR,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    migrate_legacy_data_files,
)
from src.services.accounts import run_legacy_migration
from src.services.monitor import collect_notifications_for_users, legacy_check
from src.bot.handlers import (
    CF_CONFIRM,
    CF_INSTANCE,
    CF_PASSWORD,
    CF_USERNAME,
    LOGIN_INSTANCE,
    LOGIN_PASSWORD,
    LOGIN_USERNAME,
    ayuda,
    cancel,
    cf_cancel,
    cf_confirm,
    cf_instance_selected,
    cf_password,
    cf_username,
    change_facultad_start,
    cuenta,
    cuenta_logout_cb,
    cursos,
    estado,
    get_faculty_handler,
    get_login_handler,
    login_change_faculty,
    login_instance_selected,
    login_password,
    login_start,
    login_username,
    logout,
    notificaciones,
    start,
    tareas,
)
from src.bot.keyboards import (
    _build_faculty_selection,
    _instances_keyboard,
    _menu_keyboard,
    build_faculty_selection,
    instances_keyboard,
    menu_keyboard,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def monitor_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job que se ejecuta periódicamente para notificaciones nuevas."""
    now = datetime.now()
    current_hour = now.hour

    # Solo ejecutar dentro del rango configurado (ej: 6:00 a 23:59)
    if current_hour < MONITOR_START_HOUR or current_hour >= MONITOR_END_HOUR:
        return

    if db.count_users() > 0:
        await collect_notifications_for_users(context.bot)
    else:
        chat_id = TELEGRAM_CHAT_ID or os.getenv("TELEGRAM_CHAT_ID")
        if not chat_id:
            logger.warning("TELEGRAM_CHAT_ID no configurado, saltando monitoreo")
            return
        await legacy_check(context.bot, chat_id)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("No se encontró TELEGRAM_BOT_TOKEN en .env")

    # Migrar automáticamente archivos previos de la raíz a data/
    migrate_legacy_data_files()

    # Inicializar base de datos y migración legacy si aplica
    db.init_db()
    run_legacy_migration()

    # Construir aplicación con timeouts aumentados para evitar TimedOut
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .build()
    )

    # Registrar comandos generales
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("estado", estado))

    # Registrar comandos de cursos y cuenta
    app.add_handler(CommandHandler("cursos", cursos))
    app.add_handler(CommandHandler("tareas", tareas))
    app.add_handler(CommandHandler("notificaciones", notificaciones))
    app.add_handler(CommandHandler("cuenta", cuenta))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CallbackQueryHandler(cuenta_logout_cb, pattern=r"^cuenta_logout$"))

    # Registrar callbacks interactivos (navegación rápida en mensajes)
    app.add_handler(CallbackQueryHandler(cursos, pattern=r"^view_cursos$"))
    app.add_handler(CallbackQueryHandler(tareas, pattern=r"^view_tareas$"))
    app.add_handler(CallbackQueryHandler(notificaciones, pattern=r"^view_notif$"))
    app.add_handler(CallbackQueryHandler(cuenta, pattern=r"^view_cuenta$"))

    # Registrar flujos de conversación (/cambiar_facultad y /login)
    app.add_handler(get_faculty_handler())
    app.add_handler(get_login_handler())

    # Job de monitoreo automático
    job_queue = app.job_queue
    job_queue.run_repeating(
        monitor_job,
        interval=MONITOR_INTERVAL_MINUTES * 60,
        first=10,
        name="monitor_notifications",
    )

    end_display = f"{MONITOR_END_HOUR - 1}:59" if MONITOR_END_HOUR == 24 else f"{MONITOR_END_HOUR}:59"
    print("🤖 Bot iniciado. Esperando mensajes...")
    print(f"📅 Monitoreo automático: {MONITOR_START_HOUR}:00 - {end_display} cada {MONITOR_INTERVAL_MINUTES} min")

    app.run_polling()


if __name__ == "__main__":
    main()