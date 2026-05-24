import os
import secrets
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

from database.database import get_db
from database.models import User, PasswordResetToken
from core.auth import hash_password, verify_password, verify_password_safe, create_access_token, get_current_user_from_token
from core.email import send_email, reset_password_email
from core.rate_limit import is_allowed, get_client_ip
from typing import Optional

load_dotenv()
from core.plans import generar_referral_code, aplicar_bonus_referido

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")

RECAPTCHA_SECRET = os.getenv("RECAPTCHA_SECRET_KEY", "")
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8001")
GOOGLE_REDIRECT_URI = f"{BASE_URL}/auth/google/callback"


async def verify_recaptcha(token: str) -> bool:
    """Verifica el token reCAPTCHA con Google. Si no hay secret configurado, permite pasar."""
    if not RECAPTCHA_SECRET or not token:
        return not bool(RECAPTCHA_SECRET)  # Si hay secret y no hay token, falla
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://www.google.com/recaptcha/api/siteverify",
                data={"secret": RECAPTCHA_SECRET, "response": token},
                timeout=5.0
            )
            return r.json().get("success", False)
    except Exception:
        return True  # Si falla la red, dejamos pasar (mejor experiencia)


# ─────────────────────────────────────────
#  REGISTER
# ─────────────────────────────────────────
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {
        "request": request,
        "recaptcha_site_key": RECAPTCHA_SITE_KEY,
        "google_client_id": GOOGLE_CLIENT_ID,
    })


@router.post("/register")
async def register(
    request: Request,
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    acepta_terminos: Optional[str] = Form(None),
    acepta_marketing: Optional[str] = Form(None),
    ref: Optional[str] = Form(None),
    g_recaptcha_response: str = Form("", alias="g-recaptcha-response"),
    db: Session = Depends(get_db)
):
    def error(msg):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": msg,
            "recaptcha_site_key": RECAPTCHA_SITE_KEY,
            "google_client_id": GOOGLE_CLIENT_ID,
        })

    # Rate limit: 5 registros por IP por minuto
    ip = get_client_ip(request)
    if not is_allowed(f"register:{ip}", max_calls=5, window_secs=60):
        return error("Demasiados intentos. Espera 1 minuto antes de intentarlo de nuevo.")

    if not acepta_terminos:
        return error("Debes aceptar los términos y la política de privacidad para registrarte.")

    if RECAPTCHA_SECRET:
        ok = await verify_recaptcha(g_recaptcha_response)
        if not ok:
            return error("Por favor completa el captcha para continuar.")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return error("Ya existe una cuenta con ese email.")

    if len(password) < 8:
        return error("La contraseña debe tener al menos 8 caracteres.")

    # Buscar referidor
    referidor = None
    if ref:
        referidor = db.query(User).filter(User.referral_code == ref.upper()).first()

    user = User(
        email=email,
        password_hash=hash_password(password),
        nombre=nombre,
        plan="free",
        fecha_reset_roadmaps=date.today(),
        fecha_reset_mensajes=date.today(),
        acepta_marketing=bool(acepta_marketing),
        referral_code=generar_referral_code(),
        referred_by_id=referidor.id if referidor else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Aplicar bonus de referido
    if referidor:
        aplicar_bonus_referido(user, db)         # nuevo usuario: 1 mes gratis
        referidor.referidos_count = (referidor.referidos_count or 0) + 1
        aplicar_bonus_referido(referidor, db)    # referidor: también 1 mes gratis
        print(f"🎁 Referido activado: user#{referidor.id} → user#{user.id} (ambos +1 mes Basic)")

    token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie("access_token", token, httponly=True, secure=True, samesite="lax", max_age=60*60*24*30)
    return response


# ─────────────────────────────────────────
#  LOGIN
# ─────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "recaptcha_site_key": RECAPTCHA_SITE_KEY,
        "google_client_id": GOOGLE_CLIENT_ID,
    })


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    recordarme: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    def error(msg):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": msg,
            "recaptcha_site_key": RECAPTCHA_SITE_KEY,
            "google_client_id": GOOGLE_CLIENT_ID,
        })

    # Rate limit: 5 intentos por IP por minuto
    ip = get_client_ip(request)
    if not is_allowed(f"login:{ip}", max_calls=5, window_secs=60):
        return error("Demasiados intentos. Espera 1 minuto antes de intentarlo de nuevo.")

    user = db.query(User).filter(User.email == email, User.activo == True).first()
    # verify_password_safe siempre ejecuta bcrypt aunque el usuario no exista (anti timing-attack)
    pwd_ok = verify_password_safe(password, user.password_hash if user else None)
    if not user or not pwd_ok:
        return error("Email o contraseña incorrectos.")

    # Generar código referido si no tiene
    if not user.referral_code:
        user.referral_code = generar_referral_code()
        db.commit()

    token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    max_age = 60 * 60 * 24 * 30 if recordarme else None  # 30 días o sesión
    response.set_cookie("access_token", token, httponly=True, secure=True, samesite="lax", max_age=max_age)
    return response


# ─────────────────────────────────────────
#  LOGOUT
# ─────────────────────────────────────────
@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response


# ─────────────────────────────────────────
#  RECUPERAR CONTRASEÑA
# ─────────────────────────────────────────
@router.get("/recuperar", response_class=HTMLResponse)
async def recuperar_page(request: Request):
    return templates.TemplateResponse("recuperar.html", {"request": request})


