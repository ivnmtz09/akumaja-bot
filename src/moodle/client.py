"""Cliente Moodle por usuario: envuelve src.moodle.api con sesión propia.

Cada usuario tiene su propia sesión HTTP aislada en el diccionario
``api._sessions_cache``, usando ``cache_key`` (normalmente el
``telegram_chat_id``) como clave.  Nunca se comparte una sesión entre
usuarios distintos.

Si una sesión expira (403, sesskey ausente, cookie muerta), el cliente
la invalida del caché y vuelve a iniciar sesión de forma silenciosa
en un único reintento.
"""

import logging

from src.moodle import api as moodle_api

logger = logging.getLogger(__name__)


class MoodleClient:
    """Cliente de Moodle para una cuenta específica.

    Parameters
    ----------
    base_url : str
        URL base de la instancia Moodle (sin ``/login/index.php``).
    username : str
        Usuario Moodle (credencial desencriptada).
    password : str
        Contraseña Moodle (credencial desencriptada).
    cache_key : str | None
        Clave para el caché de sesiones (``telegram_chat_id`` o
        ``moodle_username``).  Si es ``None`` se usa ``username``.
    """

    def __init__(self, base_url, username, password, *, cache_key=None):
        self.base_url = base_url
        self.username = username
        self.password = password
        self._cache_key = cache_key if cache_key is not None else username

    # ---- sesión --------------------------------------------------------

    @property
    def session(self):
        """Retorna la sesión cacheada o inicia sesión y la cachea."""
        return moodle_api.login(
            moodle_url=self.base_url,
            username=self.username,
            password=self.password,
            cache_key=self._cache_key,
        )

    def _invalidate(self):
        """Elimina la sesión de este usuario del caché global."""
        moodle_api.invalidate_session(self._cache_key)

    # ---- retry transparente -------------------------------------------

    def _call_with_retry(self, api_fn, *args, **kwargs):
        """Ejecuta ``api_fn(session, ...)``, reintentando una vez si la sesión expiró.

        En el primer intento se usa la sesión cacheada.  Si falla con un
        error que indica sesión inválida (403, sesskey, etc.) se invalida
        la sesión, se obtiene una nueva y se reintenta **una sola vez**.
        """
        try:
            return api_fn(self.session, *args, **kwargs)
        except (RuntimeError, Exception) as exc:
            if moodle_api._is_session_expired(exc):
                logger.warning(
                    "Sesión expirada para %s (%s), re-autenticando...",
                    self._cache_key, exc,
                )
                self._invalidate()
                # Segundo intento con sesión fresca; si falla, se propaga.
                return api_fn(self.session, *args, **kwargs)
            raise

    # ---- API de alto nivel -------------------------------------------

    def get_courses(self):
        return self._call_with_retry(
            moodle_api.get_courses, moodle_url=self.base_url,
        )

    def get_upcoming_events(self, days_ahead=30):
        return self._call_with_retry(
            moodle_api.get_upcoming_events,
            days_ahead=days_ahead,
            moodle_url=self.base_url,
        )

    def get_all_calendar_events(self):
        return self._call_with_retry(
            moodle_api.get_all_calendar_events, moodle_url=self.base_url,
        )

    def get_recent_activity(self, course_ids=None, days_back=7):
        return self._call_with_retry(
            moodle_api.get_recent_activity,
            course_ids=course_ids,
            days_back=days_back,
            moodle_url=self.base_url,
        )

    def get_notifications_summary(self):
        return self._call_with_retry(
            moodle_api.get_notifications_summary, moodle_url=self.base_url,
        )

    def check_new_notifications(self, user_id=None):
        return self._call_with_retry(
            moodle_api.check_new_notifications,
            moodle_url=self.base_url,
            user_id=user_id,
        )

    # ---- ciclo de vida ------------------------------------------------

    def logout(self):
        """Cierra y elimina la sesión del caché (no cierra la sesión Moodle real)."""
        self._invalidate()

    def validate(self):
        """Intenta un login real para validar credenciales.

        Invalida cualquier sesión previa para forzar una autenticación
        limpia.  Lanza excepción si las credenciales son incorrectas.
        """
        self._invalidate()
        # Forzar login fresco (session property llama a api.login)
        _ = self.session
        return True
