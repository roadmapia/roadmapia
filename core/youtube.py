import asyncio
import yt_dlp


def _search_video_sync(query: str, idioma: str = "es") -> dict:
    """Búsqueda síncrona con yt-dlp (se ejecuta en thread pool)."""
    lang_hint = "en" if idioma == "en" else "es"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(
                f"ytsearch1:{query} {lang_hint}",
                download=False
            )
            if result and result.get("entries"):
                video = result["entries"][0]
                video_id = video["id"]
                return {
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "embed": f"https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1",
                    "titulo_real": video.get("title", ""),
                }
    except Exception as e:
        print(f"⚠️ yt-dlp error para '{query}': {e}")

    # Fallback: enlace de búsqueda
    return {
        "url": f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
        "embed": None,
    }


async def search_youtube_video(query: str, idioma: str = "es") -> dict:
    """Busca un vídeo en YouTube con yt-dlp (sin API key, sin quota)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_video_sync, query, idioma)


async def enrich_roadmap_with_youtube(roadmap: dict) -> dict:
    """Enriquece el roadmap reemplazando URLs de búsqueda con vídeos reales."""
    idioma = roadmap.get("idioma", "es")

    # Recopilar todos los recursos que aún no tienen embed
    resource_refs = [
        recurso
        for fase in roadmap.get("fases", [])
        for leccion in fase.get("lecciones", [])
        for recurso in leccion.get("recursos", [])
        if not recurso.get("embed")
    ]

    if not resource_refs:
        return roadmap

    # Limitar concurrencia para no saturar YouTube (máx 5 simultáneas)
    semaphore = asyncio.Semaphore(5)

    async def search_with_limit(query, lang):
        async with semaphore:
            return await search_youtube_video(query, lang)

    print(f"🎬 Buscando {len(resource_refs)} vídeos con yt-dlp...")
    results = await asyncio.gather(
        *[search_with_limit(r["texto"], idioma) for r in resource_refs],
        return_exceptions=True
    )

    encontrados = 0
    for recurso, result in zip(resource_refs, results):
        if isinstance(result, dict):
            recurso["url"] = result["url"]
            if result.get("embed"):
                recurso["embed"] = result["embed"]
                encontrados += 1
            if result.get("titulo_real"):
                recurso["titulo_real"] = result["titulo_real"]

    print(f"✅ yt-dlp: {encontrados}/{len(resource_refs)} vídeos encontrados")
    return roadmap
