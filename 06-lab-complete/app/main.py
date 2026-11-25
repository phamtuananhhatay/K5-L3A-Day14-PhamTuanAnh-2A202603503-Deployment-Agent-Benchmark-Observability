"""
Production AI Agent — Part 6 Final Project.
"""
import asyncio
import json
import logging
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r as redis_client, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Xuất mỗi dòng log của ứng dụng thành đúng 1 JSON object hợp lệ trên 1 dòng."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        msg = record.getMessage()
        extra_data = getattr(record, "structured", None)
        if isinstance(extra_data, dict):
            payload.update(extra_data)
            payload.setdefault("msg", msg)
        else:
            payload["msg"] = msg
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logger() -> logging.Logger:
    app_logger = logging.getLogger("agent")
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_logger.setLevel(level)
    app_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _setup_logger()
START_TIME = time.time()
_shutting_down = False
_in_flight = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _shutting_down
    _shutting_down = False

    prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        global _shutting_down
        _shutting_down = True
        logger.info(
            "SIGTERM received, draining in-flight requests",
            extra={"structured": {"event": "sigterm", "in_flight": _in_flight}},
        )
        if callable(prev_sigterm):
            prev_sigterm(signum, frame)

    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:
        pass

    logger.info(
        "Agent started",
        extra={
            "structured": {
                "event": "startup",
                "environment": settings.environment,
                "port": settings.port,
            }
        },
    )

    yield

    _shutting_down = True
    deadline = time.time() + 8.0
    while _in_flight > 0 and time.time() < deadline:
        await asyncio.sleep(0.05)

    try:
        redis_client.close()
    except Exception:
        pass

    logger.info(
        "Agent shutdown complete",
        extra={"structured": {"event": "shutdown", "in_flight": _in_flight}},
    )


app = FastAPI(
    title="Production AI Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    global _in_flight
    _in_flight += 1
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        _in_flight -= 1
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "HTTP request processed",
            extra={
                "structured": {
                    "event": "http_request",
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                }
            },
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled server error",
        extra={
            "structured": {
                "event": "unhandled_error",
                "path": request.url.path,
                "error_type": type(exc).__name__,
            }
        },
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi tiến trình còn sống, không phụ thuộc Redis."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "environment": settings.environment,
    }


@app.get("/ready")
def ready():
    """Readiness probe: trả 200 khi sẵn sàng và kết nối được Redis, ngược lại trả 503."""
    if _shutting_down or not redis_healthy():
        raise HTTPException(status_code=503, detail="Service not ready: Redis unavailable")
    return {"status": "ready", "redis": "connected"}


@app.post("/ask")
async def ask(
    body: AskRequest,
    api_key: str = Depends(verify_api_key),
):
    check_rate_limit(api_key)
    check_budget()

    answer = await asyncio.to_thread(llm_ask, body.question)

    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost_usd = record_cost(input_tokens, output_tokens)

    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "cost_usd": cost_usd,
    }
