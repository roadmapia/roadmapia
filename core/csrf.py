"""
Protección CSRF para formularios sensibles.
Usa tokens HMAC firmados con SECRET_KEY, válidos 2 horas, ligados al user_id.
No requiere sesión ni cookie extra — el token va como campo oculto en el formulario.
"""
import hmac
import hashlib
import time
import secrets
import os
from dotenv import load_dotenv

load_dotenv()

_SECRET = os.getenv("SECRET_KEY", "").encode()


def generate_csrf_token(user_id: int) -> str:
    """
    Genera un token CSRF válido ~2 horas para el usuario dado.
    Formato: '{user_id}:{hora_unix}:{firma_hex}'
    """
    timestamp = str(int(time.time() // 3600))  # cambia cada hora
    msg = f"{user_id}:{timestamp}".encode()
    sig = hmac.new(_SECRET, msg, hashlib.sha256).hexdigest()[:20]
    return f"{user_id}:{timestamp}:{sig}"


def validate_csrf_token(token: str, user_id: int) -> bool:
    """
    Valida el token CSRF. Acepta el de la hora actual y el de la anterior (ventana ~2h).
    Retorna False si el token es inválido, expirado o no coincide con el user_id.
    """
    if not token or not _SECRET:
        return not bool(_SECRET)  # Si no hay SECRET configurado, permite (dev mode)
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        uid_str, ts_str, sig = parts
        if int(uid_str) != user_id:
            return False
        now = int(time.time() // 3600)
        if int(ts_str) not in (now, now - 1):  # ventana de hasta ~2 horas
            return False
        msg = f"{uid_str}:{ts_str}".encode()
        expected = hmac.new(_SECRET, msg, hashlib.sha256).hexdigest()[:20]
        return secrets.compare_digest(sig, expected)
    except Exception:
        return False
