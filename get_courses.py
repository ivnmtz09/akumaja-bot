import json
import os
import re
import sys
import time
from datetime import datetime, time as dt_time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


load_dotenv()

MOODLE_URL = os.getenv("MOODLE_URL")
USERNAME = os.getenv("MOODLE_USERNAME")
PASSWORD = os.getenv("MOODLE_PASSWORD")

# Archivo para guardar notificaciones ya enviadas (deduplicación)
SENT_NOTIFICATIONS_FILE = Path(__file__).parent / ".sent_notifications.json"


def _sent_notifications_file(user_id=None):
    """Archivo de deduplicación por usuario (aislamiento entre usuarios)."""
    if user_id is not None:
        return Path(__file__).parent / f".sent_notifications_{user_id}.json"
    return SENT_NOTIFICATIONS_FILE


def load_sent_notifications(user_id=None):
    path = _sent_notifications_file(user_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_sent_notifications(data, user_id=None):
    path = _sent_notifications_file(user_id)
    try:
        path.write_text(json.dumps(data))
    except Exception:
        pass


def login(moodle_url=None, username=None, password=None):
    moodle_url = moodle_url or MOODLE_URL
    username = username or USERNAME
    password = password or PASSWORD

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        )
    })

    login_url = f"{moodle_url}/login/index.php"

    print("🔵 Abriendo Akumaja...")

    response = session.get(
        login_url,
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    token_input = soup.find(
        "input",
        {"name": "logintoken"},
    )

    if not token_input:
        raise RuntimeError(
            "No se encontró el logintoken de Moodle."
        )

    logintoken = token_input.get("value")

    print("🔐 Iniciando sesión...")

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
        raise RuntimeError(
            "El login no parece haber sido exitoso."
        )

    print(f"✅ Login correcto: {response.url}")

    return session


def get_sesskey(session, moodle_url=None):
    moodle_url = moodle_url or MOODLE_URL
    response = session.get(f"{moodle_url}/my/courses.php", timeout=30)
    response.raise_for_status()

    match = re.search(r'"sesskey":"([a-zA-Z0-9]+)"', response.text)
    if not match:
        raise RuntimeError("No se encontró sesskey en la página.")
    return match.group(1)


def call_ajax(session, sesskey, method, args, moodle_url=None):
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
    response.raise_for_status()

    result = response.json()
    if not isinstance(result, list) or not result:
        raise RuntimeError(f"Respuesta inesperada del servicio AJAX: {result}")

    first = result[0]
    if first.get("error"):
        msg = first.get("message", "Error desconocido")
        raise RuntimeError(f"Error del servicio AJAX: {msg}")

    return first["data"]


def get_courses(session, moodle_url=None):
    moodle_url = moodle_url or MOODLE_URL
    print("📚 Consultando Course overview (vía AJAX)...")

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
    """Obtiene eventos/actividades próximas (entregas, exámenes, etc.)"""
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
                "formatted_time": datetime.fromtimestamp(timestart).strftime("%d/%m/%Y %H:%M") if timestart else "Sin fecha",
                "event_type": "calendar",
            })

    upcoming.sort(key=lambda x: x["timestart"])
    return upcoming


def get_all_calendar_events(session, moodle_url=None):
    """Obtiene todos los eventos del calendario (pasados y futuros)"""
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
            "formatted_time": datetime.fromtimestamp(timestart).strftime("%d/%m/%Y %H:%M") if timestart else "Sin fecha",
            "is_future": timestart > now if timestart else False,
            "event_type": "calendar",
        })

    all_events.sort(key=lambda x: x["timestart"] or 0, reverse=True)
    return all_events


def get_recent_activity(session, course_ids=None, days_back=7, moodle_url=None):
    """Obtiene actividad reciente de los cursos (foros, recursos nuevos, etc.)"""
    moodle_url = moodle_url or MOODLE_URL
    if not course_ids:
        return []

    sesskey = get_sesskey(session, moodle_url)
    now = datetime.now().timestamp()
    cutoff = now - (days_back * 86400)

    # Usar core_course_get_course_contents para ver módulos recientes
    # Pero es muy pesado. Alternative: usar el reporte de actividad reciente
    activity = []

    for course_id in course_ids[:5]:  # Limitar a 5 cursos para no sobrecargar
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
                            "formatted_time": datetime.fromtimestamp(mod_timemodified).strftime("%d/%m/%Y %H:%M"),
                            "event_type": "content",
                        })
        except Exception:
            continue

    activity.sort(key=lambda x: x["timemodified"], reverse=True)
    return activity[:20]


