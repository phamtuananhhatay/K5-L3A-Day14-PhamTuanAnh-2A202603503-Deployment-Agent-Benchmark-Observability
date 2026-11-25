"""
Cost guard (tiêu chí 8) — Theo dõi và bảo vệ ngân sách LLM trên Redis.
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _budget_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (
        f"cost:daily:{now.strftime('%Y-%m-%d')}",
        f"cost:monthly:{now.strftime('%Y-%m')}",
    )


def check_budget() -> None:
    """Kiểm tra tổng chi phí trên Redis TRƯỚC khi gọi LLM; vượt ngưỡng trả HTTP 402."""
    daily_key, monthly_key = _budget_keys()
    try:
        daily_spent = float(r.get(daily_key) or 0.0)
        monthly_spent = float(r.get(monthly_key) or 0.0)
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Cost guard storage unavailable") from exc

    if daily_spent >= settings.daily_budget_usd or monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail="LLM budget exceeded",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Cộng dồn chi phí USD của request vào Redis SAU khi gọi LLM và trả về chi phí request."""
    cost_usd = (
        (max(1, input_tokens) / 1000.0) * PRICE_INPUT_PER_1K
        + (max(1, output_tokens) / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    daily_key, monthly_key = _budget_keys()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(daily_key, cost_usd)
        pipe.expire(daily_key, 2 * 24 * 3600)
        pipe.incrbyfloat(monthly_key, cost_usd)
        pipe.expire(monthly_key, 32 * 24 * 3600)
        pipe.execute()
    except redis.RedisError:
        pass
    return round(cost_usd, 8)
