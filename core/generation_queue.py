"""
generation_queue.py — Cola de prioridad para generación de roadmaps.

Prioridad: Pro (0) > Basic (1) > Free (2). Dentro del mismo plan, FIFO.
Máximo MAX_CONCURRENT trabajos simultáneos para proteger el VPS de 1 CPU / 4 GB RAM.
Si la cola supera MAX_QUEUE_SIZE, se rechaza la solicitud con un error elegante.
"""

import asyncio
import heapq
import logging

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 3   # Generaciones en paralelo — conservador para 1 CPU / 4 GB
MAX_QUEUE_SIZE = 50  # Si hay más de 50 esperando → rechazar (algo va muy mal)
PLAN_PRIORITY  = {"pro": 0, "basic": 1, "free": 2}


class _GenerationQueue:
    """Singleton que gestiona la cola de prioridad de generaciones."""

    def __init__(self):
        self._heap: list   = []          # (priority, counter, roadmap_id)
        self._counter: int = 0
        self._active: set  = set()       # roadmap_ids procesándose ahora mismo
        self._lock: asyncio.Lock | None  = None
        self._started: bool = False

    # ── Lazy lock (se crea cuando ya existe el event loop) ────────────────────
    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ── API pública ───────────────────────────────────────────────────────────

    async def enqueue(self, roadmap_id: int, user_plan: str) -> int | None:
        """
        Añade el roadmap a la cola.
        Devuelve la posición estimada (1 = siguiente en ejecutarse) o None si la cola está llena.
        """
        async with self._get_lock():
            if len(self._heap) >= MAX_QUEUE_SIZE:
                return None   # Cola llena → llamante debe mostrar error elegante
            priority = PLAN_PRIORITY.get(user_plan, 2)
            self._counter += 1
            heapq.heappush(self._heap, (priority, self._counter, roadmap_id))
            return self._position_of(roadmap_id)

    async def get_info(self, roadmap_id: int) -> dict:
        """
        Devuelve un dict con el estado de este roadmap respecto a la cola:
        { estado, posicion, activos, cola }
        """
        async with self._get_lock():
            if roadmap_id in self._active:
                return {
                    "estado":   "generando",
                    "posicion": 0,
                    "activos":  len(self._active),
                    "cola":     len(self._heap),
                }
            pos = self._position_of(roadmap_id)
            if pos > 0:
                return {
                    "estado":   "en_cola",
                    "posicion": pos,
                    "activos":  len(self._active),
                    "cola":     len(self._heap),
                }
        return {
            "estado":   "no_encontrado",
            "posicion": 0,
            "activos":  len(self._active),
            "cola":     len(self._heap),
        }

    async def start(self, generate_fn):
        """
        Arranca los workers. Debe llamarse desde el lifespan de FastAPI
        (cuando el event loop ya está corriendo).
        """
        if self._started:
            return
        self._started = True
        for _ in range(MAX_CONCURRENT):
            asyncio.create_task(self._worker(generate_fn))
        logger.info(f"✅ Cola de generación lista — {MAX_CONCURRENT} workers, max {MAX_QUEUE_SIZE} en espera")

    # ── Internos ──────────────────────────────────────────────────────────────

    def _position_of(self, roadmap_id: int) -> int:
        """Posición en el heap ordenado. 1 = siguiente. 0 = no está."""
        for i, (_, _, rid) in enumerate(sorted(self._heap)):
            if rid == roadmap_id:
                return i + 1
        return 0

    async def _worker(self, generate_fn):
        """Loop eterno: extrae un trabajo del heap y lo ejecuta."""
        while True:
            roadmap_id = None
            async with self._get_lock():
                if self._heap:
                    _, _, roadmap_id = heapq.heappop(self._heap)
                    self._active.add(roadmap_id)

            if roadmap_id is None:
                await asyncio.sleep(0.5)
                continue

            try:
                logger.info(f"🚀 [Queue] Iniciando generación de roadmap {roadmap_id}")
                await generate_fn(roadmap_id)
            except Exception as e:
                logger.error(f"❌ [Queue] Error en roadmap {roadmap_id}: {e}")
                _mark_error_db(roadmap_id, str(e))
            finally:
                async with self._get_lock():
                    self._active.discard(roadmap_id)
                logger.info(f"✔ [Queue] Roadmap {roadmap_id} finalizado")


# ── Helper DB (síncrono, no toca el event loop) ───────────────────────────────

def _mark_error_db(roadmap_id: int, error: str):
    from database.database import SessionLocal
    from database.models import Roadmap
    db = SessionLocal()
    try:
        rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id).first()
        if rm:
            rm.estado    = "error"
            rm.error_msg = error[:500]
            db.commit()
    finally:
        db.close()


# ── Singleton global ───────────────────────────────────────────────────────────
generation_queue = _GenerationQueue()
