"""
Script de migración: añade embed de YouTube a roadmaps existentes que no lo tienen.
Uso: .venv/bin/python migrate_videos.py
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from database.database import SessionLocal
from database.models import Roadmap, RoadmapCache
from core.youtube import enrich_roadmap_with_youtube


def necesita_embed(contenido: dict) -> bool:
    """Devuelve True si algún recurso del roadmap no tiene embed."""
    for fase in contenido.get("fases", []):
        for leccion in fase.get("lecciones", []):
            for recurso in leccion.get("recursos", []):
                if not recurso.get("embed"):
                    return True
    return False


def contar_sin_embed(contenido: dict) -> int:
    return sum(
        1
        for fase in contenido.get("fases", [])
        for leccion in fase.get("lecciones", [])
        for recurso in leccion.get("recursos", [])
        if not recurso.get("embed")
    )


async def migrar():
    db = SessionLocal()
    try:
        # --- Migrar Roadmaps de usuarios ---
        roadmaps = db.query(Roadmap).filter(
            Roadmap.estado == "listo",
            Roadmap.activo == True
        ).all()

        print(f"📋 Roadmaps activos encontrados: {len(roadmaps)}")
        actualizados = 0
        errores = 0

        for rm in roadmaps:
            try:
                contenido = json.loads(rm.contenido)
                sin_embed = contar_sin_embed(contenido)

                if sin_embed == 0:
                    print(f"  ✅ Roadmap #{rm.id} '{rm.tema}' — ya tiene todos los embeds")
                    continue

                print(f"  🔄 Roadmap #{rm.id} '{rm.tema}' — {sin_embed} recursos sin embed...")
                contenido_nuevo = await enrich_roadmap_with_youtube(contenido)
                rm.contenido = json.dumps(contenido_nuevo, ensure_ascii=False)
                db.commit()
                actualizados += 1
                print(f"     ✅ Actualizado")

            except Exception as e:
                errores += 1
                print(f"     ❌ Error en roadmap #{rm.id}: {e}")
                db.rollback()

        print()

        # --- Migrar caché de roadmaps ---
        caches = db.query(RoadmapCache).all()
        print(f"📦 Entradas en caché encontradas: {len(caches)}")
        caches_actualizados = 0

        for cache in caches:
            try:
                contenido = json.loads(cache.contenido)
                sin_embed = contar_sin_embed(contenido)

                if sin_embed == 0:
                    print(f"  ✅ Caché '{cache.tema_normalizado}' ({cache.nivel}) — ya tiene todos los embeds")
                    continue

                print(f"  🔄 Caché '{cache.tema_normalizado}' ({cache.nivel}) — {sin_embed} recursos sin embed...")
                contenido_nuevo = await enrich_roadmap_with_youtube(contenido)
                cache.contenido = json.dumps(contenido_nuevo, ensure_ascii=False)
                db.commit()
                caches_actualizados += 1
                print(f"     ✅ Actualizado")

            except Exception as e:
                print(f"     ❌ Error en caché '{cache.tema_normalizado}': {e}")
                db.rollback()

        print()
        print("=" * 50)
        print(f"✅ Roadmaps actualizados : {actualizados}/{len(roadmaps)}")
        print(f"✅ Cachés actualizadas   : {caches_actualizados}/{len(caches)}")
        if errores:
            print(f"❌ Errores              : {errores}")
        print("=" * 50)

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(migrar())
