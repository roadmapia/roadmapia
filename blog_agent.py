#!/usr/bin/env python3
"""
Blog Agent para Roadmapia — con investigación real
=======================================================
Usa Google Suggest (datos reales de búsqueda) + Claude para:
- Descubrir qué temas busca la gente de verdad en Google
- Evaluar si la competencia los cubre o no
- Generar artículos SEO optimizados automáticamente

Comandos:
  python blog_agent.py --research-niche           # Investiga y añade ~15 temas nicho al pool
  python blog_agent.py --type niche               # Genera artículo del siguiente tema en el pool
  python blog_agent.py --type trending            # Investiga trending y genera artículo
  python blog_agent.py --list                     # Ver artículos publicados
  python blog_agent.py --stats                    # Estado del pool de nichos
  python blog_agent.py --type niche --dry-run     # Preview sin guardar
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

# ─── Rutas ───────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
REGISTRY_FILE   = BASE_DIR / "blog_registry.json"
NICHE_POOL_FILE = BASE_DIR / "niche_pool.json"
TEMPLATES_DIR   = BASE_DIR / "templates" / "blog"

MESES = ["enero","febrero","marzo","abril","mayo","junio",
         "julio","agosto","septiembre","octubre","noviembre","diciembre"]

# Competidores principales en el mercado hispanohablante de aprendizaje
COMPETITORS = [
    "coursera.org", "udemy.com", "roadmap.sh", "domestika.org",
    "platzi.com", "openwebinars.net", "miriadax.net"
]

# ─── Utilidades generales ─────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text

def format_date_es(dt: datetime) -> str:
    return f"{dt.day} de {MESES[dt.month - 1]}, {dt.year}"

def format_date_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT10:00:00+01:00")

def load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        return {"articles": []}
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))

def save_registry(registry: dict):
    REGISTRY_FILE.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ Registro: {len(registry['articles'])} artículos totales")

def load_niche_pool() -> list:
    if not NICHE_POOL_FILE.exists():
        return []
    return json.loads(NICHE_POOL_FILE.read_text(encoding="utf-8"))

def save_niche_pool(pool: list):
    NICHE_POOL_FILE.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")

def get_used_slugs(registry: dict) -> set:
    return {a["slug"] for a in registry.get("articles", [])}

def get_pool_slugs(pool: list) -> set:
    return {t["slug"] for t in pool}

def strip_codeblock(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()

def count_words(html: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", html).split())

def reading_time(words: int) -> int:
    return max(4, round(words / 210))

def articles_for_links(registry: dict, limit: int = 8) -> str:
    articles = registry.get("articles", [])[-limit:]
    return "\n".join(f'  - /blog/{a["slug"]} → "{a["titulo"]}"' for a in articles)


# ─── INVESTIGACIÓN: Google Suggest ────────────────────────────────────────────

def google_suggest(query: str, lang: str = "es", country: str = "es") -> list[str]:
    """
    Llama a la API pública de Google Suggest.
    Devuelve datos reales de lo que la gente busca en Google.
    Sin API key, sin límite conocido, gratis.
    """
    try:
        r = httpx.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "q": query, "hl": lang, "gl": country},
            timeout=8
        )
        try:
            text = r.content.decode("utf-8")
        except UnicodeDecodeError:
            text = r.content.decode("latin-1")
        return json.loads(text)[1]
    except Exception:
        return []


def discover_learning_queries(max_queries: int = 80) -> list[str]:
    """
    Descubre qué busca la gente en Google sobre 'aprender X'.
    Usa múltiples semillas + expansión por letras para maximizar cobertura.
    """
    print("  🔍 Consultando Google Suggest para descubrir qué busca la gente...")

    seeds = [
        "aprender a ", "aprender ", "como aprender ",
        "aprender desde cero ", "guia aprender ",
        "curso de ", "aprender sin dinero ",
    ]
    # Expansión letra a letra → descubre todo el catálogo de búsquedas
    alphabet = "abcdefghijklmnoprstuvz"
    for letter in alphabet:
        seeds.append(f"aprender {letter}")
        seeds.append(f"como aprender {letter}")

    all_queries: set[str] = set()

    for seed in seeds:
        suggestions = google_suggest(seed)
        for s in suggestions:
            if any(kw in s.lower() for kw in ["aprender", "aprendizaje", "aprender a", "curso"]):
                all_queries.add(s.lower().strip())
        time.sleep(0.15)  # respetar rate limit

    # Eliminar las demasiado genéricas
    filtered = [
        q for q in all_queries
        if len(q.split()) >= 3
        and not any(skip in q for skip in ["gratis pdf", "libro pdf", " app ", "para niños"])
    ]

    print(f"  📊 {len(filtered)} queries únicas encontradas en Google Suggest")
    return filtered[:max_queries]


def discover_trending_learning(now: datetime) -> list[str]:
    """
    Descubre qué temas de aprendizaje están trending ahora mismo
    usando seeds orientadas a actualidad.
    """
    mes  = MESES[now.month - 1]
    año  = now.year
    print("  🔥 Buscando temas trending en Google Suggest...")

    seeds = [
        f"habilidades más demandadas {año}",
        f"que aprender en {año}",
        f"tendencias formación {año}",
        "aprender inteligencia artificial",
        "habilidades futuro trabajo",
        f"cursos más buscados {año}",
        "trabajo del futuro aprender",
        "que estudiar para ganar dinero",
        f"profesiones más demandadas {año}",
        "aprender para cambiar de trabajo",
        "habilidades digitales más buscadas",
        f"que aprender en {mes} {año}",
        "empleo más demandado",
        "nuevas profesiones digitales",
    ]

    all_results: set[str] = set()
    for seed in seeds:
        results = google_suggest(seed)
        all_results.update(r.lower().strip() for r in results)
        time.sleep(0.15)

    return list(all_results)


# ─── INVESTIGACIÓN: Claude analiza las queries ────────────────────────────────

RESEARCH_SYSTEM = """Eres un experto en SEO y keyword research para el mercado hispanohablante (España + Latinoamérica).
Tu especialidad es encontrar keywords con demanda real pero baja competencia en el sector de educación online.

