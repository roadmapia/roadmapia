"""
Rate limiting en memoria para endpoints sensibles (login, registro, recuperar).
Sin dependencias externas. Funciona por IP, usando ventana deslizante.
Nota: los contadores se pierden al reiniciar el servidor (aceptable con SQLite/single-server).
"""
import time
from collections import defaultdict

# Diccionario: clave → lista de timestamps de llamadas
_buckets: dict[str, list[float]] = defaultdict(list)


def is_allowed(key: str, max_calls: int, window_secs: int) -> bool:
    """
    Devuelve True si la llamada está permitida, False si se supera el límite.

    Parámetros:
    - key: identificador único, p.ej. "login:192.168.1.1"
    - max_calls: número máximo de llamadas permitidas en la ventana
    - window_secs: tamaño de la ventana en segundos
    """
    now = time.monotonic()
    cutoff = now - window_secs
    # Limpiar entradas caducadas y filtrar en un solo paso
    _buckets[key] = [t for t in _buckets[key] if t > cutoff]
    if len(_buckets[key]) >= max_calls:
        return False
    _buckets[key].append(now)
    return True


def get_client_ip(request) -> str:
    """
    Extrae la IP real del cliente teniendo en cuenta proxies (nginx).
    Prioridad: X-Real-IP > X-Forwarded-For[0] > request.client.host
    """
    # nginx suele setear X-Real-IP directamente
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    # Fallback: primera IP de la cadena de proxies
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return getattr(request.client, "host", "unknown") or "unknown"
