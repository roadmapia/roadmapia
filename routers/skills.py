"""
routers/skills.py — Analizador de habilidades (solo plan Pro).

El usuario indica lo que ya sabe y Claude sugiere 6 roadmaps complementarios
que expanden sus conocimientos actuales.
"""

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database.database import get_db
from core.auth import get_current_user_from_token
from core.ai_generator import suggest_complementary_roadmaps

router = APIRouter(tags=["skills"])
templates = Jinja2Templates(directory="templates")


def get_user(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_current_user_from_token(token, db)


@router.get("/skills/analizar", response_class=HTMLResponse)
async def analizar_page(request: Request, db: Session = Depends(get_db)):
    """Página del analizador de habilidades (formulario)."""
    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    return templates.TemplateResponse("skills_analyzer.html", {
        "request": request,
        "user": user,
        "sugerencias": None,
        "skills": "",
        "objetivo": "",
        "error": None,
    })


@router.post("/skills/analizar", response_class=HTMLResponse)
async def analizar_post(
    request: Request,
    skills: str = Form(...),
    objetivo: str = Form(""),
    db: Session = Depends(get_db),
):
    """Procesa el formulario y devuelve sugerencias de Claude."""
    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    # Solo Pro puede usar esta funcionalidad
    if user.plan != "pro":
        return templates.TemplateResponse("skills_analyzer.html", {
            "request": request,
            "user": user,
            "sugerencias": None,
            "skills": skills,
            "objetivo": objetivo,
            "error": "pro_required",
        })

    # Validar entrada mínima
    skills = skills.strip()
    if len(skills) < 10:
        return templates.TemplateResponse("skills_analyzer.html", {
            "request": request,
            "user": user,
            "sugerencias": None,
            "skills": skills,
            "objetivo": objetivo,
            "error": "too_short",
        })

    try:
        sugerencias = await suggest_complementary_roadmaps(skills, objetivo.strip())
    except Exception as e:
        return templates.TemplateResponse("skills_analyzer.html", {
            "request": request,
            "user": user,
            "sugerencias": None,
            "skills": skills,
            "objetivo": objetivo,
            "error": "ai_error",
        })

    return templates.TemplateResponse("skills_analyzer.html", {
        "request": request,
        "user": user,
        "sugerencias": sugerencias,
        "skills": skills,
        "objetivo": objetivo,
        "error": None,
    })
