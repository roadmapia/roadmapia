from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./learnai.db")

_is_sqlite = "sqlite" in DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")     # escrituras no bloquean lecturas
        cursor.execute("PRAGMA synchronous=NORMAL")   # más rápido, suficientemente seguro
        cursor.execute("PRAGMA busy_timeout=5000")    # espera 5s antes de dar "locked"
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from database.models import User, Roadmap, LessonProgress, ChatMessage, PasswordResetToken, RoadmapCache, TutorQuestionCache, SupportFAQ  # noqa
    from sqlalchemy import text
    Base.metadata.create_all(bind=engine)
    # Migraciones suaves: añadir columnas nuevas si no existen
    with engine.connect() as conn:
        for table, col, definition in [
            ("users", "acepta_marketing", "BOOLEAN DEFAULT 0"),
            ("users", "google_id", "VARCHAR"),
            ("users", "referral_code", "VARCHAR"),
            ("users", "referred_by_id", "INTEGER"),
            ("users", "plan_bonus_expires", "DATETIME"),
            ("users", "referidos_count", "INTEGER DEFAULT 0"),
            ("users", "resena_completada", "BOOLEAN DEFAULT 0"),
            ("users", "mensajes_bonus_resena", "INTEGER DEFAULT 0"),
            ("roadmaps", "estado", "VARCHAR DEFAULT 'listo'"),
            ("roadmaps", "error_msg", "TEXT"),
            ("users", "token_version", "INTEGER DEFAULT 0"),
            # ── Nuevas columnas para cola + generación progresiva ──────────────
            ("roadmaps", "idioma", "VARCHAR DEFAULT 'es'"),
            ("roadmaps", "tema_normalizado", "VARCHAR"),
            ("roadmaps", "modulos_estado", "TEXT"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
                conn.commit()
            except Exception:
                pass  # columna ya existe
    print("✅ Base de datos inicializada")
