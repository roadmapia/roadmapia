import json
from datetime import datetime
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database.database import get_db
from database.models import ChatMessage, Roadmap, TutorQuestionCache
from core.tutor_ai import chat_tutor
from core.plans import can_send_tutor_message
from core.auth import get_current_user_from_token
from core.cache_utils import normalizar_pregunta, buscar_similar

router = APIRouter(prefix="/tutor", tags=["tutor"])


def get_user(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_current_user_from_token(token, db)


@router.post("/{roadmap_id}/{leccion_id}/mensaje")
async def enviar_mensaje(
    roadmap_id: int,
    leccion_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    puede, mensaje_error = can_send_tutor_message(user, db)
    if not puede:
        return JSONResponse({"error": mensaje_error}, status_code=429)

    body = await request.json()
    mensaje = body.get("mensaje", "").strip()
    if not mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")

    # Obtener contexto del roadmap y lección
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

    # Obtener historial (últimos 50 mensajes)
    historial_db = db.query(ChatMessage).filter(
        ChatMessage.roadmap_id == roadmap_id,
        ChatMessage.user_id == user.id,
        ChatMessage.leccion_id == leccion_id
    ).order_by(ChatMessage.fecha.asc()).limit(50).all()

    historial = [{"rol": m.rol, "contenido": m.contenido} for m in historial_db]

    # Detectar idioma del roadmap
    idioma_roadmap = contenido.get("idioma", "es")

    # ── CACHE DE PREGUNTAS ──────────────────────────────────────
    pregunta_norm = normalizar_pregunta(mensaje)
    respuesta = None
    desde_cache = False

    # 1. Buscar match exacto
    cached = db.query(TutorQuestionCache).filter(
        TutorQuestionCache.pregunta_normalizada == pregunta_norm,
        TutorQuestionCache.tema == roadmap.tema,
        TutorQuestionCache.idioma == idioma_roadmap
    ).first()

    if cached:
        cached.usos += 1
        cached.fecha_ultimo_uso = datetime.utcnow()
        db.commit()
        respuesta = cached.respuesta
        desde_cache = True
        print(f"💾 Cache tutor EXACTO (×{cached.usos}): '{mensaje[:60]}'")

    if not cached:
        # 2. Buscar por similitud
        candidatos = db.query(TutorQuestionCache).filter(
            TutorQuestionCache.tema == roadmap.tema,
            TutorQuestionCache.idioma == idioma_roadmap
        ).limit(300).all()

        similar = buscar_similar(pregunta_norm, candidatos)
        if similar:
            similar.usos += 1
            similar.fecha_ultimo_uso = datetime.utcnow()
            db.commit()
            respuesta = similar.respuesta
            desde_cache = True
            print(f"💾 Cache tutor SIMILAR (×{similar.usos}): '{mensaje[:60]}'")

    # 3. Si no hay cache → llamar a DeepSeek y guardar resultado
    if not desde_cache:
        try:
            respuesta = await chat_tutor(
                mensaje=mensaje,
                historial=historial,
                contexto_leccion=leccion,
                contexto_roadmap={"tema": roadmap.tema, "nivel": roadmap.nivel},
                idioma=idioma_roadmap
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error del tutor: {str(e)}")

        # Guardar en cache
        db.add(TutorQuestionCache(
            pregunta_normalizada=pregunta_norm,
            pregunta_original=mensaje,
            respuesta=respuesta,
            tema=roadmap.tema,
            nivel=roadmap.nivel,
            idioma=idioma_roadmap
        ))
        print(f"💬 DeepSeek nueva pregunta guardada en cache: '{mensaje[:60]}'")

    # Guardar mensajes
    db.add(ChatMessage(
        user_id=user.id,
        roadmap_id=roadmap_id,
        leccion_id=leccion_id,
        rol="user",
        contenido=mensaje
    ))
    db.add(ChatMessage(
        user_id=user.id,
        roadmap_id=roadmap_id,
        leccion_id=leccion_id,
        rol="assistant",
        contenido=respuesta
    ))

    user.mensajes_hoy += 1
    db.commit()

    return JSONResponse({"respuesta": respuesta})


@router.get("/{roadmap_id}/{leccion_id}/historial")
async def obtener_historial(
    roadmap_id: int,
    leccion_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    mensajes = db.query(ChatMessage).filter(
        ChatMessage.roadmap_id == roadmap_id,
        ChatMessage.user_id == user.id,
        ChatMessage.leccion_id == leccion_id
    ).order_by(ChatMessage.fecha.asc()).limit(50).all()

    return {
        "mensajes": [
            {"rol": m.rol, "contenido": m.contenido, "fecha": m.fecha.isoformat()}
            for m in mensajes
        ]
    }