Conoces en profundidad el catálogo de los grandes competidores:
- Coursera/edX: cursos universitarios, programación, data science, gestión empresarial
- Udemy: programación, diseño, marketing, productividad (muy amplio)
- Domestika: diseño, ilustración, fotografía, creatividad (nicho creativo)
- Platzi: tecnología, programación, emprendimiento digital
- roadmap.sh: rutas de aprendizaje en programación y tecnología
- OpenWebinars: tecnología, programación, sysadmin (mercado español)

Cuando analices keywords, razona sobre:
1. ¿Tiene búsqueda real? (aparece en Google Suggest = sí)
2. ¿Los competidores tienen páginas dedicadas a este tema exacto?
3. ¿Puede cubrirse bien en un artículo de 1000-1300 palabras?
4. ¿Tiene intención informacional (quiero aprender)?"""


async def claude_select_niche_topics(
    client: AsyncAnthropic,
    queries: list[str],
    registry: dict,
    pool: list,
    n: int = 15
) -> list[dict]:
    """
    Claude analiza las queries reales de Google y selecciona
    las mejores oportunidades de nicho (demanda + baja competencia).
    """
    existing_slugs = get_used_slugs(registry) | get_pool_slugs(pool)
    existing_keywords = [t["keyword_principal"] for t in pool]

    prompt = f"""Tengo {len(queries)} queries reales que la gente busca en Google sobre aprendizaje.
Tu misión: seleccionar exactamente {n} que sean BUENAS OPORTUNIDADES para posicionar en Google con baja competencia.

QUERIES REALES DE GOOGLE SUGGEST:
{chr(10).join(f'- {q}' for q in queries)}

CRITERIOS DE SELECCIÓN (aplica los 4):
1. DEMANDA REAL: aparece en Google Suggest → la gente lo busca de verdad
2. BAJA COMPETENCIA: {', '.join(COMPETITORS[:5])} NO tienen una página dedicada a este tema exacto
3. INFORMACIONAL: la persona quiere aprender algo (no comprar, no descargar)
4. ESPECÍFICO: suficientemente concreto para un artículo de ~1000 palabras (no "aprender tecnología")
5. NO DUPLICADO: evita estos temas ya en el pool:
{chr(10).join(f'   - {kw}' for kw in existing_keywords[:25])}

