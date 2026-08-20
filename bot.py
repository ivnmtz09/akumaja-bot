import os
import logging
from datetime import datetime, time as dt_time

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from get_courses import (
    login,
    get_courses,
    get_upcoming_events,
    get_all_calendar_events,
    get_recent_activity,
    get_notifications_summary,
    check_new_notifications,
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Configuración de monitoreo
MONITOR_START_HOUR = 5
MONITOR_END_HOUR = 23
MONITOR_INTERVAL_MINUTES = 30


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 ¡Hola!\n\n"
        "Soy el bot de Akumaja (Plataforma Virtual Uniguajira).\n\n"
        "Comandos disponibles:\n"
        "/cursos - Lista tus cursos inscritos\n"
        "/tareas - Muestra actividades y entregas próximas (30 días)\n"
        "/notificaciones - Resumen completo (vencimientos + actividad reciente)\n"
        "/start - Muestra este mensaje"
    )


async def cursos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Obteniendo tus cursos...")

    try:
        session = login()
        courses = get_courses(session)
    except Exception as exc:
        logger.exception("Error obteniendo cursos")
        await update.message.reply_text(f"❌ Error: {exc}")
        return

    if not courses:
        await update.message.reply_text("⚠️ No se encontraron cursos inscritos.")
        return

    lines = [f"📚 <b>Tus cursos ({len(courses)})</b>:", ""]
    for i, course in enumerate(courses, 1):
        lines.append(f"{i}. <b>{course['name']}</b>")
        lines.append(f"   🆔 ID: <code>{course['id']}</code>")
        lines.append(f"   🔗 <a href='{course['url']}'>Abrir en Moodle</a>")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def tareas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Consultando actividades próximas...")

    try:
        session = login()
        events = get_upcoming_events(session, days_ahead=30)
    except Exception as exc:
        logger.exception("Error obteniendo actividades")
        await update.message.reply_text(f"❌ Error: {exc}")
        return

    if not events:
        await update.message.reply_text("✅ No hay actividades próximas en los próximos 30 días.")
        return

    lines = [f"📅 <b>Próximas actividades ({len(events)})</b>:", ""]
    for e in events:
        lines.append(f"📌 <b>{e['name']}</b>")
        lines.append(f"   📚 Curso: {e['course_name']}")
        lines.append(f"   ⏰ Vence: {e['formatted_time']}")
        if e['url']:
            lines.append(f"   🔗 <a href='{e['url']}'>Ver en Moodle</a>")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def notificaciones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 Obteniendo resumen de notificaciones...")

    try:
        session = login()
        summary = get_notifications_summary(session)
    except Exception as exc:
        logger.exception("Error obteniendo notificaciones")
        await update.message.reply_text(f"❌ Error: {exc}")
        return

    events = summary["upcoming_events"]
    activity = summary["recent_activity"]

    lines = ["🔔 <b>Resumen de Notificaciones</b>", ""]

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
        lines.append("✅ No hay notificaciones pendientes ni actividad reciente.")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def monitor_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job que se ejecuta cada 30 min para verificar notificaciones nuevas"""
    now = datetime.now()
    current_hour = now.hour

    # Solo ejecutar entre 5:00 y 23:59
    if current_hour < MONITOR_START_HOUR or current_hour >= MONITOR_END_HOUR:
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.warning("TELEGRAM_CHAT_ID no configurado, saltando monitoreo")
        return

    try:
        session = login()
        new_notifications = check_new_notifications(session)
    except Exception as exc:
        logger.exception("Error en monitoreo automático")
        return

    if not new_notifications:
        return

    for notif in new_notifications:
        lines = [
            f"{notif['title']}",
            "",
            notif['message'],
        ]
        if notif['url']:
            lines.append("")
            lines.append(f"🔗 <a href='{notif['url']}'>Ver en Moodle</a>")

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.exception(f"Error enviando notificación: {exc}")


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "No se encontró TELEGRAM_BOT_TOKEN en .env"
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cursos", cursos))
    app.add_handler(CommandHandler("tareas", tareas))
    app.add_handler(CommandHandler("notificaciones", notificaciones))

    # Job de monitoreo automático cada 30 minutos
    job_queue = app.job_queue
    job_queue.run_repeating(
        monitor_job,
        interval=MONITOR_INTERVAL_MINUTES * 60,  # en segundos
        first=10,  # primera ejecución a los 10 segundos
        name="monitor_notifications",
    )

    print("🤖 Bot iniciado. Esperando mensajes...")
    print(f"📅 Monitoreo automático: {MONITOR_START_HOUR}:00 - {MONITOR_END_HOUR}:59 cada {MONITOR_INTERVAL_MINUTES} min")

    app.run_polling()


if __name__ == "__main__":
    main()