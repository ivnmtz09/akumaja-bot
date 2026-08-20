"""Registro central de instancias Moodle de Akumaja.

Cada dependencia/facultad de la universidad tiene su propia instancia
Moodle. Este módulo es la ÚNICA fuente de verdad para las URLs.

Para agregar una nueva instancia:
    from moodle_instances import registry
    registry.add("mi_facultad", "Mi Facultad", "https://akumajami.uniguajira.edu.co")
"""

from urllib.parse import urlparse


class MoodleInstance:
    """Una instancia Moodle con nombre visible y URL base normalizada."""

    def __init__(self, instance_id, name, base_url):
        self.instance_id = instance_id
        self.name = name
        self.base_url = self._normalize(base_url)

    @staticmethod
    def _normalize(url):
        url = url.strip()
        if url.endswith("/"):
            url = url[:-1]
        # Quitar rutas de entrada tipo /login/index.php
        for suffix in ("/login/index.php", "/login", "/index.php"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
        return url

    def url_for(self, path):
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{path}"

    def __repr__(self):
        return f"<MoodleInstance {self.instance_id}: {self.base_url}>"


MOODLE_INSTANCES = {
    "ciencias_basicas": {
        "name": "Ciencias Básicas",
        "base_url": "https://akumajafcbasicas.uniguajira.edu.co",
    },
    "ciencias_salud": {
        "name": "Ciencias de la Salud",
        "base_url": "https://akumajafcsalud.uniguajira.edu.co",
    },
    "educacion": {
        "name": "Educación",
        "base_url": "https://akumajafaced.uniguajira.edu.co",
    },
    "ciencias_sociales": {
        "name": "Ciencias Sociales",
        "base_url": "https://akumajafcsociales.uniguajira.edu.co",
    },
    "ingenierias": {
        "name": "Ingenierías (FIUG)",
        "base_url": "https://akumajafiug.uniguajira.edu.co",
    },
    "faceya": {
        "name": "FACEYA",
        "base_url": "https://akumajafaceya.uniguajira.edu.co",
    },
    "lenguas_postgrados": {
        "name": "Centro de Lenguas y Postgrados",
        "base_url": "https://virtual.uniguajira.edu.co",
    },
}


class MoodleInstanceRegistry:
    """Registro único de instancias Moodle."""

    _instances = {}

    @classmethod
    def load_defaults(cls):
        for instance_id, data in MOODLE_INSTANCES.items():
            cls._instances[instance_id] = MoodleInstance(
                instance_id,
                data["name"],
                data["base_url"],
            )

    @classmethod
    def get(cls, instance_id):
        return cls._instances.get(instance_id)

    @classmethod
    def all(cls):
        """Retorna lista de (instance_id, MoodleInstance) ordenada por nombre."""
        return sorted(
            cls._instances.items(),
            key=lambda item: item[1].name,
        )

    @classmethod
    def add(cls, instance_id, name, base_url):
        """Registra una instancia nueva (o reemplaza una existente)."""
        cls._instances[instance_id] = MoodleInstance(instance_id, name, base_url)
        return cls._instances[instance_id]

    @classmethod
    def match_base_url(cls, base_url):
        """Busca la instancia cuyo host coincide con la URL dada."""
        try:
            host = urlparse(base_url).hostname
        except Exception:
            return None

        if not host:
            return None

        for instance_id, instance in cls._instances.items():
            if urlparse(instance.base_url).hostname == host:
                return instance_id
        return None


registry = MoodleInstanceRegistry()
registry.load_defaults()