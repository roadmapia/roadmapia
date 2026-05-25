"""
ai_generator.py — Genera roadmaps con Claude API.

Dos modos de generación:
  · generate_roadmap()             — clásico (todo a la vez), para caché hits
  · generate_roadmap_progressive() — progresivo por módulos, para nuevas generaciones
    Flujo: Claude genera JSON completo → YouTube fase1 → guarda "parcial" visible →
           YouTube fase2 → actualiza → ... → marca "listo"
"""

import json
import logging
import os

import anthropic
from dotenv import load_dotenv

from core.youtube import enrich_fase_with_youtube, enrich_roadmap_with_youtube

load_dotenv()
logger = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ─── Prompts del sistema ──────────────────────────────────────────────────────

SYSTEM_PROMPT_ES = """Eres un experto en educación y diseño de programas de aprendizaje.
Tu tarea es crear un roadmap de aprendizaje completo, estructurado y práctico EN ESPAÑOL.

Responde ÚNICAMENTE con un JSON válido con esta estructura exacta, sin texto adicional, sin markdown, sin bloques de código:
{
  "titulo": "Aprende [tema] desde [nivel]",
  "descripcion": "Descripción breve del programa",
  "duracion_semanas": 12,
  "fases": [
    {
      "id": "fase1",
      "titulo": "Fase 1 — Título de la fase",
      "semanas": "1 - 2",
      "descripcion": "Qué se consigue en esta fase",
      "lecciones": [
        {
          "id": "1.1",
          "titulo": "Título de la lección",
          "descripcion": "Descripción detallada de qué se aprende",
          "recursos": [
            {
              "texto": "Título del vídeo o recurso recomendado",
              "url": "https://www.youtube.com/results?search_query=terminos+de+busqueda"
            }
          ],
          "checklist": [
            "Ítem 1 del checklist",
            "Ítem 2 del checklist"
          ],
          "ejercicio": "Descripción del ejercicio práctico a realizar"
        }
      ]
    }
  ]
}"""

