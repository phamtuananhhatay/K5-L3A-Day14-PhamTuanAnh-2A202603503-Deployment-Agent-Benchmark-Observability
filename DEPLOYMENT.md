# Deployment Information

## Public URL
https://day14-agent-phamtuananh.onrender.com

## Platform
Render (Docker Web Service `day14-agent-phamtuananh` + Render Key Value / Redis `day14-redis-phamtuananh` managed via Blueprint `render.yaml`)

> **Note (Render Free Tier):** Instance miễn phí sẽ tự tạm nghỉ (spin down) sau 15 phút không có request; request đầu tiên đánh thức container có thể mất khoảng 30–50 giây trước khi phản hồi `200 OK`.

## Test Commands

### 1. Health Check (Liveness)
```bash
curl https://day14-agent-phamtuananh.onrender.com/health
# Expected (200 OK):
# {"status":"ok","uptime_seconds":43.1,"environment":"production"}
```

### 2. Readiness Check (Redis Connectivity)
```bash
curl https://day14-agent-phamtuananh.onrender.com/ready
# Expected (200 OK):
# {"status":"ready","redis":"connected"}
```

### 3. Authentication Check (Without API Key → `401`)
```bash
curl -i -X POST https://day14-agent-phamtuananh.onrender.com/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: HTTP/2 401 — {"detail":"Invalid or missing API key"}
```

### 4. API Test (With Valid Authentication → `200`)
```bash
curl -X POST https://day14-agent-phamtuananh.onrender.com/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected (200 OK):
# {"question":"Hello","answer":"...","user_id":"test","cost_usd":2.07e-05}
```

### 5. CP6 Self-Verification Script (Status Codes Only — Safe for Screenshots)
```bash
BASE="https://day14-agent-phamtuananh.onrender.com"
AGENT_API_KEY="<YOUR_AGENT_API_KEY>"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

## Environment Variables Set
- `PORT` *(injected dynamically by Render)*
- `ENVIRONMENT` (`production`)
- `LOG_LEVEL` (`INFO`)
- `REDIS_URL` *(auto-wired via Render internal private network from `day14-redis-phamtuananh`)*
- `AGENT_API_KEY` *(auto-generated secret on Render Dashboard — never committed to Git)*
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
