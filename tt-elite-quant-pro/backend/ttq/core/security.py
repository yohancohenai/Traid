from datetime import timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from ttq.core.config import get_settings
from ttq.core.timeutil import utcnow

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
ALG = "HS256"


def verify_credentials(username: str, password: str) -> bool:
    s = get_settings()
    if username != s.admin_username:
        return False
    if s.admin_password_hash:
        return bcrypt.checkpw(password.encode(), s.admin_password_hash.encode())
    return password == s.admin_password


def create_token(sub: str) -> str:
    s = get_settings()
    return jwt.encode({"sub": sub, "exp": utcnow() + timedelta(minutes=s.jwt_expire_minutes)}, s.jwt_secret, algorithm=ALG)


def current_user(token: str | None = Depends(oauth2)) -> str:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALG])["sub"]
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token", headers={"WWW-Authenticate": "Bearer"})
