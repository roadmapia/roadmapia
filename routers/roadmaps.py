import json
import unicodedata
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database.database import get_db
from database.models import Roadmap, LessonProgress, RoadmapCache
from core.ai_generator import generate_roadmap
from core.plans import can_create_roadmap, PLANS
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
        contenido = json.loads(rm.contenido)
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
            "total": total_lecciones
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

    puede, mensaje = can_create_roadmap(user, db)
    if not puede:
        return templates.TemplateResponse("new_roadmap.html", {
            "request": request, "user": user,
            "puede_crear": False, "mensaje_limite": mensaje
        })

    tema_norm = normalizar_tema(tema)

    try:
        # 1. Buscar en cache
        cached = db.query(RoadmapCache).filter(
            RoadmapCache.tema_normalizado == tema_norm,
            RoadmapCache.nivel == nivel,
            RoadmapCache.idioma == idioma
        ).first()

        if cached:
            contenido = json.loads(cached.contenido)
            # 2. ¿Necesitan los vídeos actualizarse? (más de 90 días)
            if datetime.utcnow() - cached.fecha_videos > timedelta(days=CACHE_VIDEO_DAYS):
                print(f"🔄 Refrescando vídeos de cache: {tema_norm} / {nivel} / {idioma}")
                try:
                    contenido = await enrich_roadmap_with_youtube(contenido)
                    cached.contenido = json.dumps(contenido, ensure_ascii=False)
                    cached.fecha_videos = datetime.utcnow()
                    db.commit()
                except Exception as e:
                    print(f"⚠️ Error al refrescar vídeos: {e}")
                    # Usamos el contenido existente si falla el refresco
        else:
            # 3. Generar nuevo roadmap y guardar en cache
            contenido = await generate_roadmap(tema, nivel, horas_semana, idioma)
            nuevo_cache = RoadmapCache(
                tema_normalizado=tema_norm,
                nivel=nivel,
                idioma=idioma,
                contenido=json.dumps(contenido, ensure_ascii=False)
            )
            db.add(nuevo_cache)
            db.flush()  # guardar cache antes de continuar

    except Exception as e:
        return templates.TemplateResponse("new_roadmap.html", {
            "request": request, "user": user,
            "puede_crear": True,
            "error": f"Error al generar el roadmap: {str(e)}"
        })

    roadmap = Roadmap(
        user_id=user.id,
        tema=tema,
        nivel=nivel,
        horas_semana=horas_semana,
        contenido=json.dumps(contenido, ensure_ascii=False)
    )
    db.add(roadmap)

    user.roadmaps_este_mes += 1
    db.commit()
    db.refresh(roadmap)

    return RedirectResponse(url=f"/roadmaps/{roadmap.id}", status_code=302)


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

    contenido = json.loads(roadmap.contenido)

    # Obtener progreso
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
        "progreso_map": progreso_map,
        "porcentaje": porcentaje,
        "completadas": completadas,
        "total_lecciones": total_lecciones
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
    leccion = None
    for fase in contenido.get("fases", []):
        for lec in fase["lecciones"]:
            if lec["id"] == leccion_id:
                leccion = lec
                break

    if not leccion:
        raise HTTPException(status_code=404, detail="Lección no encontrada")

    progreso = db.query(LessonProgress).filter(
        LessonProgress.roadmap_id == roadmap_id,
        LessonProgress.user_id == user.id,
        LessonProgress.leccion_id == leccion_id
    ).first()

    checklist_estado = json.loads(progreso.checklist) if progreso else [False] * len(leccion.get("checklist", []))

    from core.plans import PLANS
    plan_info = PLANS[user.plan]

    return templates.TemplateResponse("lesson.html", {
        "request": request,
        "user": user,
        "roadmap": roadmap,
        "contenido": contenido,
        "leccion": leccion,
        "progreso": progreso,
        "checklist_estado": checklist_estado,
        "plan_info": plan_info
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
