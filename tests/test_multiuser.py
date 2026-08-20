"""Pruebas de la arquitectura multiusuario (sin credenciales reales)."""

import asyncio
from types import SimpleNamespace

import pytest

import accounts
import db
import security
from moodle_instances import MoodleInstance, registry


# ---------------------------------------------------------------------------
# moodle_instances
# ---------------------------------------------------------------------------

class TestMoodleInstances:
    def test_all_instances_loaded(self):
        instances = dict(registry.all())
        assert len(instances) >= 7
        assert "ingenierias" in instances
        assert instances["ingenierias"].name == "Ingenierías (FIUG)"

    def test_normalize_removes_trailing_slash(self):
        inst = MoodleInstance("x", "X", "https://ejemplo.edu.co/")
        assert inst.base_url == "https://ejemplo.edu.co"

    def test_normalize_removes_login_path(self):
        inst = MoodleInstance("x", "X", "https://ejemplo.edu.co/login/index.php")
        assert inst.base_url == "https://ejemplo.edu.co"

    def test_url_for(self):
        inst = MoodleInstance("x", "X", "https://ejemplo.edu.co")
        assert inst.url_for("lib/ajax/service.php") == "https://ejemplo.edu.co/lib/ajax/service.php"
        assert inst.url_for("/login/index.php") == "https://ejemplo.edu.co/login/index.php"

    def test_match_base_url(self):
        assert registry.match_base_url("https://akumajafiug.uniguajira.edu.co") == "ingenierias"
        assert registry.match_base_url("https://akumajafcbasicas.uniguajira.edu.co") == "ciencias_basicas"
        assert registry.match_base_url("https://otra.uniguajira.edu.co") is None

    def test_get_unknown_returns_none(self):
        assert registry.get("no_existe") is None


# ---------------------------------------------------------------------------
# db (SQLite aislada en tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield db
    db.DB_PATH.unlink(missing_ok=True)


class TestDb:
    def test_upsert_and_get(self, isolated_db):
        isolated_db.upsert_user("111", "ingenierias", "alumno1", "token1")
        user = isolated_db.get_user_by_chat_id("111")
        assert user is not None
        assert user["moodle_username"] == "alumno1"
        assert user["moodle_password_encrypted"] == "token1"

    def test_isolation_between_users(self, isolated_db):
        isolated_db.upsert_user("111", "ingenierias", "alumno1", "token1")
        isolated_db.upsert_user("222", "ciencias_salud", "alumno2", "token2")

        u1 = isolated_db.get_user_by_chat_id("111")
        u2 = isolated_db.get_user_by_chat_id("222")

        assert u1["moodle_instance_id"] == "ingenierias"
        assert u2["moodle_instance_id"] == "ciencias_salud"
        assert u1["moodle_username"] != u2["moodle_username"]

    def test_upsert_replaces_account(self, isolated_db):
        isolated_db.upsert_user("111", "ingenierias", "alumno1", "token1")
        isolated_db.upsert_user("111", "faceya", "alumnoX", "tokenX")

        user = isolated_db.get_user_by_chat_id("111")
        assert user["moodle_instance_id"] == "faceya"
        assert user["moodle_username"] == "alumnoX"

        assert isolated_db.count_users() == 1

    def test_delete_user(self, isolated_db):
        isolated_db.upsert_user("111", "ingenierias", "alumno1", "token1")
        isolated_db.delete_user("111")
        assert isolated_db.get_user_by_chat_id("111") is None
        assert isolated_db.count_users() == 0

    def test_list_active_users(self, isolated_db):
        isolated_db.upsert_user("111", "ingenierias", "a", "t1")
        isolated_db.upsert_user("222", "faceya", "b", "t2")
        users = isolated_db.list_active_users()
        assert len(users) == 2


