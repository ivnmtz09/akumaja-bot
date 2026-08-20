"""Cliente Moodle por usuario: envuelve get_courses con sesión propia.

Cada usuario tiene su propia instancia de MoodleClient con su sesión
HTTP independiente, credenciales y base_url. No comparte nada con
otros usuarios.
"""

import get_courses as moodle_api


class MoodleClient:
    """Cliente de Moodle para una cuenta específica."""

    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self._session = None

    @property
    def session(self):
        if self._session is None:
            self._session = moodle_api.login(
                moodle_url=self.base_url,
                username=self.username,
                password=self.password,
            )
        return self._session

    def logout(self):
        """Cierra la sesión HTTP local (no cierra la sesión Moodle real)."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def get_courses(self):
        return moodle_api.get_courses(self.session, moodle_url=self.base_url)

    def get_upcoming_events(self, days_ahead=30):
        return moodle_api.get_upcoming_events(
            self.session,
            days_ahead=days_ahead,
            moodle_url=self.base_url,
        )

    def get_all_calendar_events(self):
        return moodle_api.get_all_calendar_events(self.session, moodle_url=self.base_url)

    def get_recent_activity(self, course_ids=None, days_back=7):
        return moodle_api.get_recent_activity(
            self.session,
            course_ids=course_ids,
            days_back=days_back,
            moodle_url=self.base_url,
        )

    def get_notifications_summary(self):
        return moodle_api.get_notifications_summary(self.session, moodle_url=self.base_url)

    def check_new_notifications(self, user_id=None):
        return moodle_api.check_new_notifications(
            self.session,
            moodle_url=self.base_url,
            user_id=user_id,
        )

    def validate(self):
        """Intenta un login real para validar credenciales. Lanza excepción si falla."""
        self.logout()
        self.session  # fuerzo el login
        return True