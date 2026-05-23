import os
import httpx
import anthropic
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL  = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL    = "deepseek-chat"   # DeepSeek-V3

# Claude como fallback si DeepSeek no está configurado
_claude_client = None
def get_claude():
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _claude_client


def build_system_prompt(contexto_roadmap: dict, contexto_leccion: dict, idioma: str) -> str:
    tema  = contexto_roadmap.get("tema", "the topic")
    nivel = contexto_roadmap.get("nivel", "beginner")
    titulo    = contexto_leccion.get("titulo", "")
    desc      = contexto_leccion.get("descripcion", "")
    ejercicio = contexto_leccion.get("ejercicio", "")

    if idioma == "en":
        return f"""You are an expert and patient tutor specialized in teaching {tema}.
You are helping a student at {nivel} level.

Current lesson: {titulo}
Description: {desc}
Exercise: {ejercicio}

Always respond in English.
Your style is friendly, clear and motivating. Explain step by step with practical examples.
If the student doesn't understand, explain it a different way.
Keep responses concise (max 3-4 paragraphs) unless more detail is requested."""
    else:
        return f"""Eres un tutor experto y paciente especializado en enseñar {tema}.
Estás ayudando a un estudiante de nivel {nivel}.

Lección actual: {titulo}
Descripción: {desc}
Ejercicio: {ejercicio}

Respondes siempre en español.
Tu estilo es amable, claro y motivador. Explicas paso a paso con ejemplos prácticos.
Si el estudiante no entiende algo, lo explicas de una forma diferente.
Mantén las respuestas concisas (máximo 3-4 párrafos) salvo que se pida más detalle."""


async def _chat_deepseek(system: str, messages: list) -> str:
    """Llama a la API de DeepSeek (OpenAI-compatible)."""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 1024,
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(DEEPSEEK_API_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    # 💰 Log de costes reales DeepSeek (~$0.01/consulta real)
    usage   = data.get("usage", {})
    in_tok  = usage.get("prompt_tokens", 0)
    out_tok = usage.get("completion_tokens", 0)
    total_tok = in_tok + out_tok
    print(f"💬 DeepSeek tutor — in:{in_tok:,} · out:{out_tok:,} · total:{total_tok:,} tokens → ~$0.01/consulta")

    return data["choices"][0]["message"]["content"]


async def _chat_claude(system: str, messages: list) -> str:
    """Fallback: usa Claude si DeepSeek no está configurado."""
    response = await get_claude().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        messages=messages
    )
    return response.content[0].text


async def chat_tutor(
    mensaje: str,
    historial: list,
    contexto_leccion: dict,
    contexto_roadmap: dict,
    idioma: str = "es"
) -> str:
    """Envía un mensaje al tutor IA usando DeepSeek (o Claude como fallback)."""

    system = build_system_prompt(contexto_roadmap, contexto_leccion, idioma)

    # Construir historial (últimos 20 mensajes)
    messages = []
    for msg in historial[-20:]:
        messages.append({"role": msg["rol"], "content": msg["contenido"]})
    messages.append({"role": "user", "content": mensaje})

    # Usar DeepSeek si hay API key, si no Claude
    if DEEPSEEK_API_KEY:
        return await _chat_deepseek(system, messages)
    else:
        return await _chat_claude(system, messages)
