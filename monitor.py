"""Monitoreo automático de notificaciones para TODOS los usuarios.

Cada usuario se procesa por separado: login propio, dedup propio,
mensajes a su propio telegram_chat_id. Un fallo en un usuario NO
afecta a los demás.
"""

import logging

import db
import get_courses as moodle_api
from accounts import get_client_for

logger = logging.getLogger(__name__)


async def collect_notifications_for_users(telegram_bot):
    """
    Revisa notificaciones nuevas de todos los usuarios activos y las envía.
    Retorna el número de notificaciones enviadas (para logs/depuración).
    """
    users = db.list_active_users()
    total_sent = 0

    if not users:
        logger.info("Monitor: no hay usuarios registrados, nada que revisar.")
        return 0

    for user in users:
        chat_id = user["telegram_chat_id"]
        try:
            client = get_client_for(chat_id)
            if client is None:
                logger.warning("Monitor: no se pudo construir cliente para %s", chat_id)
                continue

            notifications = client.check_new_notifications(user_id=chat_id)
            if notifications:
                total_sent += await _send_notifications(telegram_bot, chat_id, notifications)
            db.update_last_sync(chat_id)
            client.logout()
            logger.info("Monitor: %s → %d notificación(es)", chat_id, len(notifications))
        except Exception as exc:
            logger.error("Monitor: error para %s: %s", chat_id, exc)
            continue

    return total_sent


async def _send_notifications(telegram_bot, chat_id, notifications):
    sent = 0
    for notif in notifications:
        try:
            text = f"{notif['title']}\n\n{notif['message']}"
            if notif.get("url"):
                text += f"\n\n🔗 {notif['url']}"
            await telegram_bot.send_message(chat_id=chat_id, text=text)
            sent += 1
        except Exception as exc:
            logger.error("Monitor: fallo al enviar a %s: %s", chat_id, exc)
    return sent


async def legacy_check(telegram_bot, chat_id):
    """
    Fallback: usa la cuenta legacy de .env para un chat dado.
    Se usa SOLO si la DB está vacía (modo single-user conservado).
    """
    try:
        session = moodle_api.login()
        notifications = moodle_api.check_new_notifications(session)
        if notifications:
            await _send_notifications(telegram_bot, chat_id, notifications)
        return len(notifications)
    except Exception as exc:
        logger.error("Monitor legacy: %s", exc)
        return 0