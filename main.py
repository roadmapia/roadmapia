from fastapi import FastAPI, Request, Depends, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session

from database.database import init_db, get_db
from database.models import User, Roadmap
from routers import auth, roadmaps, progress, tutor, payments


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="RoadmapIA", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Registrar routers
app.include_router(auth.router)
app.include_router(roadmaps.router)
app.include_router(progress.router)
app.include_router(tutor.router)
app.include_router(payments.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    from core.auth import get_current_user_from_token
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    return templates.TemplateResponse("pricing.html", {"request": request, "user": user})


@app.get("/api/stats")
async def stats(db: Session = Depends(get_db)):
    """Estadísticas públicas reales de la plataforma."""
    usuarios = db.query(User).filter(User.activo == True).count()
    roadmaps_count = db.query(Roadmap).filter(Roadmap.activo == True).count()
    return JSONResponse({
        "usuarios": usuarios,
        "roadmaps": roadmaps_count,
        "temas": "∞",
        "respuesta_tutor": "< 3s"
    })


@app.get("/cuenta", response_class=HTMLResponse)
async def cuenta(request: Request, success: str = None, error: str = None):
    from core.auth import get_current_user_from_token
    from core.plans import PLANS
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    if not user:
        return RedirectResponse(url="/auth/login")
    from core.plans import get_plan_efectivo, generar_referral_code
    plan_info = PLANS[get_plan_efectivo(user)]
    # Generar código referido si no tiene
    if not user.referral_code:
        user.referral_code = generar_referral_code()
        db.commit()
    has_password = user.password_hash and len(user.password_hash) > 0
    return templates.TemplateResponse("cuenta.html", {
        "request": request, "user": user, "plan_info": plan_info,
        "has_password": has_password,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@app.post("/cuenta/perfil")
async def actualizar_perfil(request: Request, nombre: str = Form(...)):
    from core.auth import get_current_user_from_token
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    if not user:
        return RedirectResponse(url="/auth/login")
    if not nombre.strip():
        return RedirectResponse(url="/cuenta?error=El+nombre+no+puede+estar+vacío", status_code=302)
    user.nombre = nombre.strip()
    db.commit()
    return RedirectResponse(url="/cuenta?success=Datos+actualizados+correctamente", status_code=302)


@app.post("/cuenta/password")
async def cambiar_password(request: Request):
    from core.auth import get_current_user_from_token, verify_password, hash_password
    from fastapi import Form as FForm
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    if not user:
        return RedirectResponse(url="/auth/login")
    form = await request.form()
    actual = form.get("password_actual", "")
    nueva = form.get("password_nueva", "")
    nueva2 = form.get("password_nueva2", "")
    if not verify_password(actual, user.password_hash):
        return RedirectResponse(url="/cuenta?error=La+contraseña+actual+es+incorrecta", status_code=302)
    if nueva != nueva2:
        return RedirectResponse(url="/cuenta?error=Las+contraseñas+nuevas+no+coinciden", status_code=302)
    if len(nueva) < 6:
        return RedirectResponse(url="/cuenta?error=La+contraseña+debe+tener+al+menos+6+caracteres", status_code=302)
    user.password_hash = hash_password(nueva)
    db.commit()
    return RedirectResponse(url="/cuenta?success=Contraseña+cambiada+correctamente", status_code=302)


@app.post("/cuenta/eliminar")
async def eliminar_cuenta(request: Request):
    from core.auth import get_current_user_from_token
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    if not user:
        return JSONResponse({"ok": False})
    user.activo = False
    db.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie("access_token")
    return response


@app.get("/certificaciones", response_class=HTMLResponse)
async def certificaciones(request: Request):
    import json
    from core.auth import get_current_user_from_token
    from database.models import Roadmap, LessonProgress
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    if not user:
        return RedirectResponse(url="/auth/login")
    roadmaps_usuario = db.query(Roadmap).filter(
        Roadmap.user_id == user.id, Roadmap.activo == True
    ).all()
    completados = []
    for rm in roadmaps_usuario:
        contenido = json.loads(rm.contenido)
        total = sum(len(f["lecciones"]) for f in contenido.get("fases", []))
        progreso = db.query(LessonProgress).filter(
            LessonProgress.roadmap_id == rm.id,
            LessonProgress.user_id == user.id,
            LessonProgress.completada == True
        ).all()
        if total > 0 and len(progreso) >= total:
            fechas = [p.fecha_completada for p in progreso if p.fecha_completada]
            fecha = max(fechas).strftime("%d/%m/%Y") if fechas else "—"
            completados.append({"roadmap": rm, "total": total, "fecha_completado": fecha})
    return templates.TemplateResponse("certificaciones.html", {
        "request": request, "user": user,
        "completados": completados,
        "es_pro": user.plan == "pro",
    })


@app.post("/api/resena-completada")
async def marcar_resena(request: Request, db: Session = Depends(get_db)):
    """El usuario confirma que ha dejado una reseña → recibe +5 mensajes/día."""
    from core.auth import get_current_user_from_token
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    if not user.resena_completada:
        user.resena_completada = True
        user.mensajes_bonus_resena = 5
        db.commit()
        print(f"⭐ Reseña completada: {user.email} → +5 mensajes/día")
    return JSONResponse({"ok": True, "bonus": user.mensajes_bonus_resena})


@app.get("/r/{code}")
async def referral_redirect(code: str):
    """Redirección de link de referido al registro."""
    return RedirectResponse(url=f"/auth/register?ref={code.upper()}", status_code=302)


@app.get("/privacidad", response_class=HTMLResponse)
async def privacidad(request: Request):
    from core.auth import get_current_user_from_token
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    return templates.TemplateResponse("privacidad.html", {"request": request, "user": user})


@app.get("/terminos", response_class=HTMLResponse)
async def terminos(request: Request):
    from core.auth import get_current_user_from_token
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    return templates.TemplateResponse("terminos.html", {"request": request, "user": user})


@app.get("/soporte", response_class=HTMLResponse)
async def soporte(request: Request):
    from core.auth import get_current_user_from_token
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    return templates.TemplateResponse("soporte.html", {"request": request, "user": user})


@app.get("/blog", response_class=HTMLResponse)
async def blog(request: Request):
    from core.auth import get_current_user_from_token
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    articles = [
        {
            "slug": "como-aprender-python-desde-cero",
            "titulo": "Cómo aprender Python desde cero en 2025: la guía definitiva",
            "resumen": "Python es el lenguaje más demandado del mercado. Te explicamos por dónde empezar, qué recursos usar y cómo estructurar tu aprendizaje para llegar al nivel profesional.",
            "emoji": "🐍",
            "categoria": "Programación",
            "minutos": 8,
            "fecha": "15 de mayo, 2025"
        },
        {
            "slug": "aprender-con-ia-vs-cursos-tradicionales",
            "titulo": "Aprender con IA vs cursos tradicionales: ¿qué funciona mejor?",
            "resumen": "Comparamos los métodos de aprendizaje online más populares: plataformas de cursos, YouTube, tutores humanos y la nueva generación de tutores IA. ¿Cuál da mejores resultados?",
            "emoji": "🤖",
            "categoria": "Aprendizaje",
            "minutos": 6,
            "fecha": "10 de mayo, 2025"
        },
        {
            "slug": "roadmap-de-aprendizaje-que-es-y-por-que-necesitas-uno",
            "titulo": "Qué es un roadmap de aprendizaje y por qué necesitas uno",
            "resumen": "Aprender sin un plan estructurado es la causa número uno de abandono. Te explicamos qué es un roadmap, cómo crearlo y por qué cambia completamente los resultados.",
            "emoji": "🗺️",
            "categoria": "Productividad",
            "minutos": 5,
            "fecha": "5 de mayo, 2025"
        },
    ]
    return templates.TemplateResponse("blog.html", {"request": request, "user": user, "articles": articles})


@app.post("/api/soporte")
async def enviar_soporte(request: Request, db: Session = Depends(get_db)):
    """Recibe el formulario de soporte y envía email a soporte@roadmapia.com."""
    import smtplib
    import os
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    from database.models import SupportFAQ
    from core.cache_utils import normalizar_pregunta, buscar_similar

    body = await request.json()
    nombre  = body.get("nombre", "").strip()
    email   = body.get("email", "").strip()
    mensaje = body.get("mensaje", "").strip()

    if not nombre or not email or not mensaje:
        return JSONResponse({"ok": False, "error": "Faltan campos"}, status_code=400)

    # ── FAQ AUTOMÁTICO ──────────────────────────────────────────
    pregunta_norm = normalizar_pregunta(mensaje)

    # Buscar respuesta en la BD
    faq_exacta = db.query(SupportFAQ).filter(
        SupportFAQ.pregunta_normalizada == pregunta_norm,
        SupportFAQ.respondida == True
    ).first()

    if not faq_exacta:
        candidatos = db.query(SupportFAQ).filter(SupportFAQ.respondida == True).limit(200).all()
        faq_exacta = buscar_similar(pregunta_norm, candidatos)

    if faq_exacta:
        faq_exacta.usos += 1
        db.commit()
        print(f"💡 FAQ auto-respondida (×{faq_exacta.usos}): '{mensaje[:60]}'")
        return JSONResponse({"ok": True, "auto_respuesta": faq_exacta.respuesta})

    # Guardar pregunta sin respuesta (para que el admin la responda después)
    faq_pendiente = db.query(SupportFAQ).filter(
        SupportFAQ.pregunta_normalizada == pregunta_norm
    ).first()
    if not faq_pendiente:
        db.add(SupportFAQ(
            pregunta_normalizada=pregunta_norm,
            pregunta_original=f"[{nombre}] {mensaje}"
        ))
        db.commit()
        print(f"📥 Pregunta soporte guardada (sin respuesta): '{mensaje[:60]}'")

    smtp_host = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    support_email = os.getenv("SUPPORT_EMAIL", smtp_user)

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Soporte RoadmapIA] Consulta de {nombre}"
        msg["From"]    = smtp_user
        msg["To"]      = support_email
        msg["Reply-To"] = email

        import html as html_module
        mensaje_safe = html_module.escape(mensaje)
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;padding:24px;background:#f9f9f9;border-radius:8px">
          <h2 style="color:#7c6fff;margin-bottom:4px">Nueva consulta de soporte</h2>
          <p style="color:#888;font-size:13px;margin-top:0">RoadmapIA — Widget de soporte</p>
          <hr style="border:1px solid #eee;margin:16px 0">
          <p><strong>Nombre:</strong> {nombre}</p>
          <p><strong>Email:</strong> <a href="mailto:{email}">{email}</a></p>
          <p><strong>Consulta:</strong></p>
          <div style="background:#fff;border-left:4px solid #7c6fff;padding:12px 16px;border-radius:4px;margin-top:8px">
            {mensaje_safe.replace('\n', '<br>')}
          </div>
          <hr style="border:1px solid #eee;margin:16px 0">
          <p style="color:#aaa;font-size:12px">Responde a este email para contestar directamente al usuario.</p>
        </div>
        """
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, support_email, msg.as_string())

        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


BLOG_SLUGS_VALIDOS = {
    "como-aprender-python-desde-cero",
    "aprender-con-ia-vs-cursos-tradicionales",
    "roadmap-de-aprendizaje-que-es-y-por-que-necesitas-uno",
}

@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(slug: str, request: Request):
    import re
    from core.auth import get_current_user_from_token
    # Validar slug contra whitelist y patrón seguro
    if slug not in BLOG_SLUGS_VALIDOS or not re.match(r"^[a-z0-9-]+$", slug):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Artículo no encontrado")
    db = next(get_db())
    token = request.cookies.get("access_token")
    user = get_current_user_from_token(token, db) if token else None
    return templates.TemplateResponse(f"blog/{slug}.html", {"request": request, "user": user})
