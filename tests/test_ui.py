"""Pruebas para el sistema de interfaz visual, formato, separadores y teclados interactivos."""

import time
from html import unescape
from types import SimpleNamespace
import asyncio

import pytest
from telegram import InlineKeyboardMarkup

from src.bot.ui import (
    LINE_DOUBLE,
    LINE_LIGHT,
    LINE_HEAVY,
    account_keyboard,
    courses_keyboard,
    format_description,
    format_urgency,
    login_prompt_keyboard,
    notifications_keyboard,
    safe_escape,
    tasks_keyboard,
    welcome_keyboard,
)


class TestUiFormatters:
    def test_dividers_defined_and_consistent(self):
        assert "═" in LINE_DOUBLE
        assert "─" in LINE_LIGHT
        assert "━" in LINE_HEAVY
        assert len(LINE_DOUBLE) >= 20
        assert len(LINE_LIGHT) >= 20

    def test_safe_escape(self):
        assert safe_escape("Matemáticas & Algoritmos") == "Matemáticas &amp; Algoritmos"
        assert safe_escape("<script>alert('x')</script>") == "&lt;script&gt;alert('x')&lt;/script&gt;"
        assert safe_escape(None) == ""
        assert safe_escape(123) == "123"

    def test_format_description_strips_html_and_truncates(self):
        html_desc = "<p>Esta es una <b>tarea importante</b> para entregar en <a href='#'>el aula</a>.</p>"
        cleaned = format_description(html_desc, limit=100)
        assert "<p>" not in cleaned
        assert "<b>" not in cleaned
        assert "tarea importante" in cleaned

        empty = format_description("")
        assert empty == ""

        whitespace = format_description("   <p>&nbsp;</p>   ")
        assert whitespace == "" or whitespace.strip() == ""

        long_desc = "palabra " * 50
        truncated = format_description(long_desc, limit=40)
        assert len(truncated) <= 45
        assert truncated.endswith("…")

    def test_format_urgency_overdue(self):
        past_ts = time.time() - 3600 * 5
        badge, time_str, icon = format_urgency(past_ts)
        assert "PLAZO VENCIDO" in badge
        assert "Venció hace" in time_str
        assert icon == "❌"

    def test_format_urgency_urgent_today(self):
        urgent_ts = time.time() + 3600 * 3
        badge, time_str, icon = format_urgency(urgent_ts)
        assert "URGENTE" in badge
        assert "Quedan" in time_str
        assert icon == "🔥"

    def test_format_urgency_attention_24h(self):
        soon_ts = time.time() + 3600 * 18
        badge, time_str, icon = format_urgency(soon_ts)
        assert "ATENCIÓN" in badge
        assert "horas" in time_str
        assert icon == "⏰"

    def test_format_urgency_in_3_days(self):
        mid_ts = time.time() + 3600 * 48
        badge, time_str, icon = format_urgency(mid_ts)
        assert "PRÓXIMO" in badge
        assert "d" in time_str
        assert icon == "⏳"

    def test_format_urgency_with_time(self):
        far_ts = time.time() + 3600 * 100
        badge, time_str, icon = format_urgency(far_ts)
        assert "PROGRAMADA CON TIEMPO" in badge
        assert "Faltan" in time_str
        assert icon == "📅"


class TestUiKeyboards:
    def _extract_callback_data(self, markup: InlineKeyboardMarkup):
        return [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]

    def test_courses_keyboard(self):
        kb = courses_keyboard()
        data = self._extract_callback_data(kb)
        assert "view_tareas" in data
        assert "view_notif" in data
        assert "view_cursos" in data
        assert "view_cuenta" in data

    def test_tasks_keyboard(self):
        kb = tasks_keyboard()
        data = self._extract_callback_data(kb)
        assert "view_tareas" in data
        assert "view_cursos" in data
        assert "view_notif" in data
        assert "view_cuenta" in data

    def test_notifications_keyboard(self):
        kb = notifications_keyboard()
        data = self._extract_callback_data(kb)
        assert "view_tareas" in data
        assert "view_cursos" in data
        assert "view_notif" in data
        assert "view_cuenta" in data

    def test_account_keyboard(self):
        kb = account_keyboard()
        data = self._extract_callback_data(kb)
        assert "cuenta_cambiar_facultad" in data
        assert "cuenta_logout" in data
        assert "view_cursos" in data
        assert "view_tareas" in data

    def test_welcome_keyboard_logged_in(self):
        kb = welcome_keyboard(logged_in=True)
        data = self._extract_callback_data(kb)
        assert "view_cursos" in data
        assert "view_tareas" in data
        assert "view_notif" in data
        assert "view_cuenta" in data

    def test_welcome_keyboard_not_logged_in(self):
        kb = welcome_keyboard(logged_in=False)
        data = self._extract_callback_data(kb)
        assert "prompt_login" in data

    def test_login_prompt_keyboard(self):
        kb = login_prompt_keyboard()
        data = self._extract_callback_data(kb)
        assert "prompt_login" in data


class MockMessage:
    def __init__(self):
        self.replies = []
        self.edited = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return self

    async def edit_text(self, text, **kwargs):
        self.edited.append((text, kwargs))
        return self


class MockUpdate:
    def __init__(self, chat_id="123", callback_query=None):
        self.message = MockMessage() if callback_query is None else None
        self.callback_query = callback_query
        self.effective_chat = SimpleNamespace(id=chat_id)


