"""Seguridad: cifrado reversible de credenciales y saneado de logs.

Las contraseñas de Moodle se cifran con Fernet (AES-128-CBC + HMAC)
usando una clave maestra definida en AKUMAJA_ENCRYPTION_KEY.

Si la clave no está definida, se genera automáticamente un archivo
local `akumaja.key` (modo desarrollo). En producción SIEMPRE definir
AKUMAJA_ENCRYPTION_KEY en el entorno.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_FILE = Path(__file__).parent / "akumaja.key"


def _load_or_create_key():
    env_key = os.getenv("AKUMAJA_ENCRYPTION_KEY")
    if env_key:
        key = env_key.strip().encode()
        try:
            Fernet(key)
        except Exception as exc:
            raise RuntimeError("AKUMAJA_ENCRYPTION_KEY no es una clave Fernet válida.") from exc
        return key

    if KEY_FILE.exists():
        return KEY_FILE.read_bytes().strip()

    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    print("⚠️ AKUMAJA_ENCRYPTION_KEY no definida: se generó akumaja.key local.")
    print("   Para producción, define AKUMAJA_ENCRYPTION_KEY y elimina akumaja.key.")
    return key


_FERNET = None


def _fernet():
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_or_create_key())
    return _FERNET


def encrypt(plaintext):
    """Cifra una cadena (contraseña) y retorna el token."""
    if not plaintext:
        raise ValueError("No se puede cifrar un valor vacío.")
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token):
    """Descifra un token cifrado con encrypt()."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError("No se pudo descifrar la credencial. ¿Se rotó la clave?") from exc


def sanitize(text):
    """Redacta valores sensibles para logs."""
    if not text:
        return text
    return "***"


# Valores que nunca deben imprimirse en logs
SENSITIVE_KEYS = {
    "password",
    "pass",
    "contraseña",
    "token",
    "cookie",
    "session",
    "encryption_key",
    "authorization",
}