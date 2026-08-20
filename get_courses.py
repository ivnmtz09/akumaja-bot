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


def load_sent_notifications():
    if SENT_NOTIFICATIONS_FILE.exists():
        try:
            return json.loads(SENT_NOTIFICATIONS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_sent_notifications(data):
    try:
        SENT_NOTIFICATIONS_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def login():
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        )
    })

    login_url = f"{MOODLE_URL}/login/index.php"

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
            "username": USERNAME,
            "password": PASSWORD,
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


def get_sesskey(session):
    response = session.get(f"{MOODLE_URL}/my/courses.php", timeout=30)
    response.raise_for_status()

    match = re.search(r'"sesskey":"([a-zA-Z0-9]+)"', response.text)
    if not match:
        raise RuntimeError("No se encontró sesskey en la página.")
    return match.group(1)


def call_ajax(session, sesskey, method, args):
    payload = json.dumps([
        {
            "index": 0,
            "methodname": method,
            "args": args,
        }
    ])

    response = session.post(
        f"{MOODLE_URL}/lib/ajax/service.php?sesskey={sesskey}",
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Referer": f"{MOODLE_URL}/my/courses.php",
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


def get_courses(session):
    print("📚 Consultando Course overview (vía AJAX)...")

    sesskey = get_sesskey(session)

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
            "url": c.get("viewurl", f"{MOODLE_URL}/course/view.php?id={course_id}"),
        })

    return result


def get_upcoming_events(session, days_ahead=30):
    """Obtiene eventos/actividades próximas (entregas, exámenes, etc.)"""
    sesskey = get_sesskey(session)

    data = call_ajax(
        session,
        sesskey,
        "core_calendar_get_action_events_by_timesort",
        {"timesortfrom": 0},
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


def get_all_calendar_events(session):
    """Obtiene todos los eventos del calendario (pasados y futuros)"""
    sesskey = get_sesskey(session)

    data = call_ajax(
        session,
        sesskey,
        "core_calendar_get_action_events_by_timesort",
        {"timesortfrom": 0},
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


def get_recent_activity(session, course_ids=None, days_back=7):
    """Obtiene actividad reciente de los cursos (foros, recursos nuevos, etc.)"""
    if not course_ids:
        return []

    sesskey = get_sesskey(session)
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


def get_notifications_summary(session):
    """Resumen combinado: próximos vencimientos + actividad reciente"""
    events = get_upcoming_events(session, days_ahead=30)
    courses = get_courses(session)
    course_ids = [c["id"] for c in courses]
    activity = get_recent_activity(session, course_ids, days_back=7)

    return {
        "upcoming_events": events,
        "recent_activity": activity,
        "total_events": len(events),
        "total_activity": len(activity),
    }


def check_new_notifications(session):
    """
    Verifica si hay notificaciones nuevas y retorna las que no se han enviado.
    Usa deduplicación basada en ID único de evento/actividad.
    """
    sent = load_sent_notifications()
    now_ts = int(time.time())
    new_notifications = []

    # 1. Verificar eventos de calendario próximos (próximas 24h)
    events = get_upcoming_events(session, days_ahead=1)
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
    all_events = get_all_calendar_events(session)
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
    courses = get_courses(session)
    course_ids = [c["id"] for c in courses]
    activity = get_recent_activity(session, course_ids, days_back=1)  # 24h
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

    save_sent_notifications(sent)
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