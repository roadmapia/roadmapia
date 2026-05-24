import anthropic
import json
import os
from dotenv import load_dotenv
from core.youtube import enrich_roadmap_with_youtube

load_dotenv()

client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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


def format_horas(horas: float) -> str:
    """Convierte horas decimales a texto legible. Ej: 2.5 → '2h 30min'"""
    h = int(horas)
    m = round((horas - h) * 60)
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}min"


async def generate_roadmap(tema: str, nivel: str, horas_semana: float, idioma: str = "es") -> dict:
    """Genera un roadmap completo usando Claude API y lo enriquece con vídeos de YouTube."""

    system_prompt = SYSTEM_PROMPT_EN if idioma == "en" else SYSTEM_PROMPT_ES
    tiempo_str = format_horas(horas_semana)

    if idioma == "en":
        user_message = f"""The user wants to learn: {tema}
Current level: {nivel}
Available time per week: {tiempo_str}

Generate the complete roadmap in JSON as specified. Include at least 3 phases with 3-4 lessons each.
All content (titles, descriptions, checklist items, exercises) must be in English.
Resource URLs should be real YouTube search queries in English.
IMPORTANT: Keep descriptions concise (max 120 characters each) to stay within token limits."""
    else:
        user_message = f"""El usuario quiere aprender: {tema}
Nivel actual: {nivel}
Tiempo disponible por semana: {tiempo_str}

Genera el roadmap completo en JSON como se ha especificado. Incluye al menos 3 fases con 3-4 lecciones cada una.
Todo el contenido (títulos, descripciones, checklist, ejercicios) debe estar en español.
Las URLs de recursos deben ser búsquedas reales de YouTube en español.
IMPORTANTE: Mantén las descripciones concisas (máximo 120 caracteres cada una) para no superar el límite de tokens."""

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )

    # 💰 Log de costes reales Claude Sonnet 4.6
    in_tok  = message.usage.input_tokens
    out_tok = message.usage.output_tokens
    # Precio real observado: ~$0.10/roadmap
    coste   = (in_tok * 3 + out_tok * 15) / 1_000_000
    print(f"💰 Claude roadmap [{idioma}|{nivel}] — "
          f"in:{in_tok:,} · out:{out_tok:,} tokens → ${coste:.4f} (~$0.10/roadmap real)")

    content = message.content[0].text.strip()

    # Limpiar posibles bloques de código markdown
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1])

    roadmap = json.loads(content)

    # Añadir el idioma al roadmap para referencia futura
    roadmap["idioma"] = idioma

    # Enriquecer con vídeos reales de YouTube
    roadmap = await enrich_roadmap_with_youtube(roadmap)

    return roadmap