SYSTEM_PROMPT_EN = """You are an expert in education and learning program design.
Your task is to create a complete, structured and practical learning roadmap IN ENGLISH.

Respond ONLY with valid JSON in this exact structure, no additional text, no markdown, no code blocks:
{
  "titulo": "Learn [topic] from [level]",
  "descripcion": "Brief description of the program",
  "duracion_semanas": 12,
  "fases": [
    {
      "id": "fase1",
      "titulo": "Phase 1 — Phase title",
      "semanas": "1 - 2",
      "descripcion": "What is achieved in this phase",
      "lecciones": [
        {
          "id": "1.1",
          "titulo": "Lesson title",
          "descripcion": "Detailed description of what is learned",
          "recursos": [
            {
              "texto": "Recommended video or resource title",
              "url": "https://www.youtube.com/results?search_query=search+terms+here"
            }
          ],
          "checklist": [
            "Checklist item 1",
            "Checklist item 2"
          ],
          "ejercicio": "Description of the practical exercise to complete"
        }
      ]
    }
  ]
}"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def format_horas(horas: float) -> str:
    """Convierte horas decimales a texto legible. Ej: 2.5 → '2h 30min'"""
    h = int(horas)
    m = round((horas - h) * 60)
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}min"


async def _call_claude(tema: str, nivel: str, horas_semana: float, idioma: str) -> dict:
    """Llama a Claude y devuelve el roadmap como dict. Solo genera estructura, sin vídeos reales."""
    system_prompt = SYSTEM_PROMPT_EN if idioma == "en" else SYSTEM_PROMPT_ES
    tiempo_str = format_horas(horas_semana)

    if idioma == "en":
        user_message = (
            f"The user wants to learn: {tema}\n"
            f"Current level: {nivel}\n"
            f"Available time per week: {tiempo_str}\n\n"
            "Generate the complete roadmap in JSON as specified. Include at least 3 phases with 3-4 lessons each.\n"
            "All content (titles, descriptions, checklist items, exercises) must be in English.\n"
            "Resource URLs should be real YouTube search queries in English.\n"
            "IMPORTANT: Keep descriptions concise (max 120 characters each) to stay within token limits."
        )
    else:
        user_message = (
            f"El usuario quiere aprender: {tema}\n"
            f"Nivel actual: {nivel}\n"
            f"Tiempo disponible por semana: {tiempo_str}\n\n"
            "Genera el roadmap completo en JSON como se ha especificado. Incluye al menos 3 fases con 3-4 lecciones cada una.\n"
            "Todo el contenido (títulos, descripciones, checklist, ejercicios) debe estar en español.\n"
            "Las URLs de recursos deben ser búsquedas reales de YouTube en español.\n"
            "IMPORTANTE: Mantén las descripciones concisas (máximo 120 caracteres cada una) para no superar el límite de tokens."
        )

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    in_tok  = message.usage.input_tokens
    out_tok = message.usage.output_tokens
    coste   = (in_tok * 3 + out_tok * 15) / 1_000_000
    logger.info(f"💰 Claude [{idioma}|{nivel}] — in:{in_tok:,} · out:{out_tok:,} → ${coste:.4f}")

    content = message.content[0].text.strip()
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:-1])

    roadmap = json.loads(content)
    roadmap["idioma"] = idioma
    return roadmap


# ─── Modo clásico (para cache hits) ──────────────────────────────────────────

async def generate_roadmap(tema: str, nivel: str, horas_semana: float, idioma: str = "es") -> dict:
    """Genera roadmap completo (Claude + todos los vídeos). Usado cuando hay cache."""
    roadmap = await _call_claude(tema, nivel, horas_semana, idioma)
    roadmap = await enrich_roadmap_with_youtube(roadmap)
    return roadmap


# ─── Modo progresivo (para nuevas generaciones vía cola) ─────────────────────

async def generate_roadmap_progressive(roadmap_id: int) -> None:
    """
    Generación progresiva:
      1. Lee los datos del roadmap de la BD
      2. Llama a Claude (genera estructura completa)
      3. Para cada fase: busca vídeos → guarda → actualiza modulos_estado
      4. La primera fase lista ya es visible para el usuario
    """
    from database.database import SessionLocal
    from database.models import Roadmap, RoadmapCache

    db = SessionLocal()
    try:
        rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id).first()
        if not rm:
            logger.error(f"Roadmap {roadmap_id} no encontrado en BD")
            return

        tema        = rm.tema
        nivel       = rm.nivel
        horas_semana = rm.horas_semana
        idioma      = rm.idioma or "es"
        tema_norm   = rm.tema_normalizado or _normalizar(tema)

    finally:
        db.close()

    db = SessionLocal()
    try:
        # ── 1. Generar estructura con Claude ─────────────────────────────────
        logger.info(f"🧠 Claude generando roadmap '{tema}'...")
        roadmap_data = await _call_claude(tema, nivel, horas_semana, idioma)

        fases = roadmap_data.get("fases", [])
        n = len(fases)
        modulos_estado = {f"fase{i+1}": "pendiente" for i in range(n)}

        rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id).first()
        if not rm:
            return

        # Guardar esqueleto — aún sin vídeos reales
        rm.contenido      = json.dumps(roadmap_data, ensure_ascii=False)
        rm.estado         = "generando"
        rm.modulos_estado = json.dumps(modulos_estado)
        db.commit()

        # ── 2. Buscar vídeos fase a fase ─────────────────────────────────────
        for i, fase in enumerate(fases):
            fase_key = f"fase{i+1}"
            modulos_estado[fase_key] = "generando"
            rm.modulos_estado = json.dumps(modulos_estado)
            db.commit()

            try:
                fases[i] = await enrich_fase_with_youtube(fase, idioma)
            except Exception as e:
                logger.warning(f"⚠️ YouTube error fase {i+1}: {e}")

            roadmap_data["fases"] = fases
            modulos_estado[fase_key] = "listo"
            rm.contenido      = json.dumps(roadmap_data, ensure_ascii=False)
            rm.modulos_estado = json.dumps(modulos_estado)

            # Tras la primera fase lista → ya visible para el usuario
            if i == 0:
                rm.estado = "parcial"

            db.commit()
            logger.info(f"✅ Fase {i+1}/{n} completada para roadmap {roadmap_id}")

        # ── 3. Todo listo ─────────────────────────────────────────────────────
        rm.estado = "listo"
        db.commit()

        # ── 4. Guardar en caché ───────────────────────────────────────────────
        try:
            cache = RoadmapCache(
                tema_normalizado=tema_norm,
                nivel=nivel,
                idioma=idioma,
                contenido=json.dumps(roadmap_data, ensure_ascii=False),
            )
            db.add(cache)
            db.commit()
            logger.info(f"💾 Roadmap {roadmap_id} guardado en caché")
        except Exception as e:
            logger.warning(f"Cache save error: {e}")

    except Exception as e:
        logger.error(f"❌ Error progresivo roadmap {roadmap_id}: {e}")
        rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id).first()
        if rm:
            rm.estado    = "error"
            rm.error_msg = str(e)[:500]
            db.commit()
        raise
    finally:
        db.close()


def _normalizar(tema: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", tema.lower().strip())
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sin_acentos.split())
