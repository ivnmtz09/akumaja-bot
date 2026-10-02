"""Cliente Moodle por usuario: envuelve src.moodle.api con sesión propia.

Cada usuario tiene su propia sesión HTTP aislada en el diccionario
``api._sessions_cache``, usando el ``username`` de Moodle como clave.
Nunca se comparte una sesión entre usuarios distintos.

Si una sesión expira (403, sesskey ausente, cookie muerta), el cliente
la invalida del caché y vuelve a iniciar sesión de forma silenciosa
en un único reintento.
"""

import inspect
import logging

from src.moodle import api as moodle_api
from src.moodle.api import SessionExpiredError

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

    El caché de sesiones en ``api._sessions_cache`` se indexa por
    ``username``, garantizando aislamiento total entre estudiantes.
    """

    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.sesskey = None

    # ---- sesión --------------------------------------------------------

    @property
    def session(self):
        """Retorna la sesión cacheada o inicia sesión y la cachea."""
        return moodle_api.login(
            moodle_url=self.base_url,
            username=self.username,
            password=self.password,
        )

    def _invalidate(self):
        """Elimina la sesión de este usuario del caché global."""
        moodle_api.invalidate_session(self.username)

    # ---- retry transparente -------------------------------------------

    def _call_with_retry(self, api_fn, *args, **kwargs):
        """Ejecuta ``api_fn(session, ...)``, reintentando una vez si la sesión expiró.

        En el primer intento se usa la sesión cacheada. Si falla con un
        error que indica sesión inválida (SessionExpiredError, 403, servicerequireslogin, etc.),
        se invalida la sesión del caché global, se re-autentica desde cero con
        moodle_api.login(...), se extrae el nuevo sesskey, se inyecta en args o kwargs
        y se reintenta **una sola vez**.
        """
        # Inyectar sesskey si ya está establecido y kwargs lo espera
        if self.sesskey and "sesskey" in kwargs:
            kwargs["sesskey"] = self.sesskey

        try:
            return api_fn(self.session, *args, **kwargs)
        except (SessionExpiredError, Exception) as exc:
            if not (isinstance(exc, SessionExpiredError) or moodle_api._is_session_expired(exc)):
                raise

            logger.warning(
                "Sesión expirada para %s (%s). Re-autenticando silenciosamente...",
                self.username, exc,
            )

            # 1. Eliminar la sesión muerta del caché global
            self._invalidate()

            # 2. Re-autenticar desde cero obteniendo nueva sesión
            new_session = moodle_api.login(
                moodle_url=self.base_url,
                username=self.username,
                password=self.password,
            )

            # 3. Extraer y guardar nuevo sesskey
            self.sesskey = moodle_api.get_sesskey(new_session, self.base_url)

            # 4. Inyección del nuevo sesskey en kwargs si aplica
            if "sesskey" in kwargs:
                kwargs["sesskey"] = self.sesskey

            # 5. Inyección del nuevo sesskey en args posicionales (ej. call_ajax)
            # Firma típica: call_ajax(session, sesskey, method, args, moodle_url=None)
            args_list = list(args)
            try:
                sig = inspect.signature(api_fn)
                params = list(sig.parameters.keys())
                # Omitir el primer parámetro 'session' que se envía por separado
                remaining = params[1:] if len(params) > 1 else []
                if "sesskey" in remaining:
                    idx = remaining.index("sesskey")
                    if idx < len(args_list):
                        args_list[idx] = self.sesskey
            except Exception:
                if getattr(api_fn, "__name__", "") == "call_ajax" and len(args_list) > 0:
                    args_list[0] = self.sesskey

            args = tuple(args_list)

            # 6. Reintento único con sesión fresca y nuevo sesskey
            return api_fn(new_session, *args, **kwargs)

    def call_ajax(self, method, args, sesskey=None):
        """Realiza una petición AJAX a través del cliente con reintento automático."""
        sesskey = sesskey or self.sesskey
        return self._call_with_retry(
            moodle_api.call_ajax,
            sesskey,
            method,
            args,
            moodle_url=self.base_url,
        )

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
