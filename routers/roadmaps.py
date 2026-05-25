import json
import unicodedata
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database.database import get_db, SessionLocal
from database.models import Roadmap, LessonProgress, RoadmapCache
from core.ai_generator import generate_roadmap
from core.generation_queue import generation_queue
from core.plans import can_create_roadmap, PLANS, reset_counters_if_needed
from core.auth import get_current_user_from_token
from core.youtube import enrich_roadmap_with_youtube

CACHE_VIDEO_DAYS = 90  # refrescar vídeos cada 3 meses


def normalizar_tema(tema: str) -> str:
    """Normaliza el tema: minúsculas, sin acentos, sin espacios extra."""
    nfkd = unicodedata.normalize("NFKD", tema.lower().strip())
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sin_acentos.split())

router = APIRouter(tags=["roadmaps"])
templates = Jinja2Templates(directory="templates")


def get_user(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_current_user_from_token(token, db)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    roadmaps = db.query(Roadmap).filter(
        Roadmap.user_id == user.id,
        Roadmap.activo == True
    ).order_by(Roadmap.fecha_creacion.desc()).all()

    # Calcular progreso de cada roadmap
    roadmaps_con_progreso = []
    for rm in roadmaps:
        try:
            contenido = json.loads(rm.contenido) if rm.contenido and rm.contenido != "{}" else {}
        except Exception:
            contenido = {}
        total_lecciones = sum(len(fase["lecciones"]) for fase in contenido.get("fases", []))
        completadas = db.query(LessonProgress).filter(
            LessonProgress.roadmap_id == rm.id,
            LessonProgress.completada == True
        ).count()
        porcentaje = int((completadas / total_lecciones * 100) if total_lecciones > 0 else 0)
        roadmaps_con_progreso.append({
            "roadmap": rm,
            "porcentaje": porcentaje,
            "completadas": completadas,
            "total": total_lecciones,
            "estado": rm.estado or "listo",
        })

    plan_info = PLANS[user.plan]
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "roadmaps": roadmaps_con_progreso,
        "plan_info": plan_info
    })


