#!/bin/bash
# ================================
# LearnAI — Script de arranque
# ================================
# Uso: ./start.sh

cd "$(dirname "$0")"

echo "🚀 Arrancando LearnAI..."
echo ""

# Verificar .env
if [ ! -f .env ]; then
  echo "❌ No se encuentra el archivo .env"
  echo "   Copia .env.example a .env y configura las keys"
  exit 1
fi

# Compilar Tailwind CSS
echo "🎨 Compilando Tailwind CSS..."
npm run css:build 2>/dev/null && echo "   ✅ CSS compilado" || echo "   ⚠️  Error compilando CSS"

# Arrancar servidor
echo ""
echo "🌐 Servidor en: http://localhost:8000"
echo "   Ctrl+C para parar"
echo ""

.venv/bin/uvicorn main:app --reload --port 8000
