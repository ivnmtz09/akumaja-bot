"""Monitoreo automático de notificaciones para TODOS los usuarios.

Cada usuario se procesa por separado: login propio, dedup propio,
mensajes a su propio telegram_chat_id. Un fallo en un usuario NO
afecta a los demás.
"""

import logging
import random
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from src.core import database as db
from src.moodle import api as moodle_api
from src.services.accounts import get_client_for
from src.bot.ui import LINE_DOUBLE, LINE_LIGHT

logger = logging.getLogger(__name__)


async def collect_notifications_for_users(telegram_bot):
    """Revisa notificaciones nuevas de todos los usuarios activos y las envía.

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
            logger.info("Monitor: %s → %d notificación(es)", chat_id, len(notifications))
        except Exception as exc:
            logger.error("Monitor: error para %s: %s", chat_id, exc)

        time.sleep(random.uniform(5, 12))

    return total_sent


async def _send_notifications(telegram_bot, chat_id, notifications):
    sent = 0
    link_opts = LinkPreviewOptions(is_disabled=True)
    for notif in notifications:
        try:
            title = notif.get("title", "Aviso de Akumaja")
            message = notif.get("message", "")
            url = notif.get("url")

            text = (
                "🔔 <b>AVISO DE AKUMAJA</b>\n"
                f"{LINE_DOUBLE}\n"
                f"{title}\n"
                f"{LINE_LIGHT}\n"
                f"{message}\n"
                f"{LINE_DOUBLE}"
            )

            reply_markup = None
            if url:
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Abrir en Moodle ➔", url=url)]
                ])

            try:
                await telegram_bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    link_preview_options=link_opts,
                )
            except TypeError:
                await telegram_bot.send_message(chat_id=chat_id, text=text)

            sent += 1
        except Exception as exc:
            logger.error("Monitor: fallo al enviar a %s: %s", chat_id, exc)
    return sent


async def legacy_check(telegram_bot, chat_id):
    """Fallback: usa la cuenta legacy de .env para un chat dado.

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
