from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Date, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, date
from database.database import Base
import secrets


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    nombre = Column(String, nullable=False)
    plan = Column(String, default="free")  # "free", "basic", "pro"
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    roadmaps_este_mes = Column(Integer, default=0)
    mensajes_hoy = Column(Integer, default=0)
    fecha_reset_roadmaps = Column(Date, default=date.today)
    fecha_reset_mensajes = Column(Date, default=date.today)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    activo = Column(Boolean, default=True)
    acepta_marketing = Column(Boolean, default=False)
    google_id = Column(String, nullable=True)
    referral_code = Column(String, unique=True, nullable=True)
    referred_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    plan_bonus_expires = Column(DateTime, nullable=True)
    referidos_count = Column(Integer, default=0)
    resena_completada = Column(Boolean, default=False)      # ha dejado reseña en Trustpilot
    mensajes_bonus_resena = Column(Integer, default=0)      # +5 si dejó reseña

    roadmaps = relationship("Roadmap", back_populates="user", cascade="all, delete-orphan")
    progreso = relationship("LessonProgress", back_populates="user", cascade="all, delete-orphan")
    mensajes = relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")


class Roadmap(Base):
    __tablename__ = "roadmaps"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tema = Column(String, nullable=False)
    nivel = Column(String, nullable=False)
    horas_semana = Column(Integer, nullable=False)
    contenido = Column(Text, nullable=False)  # JSON generado por IA
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
    activo = Column(Boolean, default=True)

    user = relationship("User", back_populates="roadmaps")
    progreso = relationship("LessonProgress", back_populates="roadmap", cascade="all, delete-orphan")
    mensajes = relationship("ChatMessage", back_populates="roadmap", cascade="all, delete-orphan")


class LessonProgress(Base):
    __tablename__ = "lesson_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    roadmap_id = Column(Integer, ForeignKey("roadmaps.id"), nullable=False)
    leccion_id = Column(String, nullable=False)
    checklist = Column(Text, default="[]")  # JSON array de booleanos
    completada = Column(Boolean, default=False)
    fecha_completada = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="progreso")
    roadmap = relationship("Roadmap", back_populates="progreso")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    roadmap_id = Column(Integer, ForeignKey("roadmaps.id"), nullable=False)
    leccion_id = Column(String, nullable=False)
    rol = Column(String, nullable=False)  # "user" o "assistant"
    contenido = Column(Text, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="mensajes")
    roadmap = relationship("Roadmap", back_populates="mensajes")


class TutorQuestionCache(Base):
    """Cache de preguntas al tutor IA para evitar llamadas repetidas a DeepSeek."""
    __tablename__ = "tutor_question_cache"

    id = Column(Integer, primary_key=True)
    pregunta_normalizada = Column(String, nullable=False, index=True)
    pregunta_original    = Column(String, nullable=False)
    respuesta            = Column(Text, nullable=False)
    tema                 = Column(String, nullable=False)
    nivel                = Column(String, nullable=False)
    idioma               = Column(String, default="es")
    usos                 = Column(Integer, default=1)
    fecha_creacion       = Column(DateTime, default=datetime.utcnow)
    fecha_ultimo_uso     = Column(DateTime, default=datetime.utcnow)


class SupportFAQ(Base):
    """FAQs de soporte: preguntas que llegan por el chat/email."""
    __tablename__ = "support_faq"

    id                   = Column(Integer, primary_key=True)
    pregunta_normalizada = Column(String, nullable=False, index=True)
    pregunta_original    = Column(String, nullable=False)
    respuesta            = Column(Text, nullable=True)   # None = pendiente de respuesta
    respondida           = Column(Boolean, default=False)
    usos                 = Column(Integer, default=0)
    fecha                = Column(DateTime, default=datetime.utcnow)


class RoadmapCache(Base):
    """Cache de roadmaps por tema+nivel+idioma para evitar regenerar."""
    __tablename__ = "roadmap_cache"

    id = Column(Integer, primary_key=True)
    tema_normalizado = Column(String, nullable=False, index=True)
    nivel = Column(String, nullable=False)
    idioma = Column(String, nullable=False, default="es")
    contenido = Column(Text, nullable=False)           # JSON del roadmap
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
    fecha_videos   = Column(DateTime, default=datetime.utcnow)  # última vez que se actualizaron los vídeos


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    expiry = Column(DateTime, nullable=False)
    usado = Column(Boolean, default=False)

    user = relationship("User")
