#!/bin/bash
# ─────────────────────────────────────────────────────────────
# setup_cron.sh — Instala los crons del blog agent en el VPS
# Ejecutar UNA SOLA VEZ en el servidor: bash scripts/setup_cron.sh
# ─────────────────────────────────────────────────────────────

SCRIPT="/var/www/roadmapia/scripts/blog_cron.sh"

# Dar permisos de ejecución al script
chmod +x "$SCRIPT"

# Leer crons actuales y añadir los nuevos si no existen ya
CRONTAB_ACTUAL=$(crontab -l 2>/dev/null || echo "")

CRON_NICHE="0 3 * * * $SCRIPT niche"        # Cada día a las 03:00
CRON_TRENDING="0 4 * * 1 $SCRIPT trending"  # Cada lunes a las 04:00
CRON_RESEARCH="0 2 * * 0 $SCRIPT research"  # Cada domingo a las 02:00

NUEVO_CRONTAB="$CRONTAB_ACTUAL"

anadir_cron() {
    local entrada="$1"
    local descripcion="$2"
    if echo "$NUEVO_CRONTAB" | grep -qF "$entrada"; then
        echo "  ⏭️  Ya existe: $descripcion"
    else
        NUEVO_CRONTAB="$NUEVO_CRONTAB"$'\n'"$entrada"
        echo "  ✅ Añadido: $descripcion"
    fi
}

echo ""
echo "🕐 Instalando crons del Blog Agent en Roadmapia..."
echo ""

anadir_cron "$CRON_RESEARCH"  "Domingo 02:00 — Investiga temas nicho (repone el pool)"
anadir_cron "$CRON_NICHE"     "Diario   03:00 — Publica artículo nicho"
anadir_cron "$CRON_TRENDING"  "Lunes   04:00 — Publica artículo trending"

echo "$NUEVO_CRONTAB" | crontab -

echo ""
echo "📋 Crons instalados. Verificando:"
echo ""
crontab -l | grep "blog_cron"
echo ""
echo "✅ Listo. El blog publicará automáticamente:"
echo "   - Todos los días a las 03:00 → artículo nicho"
echo "   - Cada lunes a las 04:00    → artículo trending"
echo "   - Cada domingo a las 02:00  → investiga temas nuevos"
echo ""
echo "📄 Logs en: /var/www/roadmapia/logs/blog_agent.log"
