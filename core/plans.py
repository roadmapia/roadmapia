from datetime import date, datetime, timedelta
import secrets
import string

PLANS = {
    "free": {
        "nombre": "Gratuito",
        "precio": 0,
        "roadmaps_mes": 1,
        "mensajes_tutor_dia": 5,   # 5 base + 5 bonus reseña = 10 (igual que antes)
        "anuncios": True,
        "certificado": False
    },
    "basic": {
        "nombre": "Básico",
        "precio": 7,
        "roadmaps_mes": 5,
        "mensajes_tutor_dia": 50,
        "anuncios": False,
        "certificado": False
    },
    "pro": {
        "nombre": "Pro",
        "precio": 17,
        "roadmaps_mes": -1,
        "mensajes_tutor_dia": -1,
        "anuncios": False,
        "certificado": True
    }
}


def generar_referral_code() -> str:
    """Genera un código de referido único de 8 caracteres."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))


def get_plan_efectivo(user) -> str:
    """Devuelve el plan real considerando el bonus de referido."""
    if user.plan_bonus_expires and datetime.utcnow() < user.plan_bonus_expires:
        # Bonus activo: al menos plan basic
        if user.plan == "free":
            return "basic"
    return user.plan


def aplicar_bonus_referido(user, db, meses: int = 1):
    """Aplica o extiende 1 mes de plan Básico gratis al usuario."""
    ahora = datetime.utcnow()
    if user.plan_bonus_expires and user.plan_bonus_expires > ahora:
        # Extender el bonus existente
        user.plan_bonus_expires = user.plan_bonus_expires + timedelta(days=30 * meses)
    else:
        user.plan_bonus_expires = ahora + timedelta(days=30 * meses)
    # Actualizar el plan si era free
    if user.plan == "free":
        user.plan = "basic"
    db.commit()
    db.refresh(user)


def reset_counters_if_needed(user, db):
    """Resetea contadores diarios/mensuales y expira el bonus si procede."""
    today = date.today()
    ahora = datetime.utcnow()
    changed = False

    # Expirar bonus de referido si ha pasado el mes
    if user.plan_bonus_expires and user.plan_bonus_expires <= ahora:
        if user.plan == "basic" and not user.stripe_subscription_id:
            user.plan = "free"
        user.plan_bonus_expires = None
        changed = True

    # Resetear mensajes del tutor cada día
    if user.fecha_reset_mensajes != today:
        user.mensajes_hoy = 0
        user.fecha_reset_mensajes = today
        changed = True

    # Resetear roadmaps cada mes (el día 1 o si cambió el mes)
    if user.fecha_reset_roadmaps.month != today.month or user.fecha_reset_roadmaps.year != today.year:
        user.roadmaps_este_mes = 0
        user.fecha_reset_roadmaps = today
        changed = True

    if changed:
        db.commit()
        db.refresh(user)

    return user


def can_create_roadmap(user, db) -> tuple[bool, str]:
    """Retorna (puede_crear, mensaje_error)."""
    user = reset_counters_if_needed(user, db)
    plan = PLANS[user.plan]
    limite = plan["roadmaps_mes"]

    if limite == -1:
        return True, ""

    if user.roadmaps_este_mes >= limite:
        return False, f"Has alcanzado el límite de {limite} roadmap(s) este mes con tu plan {plan['nombre']}."

    return True, ""


def get_limite_mensajes(user) -> int:
    """Devuelve el límite diario real sumando el bonus de reseña."""
    plan = PLANS[user.plan]
    base = plan["mensajes_tutor_dia"]
    if base == -1:
        return -1
    bonus = getattr(user, 'mensajes_bonus_resena', 0) or 0
    return base + bonus


def can_send_tutor_message(user, db) -> tuple[bool, str]:
    """Retorna (puede_enviar, mensaje_error)."""
    user = reset_counters_if_needed(user, db)
    limite = get_limite_mensajes(user)

    if limite == -1:
        return True, ""

    if user.mensajes_hoy >= limite:
        plan_nombre = PLANS[user.plan]["nombre"]
        return False, f"Has alcanzado el límite de {limite} mensajes diarios con tu plan {plan_nombre}."

    return True, ""
