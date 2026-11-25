"""
Rate limiting (tiêu chí 7) — Sliding Window 60 giây lưu trên Redis Sorted Set.
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """
    Giới hạn tối đa RATE_LIMIT_PER_MINUTE request / 60 giây cho mỗi API key.
    Lưu trạng thái trong Redis để dùng chung giữa nhiều worker/instance và bền vững qua restart.
    """
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    redis_key = f"rate_limit:{key_hash}"

    try:
        r.zremrangebyscore(redis_key, "-inf", window_start)
        current_count = r.zcard(redis_key)

        if current_count >= limit:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Rate limiter storage unavailable") from exc