# ---------------------------------------------------------------------------
# security (clave aislada en tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_security(tmp_path, monkeypatch):
    monkeypatch.setenv("AKUMAJA_ENCRYPTION_KEY", "")
    monkeypatch.delenv("AKUMAJA_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(security, "KEY_FILE", tmp_path / "akumaja.key")
    security._FERNET = None
    yield security
    security._FERNET = None


class TestSecurity:
    def test_encrypt_decrypt_roundtrip(self, isolated_security):
        token = isolated_security.encrypt("MiContraseñaSecreta123")
        assert token != "MiContraseñaSecreta123"
        assert isolated_security.decrypt(token) == "MiContraseñaSecreta123"

    def test_different_tokens_same_plaintext(self, isolated_security):
        t1 = isolated_security.encrypt("abc")
        t2 = isolated_security.encrypt("abc")
        assert t1 != t2  # Fernet usa IV aleatorio

    def test_encrypt_empty_raises(self, isolated_security):
        with pytest.raises(ValueError):
            isolated_security.encrypt("")

    def test_invalid_token_raises(self, isolated_security):
        with pytest.raises(RuntimeError):
            isolated_security.decrypt("token-invalido")


# ---------------------------------------------------------------------------
# accounts.perform_login (con MoodleClient falsificado)
# ---------------------------------------------------------------------------

class FakeClient:
    def __init__(self, base_url=None, username=None, password=None, *, should_fail=False):
        self.should_fail = should_fail
        self.logout_called = False
        self.courses = [
            {"id": i, "name": f"Curso {i}", "url": f"https://x/c{i}"}
            for i in range(19)
        ]

    def validate(self):
        if self.should_fail:
            raise RuntimeError("credenciales malas")
        return True

    def get_courses(self):
        if self.should_fail:
            raise RuntimeError("credenciales malas")
        return self.courses

    def logout(self):
        self.logout_called = True


@pytest.fixture()
def fake_login(monkeypatch, isolated_db, isolated_security):
    import accounts
    monkeypatch.setattr(accounts, "MoodleClient", FakeClient)
    monkeypatch.setattr(accounts, "_attempts", {})
    yield accounts


class TestAccounts:
    def test_perform_login_ok(self, fake_login, isolated_db, isolated_security):
        instance = fake_login.perform_login("999", "ingenierias", "alumno", "pass")
        assert instance.instance_id == "ingenierias"

        user = isolated_db.get_user_by_chat_id("999")
        assert user is not None
        # La contraseña está cifrada, no en texto plano
        assert user["moodle_password_encrypted"] != "pass"
        assert isolated_security.decrypt(user["moodle_password_encrypted"]) == "pass"

    def test_perform_login_bad_credentials(self, fake_login, isolated_db, monkeypatch):
        monkeypatch.setattr(fake_login, "MoodleClient", lambda *a, **k: FakeClient(*a, should_fail=True))
        with pytest.raises(fake_login.LoginError):
            fake_login.perform_login("999", "ingenierias", "alumno", "malapass")
        assert isolated_db.get_user_by_chat_id("999") is None

    def test_perform_login_unknown_instance(self, fake_login, isolated_db):
        with pytest.raises(fake_login.LoginError):
            fake_login.perform_login("999", "no_existe", "alumno", "pass")

    def test_logout_removes_account(self, fake_login, isolated_db):
        fake_login.perform_login("999", "ingenierias", "alumno", "pass")
        fake_login.logout_user("999")
        assert isolated_db.get_user_by_chat_id("999") is None

    def test_account_status(self, fake_login, isolated_db):
        fake_login.perform_login("999", "ingenierias", "alumno", "pass")
        info = fake_login.account_status("999")
        assert info["username"] == "alumno"
        assert info["instance_name"] == "Ingenierías (FIUG)"


# ---------------------------------------------------------------------------
# monitor.collect_notifications_for_users (con fakes)
# ---------------------------------------------------------------------------

class FakeMoodleClient:
    def __init__(self, notifications):
        self.notifications = notifications
        self.logout_called = False

    def check_new_notifications(self, user_id=None):
        return self.notifications

    def logout(self):
        self.logout_called = True


class FakeTelegramBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class TestMonitor:
    def test_collect_sends_per_user(self, monkeypatch, isolated_db, isolated_security):
        import monitor
        import accounts

        isolated_db.upsert_user("111", "ingenierias", "a", "t1")
        isolated_db.upsert_user("222", "faceya", "b", "t2")

        def fake_client_for(chat_id):
            if chat_id == "111":
                return FakeMoodleClient([{"title": "⏰ Entrega", "message": "msg1", "url": "https://x"}])
            return FakeMoodleClient([])

        monkeypatch.setattr(monitor, "get_client_for", fake_client_for)

        bot = FakeTelegramBot()
        sent = asyncio.run(monitor.collect_notifications_for_users(bot))

        assert sent == 1
        assert len(bot.sent) == 1
        assert bot.sent[0][0] == "111"

    def test_one_user_failure_does_not_affect_others(self, monkeypatch, isolated_db, isolated_security):
        import monitor

        isolated_db.upsert_user("111", "ingenierias", "a", "t1")
        isolated_db.upsert_user("222", "faceya", "b", "t2")

        class ExplodingClient(FakeMoodleClient):
            def check_new_notifications(self, user_id=None):
                raise RuntimeError("boom")

        def fake_client_for(chat_id):
            if chat_id == "111":
                return ExplodingClient([])
            return FakeMoodleClient([{"title": "T", "message": "m", "url": ""}])

        monkeypatch.setattr(monitor, "get_client_for", fake_client_for)

        bot = FakeTelegramBot()
        sent = asyncio.run(monitor.collect_notifications_for_users(bot))

        assert sent == 1
        assert bot.sent[0][0] == "222"


# ---------------------------------------------------------------------------
# normalización de usuario (Mejora 2)
# ---------------------------------------------------------------------------

class TestNormalizeUsername:
    def test_plain_username_preserved(self):
        assert accounts.normalize_username("ijesusmartinez") == "ijesusmartinez"

    def test_email_converted_to_username(self):
        assert accounts.normalize_username("ijesusmartinez@uniguajira.edu.co") == "ijesusmartinez"

    def test_surrounding_spaces_removed(self):
        assert accounts.normalize_username("  ijesusmartinez  ") == "ijesusmartinez"

    def test_uppercase_lowered(self):
        assert accounts.normalize_username("IJESUSMARTINEZ") == "ijesusmartinez"

    def test_email_with_spaces_and_uppercase(self):
        assert accounts.normalize_username("  IJESUSMARTINEZ@uniguajira.edu.co  ") == "ijesusmartinez"

    def test_empty_or_blank(self):
        assert accounts.normalize_username("") == ""
        assert accounts.normalize_username("   ") == ""


# ---------------------------------------------------------------------------
# cambio de facultad (Mejoras 1, 5, 6) con mocks
# ---------------------------------------------------------------------------

@pytest.fixture()
def dedup_in_tmp(tmp_path, monkeypatch):
    """Redirige los archivos de dedup a tmp_path para no tocar el proyecto."""
    monkeypatch.setattr(
        accounts.moodle_api,
        "_sent_notifications_file",
        lambda user_id: tmp_path / f"sn_{user_id}.json",
    )
    return tmp_path


class TestFacultyChange:
    def test_select_faculty_returns_selected_instance(self, fake_login, isolated_db):
        """Usuario selecciona facultad correctamente (1)."""
        chat = _setup_user(fake_login, isolated_db)
        instance, count = fake_login.validate_login(chat, "ciencias_salud", "alumno", "pass")
        assert instance.instance_id == "ciencias_salud"
        assert count == 19

    def test_validate_does_not_persist_before_apply(self, fake_login, isolated_db, isolated_security):
        """La validación contra la nueva instancia NO toca la cuenta actual."""
        chat = _setup_user(fake_login, isolated_db)
        fake_login.validate_login(chat, "educacion", "alumno", "pass")
        user = isolated_db.get_user_by_chat_id(chat)
        assert user["moodle_instance_id"] == "ingenierias"

    def test_change_ingenierias_to_educacion_ok(self, fake_login, isolated_db, isolated_security, dedup_in_tmp):
        """Usuario cambia de Ingenierías a Educación exitosamente (2)."""
        chat = _setup_user(fake_login, isolated_db)
        (dedup_in_tmp / f"sn_{chat}.json").write_text('{"old": 1}')

        instance, count = fake_login.validate_login(chat, "educacion", "alumno", "nuevapass")
        assert instance.instance_id == "educacion"
        assert count == 19

        fake_login.apply_faculty_change(chat, "educacion", "alumno", "nuevapass")

        user = isolated_db.get_user_by_chat_id(chat)
        assert user["moodle_instance_id"] == "educacion"
        assert isolated_security.decrypt(user["moodle_password_encrypted"]) == "nuevapass"
        assert user["last_sync_at"] is not None
        # el dedup de la instancia anterior se reinicia
        assert not (dedup_in_tmp / f"sn_{chat}.json").exists()

    def test_change_educacion_to_salud_ok(self, fake_login, isolated_db, isolated_security):
        """Usuario cambia de Educación a Ciencias de la Salud exitosamente (3)."""
        chat = _setup_user(fake_login, isolated_db, instance="educacion")

        instance, _ = fake_login.validate_login(chat, "ciencias_salud", "alumno", "pass")
        fake_login.apply_faculty_change(chat, "ciencias_salud", "alumno", "pass")

        user = isolated_db.get_user_by_chat_id(chat)
        assert user["moodle_instance_id"] == "ciencias_salud"
        assert isolated_security.decrypt(user["moodle_password_encrypted"]) == "pass"

    def test_change_bad_credentials_keeps_previous(self, fake_login, isolated_db, isolated_security, monkeypatch):
        """Cambio con credenciales incorrectas: se conserva la instancia anterior (4, 6)."""
        chat = _setup_user(fake_login, isolated_db)  # ingenierias

        def failing_factory(*a, **k):
            return FakeClient(*a, should_fail=True)

        monkeypatch.setattr(fake_login, "MoodleClient", failing_factory)

        with pytest.raises(fake_login.LoginError):
            fake_login.validate_login(chat, "educacion", "alumno", "malapass")

        user = isolated_db.get_user_by_chat_id(chat)
        assert user["moodle_instance_id"] == "ingenierias"
        assert isolated_security.decrypt(user["moodle_password_encrypted"]) == "pass"

    def test_failed_change_then_original_still_works(self, fake_login, isolated_db, isolated_security, monkeypatch):
        """Tras un fallo, la cuenta anterior sigue funcionando (6)."""
        chat = _setup_user(fake_login, isolated_db)

        def failing_factory(*a, **k):
            return FakeClient(*a, should_fail=True)

        monkeypatch.setattr(fake_login, "MoodleClient", failing_factory)
        with pytest.raises(fake_login.LoginError):
            fake_login.validate_login(chat, "educacion", "alumno", "malapass")

        monkeypatch.setattr(fake_login, "MoodleClient", FakeClient)
        instance, _ = fake_login.validate_login(chat, "ingenierias", "alumno", "pass")
        assert instance.instance_id == "ingenierias"

    def test_account_status_shows_current_instance(self, fake_login, isolated_db):
        """/cuenta muestra la instancia actual (6)."""
        chat = _setup_user(fake_login, isolated_db)
        info = fake_login.account_status(chat)
        assert info["instance_id"] == "ingenierias"
        assert info["instance_name"] == "Ingenierías (FIUG)"
        assert info["instance_base_url"] == "https://akumajafiug.uniguajira.edu.co"
        assert info["username"] == "alumno"

    def test_other_user_cannot_affect_this_user(self, fake_login, isolated_db, isolated_security):
        """Otro usuario no puede afectar la instancia de este usuario (12)."""
        fake_login.perform_login("111", "ingenierias", "alumnoA", "passA")
        fake_login.perform_login("222", "educacion", "alumnoB", "passB")

        fake_login.validate_login("111", "ciencias_salud", "alumnoA", "passA")
        fake_login.apply_faculty_change("111", "ciencias_salud", "alumnoA", "passA")

        assert isolated_db.get_user_by_chat_id("111")["moodle_instance_id"] == "ciencias_salud"
        assert isolated_db.get_user_by_chat_id("222")["moodle_instance_id"] == "educacion"
        assert isolated_db.get_user_by_chat_id("222")["moodle_username"] == "alumnoB"


# ---------------------------------------------------------------------------
# flujo de /cambiar_facultad en bot.py (con fakes mínimos)
# ---------------------------------------------------------------------------

class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.edited = []
        self.last_kwargs = {}
        self.answered = False

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text, **kwargs):
        self.edited.append(text)
        self.last_kwargs = kwargs


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def _setup_user(accounts_, db_, instance="ingenierias"):
    chat = "777"
    accounts_.perform_login(chat, instance, "alumno", "pass")
    return chat


