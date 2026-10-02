"""Pruebas unitarias para la auto-recuperación transparente de sesión en Moodle."""

import time
from unittest.mock import MagicMock, patch
import pytest
import requests

from src.moodle import api as moodle_api
from src.moodle.api import SessionExpiredError
from src.moodle.client import MoodleClient


class TestDetectionFalse200And403:
    """Regla 1: Detección del falso 200 OK y HTTP 403 en api.py."""

    def test_call_ajax_servicerequireslogin_raises_session_expired(self):
        """Moodle responde HTTP 200 con exception.errorcode = 'servicerequireslogin'."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "error": True,
                "exception": {
                    "errorcode": "servicerequireslogin",
                    "message": "Esta función requiere que haya iniciado sesión.",
                },
            }
        ]
        mock_session.post.return_value = mock_response

        with pytest.raises(SessionExpiredError) as exc_info:
            moodle_api.call_ajax(
                mock_session,
                sesskey="expired_sesskey",
                method="core_calendar_get_action_events_by_timesort",
                args={"timesortfrom": 0},
                moodle_url="https://moodle.test",
            )
        assert "servicerequireslogin" in str(exc_info.value).lower()

    def test_call_ajax_direct_errorcode_raises_session_expired(self):
        """Moodle responde con errorcode directo 'servicerequireslogin'."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "error": True,
                "errorcode": "servicerequireslogin",
                "message": "Sesión expirada",
            }
        ]
        mock_session.post.return_value = mock_response

        with pytest.raises(SessionExpiredError):
            moodle_api.call_ajax(
                mock_session,
                sesskey="expired_sesskey",
                method="core_calendar_get_action_events_by_timesort",
                args={},
                moodle_url="https://moodle.test",
            )

    def test_call_ajax_http_403_raises_session_expired(self):
        """Moodle responde HTTP 403 Forbidden en AJAX."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 403
        http_err = requests.exceptions.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = http_err
        mock_session.post.return_value = mock_response

        with pytest.raises(SessionExpiredError):
            moodle_api.call_ajax(
                mock_session,
                sesskey="expired_sesskey",
                method="core_calendar_get_action_events_by_timesort",
                args={},
                moodle_url="https://moodle.test",
            )

    def test_call_ajax_business_error_raises_runtime_error(self):
        """Errores normales que no son de sesión deben seguir lanzando RuntimeError."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "error": True,
                "errorcode": "invalidcourseid",
                "message": "ID de curso no válido",
            }
        ]
        mock_session.post.return_value = mock_response

        with pytest.raises(RuntimeError) as exc_info:
            moodle_api.call_ajax(
                mock_session,
                sesskey="valid_sesskey",
                method="core_course_get_course_contents",
                args={"courseid": 9999},
                moodle_url="https://moodle.test",
            )
        assert not isinstance(exc_info.value, SessionExpiredError)
        assert "ID de curso no válido" in str(exc_info.value)

    def test_get_sesskey_redirect_to_login_raises_session_expired(self):
        """Si /my/courses.php redirige a /login/index.php, es sesión expirada."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://moodle.test/login/index.php"
        mock_response.text = "<html>Formulario de login</html>"
        mock_session.get.return_value = mock_response

        with pytest.raises(SessionExpiredError):
            moodle_api.get_sesskey(mock_session, "https://moodle.test")

    def test_get_sesskey_missing_sesskey_raises_session_expired(self):
        """Si la página no contiene sesskey, se levanta SessionExpiredError."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://moodle.test/my/courses.php"
        mock_response.text = "<html>Sin sesskey disponible</html>"
        mock_session.get.return_value = mock_response

        with pytest.raises(SessionExpiredError):
            moodle_api.get_sesskey(mock_session, "https://moodle.test")

    def test_get_sesskey_403_raises_session_expired(self):
        """HTTP 403 al obtener sesskey levanta SessionExpiredError."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_session.get.return_value = mock_response

        with pytest.raises(SessionExpiredError):
            moodle_api.get_sesskey(mock_session, "https://moodle.test")


class TestClientDeepReLoginAndSesskeyInjection:
    """Reglas 2 y 3: Re-login profundo e inyección de sesskey en client.py."""

    def test_client_stores_password(self):
        """MoodleClient almacena la contraseña para poder re-autenticar."""
        client = MoodleClient("https://moodle.test", "estudiante1", "password_secreta")
        assert client.password == "password_secreta"
        assert client.username == "estudiante1"
        assert client.base_url == "https://moodle.test"

    def test_call_with_retry_injects_new_sesskey_in_positional_args(self):
        """En call_ajax(session, sesskey, method, args), el retry debe inyectar el nuevo sesskey en args[0]."""
        client = MoodleClient("https://moodle.test", "estudiante1", "clave123")
        client.sesskey = "old_sesskey"

        call_records = []

        def fake_call_ajax(session, sesskey, method, args, moodle_url=None):
            call_records.append({"session": session, "sesskey": sesskey, "method": method})
            if len(call_records) == 1:
                # Primer intento: falla por sesión expirada
                raise SessionExpiredError("Sesión expirada")
            # Segundo intento: éxito
            return {"status": "ok"}

        mock_new_session = MagicMock(name="fresh_session")

        with patch.object(client, "_invalidate") as mock_invalidate, \
             patch("src.moodle.api.login", return_value=mock_new_session) as mock_login, \
             patch("src.moodle.api.get_sesskey", return_value="new_fresh_sesskey") as mock_get_sesskey:

            # Simular sesión inicial
            with patch.object(MoodleClient, "session", return_value=MagicMock(name="old_session")):
                result = client._call_with_retry(
                    fake_call_ajax,
                    "old_sesskey",
                    "core_calendar_get_action_events_by_timesort",
                    {"timesortfrom": 0},
                    moodle_url=client.base_url,
                )

        assert result == {"status": "ok"}
        assert len(call_records) == 2
        # El 1er intento usó el sesskey viejo
        assert call_records[0]["sesskey"] == "old_sesskey"
        # ¡El 2do intento recibió el nuevo sesskey en su argumento posicional!
        assert call_records[1]["sesskey"] == "new_fresh_sesskey"
        assert call_records[1]["session"] == mock_new_session

        mock_invalidate.assert_called_once()
        mock_login.assert_called_once_with(
            moodle_url="https://moodle.test",
            username="estudiante1",
            password="clave123",
        )
        assert client.sesskey == "new_fresh_sesskey"

    def test_call_with_retry_injects_new_sesskey_in_kwargs(self):
        """Si la función recibe sesskey en kwargs, el retry debe actualizarlo."""
        client = MoodleClient("https://moodle.test", "estudiante1", "clave123")

        call_records = []

        def fake_api_fn(session, moodle_url=None, sesskey=None):
            call_records.append({"session": session, "sesskey": sesskey})
            if len(call_records) == 1:
                raise SessionExpiredError("Sesión expirada")
            return [{"id": 1, "name": "Curso 1"}]

        mock_new_session = MagicMock(name="fresh_session")

        with patch.object(client, "_invalidate") as mock_invalidate, \
             patch("src.moodle.api.login", return_value=mock_new_session) as mock_login, \
             patch("src.moodle.api.get_sesskey", return_value="new_fresh_sesskey"):

            with patch.object(MoodleClient, "session", return_value=MagicMock(name="old_session")):
                result = client._call_with_retry(
                    fake_api_fn,
                    moodle_url=client.base_url,
                    sesskey="old_sesskey",
                )

        assert len(result) == 1
        assert len(call_records) == 2
        assert call_records[0]["sesskey"] == "old_sesskey"
        assert call_records[1]["sesskey"] == "new_fresh_sesskey"
        mock_invalidate.assert_called_once()
        mock_login.assert_called_once()

    def test_client_call_ajax_helper_method(self):
        """El método wrapper client.call_ajax delega a _call_with_retry y funciona."""
        client = MoodleClient("https://moodle.test", "estudiante1", "clave123")
        client.sesskey = "current_sesskey"

        with patch.object(client, "_call_with_retry", return_value={"data": 123}) as mock_cwr:
            res = client.call_ajax("test_method", {"param": 1})
            assert res == {"data": 123}
            mock_cwr.assert_called_once_with(
                moodle_api.call_ajax,
                "current_sesskey",
                "test_method",
                {"param": 1},
                moodle_url="https://moodle.test",
            )


class TestTransparentHandlerFlow:
    """Regla 4: Flujo transparente en /tareas y handlers."""

    def test_get_upcoming_events_transparent_recovery(self):
        """Simula exactamente lo que ocurre en /tareas:

        1. Se llama client.get_upcoming_events(days_ahead=30).
        2. La llamada AJAX inicial falla con servicerequireslogin (HTTP 200).
        3. El cliente se auto-recupera silenciosamente:
           - Invalida la sesión vieja.
           - Loguea de nuevo.
           - Extrae nuevo sesskey.
           - Reintenta la petición.
        4. Retorna la lista de eventos exitosamente sin error hacia el llamador.
        """
        client = MoodleClient("https://moodle.test", "estudiante1", "clave123")

        old_session = MagicMock(name="old_session")
        new_session = MagicMock(name="new_session")

        # Configurar llamada AJAX:
        # Primer intento -> servicerequireslogin
        # Segundo intento -> eventos válidos
        ajax_attempt = 0

        def fake_ajax_post(url, *args, **kwargs):
            nonlocal ajax_attempt
            ajax_attempt += 1
            resp = MagicMock()
            resp.status_code = 200
            event_time = int(time.time()) + 3600
            if ajax_attempt == 1:
                resp.json.return_value = [
                    {
                        "error": True,
                        "exception": {
                            "errorcode": "servicerequireslogin",
                            "message": "Sesión finalizada",
                        },
                    }
                ]
            else:
                resp.json.return_value = [
                    {
                        "data": {
                            "events": [
                                {
                                    "name": "Entrega Taller 3",
                                    "course": {"id": 10, "fullname": "Cálculo Integral"},
                                    "timestart": event_time,
                                    "timeend": 0,
                                    "url": "https://moodle.test/mod/assign/view.php?id=50",
                                }
                            ]
                        }
                    }
                ]
            return resp

        old_session.post.side_effect = fake_ajax_post
        new_session.post.side_effect = fake_ajax_post

        # Configurar get_sesskey para ambas sesiones
        def fake_get_sesskey(session, moodle_url=None):
            if session == old_session:
                return "old_sesskey"
            return "new_sesskey"

        with patch("src.moodle.api.get_sesskey", side_effect=fake_get_sesskey), \
             patch("src.moodle.api.login", return_value=new_session) as mock_login, \
             patch.object(moodle_api, "invalidate_session") as mock_invalidate:

            # Inyectar sesión inicial cacheada
            moodle_api._sessions_cache["estudiante1"] = old_session

            # Ejecutar /tareas vía el cliente
            events = client.get_upcoming_events(days_ahead=30)

        assert len(events) == 1
        assert events[0]["name"] == "Entrega Taller 3"
        assert events[0]["course_name"] == "Cálculo Integral"
        assert mock_invalidate.called
        assert mock_login.called
        assert client.sesskey == "new_sesskey"
