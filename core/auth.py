from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import Optional
import os
import secrets
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("❌ SECRET_KEY no configurada en .env — la aplicación no puede arrancar sin ella.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# Hash dummy para timing-safe login (evita enumeración de usuarios)
_DUMMY_HASH = pwd_context.hash("dummy_password_for_timing")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def verify_password_safe(plain: str, hashed: Optional[str]) -> bool:
    """Siempre ejecuta bcrypt aunque el usuario no exista (anti timing-attack)."""
    if not hashed:
        pwd_context.verify(plain, _DUMMY_HASH)
        return False
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None, token_version: int = 0) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire, "ver": token_version})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user_from_token(token: str, db: Session):
    from database.models import User
    payload = decode_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == int(user_id), User.activo == True).first()
    if not user:
        return None
    # Verificar versión del token — si el usuario cambió contraseña, ver != token_version
    token_ver = payload.get("ver", 0)
    user_ver = user.token_version or 0
    if token_ver != user_ver:
        return None  # Token revocado
    return user


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    access_token: Optional[str] = Cookie(default=None),
    db: Session = None
):
    """Extrae el usuario del Bearer token o de la cookie."""
    from database.database import get_db
    from database.models import User

    actual_token = token or access_token
    if not actual_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    user = get_current_user_from_token(actual_token, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")
    return user