@router.get("/roadmaps/nuevo", response_class=HTMLResponse)
async def nuevo_roadmap_page(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    puede, mensaje = can_create_roadmap(user, db)
    return templates.TemplateResponse("new_roadmap.html", {
        "request": request,
        "user": user,
        "puede_crear": puede,
        "mensaje_limite": mensaje
    })


NIVELES_VALIDOS = {"principiante", "intermedio", "avanzado"}
IDIOMAS_VALIDOS = {"es", "en"}


@router.post("/roadmaps/nuevo")
async def crear_roadmap(
    request: Request,
    tema: str = Form(...),
    nivel: str = Form(...),
    horas_semana: float = Form(...),
    idioma: str = Form("es"),
    db: Session = Depends(get_db)
):
    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    # Validar valores permitidos (anti prompt injection)
    if nivel not in NIVELES_VALIDOS:
        nivel = "principiante"
    if idioma not in IDIOMAS_VALIDOS:
        idioma = "es"

    puede, mensaje = can_create_roadmap(user, db, nivel)
    if not puede:
        return templates.TemplateResponse("new_roadmap.html", {
            "request": request, "user": user,
            "puede_crear": False, "mensaje_limite": mensaje
        })

    tema_norm = normalizar_tema(tema)

    # ── ¿Hay cache? → entrega instantánea ─────────────────────────────────────
    cached = db.query(RoadmapCache).filter(
        RoadmapCache.tema_normalizado == tema_norm,
        RoadmapCache.nivel == nivel,
        RoadmapCache.idioma == idioma
    ).first()

    if cached:
        contenido = json.loads(cached.contenido)
        if datetime.utcnow() - cached.fecha_videos > timedelta(days=CACHE_VIDEO_DAYS):
            try:
                contenido = await enrich_roadmap_with_youtube(contenido)
                cached.contenido    = json.dumps(contenido, ensure_ascii=False)
                cached.fecha_videos = datetime.utcnow()
                db.commit()
            except Exception as e:
                print(f"⚠️ Error al refrescar vídeos: {e}")

        roadmap = Roadmap(
            user_id=user.id, tema=tema, nivel=nivel,
            horas_semana=horas_semana, idioma=idioma,
            tema_normalizado=tema_norm,
            contenido=json.dumps(contenido, ensure_ascii=False),
            estado="listo"
        )
        db.add(roadmap)
        user.roadmaps_este_mes += 1
        db.commit()
        db.refresh(roadmap)
        return RedirectResponse(url=f"/roadmaps/{roadmap.id}", status_code=302)

    # ── Sin cache → cola de generación progresiva ──────────────────────────────
    roadmap = Roadmap(
        user_id=user.id, tema=tema, nivel=nivel,
        horas_semana=horas_semana, idioma=idioma,
        tema_normalizado=tema_norm,
        contenido="{}",
        estado="en_cola"
    )
    db.add(roadmap)
    user.roadmaps_este_mes += 1
    db.commit()
    db.refresh(roadmap)

    posicion = await generation_queue.enqueue(roadmap.id, user.plan)
    if posicion is None:
        # Cola llena — rechazar con gracia
        roadmap.estado    = "error"
        roadmap.error_msg = "El servidor está muy ocupado en este momento. Por favor inténtalo en unos minutos."
        user.roadmaps_este_mes -= 1
        db.commit()

    return RedirectResponse(url=f"/roadmaps/{roadmap.id}", status_code=302)


@router.get("/api/roadmaps/{roadmap_id}/estado")
async def estado_roadmap(roadmap_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Endpoint de polling para conocer el estado de generación de un roadmap.
    Devuelve: estado, posicion (en cola), modulos_estado, error.
    """
    user = get_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    roadmap = db.query(Roadmap).filter(
        Roadmap.id == roadmap_id,
        Roadmap.user_id == user.id
    ).first()
    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap no encontrado")

    estado = roadmap.estado or "listo"
    response: dict = {"estado": estado, "error": roadmap.error_msg}

    # Para estados de cola/generación, enriquecer con info de posición
    if estado in ("en_cola", "generando"):
        info = await generation_queue.get_info(roadmap_id)
        response.update({
            "posicion": info.get("posicion", 0),
            "activos":  info.get("activos", 0),
            "cola":     info.get("cola", 0),
        })

    # Para generación progresiva, incluir estado de módulos
    if estado in ("parcial", "listo") and roadmap.modulos_estado:
        response["modulos_estado"] = json.loads(roadmap.modulos_estado)

    return JSONResponse(response)


@router.get("/roadmaps/{roadmap_id}", response_class=HTMLResponse)
async def ver_roadmap(roadmap_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    roadmap = db.query(Roadmap).filter(
        Roadmap.id == roadmap_id,
        Roadmap.user_id == user.id,
        Roadmap.activo == True
    ).first()
    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap no encontrado")

    estado = roadmap.estado or "listo"
    contenido = json.loads(roadmap.contenido) if roadmap.contenido and roadmap.contenido != "{}" else {}

    # Estados de espera — mostrar pantalla de cola/spinner sin calcular progreso
    if estado in ("en_cola", "generando"):
        return templates.TemplateResponse("roadmap.html", {
            "request": request,
            "user": user,
            "roadmap": roadmap,
            "contenido": {},
            "estado": estado,
            "modulos_estado": {},
            "progreso_map": {},
            "porcentaje": 0,
            "completadas": 0,
            "total_lecciones": 0,
        })

    # Estado parcial o listo — mostrar roadmap (puede tener módulos pendientes)
    modulos_estado = json.loads(roadmap.modulos_estado) if roadmap.modulos_estado else {}

    progreso_db = db.query(LessonProgress).filter(
        LessonProgress.roadmap_id == roadmap_id,
        LessonProgress.user_id == user.id
    ).all()
    progreso_map = {p.leccion_id: p for p in progreso_db}

    total_lecciones = sum(len(f["lecciones"]) for f in contenido.get("fases", []))
    completadas = sum(1 for p in progreso_db if p.completada)
    porcentaje = int((completadas / total_lecciones * 100) if total_lecciones > 0 else 0)

    return templates.TemplateResponse("roadmap.html", {
        "request": request,
        "user": user,
        "roadmap": roadmap,
        "contenido": contenido,
        "estado": estado,
        "modulos_estado": modulos_estado,
        "progreso_map": progreso_map,
        "porcentaje": porcentaje,
        "completadas": completadas,
        "total_lecciones": total_lecciones,
    })


@router.get("/roadmaps/{roadmap_id}/leccion/{leccion_id}", response_class=HTMLResponse)
async def ver_leccion(roadmap_id: int, leccion_id: str, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    roadmap = db.query(Roadmap).filter(
        Roadmap.id == roadmap_id,
        Roadmap.user_id == user.id
    ).first()
    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap no encontrado")

    contenido = json.loads(roadmap.contenido)

    # Recopilar todas las lecciones en orden para saber cuáles son las últimas
    todas_lecciones = [
        lec
        for fase in contenido.get("fases", [])
        for lec in fase["lecciones"]
    ]
    leccion = next((l for l in todas_lecciones if l["id"] == leccion_id), None)

    if not leccion:
        raise HTTPException(status_code=404, detail="Lección no encontrada")

    # Bloquear las últimas N lecciones para usuarios del plan free
    plan_info = PLANS[user.plan]
    lecciones_bloqueadas = plan_info.get("lecciones_bloqueadas", 0)
    if lecciones_bloqueadas > 0 and len(todas_lecciones) > lecciones_bloqueadas:
        ids_bloqueadas = {l["id"] for l in todas_lecciones[-lecciones_bloqueadas:]}
        if leccion_id in ids_bloqueadas:
            return templates.TemplateResponse("lesson_locked.html", {
                "request": request,
                "user": user,
                "roadmap": roadmap,
                "leccion": leccion,
            })

    # Resetear contador mensual si es necesario (para mostrar dato fresco)
    reset_counters_if_needed(user, db)

    progreso = db.query(LessonProgress).filter(
        LessonProgress.roadmap_id == roadmap_id,
        LessonProgress.user_id == user.id,
        LessonProgress.leccion_id == leccion_id
    ).first()

    checklist_estado = json.loads(progreso.checklist) if progreso else [False] * len(leccion.get("checklist", []))

    return templates.TemplateResponse("lesson.html", {
        "request": request,
        "user": user,
        "roadmap": roadmap,
        "contenido": contenido,
        "leccion": leccion,
        "progreso": progreso,
        "checklist_estado": checklist_estado,
        "plan_info": plan_info,
        "mensajes_restantes": (
            -1 if plan_info["mensajes_tutor_mes"] == -1
            else max(0, plan_info["mensajes_tutor_mes"] + (user.mensajes_bonus_resena or 0) - user.mensajes_hoy)
        )
    })


@router.get("/roadmaps/{roadmap_id}/certificado", response_class=HTMLResponse)
async def ver_certificado(roadmap_id: int, request: Request, db: Session = Depends(get_db)):
    import hashlib
    from datetime import datetime
    from core.plans import PLANS

    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    # Solo plan Pro
    plan_info = PLANS[user.plan]
    if not plan_info.get("certificado"):
        return RedirectResponse(url="/pricing?upgrade=certificado")

    roadmap = db.query(Roadmap).filter(
        Roadmap.id == roadmap_id,
        Roadmap.user_id == user.id,
        Roadmap.activo == True
    ).first()
    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap no encontrado")

    contenido = json.loads(roadmap.contenido)

    # Calcular progreso
    progreso_db = db.query(LessonProgress).filter(
        LessonProgress.roadmap_id == roadmap_id,
        LessonProgress.user_id == user.id
    ).all()
    total_lecciones = sum(len(f["lecciones"]) for f in contenido.get("fases", []))
    completadas = sum(1 for p in progreso_db if p.completada)
    porcentaje = int((completadas / total_lecciones * 100) if total_lecciones > 0 else 0)

    if porcentaje < 100:
        return RedirectResponse(url=f"/roadmaps/{roadmap_id}?msg=completa_primero")

    # Fecha de finalización (última lección completada)
    fechas = [p.fecha_completada for p in progreso_db if p.completada and p.fecha_completada]
    fecha_fin = max(fechas) if fechas else datetime.utcnow()

    # ID único del certificado
    raw = f"{user.id}-{roadmap_id}-{roadmap.fecha_creacion}"
    cert_id = "LAI-" + hashlib.sha256(raw.encode()).hexdigest()[:12].upper()

    return templates.TemplateResponse("certificate.html", {
        "request": request,
        "user": user,
        "roadmap": roadmap,
        "contenido": contenido,
        "total_lecciones": total_lecciones,
        "fecha_fin": fecha_fin,
        "cert_id": cert_id,
    })


@router.delete("/roadmaps/{roadmap_id}")
async def eliminar_roadmap(roadmap_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    roadmap = db.query(Roadmap).filter(
        Roadmap.id == roadmap_id,
        Roadmap.user_id == user.id
    ).first()
    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap no encontrado")

    roadmap.activo = False
    db.commit()
    return {"ok": True}