RAZONA para cada uno que selecciones: ¿por qué la competencia no lo cubre bien?
(ej: "Coursera no tiene cursos de guitarra flamenca", "Udemy cubre Python general pero no Python para biólogos")

Devuelve un JSON array con exactamente {n} objetos:
[
  {{
    "keyword_principal": "la keyword exacta tal como aparece en Suggest",
    "tema": "descripción del tema en infinitivo (aprender X desde cero)",
    "titulo": "Título del artículo, 55-60 chars con keyword al inicio",
    "slug": "slug-seo-url-friendly",
    "resumen": "Resumen para el blog, 120-155 chars, práctico",
    "categoria": "Categoría (Idiomas/Programación/Arte/Hobbies/Finanzas/etc)",
    "emoji": "emoji representativo",
    "minutos": 7,
    "razon_oportunidad": "Por qué tiene baja competencia real (1 frase)",
    "competidores_que_lo_cubren": "ninguno / parcialmente Udemy / solo inglés"
  }}
]

Devuelve SOLO el JSON, sin texto adicional."""

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=RESEARCH_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )

    text = strip_codeblock(response.content[0].text)
    # Extraer JSON si viene con texto extra
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        text = match.group(0)

    return json.loads(text)


async def claude_select_trending_topic(
    client: AsyncAnthropic,
    raw_queries: list[str],
    registry: dict,
    now: datetime
) -> dict:
    """
    Claude analiza queries trending de Google y elige el mejor tema,
    SIEMPRE enmarcado como "cómo aprender X" para competir con intención
    de búsqueda de aprendizaje (no con medios de noticias).
    """
    used = list(get_used_slugs(registry))
    mes  = MESES[now.month - 1]
    año  = now.year

    prompt = f"""Tengo datos reales de Google Suggest sobre qué habilidades y temas están trending ahora.
Fecha actual: {format_date_es(now)} ({mes} {año})

SEÑALES DE TRENDING REALES DE GOOGLE:
{chr(10).join(f'- {q}' for q in raw_queries[:40])}

TEMAS YA PUBLICADOS (no repetir):
{json.dumps(used[:15], ensure_ascii=False)}

MISIÓN EN 2 PASOS:

PASO 1 — Identifica QUÉ está trending ahora en el mundo del trabajo y la formación.
Puede ser una habilidad, una tecnología, un perfil profesional o una tendencia laboral
que esté siendo muy buscada en España/Latinoamérica en {mes} {año}.

PASO 2 — Transforma ese tema trending en un artículo de APRENDIZAJE.
En vez de "qué es X" (que lo cubren los medios grandes), escribe "cómo aprender X desde cero".
Así compites en búsquedas con intención de aprender, donde Roadmapia tiene ventaja.

EJEMPLOS de transformación correcta:
  ❌ "Inteligencia artificial en el mercado laboral 2026"  ← lo cubre El País, Forbes, etc.
  ✅ "Cómo aprender inteligencia artificial desde cero en 2026"  ← intención de aprender, menos competencia

  ❌ "Ciberseguridad: profesión más demandada"
  ✅ "Cómo aprender ciberseguridad sin experiencia previa"

  ❌ "No-code transforma las empresas"
  ✅ "Cómo aprender no-code y crear apps sin programar"

El artículo debe:
✓ Tener ALTO volumen de búsqueda (tema caliente, no nicho)
✓ Usar intención "cómo aprender X" (no noticias, no debate)
✓ Ser algo en lo que Roadmapia puede ayudar directamente con un roadmap
✓ Tener keyword principal que empiece por "cómo aprender" o "aprender X desde cero"

Devuelve un JSON con este único tema:
{{
  "trending_raw": "el tema trending que detectaste (ej: inteligencia artificial generativa)",
  "keyword_principal": "cómo aprender X desde cero (la transformación learning-intent)",
  "tema": "descripción del tema del artículo",
  "titulo": "Cómo aprender X desde cero en {año} — 55-60 chars total",
  "slug": "como-aprender-x-desde-cero-{año}",
  "resumen": "Resumen 120-155 chars con beneficio concreto",
  "categoria": "Categoría",
  "emoji": "emoji",
  "minutos": 8,
  "por_que_trending": "Por qué X está en auge ahora mismo (1-2 frases con contexto actual)"
}}

