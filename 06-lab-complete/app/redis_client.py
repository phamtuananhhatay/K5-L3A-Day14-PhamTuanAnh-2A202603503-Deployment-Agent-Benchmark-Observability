"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

Lưu ý thiết kế:
  • Khởi tạo connection pool lười (lazy), KHÔNG gọi ping() lúc import để container
    vẫn khởi động và trả /health 200 ngay cả khi Redis chưa sẵn sàng.
  • redis_healthy() kiểm tra thực tế bằng PING với timeout ngắn cho endpoint /ready.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url or "redis://localhost:6379/0",
    decode_responses=True,
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
)


def redis_healthy() -> bool:
    """Trả True nếu Redis phản hồi PING, False nếu mất kết nối."""
    try:
        return bool(r.ping())
    except Exception:
        return False
