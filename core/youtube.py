import httpx
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


async def search_youtube_video(query: str, idioma: str = "es") -> dict:
    """Busca un vídeo real en YouTube y retorna URL de watch y embed."""
    if not YOUTUBE_API_KEY:
        return {
            "url": f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
            "embed": None
        }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(YOUTUBE_SEARCH_URL, params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 1,
                "key": YOUTUBE_API_KEY,
                "relevanceLanguage": idioma,   # "es" o "en"
                "videoEmbeddable": "true"
            })
            data = response.json()

        if data.get("items"):
            video_id = data["items"][0]["id"]["videoId"]
            titulo = data["items"][0]["snippet"]["title"]
            return {
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "embed": f"https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1",
                "titulo_real": titulo
            }
    except Exception as e:
        print(f"⚠️ YouTube API error para '{query}': {e}")

    # Fallback si falla
    return {
        "url": f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
        "embed": None
    }


async def enrich_roadmap_with_youtube(roadmap: dict) -> dict:
    """Enriquece el roadmap reemplazando URLs de búsqueda con vídeos reales."""
    if not YOUTUBE_API_KEY:
        return roadmap

    idioma = roadmap.get("idioma", "es")  # usa el idioma del roadmap

    # Recopilar todos los recursos a buscar
    resource_refs = []
    tasks = []

    for fase in roadmap.get("fases", []):
        for leccion in fase.get("lecciones", []):
            for recurso in leccion.get("recursos", []):
                tasks.append(search_youtube_video(recurso["texto"], idioma))
                resource_refs.append(recurso)

    if not tasks:
        return roadmap

    # Ejecutar todas las búsquedas en paralelo
    print(f"🎬 Buscando {len(tasks)} vídeos en YouTube...")
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Actualizar los recursos con las URLs reales
    for recurso, result in zip(resource_refs, results):
        if isinstance(result, dict):
            recurso["url"] = result["url"]
            if result.get("embed"):
                recurso["embed"] = result["embed"]
            if result.get("titulo_real"):
                recurso["titulo_real"] = result["titulo_real"]

    print(f"✅ YouTube: {sum(1 for r in results if isinstance(r, dict) and r.get('embed'))} vídeos encontrados")
    return roadmap
