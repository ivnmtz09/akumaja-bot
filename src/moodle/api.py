"""Cliente de bajo nivel y scraping de API AJAX de Moodle para Akumaja.

Maneja autenticación por sesión HTTP, extracción de sesskey y llamadas
a los endpoints AJAX internos de Moodle (courses, calendar, recent activity).
"""

import json
import os
import re
import sys
import time
import random
import requests
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from src.core.config import MOODLE_URL, MOODLE_USERNAME, MOODLE_PASSWORD
from src.services.notifications import (
    SENT_NOTIFICATIONS_FILE,
    get_sent_notifications_file,
    load_sent_notifications,
    save_sent_notifications,
)

# Alias de compatibilidad hacia atrás
_sent_notifications_file = get_sent_notifications_file


# ---------------------------------------------------------------------------
# Caché de sesiones autenticadas por usuario.
# Clave: username de Moodle (garantiza aislamiento entre estudiantes).
# Valor: objeto cloudscraper autenticado.
# ---------------------------------------------------------------------------
_sessions_cache: dict = {}


def login(moodle_url=None, username=None, password=None):
    """Inicia sesión en Moodle y retorna una sesión HTTP con cookies autenticadas.

    Usa ``username`` como clave del caché de sesiones.  Si ya existe una
    sesión cacheada para ese usuario, se retorna directamente.

    **No** existe fallback a variables de entorno.  Si ``username`` o
    ``password`` son ``None`` o cadenas vacías se lanza ``ValueError``
    para evitar fugas de credenciales entre usuarios.
    """
    moodle_url = moodle_url if moodle_url is not None else MOODLE_URL

    # ── Validación estricta de credenciales ──────────────────────────
    if not username:
        raise ValueError(
            "Credenciales faltantes: 'username' es obligatorio para login. "
            "Proporciona las credenciales desencriptadas del usuario."
        )
    if not password:
        raise ValueError(
            "Credenciales faltantes: 'password' es obligatorio para login. "
            "Proporciona las credenciales desencriptadas del usuario."
        )

    # ── Verificar sesión en caché (clave = username) ─────────────────
    if username in _sessions_cache:
        return _sessions_cache[username]

    session = cloudscraper.create_scraper(
        delay=10,
        browser={
            'browser': 'firefox',
            'platform': 'windows',
            'desktop': True
        }
    )

    login_url = f"{moodle_url}/login/index.php"

    try:
        response = session.get(login_url, timeout=30)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code in (403, 503):
            raise RuntimeError("El firewall bloqueó la conexión al iniciar sesión. Intenta de nuevo más tarde.")
        raise

    soup = BeautifulSoup(response.text, "html.parser")
    token_input = soup.find("input", {"name": "logintoken"})

    if not token_input:
        raise RuntimeError("No se encontró el logintoken de Moodle.")

    logintoken = token_input.get("value")

    response = session.post(
        login_url,
        data={
            "username": username,
            "password": password,
            "logintoken": logintoken,
        },
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()

    if "/login/" in response.url:
        raise RuntimeError("El login no parece haber sido exitoso.")

    # Guardar en caché usando username como clave
    _sessions_cache[username] = session

    return session


def invalidate_session(username):
    """Elimina la sesión de un usuario específico del caché.

    La clave del caché es el ``username`` de Moodle.
    Debe llamarse cuando la sesión expira (403, sesskey ausente, etc.)
    para forzar un re-login limpio en la próxima petición.
    """
    cached = _sessions_cache.pop(username, None)
    if cached is not None:
        try:
            cached.close()
        except Exception:
            pass


def _is_session_expired(error):
    """Detecta si un error indica sesión expirada o bloqueada."""
    msg = str(error).lower()
    return any(kw in msg for kw in (
        "firewall bloqueó",
        "sesskey",
        "403",
        "login",
    ))




def get_sesskey(session, moodle_url=None):
    """Obtiene la clave de sesión (sesskey) de Moodle."""
    moodle_url = moodle_url or MOODLE_URL
    response = session.get(f"{moodle_url}/my/courses.php", timeout=30)
    response.raise_for_status()

    match = re.search(r'"sesskey":"([a-zA-Z0-9]+)"', response.text)
    if not match:
        raise RuntimeError("No se encontró sesskey en la página.")
    return match.group(1)


def call_ajax(session, sesskey, method, args, moodle_url=None):
    """Realiza una petición al endpoint AJAX de Moodle."""
    moodle_url = moodle_url or MOODLE_URL

    payload = json.dumps([
        {
            "index": 0,
            "methodname": method,
            "args": args,
        }
    ])

    response = session.post(
        f"{moodle_url}/lib/ajax/service.php?sesskey={sesskey}",
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Referer": f"{moodle_url}/my/courses.php",
            "X-RequestedWith": "XMLHttpRequest",
        },
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code in (403, 503):
            raise RuntimeError("El firewall bloqueó la petición AJAX. Intenta de nuevo más tarde.")
        raise

    result = response.json()
    if not isinstance(result, list) or not result:
        raise RuntimeError(f"Respuesta inesperada del servicio AJAX: {result}")

    first = result[0]
    if first.get("error"):
        msg = first.get("message", "Error desconocido")
        raise RuntimeError(f"Error del servicio AJAX: {msg}")

    return first["data"]


def get_courses(session, moodle_url=None):
    """Obtiene los cursos inscritos del usuario vía AJAX."""
    moodle_url = moodle_url or MOODLE_URL
    sesskey = get_sesskey(session, moodle_url)

    data = call_ajax(
        session,
        sesskey,
        "core_course_get_enrolled_courses_by_timeline_classification",
        {
            "classification": "all",
            "limit": 0,
            "offset": 0,
            "sort": "fullname",
            "customfieldname": "",
            "customfieldvalue": "",
        },
        moodle_url=moodle_url,
    )

    courses = data.get("courses", [])
    result = []
    for c in courses:
        course_id = c.get("id")
        if not course_id:
            continue
        result.append({
            "id": course_id,
            "name": c.get("fullname", f"Curso {course_id}"),
            "url": c.get("viewurl", f"{moodle_url}/course/view.php?id={course_id}"),
        })

    return result


def get_upcoming_events(session, days_ahead=30, moodle_url=None):
    """Obtiene eventos/actividades próximas (entregas, exámenes, etc.)."""
    moodle_url = moodle_url or MOODLE_URL
    sesskey = get_sesskey(session, moodle_url)

    data = call_ajax(
        session,
        sesskey,
        "core_calendar_get_action_events_by_timesort",
        {"timesortfrom": 0},
        moodle_url=moodle_url,
    )

    events = data.get("events", [])
    now = datetime.now().timestamp()
    cutoff = now + (days_ahead * 86400)

    upcoming = []
    for e in events:
        timestart = e.get("timestart", 0)
        if timestart and now <= timestart <= cutoff:
            course = e.get("course", {})
            upcoming.append({
                "name": e.get("name", "Sin nombre"),
                "description": e.get("description", ""),
                "course_name": course.get("fullname", "Curso desconocido"),
                "course_id": course.get("id"),
                "timestart": timestart,
                "timeend": e.get("timeend", 0),
                "url": e.get("url", ""),
                "formatted_time": datetime.fromtimestamp(timestart, tz=ZoneInfo("America/Bogota")).strftime("%d/%m/%Y %H:%M") if timestart else "Sin fecha",
                "event_type": "calendar",
            })

    upcoming.sort(key=lambda x: x["timestart"])
    return upcoming


def get_all_calendar_events(session, moodle_url=None):
    """Obtiene todos los eventos del calendario (pasados y futuros)."""
    moodle_url = moodle_url or MOODLE_URL
    sesskey = get_sesskey(session, moodle_url)

    data = call_ajax(
        session,
        sesskey,
        "core_calendar_get_action_events_by_timesort",
        {"timesortfrom": 0},
        moodle_url=moodle_url,
    )

    events = data.get("events", [])
    now = datetime.now().timestamp()

    all_events = []
    for e in events:
        timestart = e.get("timestart", 0)
        course = e.get("course", {})
        all_events.append({
            "name": e.get("name", "Sin nombre"),
            "description": e.get("description", ""),
            "course_name": course.get("fullname", "Curso desconocido"),
            "course_id": course.get("id"),
            "timestart": timestart,
            "timeend": e.get("timeend", 0),
            "url": e.get("url", ""),
            "formatted_time": datetime.fromtimestamp(timestart, tz=ZoneInfo("America/Bogota")).strftime("%d/%m/%Y %H:%M") if timestart else "Sin fecha",
            "is_future": timestart > now if timestart else False,
            "event_type": "calendar",
        })

    all_events.sort(key=lambda x: x["timestart"] or 0, reverse=True)
    return all_events


def get_recent_activity(session, course_ids=None, days_back=7, moodle_url=None):
    """Obtiene actividad reciente de los cursos (foros, recursos nuevos, etc.)."""
    moodle_url = moodle_url or MOODLE_URL
    if not course_ids:
        return []

    sesskey = get_sesskey(session, moodle_url)
    now = datetime.now().timestamp()
    cutoff = now - (days_back * 86400)

    activity = []
    import time
    for course_id in course_ids:
        time.sleep(random.uniform(0.5, 1.5))
        try:
            data = call_ajax(
                session,
                sesskey,
                "core_course_get_course_contents",
                {"courseid": course_id},
                moodle_url=moodle_url,
            )
            sections = data if isinstance(data, list) else data.get("sections", [])
            for section in sections:
                modules = section.get("modules", [])
                for mod in modules:
                    mod_timemodified = mod.get("timemodified", 0)
                    if mod_timemodified and mod_timemodified > cutoff:
                        activity.append({
                            "name": mod.get("name", "Sin nombre"),
                            "modname": mod.get("modname", ""),
                            "course_id": course_id,
                            "url": mod.get("url", ""),
                            "timemodified": mod_timemodified,
                            "formatted_time": datetime.fromtimestamp(mod_timemodified, tz=ZoneInfo("America/Bogota")).strftime("%d/%m/%Y %H:%M"),
                            "event_type": "content",
                        })
        except Exception:
            continue

    activity.sort(key=lambda x: x["timemodified"], reverse=True)
    return activity[:20]


def get_notifications_summary(session, moodle_url=None):
    """Resumen combinado: próximos vencimientos + actividad reciente."""
    moodle_url = moodle_url or MOODLE_URL
    events = get_upcoming_events(session, days_ahead=30, moodle_url=moodle_url)
    courses = get_courses(session, moodle_url=moodle_url)
    course_ids = [c["id"] for c in courses]
    activity = get_recent_activity(session, course_ids, days_back=7, moodle_url=moodle_url)

    return {
        "upcoming_events": events,
        "recent_activity": activity,
        "total_events": len(events),
        "total_activity": len(activity),
    }


def _clean_event_name(raw_name: str) -> str:
    """Limpia prefijos redundantes comunes de Moodle en nombres de actividades."""
    if not raw_name:
        return "Actividad sin nombre"

    name = raw_name.strip()
    prefixes = [
        "se vence el plazo para la entrega de",
        "se vence el plazo para la entrega",
        "se vence el plazo para",
        "se vence el plazo de",
        "se vence:",
        "vencimiento de la entrega de",
        "vencimiento de entrega de",
        "vencimiento de la entrega:",
        "vencimiento de",
        "vencimiento:",
        "entrega de",
        "entrega:",
    ]

    lower = name.lower()
    for prefix in prefixes:
        if lower.startswith(prefix):
            remainder = name[len(prefix):].strip(" :,-")
            if remainder:
                return remainder

    return name


def check_new_notifications(session, moodle_url=None, user_id=None):
    """Verifica notificaciones nuevas con deduplicación por usuario."""
    moodle_url = moodle_url or MOODLE_URL
    sent = load_sent_notifications(user_id=user_id)
    now_ts = int(time.time())
    new_notifications = []

    # 1. Eventos de calendario próximos (próximas 24h)
    events = get_upcoming_events(session, days_ahead=1, moodle_url=moodle_url)
    for e in events:
        event_id = f"cal_{e['course_id']}_{e['timestart']}_{e['name'][:30]}"
        if event_id not in sent:
            hours_left = max(0, int((e['timestart'] - now_ts) / 3600))
            clean_name = _clean_event_name(e['name'])
            new_notifications.append({
                "id": event_id,
                "type": "deadline_soon",
                "title": f"⏰ <b>Próxima entrega:</b> {escape(clean_name)}",
                "message": (
                    f"📚 <b>Materia:</b> {escape(e['course_name'])}\n"
                    f"⏳ <b>Tiempo restante:</b> <code>{hours_left} horas</code>\n"
                    f"📅 <b>Fecha límite:</b> <code>{e['formatted_time']}</code>\n\n"
                    "💪 <i>¡Ponte las pilas y no lo dejes para el final!</i>"
                ),
                "url": e['url'],
                "timestamp": e['timestart'],
            })
            sent[event_id] = now_ts

    # 2. Eventos vencidos (overdue) - últimas 24h
    all_events = get_all_calendar_events(session, moodle_url=moodle_url)
    for e in all_events:
        if not e["is_future"] and e["timestart"]:
            hours_ago = int((now_ts - e["timestart"]) / 3600)
            if 0 < hours_ago <= 24:
                event_id = f"overdue_{e['course_id']}_{e['timestart']}_{e['name'][:30]}"
                if event_id not in sent:
                    clean_name = _clean_event_name(e['name'])
                    new_notifications.append({
                        "id": event_id,
                        "type": "overdue",
                        "title": f"🚨 <b>Entrega vencida:</b> {escape(clean_name)}",
                        "message": (
                            f"📚 <b>Materia:</b> {escape(e['course_name'])}\n"
                            f"⏰ <b>Venció hace:</b> <code>{hours_ago} horas</code>\n"
                            f"📅 <b>Fecha original:</b> <code>{e['formatted_time']}</code>\n\n"
                            "⚠️ <i>Revisa en la plataforma si tu docente aún permite entregas con retraso.</i>"
                        ),
                        "url": e['url'],
                        "timestamp": e['timestart'],
                    })
                    sent[event_id] = now_ts

    # 3. Contenido nuevo en cursos (últimas 6h)
    courses = get_courses(session, moodle_url=moodle_url)
    course_ids = [c["id"] for c in courses]
    activity = get_recent_activity(session, course_ids, days_back=1, moodle_url=moodle_url)
    for a in activity:
        hours_ago = int((now_ts - a["timemodified"]) / 3600)
        if 0 < hours_ago <= 6:
            act_id = f"content_{a['course_id']}_{a['timemodified']}_{a['name'][:30]}"
            if act_id not in sent:
                modname = a["modname"].replace("mod_", "")
                clean_name = _clean_event_name(a['name'])
                new_notifications.append({
                    "id": act_id,
                    "type": "new_content",
                    "title": f"📄 <b>Nuevo material en curso:</b> {escape(clean_name)}",
                    "message": (
                        f"📚 <b>Curso ID:</b> <code>{a['course_id']}</code>\n"
                        f"📝 <b>Tipo de recurso:</b> <code>{escape(modname)}</code>\n"
                        f"🕐 <b>Publicado hace:</b> <code>{hours_ago}h ({a['formatted_time']})</code>\n\n"
                        "👀 <i>Échale un vistazo en Moodle cuando puedas.</i>"
                    ),
                    "url": a['url'],
                    "timestamp": a['timemodified'],
                })
                sent[act_id] = now_ts

    # Limpiar notificaciones antiguas (> 7 días)
    cutoff = now_ts - (7 * 86400)
    sent = {k: v for k, v in sent.items() if v > cutoff}

    save_sent_notifications(sent, user_id=user_id)
    return new_notifications


def main():
    if not MOODLE_URL:
        print("❌ Falta MOODLE_URL en .env")
        sys.exit(1)

    if not MOODLE_USERNAME:
        print("❌ Falta MOODLE_USERNAME en .env")
        sys.exit(1)

    if not MOODLE_PASSWORD:
        print("❌ Falta MOODLE_PASSWORD en .env")
        sys.exit(1)

    session = login(
        moodle_url=MOODLE_URL,
        username=MOODLE_USERNAME,
        password=MOODLE_PASSWORD,
    )

    try:
        courses = get_courses(session)
    except Exception as exc:
        print(f"❌ Error obteniendo cursos: {exc}")
        sys.exit(1)

    print()
    print("=" * 70)
    print(f"📚 CURSOS ENCONTRADOS: {len(courses)}")
    print("=" * 70)

    if not courses:
        print("⚠️ No se encontraron cursos.")
        return

    for number, course in enumerate(courses, start=1):
        print()
        print(f"{number}. {course['name']}")
        print(f"   🆔 ID: {course['id']}")
        print(f"   🔗 {course['url']}")


if __name__ == "__main__":
    main()