class TestFacultyChangeFlow:
    def _make_update(self, query, chat_id):
        return SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(id=str(chat_id)))

    def test_faculty_selection_shows_all_options_with_current_marked(self):
        """/cambiar_facultad muestra las opciones y marca la actual (7)."""
        import bot as bot_module

        buttons = bot_module._build_faculty_selection("ingenierias")
        labels = [btn[0].text for btn in buttons]
        assert "✅ Ingenierías (FIUG) (actual)" in labels
        assert "Educación" in labels
        assert "Ciencias de la Salud" in labels
        assert "Centro de Lenguas y Postgrados" in labels
        assert len(buttons) == 8  # 7 instancias + Cancelar
        assert labels[-1] == "❌ Cancelar"

    def test_cancel_button_preserves_account(self, fake_login, isolated_db, isolated_security):
        """Cancelar cambio no modifica nada (11)."""
        import bot as bot_module

        chat = _setup_user(fake_login, isolated_db)

        ctx = FakeCtx()
        ctx.user_data["cf_instance_id"] = "educacion"
        query = FakeQuery("cf_cancel")
        update = self._make_update(query, chat)

        result = asyncio.run(bot_module.cf_cancel(update, ctx))
        assert result == bot_module.ConversationHandler.END
        assert "no cambió" in query.edited[0]

        user = isolated_db.get_user_by_chat_id(chat)
        assert user["moodle_instance_id"] == "ingenierias"
        assert isolated_security.decrypt(user["moodle_password_encrypted"]) == "pass"

    def test_confirm_no_preserves_account(self, fake_login, isolated_db, isolated_security):
        """Pulsar Cancelar en la confirmación no modifica nada (5, 11)."""
        import bot as bot_module

        chat = _setup_user(fake_login, isolated_db)

        ctx = FakeCtx()
        ctx.user_data["cf_instance_id"] = "educacion"
        query = FakeQuery("cf_confirm:no")
        update = self._make_update(query, chat)

        result = asyncio.run(bot_module.cf_confirm(update, ctx))
        assert result == bot_module.ConversationHandler.END
        assert "no cambió" in query.edited[0]

        user = isolated_db.get_user_by_chat_id(chat)
        assert user["moodle_instance_id"] == "ingenierias"

    def test_confirm_yes_asks_for_credentials(self, fake_login, isolated_db, isolated_security):
        """Continuar pide las credenciales (5)."""
        import bot as bot_module

        chat = _setup_user(fake_login, isolated_db)

        ctx = FakeCtx()
        ctx.user_data["cf_instance_id"] = "educacion"
        query = FakeQuery("cf_confirm:yes")
        update = self._make_update(query, chat)

        result = asyncio.run(bot_module.cf_confirm(update, ctx))
        assert result == bot_module.CF_USERNAME
        assert "educacion" in query.edited[0].lower() or "Educación" in query.edited[0]
        assert "uniguajira.edu.co" in query.edited[0]

        # La cuenta NO cambió todavía (la validación no ha ocurrido)
        user = isolated_db.get_user_by_chat_id(chat)
        assert user["moodle_instance_id"] == "ingenierias"