def get_notifications_summary(session, moodle_url=None):
    """Resumen combinado: próximos vencimientos + actividad reciente"""
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


def check_new_notifications(session, moodle_url=None, user_id=None):
    """
    Verifica si hay notificaciones nuevas y retorna las que no se han enviado.
    Usa deduplicación por USUARIO (user_id) basada en ID único de evento/actividad.
    """
    moodle_url = moodle_url or MOODLE_URL
    sent = load_sent_notifications(user_id=user_id)
    now_ts = int(time.time())
    new_notifications = []

    # 1. Verificar eventos de calendario próximos (próximas 24h)
    events = get_upcoming_events(session, days_ahead=1, moodle_url=moodle_url)
    for e in events:
        event_id = f"cal_{e['course_id']}_{e['timestart']}_{e['name'][:30]}"
        if event_id not in sent:
            hours_left = max(0, int((e['timestart'] - now_ts) / 3600))
            new_notifications.append({
                "id": event_id,
                "type": "deadline_soon",
                "title": f"⏰ Entrega próxima: {e['name']}",
                "message": f"Curso: {e['course_name']}\nVence en: {hours_left}h ({e['formatted_time']})",
                "url": e['url'],
                "timestamp": e['timestart'],
            })
            sent[event_id] = now_ts

    # 2. Verificar eventos vencidos (overdue) - últimos 24h
    all_events = get_all_calendar_events(session, moodle_url=moodle_url)
    for e in all_events:
        if not e["is_future"] and e["timestart"]:
            hours_ago = int((now_ts - e["timestart"]) / 3600)
            if 0 < hours_ago <= 24:
                event_id = f"overdue_{e['course_id']}_{e['timestart']}_{e['name'][:30]}"
                if event_id not in sent:
                    new_notifications.append({
                        "id": event_id,
                        "type": "overdue",
                        "title": f"🚨 Vencido: {e['name']}",
                        "message": f"Curso: {e['course_name']}\nVenció hace: {hours_ago}h ({e['formatted_time']})",
                        "url": e['url'],
                        "timestamp": e['timestart'],
                    })
                    sent[event_id] = now_ts

    # 3. Verificar contenido nuevo en cursos (últimas 6h)
    courses = get_courses(session, moodle_url=moodle_url)
    course_ids = [c["id"] for c in courses]
    activity = get_recent_activity(session, course_ids, days_back=1, moodle_url=moodle_url)
    for a in activity:
        hours_ago = int((now_ts - a["timemodified"]) / 3600)
        if 0 < hours_ago <= 6:
            act_id = f"content_{a['course_id']}_{a['timemodified']}_{a['name'][:30]}"
            if act_id not in sent:
                modname = a["modname"].replace("mod_", "")
                new_notifications.append({
                    "id": act_id,
                    "type": "new_content",
                    "title": f"📄 Contenido nuevo: {a['name']}",
                    "message": f"Curso ID: {a['course_id']}\nTipo: {modname}\nHace: {hours_ago}h ({a['formatted_time']})",
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

    if not USERNAME:
        print("❌ Falta MOODLE_USERNAME en .env")
        sys.exit(1)

    if not PASSWORD:
        print("❌ Falta MOODLE_PASSWORD en .env")
        sys.exit(1)

    session = login()

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
        print(
            "⚠️ No se encontraron cursos."
        )
        return

    for number, course in enumerate(
        courses,
        start=1,
    ):
        print()
        print(
            f"{number}. {course['name']}"
        )
        print(
            f"   🆔 ID: {course['id']}"
        )
        print(
            f"   🔗 {course['url']}"
        )


if __name__ == "__main__":
    main()