Devuelve SOLO el JSON."""

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=RESEARCH_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )

    text = strip_codeblock(response.content[0].text)
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


# ─── Generación de artículos con Claude ───────────────────────────────────────

SYSTEM_PROMPT = """Eres un experto en SEO y redacción de contenidos para Roadmapia (roadmapia.com).
Roadmapia genera roadmaps de aprendizaje personalizados con IA. Planes: Gratis, Básico 7€/mes, Pro 17€/mes.

REGLAS SEO ESTRICTAS (Google Helpful Content):
• Título <title>: 55-60 chars exactos. Keyword al inicio. Sin clickbait.
• Meta description: 148-158 chars exactos. Beneficio + CTA implícita.
• H1 único. H2: 5-7 secciones con keywords semánticas.
• 950-1350 palabras en texto visible. Práctico y directo.
• 2-3 links internos a otros artículos del blog integrados en el texto.
• FAQ final: 3-4 preguntas reales (People Also Ask). H3 + respuesta 2-4 frases.
• JSON-LD: BlogPosting + FAQPage con datos reales (no placeholders).
• Tono: tutea al lector. Párrafos de 2-4 líneas. Sin relleno.
• CTA al final en <div class="blog-post-cta">.

Devuelve SOLO el HTML del template Jinja2. Sin explicaciones ni markdown.
El archivo empieza directamente con: {%% extends "base.html" %%}"""


def build_article_prompt(topic: dict, registry: dict, now: datetime) -> str:
    fecha_es  = format_date_es(now)
    fecha_iso = format_date_iso(now)
    slug      = topic["slug"]
    año       = now.year
    links     = articles_for_links(registry)
    categoria = topic.get("categoria", "Aprendizaje")
    emoji     = topic.get("emoji", "📚")

    return (
        f"Genera el artículo de blog SEO completo.\n\n"
        f"DATOS:\n"
        f"- Keyword principal: {topic['keyword_principal']}\n"
        f"- Tema: {topic['tema']}\n"
        f"- Keywords secundarias: {', '.join(topic.get('keywords_secundarias', []))}\n"
        f"- Categoría: {categoria} | Emoji: {emoji}\n"
        f"- Slug: {slug}\n"
        f"- URL: https://roadmapia.com/blog/{slug}\n"
        f"- Fecha: {fecha_es} | ISO: {fecha_iso}\n"
        f"- Año: {año}\n\n"
        f"ARTÍCULOS EXISTENTES (para 2-3 links internos):\n{links}\n\n"
        f"ESTRUCTURA OBLIGATORIA:\n"
        f"1. Intro directa (2 párrafos) — responde la pregunta sin preámbulos\n"
        f"2. El error más común (H2)\n"
        f"3. Cómo empezar / Guía paso a paso (H2 + H3s si procede)\n"
        f"4. Recursos / Herramientas / Materiales (H2)\n"
        f"5. ¿Cuánto tiempo lleva? (H2)\n"
        f"6. Sección adicional relevante (H2)\n"
        f"7. Preguntas frecuentes (H2 + 3-4 H3 con respuestas)\n"
        f"8. CTA con Roadmapia\n\n"
        f"FORMATO HTML EXACTO:\n"
        f"{{% extends \"base.html\" %}}\n"
        f"{{% block title %}}[TÍTULO 55-60 chars] — RoadmapIA Blog{{% endblock %}}\n"
        f"{{% block description %}}[META DESC 148-158 chars]{{% endblock %}}\n"
        f"{{% block canonical %}}https://roadmapia.com/blog/{slug}{{% endblock %}}\n"
        f"{{% block og_title %}}[TÍTULO]{{% endblock %}}\n"
        f"{{% block head %}}\n"
        f'<script type="application/ld+json">\n'
        f'{{\n'
        f'  "@context": "https://schema.org",\n'
        f'  "@graph": [\n'
        f'    {{\n'
        f'      "@type": "BlogPosting",\n'
        f'      "headline": "[TÍTULO]",\n'
        f'      "description": "[META DESC]",\n'
        f'      "datePublished": "{fecha_iso}",\n'
        f'      "dateModified": "{fecha_iso}",\n'
        f'      "author": {{"@type": "Organization", "name": "RoadmapIA", "url": "https://roadmapia.com"}},\n'
        f'      "publisher": {{"@type": "Organization", "name": "RoadmapIA"}},\n'
        f'      "mainEntityOfPage": {{"@type": "WebPage", "@id": "https://roadmapia.com/blog/{slug}"}},\n'
        f'      "inLanguage": "es-ES",\n'
        f'      "url": "https://roadmapia.com/blog/{slug}"\n'
        f'    }},\n'
        f'    {{\n'
        f'      "@type": "FAQPage",\n'
        f'      "mainEntity": [\n'
        f'        {{"@type": "Question", "name": "[FAQ 1]", "acceptedAnswer": {{"@type": "Answer", "text": "[R1]"}}}},\n'
        f'        {{"@type": "Question", "name": "[FAQ 2]", "acceptedAnswer": {{"@type": "Answer", "text": "[R2]"}}}},\n'
        f'        {{"@type": "Question", "name": "[FAQ 3]", "acceptedAnswer": {{"@type": "Answer", "text": "[R3]"}}}}\n'
        f'      ]\n'
        f'    }}\n'
        f'  ]\n'
        f'}}\n'
        f'</script>\n'
        f"{{% endblock %}}\n"
        f"{{% block content %}}\n"
        f'<div class="blog-post-wrap">\n'
        f'  <div class="blog-post-header">\n'
        f'    <a href="/blog" class="blog-post-back">← Volver al blog</a>\n'
        f'    <div class="blog-post-meta">\n'
        f'      <span class="blog-tag">{categoria}</span>\n'
        f'      <span class="blog-time">[X] min lectura</span>\n'
        f'      <span class="blog-date">{fecha_es}</span>\n'
        f'    </div>\n'
        f'    <h1>{emoji} [TÍTULO SIN EMOJI]</h1>\n'
        f'    <p class="blog-post-excerpt">[INTRO 150-200 chars]</p>\n'
        f'  </div>\n'
        f'  <div class="blog-post-body">\n'
        f'    [CUERPO con H2, H3, p, ul, strong, links internos...]\n\n'
        f'    <section aria-label="Preguntas frecuentes">\n'
        f'      <h2>Preguntas frecuentes sobre {topic["tema"]}</h2>\n'
        f'      [3-4 H3 con preguntas + P con respuestas]\n'
        f'    </section>\n\n'
        f'    <div class="blog-post-cta">\n'
        f'      <div class="blog-cta-text">\n'
        f'        <strong>{emoji} [CTA título relacionado con el tema]</strong>\n'
        f'        <span>La IA crea tu plan personalizado en 30 segundos. Sin tarjeta de crédito.</span>\n'
        f'      </div>\n'
        f'      <a href="/auth/register" class="btn btn-primary">Empezar gratis →</a>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'</div>\n'
        f"{{% endblock %}}\n\n"
        f"RECUERDA:\n"
        f"- Devuelve SOLO el HTML completo, sin markdown ni explicaciones\n"
        f"- JSON-LD con datos REALES (no placeholders entre corchetes)\n"
        f"- Links internos integrados en el texto (no en lista)\n"
        f"- Calcula palabras reales y pon el tiempo correcto en [X]"
    )


async def generate_article(client: AsyncAnthropic, topic: dict, registry: dict, now: datetime) -> str:
    """Genera el HTML completo del artículo con Claude."""
    print(f"  ✍️  Generando artículo: '{topic['tema']}'...")
    prompt = build_article_prompt(topic, registry, now)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    html = strip_codeblock(response.content[0].text)
    words = count_words(html)
    mins  = reading_time(words)
    print(f"  📝 Artículo: ~{words} palabras, ~{mins} min lectura")
    return html


def save_article(html: str, slug: str, dry_run: bool = False) -> bool:
    if not slug:
        print("  ❌ Slug vacío, imposible guardar")
        return False

    if dry_run:
        print(f"\n{'='*60}\nDRY RUN — {slug}.html\n{'='*60}")
        print(html[:3500])
        if len(html) > 3500:
            print(f"... [{len(html)-3500} chars más]")
        return True

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    (TEMPLATES_DIR / f"{slug}.html").write_text(html, encoding="utf-8")
    print(f"  💾 Guardado: templates/blog/{slug}.html")
    return True


# ─── COMANDO: Investigar y poblar el pool ─────────────────────────────────────

async def cmd_research_niche(client: AsyncAnthropic, n: int = 15):
    """
    Investiga con Google Suggest + Claude qué temas nicho tienen
    demanda real pero baja competencia, y los añade al pool.
    """
    print(f"\n🧪 INVESTIGACIÓN NICHE — buscando {n} temas con demanda real y baja competencia...\n")

    registry = load_registry()
    pool     = load_niche_pool()

    # 1. Descubrir queries reales de Google
    queries = discover_learning_queries(max_queries=100)

    # 2. Claude analiza y selecciona las mejores oportunidades
    print(f"\n  🤖 Claude analizando {len(queries)} queries para encontrar las mejores oportunidades...")
    selected = await claude_select_niche_topics(client, queries, registry, pool, n=n)

    # 3. Añadir al pool
    max_id = max((t["id"] for t in pool), default=0)
    added  = 0
    pool_slugs = get_pool_slugs(pool)

    print(f"\n  📥 Añadiendo al pool:")
    for i, t in enumerate(selected):
        slug = t.get("slug", slugify(t.get("keyword_principal", "")))
        if slug in pool_slugs or slug in get_used_slugs(registry):
            print(f"     ⏭️  Saltado (ya existe): {slug}")
            continue

        pool.append({
            "id":                   max_id + i + 1,
            "usado":                False,
            "fecha_uso":            None,
            "tema":                 t.get("tema", t["keyword_principal"]),
            "keyword_principal":    t["keyword_principal"],
            "keywords_secundarias": t.get("keywords_secundarias", []),
            "titulo":               t.get("titulo", ""),
            "slug":                 slug,
            "resumen":              t.get("resumen", ""),
            "categoria":            t.get("categoria", "Aprendizaje"),
            "emoji":                t.get("emoji", "📚"),
            "minutos":              t.get("minutos", 7),
            "fuente":               "google-suggest",
            "razon_oportunidad":    t.get("razon_oportunidad", ""),
            "competidores":         t.get("competidores_que_lo_cubren", "bajo"),
        })
        added += 1
        print(f"     ✅ [{t.get('categoria','?')}] {t['keyword_principal']}")
        print(f"        💡 {t.get('razon_oportunidad', '')}")

    save_niche_pool(pool)
    print(f"\n🎉 Investigación completada: {added} temas nuevos añadidos al pool")
    print(f"   Pool total: {len(pool)} temas ({sum(1 for t in pool if not t.get('usado'))} disponibles)")


# ─── COMANDO: Generar artículo NICHE ─────────────────────────────────────────

async def cmd_niche(client: AsyncAnthropic, dry_run: bool = False):
    """Genera artículo del siguiente tema no usado del pool."""
    print("\n🎯 Modo NICHE — seleccionando siguiente tema del pool...")

    registry = load_registry()
    pool     = load_niche_pool()
    used     = get_used_slugs(registry)

    # Preferir temas investigados (fuente google-suggest) sobre los manuales
    topic = None
    idx   = -1
    for i, t in enumerate(pool):
        if not t.get("usado") and t["slug"] not in used:
            if t.get("fuente") == "google-suggest" and topic is None:
                topic, idx = t, i  # guardar el primero investigado
                break
            elif topic is None:
                topic, idx = t, i  # fallback al primero disponible

    if not topic:
        print("❌ Pool vacío. Ejecuta: python blog_agent.py --research-niche")
        sys.exit(1)

    fuente_label = "🔬 investigado" if topic.get("fuente") == "google-suggest" else "✍️ manual"
    print(f"  ✅ [{fuente_label}] {topic['tema']}")
    print(f"  🔗 Slug: {topic['slug']}")
    if topic.get("razon_oportunidad"):
        print(f"  💡 Oportunidad: {topic['razon_oportunidad']}")

    now  = datetime.now()
    html = await generate_article(client, topic, registry, now)
    if not save_article(html, topic["slug"], dry_run) or dry_run:
        return

    # Actualizar registro y pool
    words  = count_words(html)
    mins   = reading_time(words)
    registry["articles"].append({
        "slug":      topic["slug"],
        "titulo":    topic.get("titulo", topic["tema"]),
        "resumen":   topic.get("resumen", ""),
        "emoji":     topic.get("emoji", "📚"),
        "categoria": topic.get("categoria", "Aprendizaje"),
        "minutos":   mins,
        "fecha":     format_date_es(now),
        "fecha_iso": now.strftime("%Y-%m-%d"),
        "tipo":      "niche",
        "fuente":    topic.get("fuente", "manual"),
    })
    save_registry(registry)

    pool[idx]["usado"]     = True
    pool[idx]["fecha_uso"] = now.strftime("%Y-%m-%d")
    save_niche_pool(pool)

    generate_sitemap(registry)
    print(f"\n🎉 Artículo publicado: https://roadmapia.com/blog/{topic['slug']}")


# ─── COMANDO: Generar artículo TRENDING ──────────────────────────────────────

async def cmd_trending(client: AsyncAnthropic, dry_run: bool = False):
    """
    Investiga con Google Suggest qué temas de aprendizaje son trending
    esta semana y genera un artículo de actualidad.
    """
    print("\n🔥 Modo TRENDING — investigando qué está buscando la gente esta semana...")

    registry = load_registry()
    now      = datetime.now()

    # 1. Google Suggest → queries trending reales
    raw_queries = discover_trending_learning(now)
    print(f"  📊 {len(raw_queries)} queries de actualidad encontradas")

    # 2. Claude elige el mejor tema trending
    print("  🤖 Claude seleccionando el tema más relevante...")
    topic = await claude_select_trending_topic(client, raw_queries, registry, now)

    print(f"  ✅ Tema trending elegido: {topic['keyword_principal']}")
    print(f"  🔗 Slug: {topic['slug']}")
    print(f"  🌡️  Por qué trending: {topic.get('por_que_trending', '?')}")

    # 3. Verificar que no esté ya publicado
    slug = topic["slug"]
    if slug in get_used_slugs(registry):
        slug = f"{slug}-{now.strftime('%Y%m')}"
        topic["slug"] = slug
        print(f"  ⚠️  Slug duplicado, usando: {slug}")

    # 4. Generar el artículo
    html = await generate_article(client, topic, registry, now)
    if not save_article(html, slug, dry_run) or dry_run:
        return

    # 5. Guardar en registro
    words = count_words(html)
    mins  = reading_time(words)
    registry["articles"].append({
        "slug":      slug,
        "titulo":    topic.get("titulo", topic["keyword_principal"]),
        "resumen":   topic.get("resumen", ""),
        "emoji":     topic.get("emoji", "🔥"),
        "categoria": topic.get("categoria", "Tendencias"),
        "minutos":   mins,
        "fecha":     format_date_es(now),
        "fecha_iso": now.strftime("%Y-%m-%d"),
        "tipo":      "trending",
        "fuente":    "google-suggest",
    })
    save_registry(registry)

    generate_sitemap(registry)
    print(f"\n🎉 Artículo trending publicado: https://roadmapia.com/blog/{slug}")


# ─── Sitemap XML ─────────────────────────────────────────────────────────────

SITEMAP_PATH   = BASE_DIR / "static" / "sitemap.xml"
BASE_URL       = "https://roadmapia.com"

# Páginas estáticas principales del sitio
STATIC_PAGES = [
    {"loc": "/",          "priority": "1.0", "changefreq": "weekly"},
    {"loc": "/pricing",   "priority": "0.8", "changefreq": "monthly"},
    {"loc": "/blog",      "priority": "0.9", "changefreq": "daily"},
    {"loc": "/soporte",   "priority": "0.5", "changefreq": "monthly"},
]


def generate_sitemap(registry: dict, dry_run: bool = False) -> str:
    """
    Genera el sitemap.xml completo con todas las páginas y artículos del blog.
    Google lo usa para descubrir e indexar contenido nuevo rápidamente.
    """
    now_iso = datetime.now().strftime("%Y-%m-%d")
    articles = registry.get("articles", [])

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    # Páginas estáticas
    for page in STATIC_PAGES:
        lines += [
            "  <url>",
            f"    <loc>{BASE_URL}{page['loc']}</loc>",
            f"    <lastmod>{now_iso}</lastmod>",
            f"    <changefreq>{page['changefreq']}</changefreq>",
            f"    <priority>{page['priority']}</priority>",
            "  </url>",
        ]

    # Un <url> por cada artículo del blog
    for article in articles:
        slug     = article.get("slug", "")
        lastmod  = article.get("fecha_iso", now_iso)
        if not slug:
            continue
        lines += [
            "  <url>",
            f"    <loc>{BASE_URL}/blog/{slug}</loc>",
            f"    <lastmod>{lastmod}</lastmod>",
            "    <changefreq>monthly</changefreq>",
            "    <priority>0.7</priority>",
            "  </url>",
        ]

    lines.append("</urlset>")
    xml = "\n".join(lines)

    if dry_run:
        print(f"\n  📄 Sitemap (preview):\n{xml[:600]}...")
        return xml

    SITEMAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    SITEMAP_PATH.write_text(xml, encoding="utf-8")
    total = len(STATIC_PAGES) + len(articles)
    print(f"  🗺️  Sitemap actualizado: {total} URLs → static/sitemap.xml")
    return xml


# ─── Comandos informativos ────────────────────────────────────────────────────

def cmd_list(registry: dict):
    articles = registry.get("articles", [])
    print(f"\n📚 Artículos publicados ({len(articles)} total):\n")
    for i, a in enumerate(articles, 1):
        tipo  = {"niche": "🎯", "trending": "🔥", "manual": "✍️"}.get(a.get("tipo","manual"), "📄")
        fuente = "🔬" if a.get("fuente") == "google-suggest" else ""
        print(f"  {i:3}. {tipo}{fuente} [{a.get('categoria','?')}] {a['titulo']}")
        print(f"       /blog/{a['slug']} — {a.get('fecha','?')}")
    print()


def cmd_stats(pool: list, registry: dict):
    used_slugs = get_used_slugs(registry)
    total    = len(pool)
    usados   = sum(1 for t in pool if t.get("usado") or t["slug"] in used_slugs)
    restantes = total - usados
    investigados = sum(1 for t in pool if t.get("fuente") == "google-suggest" and not t.get("usado"))
    manuales     = restantes - investigados

    print(f"\n📊 Estado del pool:")
    print(f"  Total:           {total} temas")
    print(f"  Usados:          {usados}")
    print(f"  Disponibles:     {restantes} (~{restantes} días)")
    print(f"  └ Investigados:  {investigados} (Google Suggest + Claude)")
    print(f"  └ Manuales:      {manuales} (creados a mano, sin investigar)")

    cats = {}
    for t in pool:
        if not t.get("usado") and t["slug"] not in used_slugs:
            c = t["categoria"]
            cats[c] = cats.get(c, 0) + 1
    if cats:
        print(f"\n  Por categoría:")
        for cat, n in sorted(cats.items(), key=lambda x: -x[1])[:12]:
            print(f"    {cat:30} {n}")
    print()


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Blog Agent Roadmapia — investigación real con Google Suggest + Claude"
    )
    parser.add_argument("--type", choices=["niche", "trending"])
    parser.add_argument("--research-niche", action="store_true",
                        help="Investiga con Google Suggest y añade temas al pool")
    parser.add_argument("--research-n", type=int, default=15,
                        help="Número de temas a investigar (default: 15)")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--list",     action="store_true")
    parser.add_argument("--stats",    action="store_true")
    args = parser.parse_args()

    if args.list:
        cmd_list(load_registry())
        return

    if args.stats:
        cmd_stats(load_niche_pool(), load_registry())
        return

    if not args.type and not args.research_niche:
        parser.print_help()
        return

    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY no encontrada en .env")
        sys.exit(1)

    client = AsyncAnthropic(api_key=api_key)

    if args.research_niche:
        await cmd_research_niche(client, n=args.research_n)
    elif args.type == "niche":
        await cmd_niche(client, dry_run=args.dry_run)
    elif args.type == "trending":
        await cmd_trending(client, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
