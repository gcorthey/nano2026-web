from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
import os
import hashlib

SECRET_KEY = os.environ.get("SECRET_KEY", "50d5842e8962618c774c72ae20cbc6c58e9cea35c2a41aa2096b63f4c6a8d7f3")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 horas
REVISION_TOKEN_EXPIRE_HOURS = 72
PASSWORD_RESET_TOKEN_EXPIRE_HOURS = 2

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_revision_token(abstract_id: int, email_autor: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=REVISION_TOKEN_EXPIRE_HOURS)
    payload = {
        "purpose": "abstract_revision",
        "abstract_id": abstract_id,
        "email_autor": email_autor,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def password_reset_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()

def create_password_reset_token(user_id: int, email: str, password_hash: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
    payload = {
        "purpose": "password_reset",
        "user_id": user_id,
        "email": email,
        "pwd": password_reset_fingerprint(password_hash),
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_revision_token(token: str) -> dict:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("purpose") != "abstract_revision":
        raise JWTError("Token inválido")
    return payload

def verify_password_reset_token(token: str) -> dict:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("purpose") != "password_reset":
        raise JWTError("Token inválido")
    return payload

def get_token_from_cookie(request: Request) -> str | None:
    return request.cookies.get("access_token")

def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    token = get_token_from_cookie(request)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=302, headers={"Location": "/login"})
    except JWTError:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user

def require_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.require_password_change:
        raise HTTPException(status_code=302, headers={"Location": "/force-password-change"})
    if current_user.role != models.RoleEnum.admin:
        raise HTTPException(status_code=403, detail="Acceso solo para administradores")
    return current_user

def require_evaluador(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.require_password_change:
        raise HTTPException(status_code=302, headers={"Location": "/force-password-change"})
    if current_user.role not in (models.RoleEnum.evaluador, models.RoleEnum.admin):
        raise HTTPException(status_code=403, detail="Acceso solo para evaluadores")
    return current_user
