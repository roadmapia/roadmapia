import json
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime

from database.database import get_db
from database.models import LessonProgress, Roadmap
from core.auth import get_current_user_from_token

router = APIRouter(prefix="/progress", tags=["progress"])


def get_user(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_current_user_from_token(token, db)


@router.post("/{roadmap_id}/{leccion_id}/checklist")
async def guardar_checklist(
    roadmap_id: int,
    leccion_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    body = await request.json()
    checklist = body.get("checklist", [])

    progreso = db.query(LessonProgress).filter(
        LessonProgress.roadmap_id == roadmap_id,
        LessonProgress.user_id == user.id,
        LessonProgress.leccion_id == leccion_id
    ).first()

    if not progreso:
        progreso = LessonProgress(
            user_id=user.id,
            roadmap_id=roadmap_id,
            leccion_id=leccion_id,
            checklist=json.dumps(checklist)
        )
        db.add(progreso)
    else:
        progreso.checklist = json.dumps(checklist)

    db.commit()
    return JSONResponse({"ok": True, "checklist": checklist})


@router.post("/{roadmap_id}/{leccion_id}/completar")
async def completar_leccion(
    roadmap_id: int,
    leccion_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    progreso = db.query(LessonProgress).filter(
        LessonProgress.roadmap_id == roadmap_id,
        LessonProgress.user_id == user.id,
        LessonProgress.leccion_id == leccion_id
    ).first()

    if not progreso:
        progreso = LessonProgress(
            user_id=user.id,
            roadmap_id=roadmap_id,
            leccion_id=leccion_id,
            checklist="[]"
        )
        db.add(progreso)

    progreso.completada = True
    progreso.fecha_completada = datetime.utcnow()
    db.commit()

    # Contar lecciones totales completadas por el usuario
    from database.models import LessonProgress as LP
    total_completadas = db.query(LP).filter(
        LP.user_id == user.id,
        LP.completada == True
    ).count()

    # Mostrar modal de reseña en lección 1 y 5 si no ha dejado reseña aún
    pedir_resena = (
        total_completadas in (1, 5) and
        not getattr(user, 'resena_completada', False)
    )

    return JSONResponse({"ok": True, "pedir_resena": pedir_resena, "total_completadas": total_completadas})


@router.get("/{roadmap_id}")
async def obtener_progreso(
    roadmap_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    progreso = db.query(LessonProgress).filter(
        LessonProgress.roadmap_id == roadmap_id,
        LessonProgress.user_id == user.id
    ).all()

    return {
        "lecciones": [
            {
                "leccion_id": p.leccion_id,
                "completada": p.completada,
                "checklist": json.loads(p.checklist)
            }
            for p in progreso
        ]
    }