# ---------------------------------------------------------------------------
# barra de botones persistente (ReplyKeyboardMarkup)
# ---------------------------------------------------------------------------

class TestMenuKeyboard:
    def test_logged_in_menu(self):
        """Logueado: sin /login, con /logout y comandos de contenido."""
        import bot as bot_module

        kb = bot_module._menu_keyboard(logged_in=True)
        labels = [b.text for row in kb.keyboard for b in row]

        assert "/start" in labels
        assert "/ayuda" in labels
        assert "/cursos" in labels
        assert "/tareas" in labels
        assert "/notificaciones" in labels
        assert "/cuenta" in labels
        assert "/cambiar_facultad" in labels
        assert "/logout" in labels
        assert "/login" not in labels

    def test_not_logged_in_menu(self):
        """No logueado: con /login, sin /logout ni comandos de contenido."""
        import bot as bot_module

        kb = bot_module._menu_keyboard(logged_in=False)
        labels = [b.text for row in kb.keyboard for b in row]

        assert "/start" in labels
        assert "/login" in labels
        assert "/ayuda" in labels
        assert "/logout" not in labels
        assert "/cursos" not in labels
        assert "/cuenta" not in labels


# ---------------------------------------------------------------------------
# flujo de /login en bot.py (con fakes mínimos)
# ---------------------------------------------------------------------------