class TestUiHandlers:
    def test_cursos_not_logged_in_shows_login_card(self, monkeypatch):
        from src.bot.handlers import courses as courses_handler

        monkeypatch.setattr(courses_handler, "get_client_for", lambda chat_id: None)
        update = MockUpdate("999")
        ctx = SimpleNamespace(user_data={})

        asyncio.run(courses_handler.cursos(update, ctx))
        # Verifica que el mensaje fue editado in-place con el aviso estructurado y botón de login
        assert len(update.message.edited) == 1
        last_text, last_kwargs = update.message.edited[0]
        assert "ACCESO NO AUTORIZADO" in last_text
        assert LINE_DOUBLE in last_text
        assert "reply_markup" in last_kwargs

    def test_cursos_logged_in_shows_formatted_cards(self, monkeypatch):
        from src.bot.handlers import courses as courses_handler

        class FakeClient:
            def get_courses(self):
                return [
                    {"id": 101, "name": "Cálculo I", "url": "https://moodle.com/101"},
                    {"id": 102, "name": "Física & Química", "url": "https://moodle.com/102"},
                ]
            def logout(self):
                pass

        monkeypatch.setattr(courses_handler, "get_client_for", lambda chat_id: FakeClient())
        update = MockUpdate("999")
        ctx = SimpleNamespace(user_data={})

        asyncio.run(courses_handler.cursos(update, ctx))
        assert len(update.message.edited) == 1
        final_text, kwargs = update.message.edited[0]
        assert LINE_DOUBLE in final_text
        assert LINE_LIGHT in final_text
        assert "Cálculo I" in final_text
        assert "Física &amp; Química" in final_text
        assert "Total matriculadas:" in final_text
        assert kwargs.get("parse_mode") == "HTML"

    def test_tareas_empty_shows_congratulations(self, monkeypatch):
        from src.bot.handlers import courses as courses_handler

        class FakeClient:
            def get_upcoming_events(self, days_ahead=30):
                return []
            def logout(self):
                pass

        monkeypatch.setattr(courses_handler, "get_client_for", lambda chat_id: FakeClient())
        update = MockUpdate("999")
        ctx = SimpleNamespace(user_data={})

        asyncio.run(courses_handler.tareas(update, ctx))
        assert len(update.message.edited) == 1
        final_text, _ = update.message.edited[0]
        assert "TODO AL DÍA" in final_text
        assert LINE_DOUBLE in final_text

    def test_tareas_with_events_shows_urgency_and_separators(self, monkeypatch):
        from src.bot.handlers import courses as courses_handler

        class FakeClient:
            def get_upcoming_events(self, days_ahead=30):
                return [{
                    "id": 1,
                    "name": "Entrega de Taller 1",
                    "course_name": "Programación II",
                    "timestart": time.time() + 7200,  # 2 horas
                    "formatted_time": "15/09/2026 23:59",
                    "description": "<p>Hacer ejercicios 1 al 4</p>",
                    "url": "https://moodle.com/assign/1",
                }]
            def logout(self):
                pass

        monkeypatch.setattr(courses_handler, "get_client_for", lambda chat_id: FakeClient())
        update = MockUpdate("999")
        ctx = SimpleNamespace(user_data={})

        asyncio.run(courses_handler.tareas(update, ctx))
        assert len(update.message.edited) == 1
        final_text, _ = update.message.edited[0]
        assert LINE_DOUBLE in final_text
        assert "URGENTE" in final_text
        assert "Taller 1" in final_text
        assert "Programación II" in final_text
        assert "Hacer ejercicios 1 al 4" in final_text
        assert "Ir a la entrega en Moodle" in final_text

    def test_cuenta_shows_profile_card(self, monkeypatch):
        from src.bot.handlers import courses as courses_handler

        monkeypatch.setattr(courses_handler, "account_status", lambda chat_id: {
            "username": "estudiante.test",
            "instance_name": "Ingenierías (FIUG)",
            "instance_base_url": "https://akumajafiug.uniguajira.edu.co",
            "last_sync_at": "12/09/2026 22:00",
        })
        monkeypatch.setattr(courses_handler, "get_client_for", lambda chat_id: None)

        update = MockUpdate("999")
        ctx = SimpleNamespace(user_data={})

        asyncio.run(courses_handler.cuenta(update, ctx))
        assert len(update.message.replies) == 1
        text, kwargs = update.message.replies[0]
        assert "MI CUENTA AKUMAJA" in text
        assert LINE_DOUBLE in text
        assert "estudiante.test" in text
        assert "Ingenierías (FIUG)" in text
        assert kwargs.get("parse_mode") == "HTML"

    def test_start_logged_in_and_not_logged_in(self, monkeypatch):
        from src.bot.handlers import general as general_handler

        # 1. No logueado
        monkeypatch.setattr(general_handler, "account_status", lambda chat_id: None)
        update1 = MockUpdate("999")
        ctx = SimpleNamespace(user_data={})
        asyncio.run(general_handler.start(update1, ctx))
        assert "Aún no has conectado tu cuenta Moodle" in update1.message.replies[0][0]
        assert LINE_DOUBLE in update1.message.replies[0][0]

        # 2. Logueado
        monkeypatch.setattr(general_handler, "account_status", lambda chat_id: {
            "username": "alumno",
            "instance_name": "Educación",
            "instance_base_url": "https://moodle.edu",
            "last_sync_at": "Hoy",
        })
        update2 = MockUpdate("999")
        asyncio.run(general_handler.start(update2, ctx))
        assert "HOLA DE NUEVO" in update2.message.replies[0][0]
        assert "alumno" in update2.message.replies[0][0]
        assert LINE_DOUBLE in update2.message.replies[0][0]
