#!/bin/bash
# ─────────────────────────────────────────────────────────────
# blog_cron.sh — Script que ejecutan los crons del blog agent
# ─────────────────────────────────────────────────────────────
# Uso (no ejecutar directamente, lo llama el cron):
#   niche     → publica artículo nicho diario
#   trending  → publica artículo trending semanal
#   research  → investiga nuevos temas nicho y los añade al pool

APP_DIR="/var/www/roadmapia"
PYTHON="$APP_DIR/.venv/bin/python"
AGENT="$APP_DIR/blog_agent.py"
LOG="$APP_DIR/logs/blog_agent.log"
TIPO="${1:-niche}"

# Crear carpeta de logs si no existe
mkdir -p "$APP_DIR/logs"

echo "" >> "$LOG"
echo "═══════════════════════════════════════════" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') — Iniciando: $TIPO" >> "$LOG"
echo "═══════════════════════════════════════════" >> "$LOG"

cd "$APP_DIR" || exit 1

if [ "$TIPO" = "research" ]; then
    "$PYTHON" "$AGENT" --research-niche --research-n 15 >> "$LOG" 2>&1
    STATUS=$?
else
    "$PYTHON" "$AGENT" --type "$TIPO" >> "$LOG" 2>&1
    STATUS=$?
fi

if [ $STATUS -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ Completado correctamente" >> "$LOG"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ Error (código $STATUS)" >> "$LOG"
fi

exit $STATUS
