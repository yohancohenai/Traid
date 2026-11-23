"""FastAPI application entrypoint: uvicorn ttq.main:app"""
import logging
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text

from ttq.api.routers import core, ops
from ttq.core.config import get_settings
from ttq.core.db import SessionLocal
from ttq.core.logging import setup_logging
from ttq.core.security import create_token, verify_credentials
from ttq.core.timeutil import utcnow
from ttq.models import Match

setup_logging()
log = logging.getLogger("ttq.api")
s = get_settings()
app = FastAPI(title="TT Elite Quant Pro", version="1.0.0",
              description="Research platform for TT Elite Series. Never places wagers. Estimated EV is not guaranteed profit.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

_hits: dict[str, list[float]] = {}


@app.middleware("http")
async def access_log(request: Request, call_next):
    t = time.time()
    if request.url.path == "/api/auth/login":  # brute-force protection
        ip = request.client.host if request.client else "?"
        h = [x for x in _hits.get(ip, []) if t - x < 60]
        if len(h) >= 10:
            return JSONResponse({"detail": "too many login attempts"}, status_code=429)
        _hits[ip] = h + [t]
    try:
        resp = await call_next(request)
    except Exception:  # noqa
        log.exception("unhandled error", extra={"event": request.url.path})
        return JSONResponse({"detail": "internal error"}, status_code=500)
    log.info(f"{request.method} {request.url.path} {resp.status_code} {1000*(time.time()-t):.0f}ms")
    return resp


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn):
    if not verify_credentials(body.username, body.password):
        raise HTTPException(401, "invalid credentials")
    return {"access_token": create_token(body.username), "token_type": "bearer"}


@app.get("/api/health")
def health():
    out = {"status": "ok", "time": utcnow().isoformat(), "version": app.version}
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
            out["db"] = "ok"
            out["live_matches_in_db"] = db.scalar(select(func.count(Match.id)).where(Match.is_demo.is_(False)))
            out["demo_matches_in_db"] = db.scalar(select(func.count(Match.id)).where(Match.is_demo.is_(True)))
    except Exception as e:  # noqa
        out["status"], out["db"] = "degraded", f"error: {e.__class__.__name__}"
    try:
        import redis
        redis.from_url(s.redis_url, socket_timeout=1).ping()
        out["redis"] = "ok"
    except Exception:  # noqa
        out["redis"] = "unavailable"
    return out


@app.get("/api/meta")
def meta():
    return {"timezone": s.user_timezone, "region": s.user_region, "primary_book": "Hard Rock Bet",
            "reference_books": ["DraftKings (reference only, not executable in Florida)"],
            "demo_enabled": s.enable_demo, "max_quote_age_seconds": s.max_quote_age_seconds,
            "disclaimer": "Research tool only. Probabilities are model estimates; estimated EV is conditional on the model "
                          "being accurate and is not a guarantee of profit. You place every bet yourself in the Hard Rock Bet "
                          "app. This software never places wagers. If gambling stops being fun, call 1-800-GAMBLER."}


app.include_router(core.router, prefix="/api")
app.include_router(ops.router, prefix="/api")
