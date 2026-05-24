# Roadmapia — Plataforma de aprendizaje personalizado con IA

## ¿Qué es este proyecto?

Plataforma web freemium (roadmapia.com) donde el usuario indica qué quiere aprender y la IA genera automáticamente un roadmap completo con fases, lecciones, vídeos de YouTube embebidos y un tutor IA integrado.

- **Dominio**: roadmapia.com
- **GitHub**: https://github.com/roadmapia/roadmapia
- **VPS**: `/var/www/roadmapia/` (Hostinger, Nginx como proxy)
- **Servicio systemd**: `roadmapia`
- **Código local**: `/home/ruben/proyectos/learnai/learnai/` (carpeta heredada del nombre antiguo LearnAI)

## Documentación del proyecto

- **`docs/learnai_spec.md`** — Especificación técnica completa
- **`docs/learnai_marketing.md`** — Plan de lanzamiento y marketing

## Stack tecnológico

| Componente | Tecnología |
|---|---|
| Backend | Python 3.12 · FastAPI · Uvicorn |
| Frontend | Jinja2 templates · Tailwind CSS v4 · JS vanilla |
| Base de datos | SQLite (dev y prod actual) |
| IA | Anthropic API · `claude-sonnet-4-6` (AsyncAnthropic) |
| Vídeos | **yt-dlp** (sin API key, sin quota) |
| Pagos | Stripe (modo test configurado) |
| Seguridad | CSRF protection (`core/csrf.py`) · Rate limiting (`core/rate_limit.py`) |
| CSS framework | Tailwind CSS v4 + CSS custom en `style.css` |

## Estructura del proyecto

```
learnai/                        ← raíz del repo (nombre antiguo, no cambiar)
├── CLAUDE.md
├── docs/
└── learnai/                    ← código de la app
    ├── main.py
    ├── migrate_videos.py       ← script migración: añade embeds a roadmaps sin vídeo
    ├── start.sh                ← arranque local
    ├── .env                    ← API keys (no subir a git)
    ├── requirements.txt
    ├── package.json            ← Tailwind CSS build
    ├── database/
    │   ├── models.py           ← User, Roadmap, RoadmapCache, LessonProgress, ChatMessage
    │   └── database.py
    ├── routers/
    │   ├── auth.py             ← registro, login, JWT via cookies
    │   ├── roadmaps.py         ← CRUD roadmaps + vista lección + caché
    │   ├── progress.py         ← checklist y completar lección (AJAX)
    │   ├── tutor.py            ← chat IA (AJAX)
    │   └── payments.py         ← Stripe checkout + webhook
    ├── core/
    │   ├── ai_generator.py     ← genera roadmap con Claude (AsyncAnthropic)
    │   ├── tutor_ai.py         ← chat tutor con Claude (AsyncAnthropic)
    │   ├── youtube.py          ← busca vídeos con yt-dlp (sin API key)
    │   ├── auth.py             ← JWT, hashing bcrypt
    │   ├── plans.py            ← lógica de límites por plan
    │   ├── csrf.py             ← protección CSRF
    │   └── rate_limit.py       ← rate limiting por IP/usuario
    ├── templates/              ← Jinja2 HTML
    │   ├── lesson.html         ← vista de lección con vídeo embebido y tutor IA
    │   └── lesson_locked.html  ← lección bloqueada para plan free
    └── static/
        ├── css/
        │   ├── tailwind.css    ← generado por npm run css:build
        │   ├── src/input.css   ← fuente Tailwind
        │   └── style.css       ← CSS custom del proyecto
        └── js/main.js
```

## Comandos importantes

```bash
# --- LOCAL ---
# Arrancar la app en local
cd /home/ruben/proyectos/learnai/learnai
.venv/bin/uvicorn main:app --reload

# Compilar Tailwind CSS (cuando cambies clases)
npm run css:build

# Compilar Tailwind en modo watch (mientras desarrollas)
npm run css:watch

# Migrar vídeos (rellenar embeds en roadmaps existentes)
.venv/bin/python migrate_videos.py

# --- DEPLOY (en el VPS) ---
cd /var/www/roadmapia
git pull
sudo systemctl restart roadmapia
sudo systemctl status roadmapia

# Instalar nuevas dependencias en VPS
cd /var/www/roadmapia
.venv/bin/pip install -r requirements.txt
```

## Variables de entorno (.env)

```
ANTHROPIC_API_KEY=sk-ant-...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_BASIC=price_...
STRIPE_PRICE_PRO=price_...
SECRET_KEY=clave_jwt_secreta
DATABASE_URL=sqlite:///./roadmapia.db
BASE_URL=https://roadmapia.com
```

> ⚠️ YOUTUBE_API_KEY ya NO se usa — los vídeos se buscan con yt-dlp sin API key.

## MCPs instalados (herramientas IA disponibles)

| MCP | Para qué sirve |
|---|---|
| **Playwright** | Ver y controlar el navegador, hacer screenshots, probar interacciones |
| **Context7** | Documentación actualizada de cualquier librería (Tailwind, FastAPI, etc.) |

## Planes

| Plan | Precio | Roadmaps/mes | Mensajes tutor/mes | Anuncios | Certificado |
|---|---|---|---|---|---|
| Free | 0€ | 1 | 10 | Sí | No |
| Básico | 7€/mes | 5 | 50 | No | No |
| Pro | 17€/mes | ∞ | ∞ | No | Sí |

## Estado actual

- [x] App completa desplegada en VPS (roadmapia.com)
- [x] Backend completo (auth, roadmaps, tutor, pagos)
- [x] Frontend con diseño oscuro moderno
- [x] Vídeos YouTube embebidos con yt-dlp (sin API key, sin quota)
- [x] Tailwind CSS v4 configurado
- [x] SEO básico (meta tags, OG, canonical)
- [x] Protección CSRF
- [x] Rate limiting
- [x] Lecciones bloqueadas para plan free
- [ ] Stripe configurado con keys reales de producción
- [ ] Google AdSense activado
- [ ] Blog

## Notas de desarrollo críticas

- El cliente Anthropic es **AsyncAnthropic** (async) — nunca usar el síncrono
- Los vídeos usan **yt-dlp** — NO la YouTube Data API (eliminada por quota limitada)
- Compilar Tailwind tras cambiar clases: `npm run css:build`
- El JSON del roadmap se guarda en BD como texto en columna `contenido`
- Chat y checklist usan AJAX (sin recarga de página)
- Los contadores (roadmaps_este_mes, mensajes_hoy) se resetean automáticamente en `core/plans.py`
- Si un roadmap se creó sin embeds, ejecutar `migrate_videos.py` para rellenarlos