class TestLoginFlow:
    def _make_update(self, query, chat_id="999"):
        return SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(id=chat_id))

    def test_instance_selected_uses_generic_example_and_change_button(self):
        """El mensaje usa un ejemplo genérico y ofrece cambiar de facultad."""
        import bot as bot_module

        ctx = FakeCtx()
        query = FakeQuery("inst:educacion")
        update = self._make_update(query)

        result = asyncio.run(bot_module.login_instance_selected(update, ctx))

        assert result == bot_module.LOGIN_USERNAME
        assert ctx.user_data["login_instance_id"] == "educacion"

        text = query.edited[0]
        assert "ijesusmartinez" not in text          # no expone tu usuario real
        assert "nombre.apellido@uniguajira.edu.co" in text

        # el botón para corregir la facultad está en el teclado inline
        markup = query.last_kwargs.get("reply_markup")
        assert markup is not None
        flat = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
        ]
        assert "login_change_faculty" in flat

    def test_change_faculty_button_returns_to_selection(self):
        """El botón 'Cambiar facultad' vuelve al listado de facultades."""
        import bot as bot_module

        ctx = FakeCtx()
        ctx.user_data["login_instance_id"] = "educacion"
        ctx.user_data["login_username"] = "alumno"
        query = FakeQuery("login_change_faculty")
        update = self._make_update(query)

        result = asyncio.run(bot_module.login_change_faculty(update, ctx))

        assert result == bot_module.LOGIN_INSTANCE
        assert "login_instance_id" not in ctx.user_data
        assert "login_username" not in ctx.user_data
        assert "facultad" in query.edited[0].lower()