@router.post("/recuperar")
async def recuperar(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    # Rate limit: 3 intentos por IP por minuto (evitar spam de emails)
    ip = get_client_ip(request)
    if not is_allowed(f"recuperar:{ip}", max_calls=3, window_secs=60):
        return templates.TemplateResponse("recuperar.html", {
            "request": request,
            "error": "Demasiados intentos. Espera 1 minuto antes de intentarlo de nuevo."
        })

    # Siempre mostramos el mismo mensaje para no revelar si el email existe
    msg_ok = "Si ese email está registrado recibirás un enlace en unos minutos."

    user = db.query(User).filter(User.email == email, User.activo == True).first()
    if user:
        # Invalidar tokens anteriores
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.usado == False
        ).update({"usado": True})
        db.commit()

        token_str = secrets.token_urlsafe(32)
        token_obj = PasswordResetToken(
            user_id=user.id,
            token=token_str,
            expiry=datetime.utcnow() + timedelta(hours=1)
        )
        db.add(token_obj)
        db.commit()

        reset_url = f"{BASE_URL}/auth/reset/{token_str}"
        try:
            send_email(
                to=user.email,
                subject="Restablecer contraseña — RoadmapIA",
                html=reset_password_email(user.nombre, user.email, reset_url)
            )
        except Exception:
            pass  # No revelamos el error

    return templates.TemplateResponse("recuperar.html", {
        "request": request,
        "success": msg_ok
    })


@router.get("/reset/{token}", response_class=HTMLResponse)
async def reset_password_page(token: str, request: Request, db: Session = Depends(get_db)):
    token_obj = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token,
        PasswordResetToken.usado == False,
        PasswordResetToken.expiry > datetime.utcnow()
    ).first()

    if not token_obj:
        return templates.TemplateResponse("recuperar.html", {
            "request": request,
            "error": "El enlace no es válido o ha expirado. Solicita uno nuevo."
        })
    return templates.TemplateResponse("reset_password.html", {
        "request": request, "token": token
    })


@router.post("/reset/{token}")
async def reset_password(
    token: str,
    request: Request,
    password: str = Form(...),
    password2: str = Form(...),
    db: Session = Depends(get_db)
):
    token_obj = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token,
        PasswordResetToken.usado == False,
        PasswordResetToken.expiry > datetime.utcnow()
    ).first()

    if not token_obj:
        return templates.TemplateResponse("reset_password.html", {
            "request": request, "token": token,
            "error": "Enlace expirado. Solicita uno nuevo."
        })

    if password != password2:
        return templates.TemplateResponse("reset_password.html", {
            "request": request, "token": token,
            "error": "Las contraseñas no coinciden."
        })

    if len(password) < 8:
        return templates.TemplateResponse("reset_password.html", {
            "request": request, "token": token,
            "error": "La contraseña debe tener al menos 8 caracteres."
        })

    user = token_obj.user
    user.password_hash = hash_password(password)
    user.token_version = (user.token_version or 0) + 1  # invalidar tokens viejos
    token_obj.usado = True
    db.commit()

    return templates.TemplateResponse("recuperar.html", {
        "request": request,
        "success": "✅ Contraseña actualizada. Ya puedes iniciar sesión."
    })


# ─────────────────────────────────────────
#  GOOGLE OAUTH
# ─────────────────────────────────────────
@router.get("/google")
async def google_login(request: Request):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google OAuth no configurado")
    from urllib.parse import urlencode
    # Generar state anti-CSRF (se guarda en cookie httpOnly, no en sesión)
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": state,
    }
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
    response.set_cookie("oauth_state", state, httponly=True, secure=True, samesite="lax", max_age=300)
    return response


@router.get("/google/callback")
async def google_callback(request: Request, code: str = None, error: str = None, state: str = None, db: Session = Depends(get_db)):
    if error or not code:
        return RedirectResponse(url="/auth/login?error=google_cancel")
    # Verificar state anti-CSRF
    expected_state = request.cookies.get("oauth_state")
    if not expected_state or expected_state != state:
        return RedirectResponse(url="/auth/login?error=oauth_state_invalid")

    try:
        async with httpx.AsyncClient() as client:
            # Intercambiar code por access_token
            token_r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                timeout=10.0
            )
            tokens = token_r.json()
            if "access_token" not in tokens:
                raise ValueError("Token exchange failed")

            # Obtener info del usuario
            user_r = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
                timeout=10.0
            )
            g = user_r.json()

        google_id = g.get("sub")
        email = g.get("email")
        nombre = g.get("name") or email.split("@")[0]

        if not email:
            raise ValueError("No email from Google")

        # Buscar por google_id primero, luego por email
        user = db.query(User).filter(User.google_id == google_id).first()
        if not user:
            user = db.query(User).filter(User.email == email).first()

        if user:
            # Actualizar google_id si no lo tiene
            if not user.google_id:
                user.google_id = google_id
                db.commit()
        else:
            # Crear usuario nuevo
            user = User(
                email=email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                nombre=nombre,
                plan="free",
                google_id=google_id,
                fecha_reset_roadmaps=date.today(),
                fecha_reset_mensajes=date.today(),
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        jwt_token = create_access_token({"sub": str(user.id)})
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
        response.set_cookie("access_token", jwt_token, httponly=True, secure=True, samesite="lax", max_age=60*60*24*30)
        return response

    except Exception as e:
        return RedirectResponse(url=f"/auth/login?error=google_error")


# ─────────────────────────────────────────
#  ME
# ─────────────────────────────────────────
@router.get("/me")
async def me(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    user = get_current_user_from_token(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido")
    return {"id": user.id, "email": user.email, "nombre": user.nombre, "plan": user.plan}
