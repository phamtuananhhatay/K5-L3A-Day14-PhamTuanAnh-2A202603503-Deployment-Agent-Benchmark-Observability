# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

Qua đối chiếu `01-localhost-vs-production/develop/app.py` với nguyên lý **12-Factor App** và bản chuẩn `01-localhost-vs-production/production/`, có **6 anti-patterns** nghiêm trọng khiến code chạy được trên laptop nhưng không thể đưa thẳng lên production:

1. **Hardcode thông tin nhạy cảm (Secrets) trực tiếp trong mã nguồn (`develop/app.py`, dòng 17–18):**
   ```python
   OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"
   DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"
   ```
   - **Rủi ro:** Ngay khi push code lên Git repository, API key và mật khẩu cơ sở dữ liệu sẽ bị lộ (kể cả xóa ở commit sau thì secret vẫn nằm trong lịch sử Git). Ngoài ra không thể xoay vòng (rotate) khóa hoặc dùng khóa khác nhau cho môi trường `dev` / `staging` / `production` nếu không sửa code và build lại.
   - **Cách bản `production` khắc phục (`production/config.py`, dòng 27, 32, 37–46):** Đọc toàn bộ khóa từ biến môi trường qua `os.getenv("OPENAI_API_KEY", "")`, `os.getenv("AGENT_API_KEY", "")` và kiểm tra điều kiện bắt buộc trong `Settings.validate()` (báo lỗi fail-fast nếu `ENVIRONMENT == "production"` mà thiếu `AGENT_API_KEY`).

2. **Gán cứng cấu hình ứng dụng trong code thay vì quản lý tập trung qua biến môi trường (`develop/app.py`, dòng 21–22):**
   ```python
   DEBUG = True
   MAX_TOKENS = 500
   ```
   - **Rủi ro:** Vi phạm nguyên tắc *Factor III — Store config in the environment*. Không thể tinh chỉnh tham số (`MAX_TOKENS`, `DEBUG`, `LLM_MODEL`, `ALLOWED_ORIGINS`) theo từng môi trường triển khai; bật cứng `DEBUG = True` trên môi trường thật còn tiềm ẩn nguy cơ lộ thông tin nội bộ khi xảy ra lỗi.
   - **Cách bản `production` khắc phục (`production/config.py`, dòng 14–35):** Gom toàn bộ cấu hình vào dataclass `Settings` đọc động từ `os.getenv(...)` với giá trị mặc định an toàn (`DEBUG=false`).

3. **Dùng `print()` thay cho Structured Logging và in thẳng secret ra stdout (`develop/app.py`, dòng 33–34, 38):**
   ```python
   print(f"[DEBUG] Got question: {question}")
   print(f"[DEBUG] Using key: {OPENAI_API_KEY}")  # log ra secret!
   print(f"[DEBUG] Response: {response}")
   ```
   - **Rủi ro:** `print()` xuất chuỗi văn bản thuần không có timestamp chuẩn, không phân cấp mức độ (`DEBUG` / `INFO` / `WARNING` / `ERROR`) nên các hệ thống thu thập log tập trung (Loki, Datadog, CloudWatch, ELK) rất khó lọc và cảnh báo. Đặc biệt, dòng 34 in trực tiếp `OPENAI_API_KEY` ra stdout làm lộ khóa cho bất kỳ ai xem được container logs.
   - **Cách bản `production` khắc phục (`production/app.py`, dòng 28–32, 111–122):** Dùng module `logging` xuất định dạng JSON có cấu trúc và chỉ ghi nhận thông tin vận hành an toàn (`question_length`, `client_ip`, `response_length`), tuyệt đối không log secret.

4. **Không có Health Check (`/health`) và Readiness Check (`/ready`) endpoints (`develop/app.py`, dòng 42–43):**
   - **Rủi ro:** Khi triển khai lên Docker, Kubernetes, Railway hay Render, nền tảng không có endpoint để kiểm tra container còn phản hồi hay đã treo (liveness) để tự động khởi động lại, cũng như không biết ứng dụng đã nạp xong tài nguyên/kết nối để bắt đầu điều phối traffic vào hay chưa (readiness).
   - **Cách bản `production` khắc phục (`production/app.py`, dòng 135–162):** Bổ sung `GET /health` (liveness probe trả `200 OK` kèm `uptime_seconds`, `version`) và `GET /ready` (readiness probe trả `200` khi sẵn sàng hoặc `503 Service Unavailable` khi `is_ready == False`).

5. **Bind cứng `host="localhost"`, cố định `port=8000` và bật cứng `reload=True` (`develop/app.py`, dòng 49–54):**
   ```python
   uvicorn.run(
       "app:app",
       host="localhost",   # chỉ chạy được trên local
       port=8000,          # cứng port
       reload=True         # debug reload trong production
   )
   ```
   - **Rủi ro:**
     - `host="localhost"` (`127.0.0.1`) chỉ lắng nghe trên loopback nội bộ; khi đóng gói vào Docker container, các kết nối từ bên ngoài container (Nginx, cloud load balancer) sẽ bị từ chối kết nối.
     - `port=8000` cố định sẽ gây lỗi healthcheck/routing trên các PaaS như Railway, Render, Cloud Run vốn cấp cổng động qua biến môi trường `PORT`.
     - `reload=True` sinh thêm tiến trình theo dõi file (`WatchFiles`), gây tốn CPU/RAM và mất ổn định trên môi trường production.
   - **Cách bản `production` khắc phục (`production/config.py`, dòng 17–19 & `production/app.py`, dòng 194–199):** Mặc định `HOST="0.0.0.0"`, đọc cổng động `int(os.getenv("PORT", "8000"))`, và chỉ bật `reload=settings.debug`.

6. **Không xử lý Graceful Shutdown (`SIGTERM`) và vòng đời ứng dụng (`develop/app.py`, toàn file; kèm hạn chế nhận input ở dòng 30–31):**
   - **Rủi ro:** Khi hệ thống scale down hoặc rolling deploy bản mới, orchestrator gửi tín hiệu `SIGTERM`. Bản `develop` không quản lý trạng thái đóng ứng dụng nên có thể ngắt ngang các request LLM đang xử lý dở (gây lỗi `502`/`504` cho client) và không giải phóng kết nối sạch sẽ. Ngoài ra `POST /ask` nhận `question: str` qua query string thay vì JSON body chuẩn và thiếu cấu hình CORS kiểm soát origin.
   - **Cách bản `production` khắc phục (`production/app.py`, dòng 39–82, 102–109, 180–189):** Sử dụng `lifespan` context manager (hạ cờ `is_ready = False` khi shutdown, đợi request đang chạy hoàn tất), đăng ký `signal.signal(signal.SIGTERM, handle_sigterm)`, cấu hình `CORSMiddleware` từ `ALLOWED_ORIGINS` và kiểm tra hợp lệ JSON payload (`422` nếu thiếu `question`).

---

### Exercise 1.2: Chạy thử bản `develop` và quan sát thực tế

- **Lệnh thực thi trên WSL2 Ubuntu (`~/.venvs/day14`):**
  ```bash
  cd 01-localhost-vs-production/develop
  pip install -r requirements.txt
  python app.py
  ```

- **Kiểm thử endpoint `POST /ask` (nhận tham số qua query string):**
  ```bash
  curl -i -X POST "http://localhost:8000/ask?question=Hello"
  ```

- **Kết quả trả về thực tế:**
  ```http
  HTTP/1.1 200 OK
  date: Wed, 25 Nov 2026 09:21:03 GMT
  server: uvicorn
  content-length: 126
  content-type: application/json

  {"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
  ```

- **Log xuất ra trên terminal của server `develop`:**
  ```text
  INFO:     Will watch for changes in these directories: ['/mnt/d/vinuni/K5-L3A-Day14-PhamTuanAnh-2A202603503-Deployment-Agent-Benchmark-Observability/01-localhost-vs-production/develop']
  INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
  INFO:     Started reloader process [6294] using WatchFiles
  Starting agent on localhost:8000...
  INFO:     Started server process [6299]
  INFO:     Waiting for application startup.
  INFO:     Application startup complete.
  [DEBUG] Got question: Hello
  [DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
  [DEBUG] Response: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.
  INFO:     127.0.0.1:42440 - "POST /ask?question=Hello HTTP/1.1" 200 OK
  ```

- **Nhận xét:** Dù API trả `200 OK` trên máy cá nhân, log thực tế lộ rõ ngay các vấn đề không thể chấp nhận trên production: server chỉ bind vào `http://localhost:8000`, tự động bật tiến trình `WatchFiles` reloader, và in thẳng chuỗi khóa bí mật `sk-hardcoded-fake-key-never-do-this` ra màn hình console ở mỗi lần gọi API. Đã dừng server và giải phóng cổng `8000` sau khi kiểm thử.

---

### Exercise 1.3: Kiểm chứng bản `production` & Bảng so sánh chi tiết

- **Kết quả chạy kiểm chứng `01-localhost-vs-production/production/app.py`:**
  - `GET /health`:
    ```http
    HTTP/1.1 200 OK
    content-type: application/json

    {"status":"ok","uptime_seconds":0.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:21:08.614339+00:00"}
    ```
  - `GET /ready`:
    ```http
    HTTP/1.1 200 OK
    content-type: application/json

    {"ready":true}
    ```
  - `POST /ask` (JSON body `{"question": "Hello"}`):
    ```http
    HTTP/1.1 200 OK
    content-type: application/json

    {"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
    ```

- **Bảng so sánh `Develop` vs `Production`:**

| Khía cạnh | Develop (`develop/app.py`) | Production (`production/app.py` & `config.py`) | Tại sao quan trọng trong Production? |
| :--- | :--- | :--- | :--- |
| **Config** | Gán cứng trực tiếp trong code (`DEBUG = True`, `MAX_TOKENS = 500`), không tách file cấu hình. | Quản lý tập trung qua `Settings` trong `config.py`, đọc từ biến môi trường (`os.getenv`) kèm mẫu `.env.example` và hàm `validate()`. | Đảm bảo nguyên lý **12-Factor (Config)**: cùng một bản build/image có thể triển khai sang `dev`, `staging`, `production` chỉ bằng cách đổi biến môi trường mà không phải sửa code hay build lại; fail-fast sớm nếu cấu hình bắt buộc bị thiếu. |
| **Secrets** | Hardcode `OPENAI_API_KEY` và `DATABASE_URL` kèm mật khẩu trong `app.py`; thậm chí `print()` thẳng ra console. | Không lưu secret trong mã nguồn; đọc qua biến môi trường (`OPENAI_API_KEY`, `AGENT_API_KEY`) được inject lúc runtime và không bao giờ ghi ra log. | Ngăn chặn rò rỉ khóa API / mật khẩu DB lên Git hoặc hệ thống log tập trung; cho phép xoay vòng (rotate) khóa định kỳ hoặc thu hồi khẩn cấp trên cloud dashboard mà không cần đụng tới source code. |
| **Host & Port** | Bind cứng `host="localhost"`, `port=8000` và luôn bật `reload=True`. | Bind `HOST="0.0.0.0"`, đọc cổng động từ biến môi trường `PORT` (mặc định `8000`), chỉ bật `reload` khi `DEBUG=true`. | Trong container Docker/cloud, ứng dụng bắt buộc lắng nghe trên `0.0.0.0` để nhận traffic qua network interface của container, đồng thời phải đọc đúng `PORT` do Railway/Render/Cloud Run cấp động; tắt auto-reload giúp tiết kiệm tài nguyên và ổn định tiến trình. |
| **Health & Readiness Check** | Không có bất kỳ endpoint kiểm tra sức khỏe nào. | Tách bạch `GET /health` (liveness probe) và `GET /ready` (readiness probe trả `503` khi chưa sẵn sàng). | Giúp nền tảng cloud/orchestrator tự động phát hiện và restart container bị treo (`liveness`), đồng thời giúp Load Balancer chỉ định tuyến người dùng tới các instance đã khởi tạo xong và đủ điều kiện phục vụ (`readiness`), đảm bảo zero-downtime deployment. |
| **Logging** | Dùng `print()` xuất chuỗi tự do, không có timestamp, không phân mức độ và làm lộ dữ liệu nhạy cảm. | Dùng thư viện `logging` xuất **Structured JSON** (`time`, `level`, `msg`/`event`, metadata an toàn như `question_length`, `client_ip`). | Log dạng JSON trên một dòng giúp các công cụ giám sát (Loki, Grafana, Datadog, ELK) tự động parse trường dữ liệu, tìm kiếm nhanh theo sự kiện, thống kê tần suất lỗi và thiết lập cảnh báo mà không làm rò rỉ dữ liệu nhạy cảm. |
| **Graceful Shutdown** | Không xử lý tín hiệu dừng; tắt đột ngột ngay khi nhận tín hiệu từ hệ điều hành. | Bắt tín hiệu `signal.SIGTERM` kết hợp FastAPI `lifespan`: chuyển `is_ready = False` để ngưng nhận request mới, chờ các request đang chạy hoàn tất rồi mới đóng tài nguyên. | Các tác vụ gọi LLM thường kéo dài vài giây; khi rolling update hoặc autoscale thu hồi container, graceful shutdown giúp tránh cắt đứt kết nối giữa chừng (tránh lỗi `502`/`504` cho người dùng) và tránh hỏng dữ liệu/rò rỉ kết nối DB/Redis. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - Base image là **`python:3.11`** (`FROM python:3.11`, dòng 8) — bản phân phối Python 3.11 đầy đủ dựa trên hệ điều hành Debian (chứa sẵn trình biên dịch C, các gói công cụ hệ thống và thư viện phát triển nên dung lượng rất lớn).

2. **Working directory (`WORKDIR`) là gì?**
   - Thư mục làm việc bên trong container là **`/app`** (`WORKDIR /app`, dòng 11). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều thực thi tương đối tại đường dẫn `/app` này.

3. **Tại sao `COPY requirements.txt` và `RUN pip install` phải đặt trước `COPY` mã nguồn?**
   - Docker xây dựng image theo từng lớp bất biến (**read-only layers**) từ trên xuống dưới và lưu **Docker Layer Cache** dựa trên nội dung lệnh cùng checksum của các file được `COPY`. Theo quy tắc **cache invalidation**, ngay khi một layer bị thay đổi, toàn bộ các layer nằm bên dưới nó đều mất hiệu lực cache và buộc phải chạy lại.
   - Trong quá trình phát triển, mã nguồn (`app.py`, `utils/mock_llm.py`) thay đổi liên tục ở hầu hết mọi lần build, trong khi danh sách thư viện (`requirements.txt`) rất ít khi thay đổi. Đặt `COPY 02-docker/develop/requirements.txt .` và `RUN pip install --no-cache-dir -r requirements.txt` **trước** khi copy code giúp Docker tái sử dụng lại layer cài đặt thư viện từ cache, rút ngắn thời gian build từ hàng chục giây xuống chưa đầy 1 giây khi chỉ sửa code. *(Lưu ý: cờ `--no-cache-dir` chỉ tắt bộ đệm gói tải về của `pip` bên trong container để giảm dung lượng image, không tắt cơ chế layer cache của Docker).*

4. **`CMD` khác `ENTRYPOINT` như thế nào?**
   - **`CMD`** khai báo lệnh (hoặc các tham số) mặc định khi container khởi động và **bị ghi đè hoàn toàn** nếu người dùng truyền lệnh khác ở cuối `docker run <image> <lệnh-mới>` (ví dụ `docker run --rm -it my-agent:develop sh` sẽ mở shell `sh` thay vì chạy `python app.py`).
   - **`ENTRYPOINT`** cố định chương trình thực thi chính của container (biến container hoạt động như một file thực thi chuyên biệt); mọi đối số truyền thêm ở cuối `docker run <image> <args>` sẽ được **nối thêm làm tham số** cho `ENTRYPOINT` thay vì thay thế nó (muốn ghi đè phải chỉ định tường minh cờ `--entrypoint`).
   - Khi kết hợp cả hai (ví dụ `ENTRYPOINT ["uvicorn", "main:app"]` và `CMD ["--host", "0.0.0.0", "--port", "8000"]`), `ENTRYPOINT` giữ cố định binary thực thi còn `CMD` cung cấp bộ tham số mặc định có thể linh hoạt ghi đè.

---

### Exercise 2.2: Build và chạy thử `my-agent:develop` từ gốc repository

- **Lệnh thực thi trên WSL2 Ubuntu:**
  ```bash
  cd /mnt/d/vinuni/K5-L3A-Day14-PhamTuanAnh-2A202603503-Deployment-Agent-Benchmark-Observability
  docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
  docker run -d --name test-dev-agent -p 8000:8000 my-agent:develop
  curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
  docker rm -f test-dev-agent
  ```

- **Kết quả kiểm thử container `test-dev-agent`:**
  - `GET /health`:
    ```http
    HTTP/1.1 200 OK
    date: Wed, 25 Nov 2026 09:35:08 GMT
    server: uvicorn
    content-length: 53
    content-type: application/json

    {"status":"ok","uptime_seconds":0.6,"container":true}
    ```
  - `POST /ask?question=What%20is%20Docker`:
    ```http
    HTTP/1.1 200 OK
    date: Wed, 25 Nov 2026 09:35:08 GMT
    server: uvicorn
    content-length: 103
    content-type: application/json

    {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
    ```
- Đã xoá container `test-dev-agent` (`docker rm -f test-dev-agent`) để giải phóng cổng `8000`.

---

### Exercise 2.3: Multi-stage Build (`02-docker/production/Dockerfile`) & Đo dung lượng thực tế

- **Vai trò của từng Stage trong `02-docker/production/Dockerfile`:**
  - **Stage 1 — `builder` (`FROM python:3.11-slim AS builder`, dòng 16–29):** Cài đặt các gói công cụ biên dịch C và header hệ thống (`gcc`, `libpq-dev`) qua `apt-get`, sau đó biên dịch và cài đặt toàn bộ Python packages từ `requirements.txt` vào thư mục `/root/.local` (`pip install --no-cache-dir --user`). Toàn bộ layer nặng của Stage 1 bị loại bỏ khi xuất image cuối.
  - **Stage 2 — `runtime` (`FROM python:3.11-slim AS runtime`, dòng 36–72):** Khởi tạo mới hoàn toàn từ image nền gọn nhẹ `python:3.11-slim`, tạo nhóm và tài khoản không đặc quyền `appuser` (`groupadd`/`useradd`), chỉ sao chép thư mục thư viện đã cài đặt `/root/.local` từ `builder` sang `/home/appuser/.local` (`COPY --from=builder`), copy mã nguồn `main.py` + `utils/mock_llm.py`, chuyển sang chạy dưới quyền `USER appuser`, cấu hình `HEALTHCHECK` tự động và chạy `uvicorn` với 2 workers.
  - **Tại sao giảm mạnh kích thước và tăng bảo mật?**
    1. *Giảm kích thước:* Chuyển từ `python:3.11` đầy đủ sang `python:3.11-slim` và bỏ lại toàn bộ trình biên dịch (`gcc`, `binutils`, `libc6-dev`, `libpq-dev`, `pip` build artifacts) ở Stage `builder`, chỉ giữ lại Python runtime và `site-packages` cần thiết để chạy.
    2. *Tăng bảo mật:* Không tồn tại trình biên dịch hay công cụ build trong container runtime (giảm bề mặt tấn công — *attack surface* nếu kẻ tấn công chiếm được shell), đồng thời tiến trình chạy bằng user thường `appuser` thay vì `root` (ngăn chặn leo thang đặc quyền ra máy host).

- **Kết quả đo kích thước thực tế bằng `docker images` (Docker 29.1.3 trên WSL2 Ubuntu):**
  ```text
  IMAGE               ID             DISK USAGE   CONTENT SIZE   EXTRA
  my-agent:advanced   1129ea14834a        240MB         57.4MB
  my-agent:develop    c11a50afce4f       1.67GB          426MB
  ```
  *(Kiểm tra byte chính xác qua `docker image inspect --format '{{.Size}}'`: `my-agent:develop` = `426,319,465 bytes` ≈ `426.32 MB`; `my-agent:advanced` = `57,408,416 bytes` ≈ `57.41 MB`).*

| Phiên bản Image | Disk Usage (Unpacked trên đĩa) | Content Size (Image Layers) | Nhận xét |
| :--- | :---: | :---: | :--- |
| **Develop (`my-agent:develop`)** | `1.67 GB` (~`1670 MB`) | `426.32 MB` | Single-stage dùng `python:3.11` đầy đủ |
| **Production (`my-agent:advanced`)** | `240 MB` | `57.41 MB` | Multi-stage dùng `python:3.11-slim` + non-root |
| **Chênh lệch / Tỷ lệ giảm** | **Giảm `1430 MB` (`85.63%`)** | **Giảm `368.91 MB` (`86.53%`)** | Nhỏ hơn ~7 lần, đạt chuẩn `< 500 MB` |

---

### Exercise 2.4: Docker Compose Stack (`02-docker/production/docker-compose.yml`) & Kiểm thử qua Nginx

- **Sơ đồ kiến trúc các service và cơ chế giao tiếp:**

  ```text
                       Host Machine (Ports 80, 443)
                                    │
                                    ▼
  ┌─────────────────── Docker Bridge Network: internal ───────────────────┐
  │                                                                       │
  │   ┌─────────────────────────┐                                         │
  │   │  nginx (nginx:alpine)   │  Reverse Proxy, Rate Limit (10 req/s),  │
  │   │  Listen :80 / :443      │  Security Headers                       │
  │   └────────────┬────────────┘                                         │
  │                │  proxy_pass http://agent_backend (agent:8000)        │
  │                ▼                                                      │
  │   ┌─────────────────────────┐                                         │
  │   │  agent (FastAPI, :8000) │  2 Uvicorn workers (non-root appuser)   │
  │   │  Không mở port ra host  │                                         │
  │   └─────┬─────────────┬─────┘                                         │
  │         │             │                                               │
  │         │             └──────────────────────────┐                    │
  │         ▼ REDIS_URL=redis://redis:6379/0         ▼ QDRANT_URL=http://qdrant:6333
  │   ┌─────────────────────────┐          ┌──────────────────────────┐   │
  │   │  redis (redis:7-alpine) │          │ qdrant (qdrant:v1.9.0)   │   │
  │   │  Port :6379 + Volume    │          │ Port :6333 + Volume      │   │
  │   │  redis_data:/data       │          │ qdrant_data:/qdrant/...  │   │
  │   └─────────────────────────┘          └──────────────────────────┘   │
  └───────────────────────────────────────────────────────────────────────┘
  ```

- **Giải thích cách 4 service phối hợp và giao tiếp:**
  1. **Cô lập mạng nội bộ (`internal` bridge network):** Cả 4 service (`nginx`, `agent`, `redis`, `qdrant`) cùng gắn vào mạng bridge `internal`. Chỉ duy nhất `nginx` publish cổng `80:80` và `443:443` ra máy host; `agent` (`8000`), `redis` (`6379`) và `qdrant` (`6333`) hoàn toàn ẩn khỏi truy cập trực tiếp từ bên ngoài.
  2. **Service Discovery bằng Docker DNS:** Các container gọi nhau trực tiếp qua tên service trong `docker-compose.yml`: `nginx` chuyển tiếp request vào `upstream agent_backend` (`server agent:8000;`), còn `agent` kết nối tới cache và vector DB qua `REDIS_URL=redis://redis:6379/0` và `QDRANT_URL=http://qdrant:6333`.
  3. **Thứ tự khởi động tin cậy (`depends_on` + `service_healthy`):** `redis` kiểm tra bằng `redis-cli ping`, `qdrant` kiểm tra cổng TCP `6333` bằng `/dev/tcp/localhost/6333`. Service `agent` chỉ được khởi chạy sau khi cả `redis` và `qdrant` đều báo `healthy`, và `nginx` đứng trước làm cổng giao tiếp duy nhất (kèm giới hạn `10r/s` và gắn security headers `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`).

- **Trạng thái các container khi chạy stack `k5-day14-part2`:**
  ```text
  NAME                      IMAGE                  SERVICE   STATUS                    PORTS
  k5-day14-part2-agent-1    k5-day14-part2-agent   agent     Up 7 seconds (healthy)    8000/tcp
  k5-day14-part2-nginx-1    nginx:alpine           nginx     Up 7 seconds              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
  k5-day14-part2-qdrant-1   qdrant/qdrant:v1.9.0   qdrant    Up 19 seconds (healthy)   6333-6334/tcp
  k5-day14-part2-redis-1    redis:7-alpine         redis     Up 19 seconds (healthy)   6379/tcp
  ```

- **Kết quả kiểm thử qua Reverse Proxy Nginx (cổng `80`):**
  - `curl -i http://localhost/health`:
    ```http
    HTTP/1.1 200 OK
    Server: nginx
    Date: Wed, 25 Nov 2026 09:43:01 GMT
    Content-Type: application/json
    Content-Length: 95
    Connection: keep-alive
    X-Frame-Options: DENY
    X-Content-Type-Options: nosniff
    X-XSS-Protection: 1; mode=block

    {"status":"ok","uptime_seconds":3.6,"version":"2.0.0","timestamp":"2026-11-25T09:43:01.534053"}
    ```
  - `curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'`:
    ```http
    HTTP/1.1 200 OK
    Server: nginx
    Date: Wed, 25 Nov 2026 09:43:01 GMT
    Content-Type: application/json
    Content-Length: 95
    Connection: keep-alive
    X-Frame-Options: DENY
    X-Content-Type-Options: nosniff
    X-XSS-Protection: 1; mode=block

    {"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
    ```
- Đã dọn sạch toàn bộ stack bằng `docker compose -p k5-day14-part2 -f 02-docker/production/docker-compose.yml down -v` và giải phóng cổng `80`/`443`.

---

## Part 3: Cloud Deployment

### Exercise 3.1 & 3.2 (Deploy): Triển khai Agent Part 6 (`06-lab-complete/`) lên Render Cloud

- **Nền tảng triển khai:** **Render** (Docker Web Service `day14-agent-phamtuananh` + Render Key Value / Redis `day14-redis-phamtuananh` triển khai tự động qua Blueprint `render.yaml`, gói Free).
- **Public URL đang hoạt động:** https://day14-agent-phamtuananh.onrender.com
- **Kết quả chạy 4 lệnh tự kiểm tra CP6 (không lộ API key):**
  ```text
  GET  https://day14-agent-phamtuananh.onrender.com/health            -> 200  {"status":"ok","uptime_seconds":43.1,"environment":"production"}
  GET  https://day14-agent-phamtuananh.onrender.com/ready             -> 200  {"status":"ready","redis":"connected"}
  POST https://day14-agent-phamtuananh.onrender.com/ask (no key)      -> 401  {"detail":"Invalid or missing API key"}
  POST https://day14-agent-phamtuananh.onrender.com/ask (valid key)   -> 200  {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","user_id":null,"cost_usd":2.07e-05}
  ```
- **Kiểm chứng bằng `check_production_ready.py --public-url`:**
  `✅ Public URL: GET https://day14-agent-phamtuananh.onrender.com/health → 200`
- **Screenshots minh chứng trong repo:**
  - Dashboard & Environment Variables (đã che secret): [screenshots/dashboard.png](screenshots/dashboard.png)
  - Trạng thái Live & Structured JSON Logs: [screenshots/running.png](screenshots/running.png)
  - Kết quả kiểm thử 4 lệnh `curl` (`200 / 200 / 401 / 200`): [screenshots/test.png](screenshots/test.png)

---

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` (Railway Config-as-Code) | `render.yaml` (Render Blueprint — IaC) | Ý nghĩa & Lý do khác biệt |
| :--- | :--- | :--- | :--- |
| **Định dạng & Cú pháp** | Định dạng **TOML** gọn nhẹ chia theo hai bảng `[build]` và `[deploy]`. | Định dạng **YAML** phân cấp theo chuẩn Infrastructure-as-Code (`services:`). | Railway ưu tiên tốc độ khởi tạo nhanh tối giản cho từng service đơn lẻ, trong khi Render hướng tới khai báo kiến trúc đầy đủ trong một file duy nhất. |
| **Phạm vi quản lý tài nguyên (Scope)** | **Single-service:** Chỉ mô tả cách build và chạy của **một service duy nhất**. Các phụ thuộc đi kèm như Redis/PostgreSQL phải tạo thêm trên Railway Dashboard hoặc CLI rồi nối qua biến tham chiếu `${{Redis.REDIS_URL}}`. | **Multi-service Stack:** Khai báo đồng thời toàn bộ hạ tầng trong một Blueprint (`type: web` cho AI Agent, `type: redis` cho cache/rate-limit, persistent `disk`, `region`, `plan`) và tự động liên kết nội bộ qua `fromService` (`property: connectionString`). | Khi cần tái tạo toàn bộ môi trường (staging/production) từ Git chỉ bằng 1 cú click, `render.yaml` tránh được thao tác cấu hình tay rời rạc cho từng database/cache. |
| **Cơ chế Build & Start** | Khai báo `builder = "DOCKERFILE"` (hoặc `"NIXPACKS"`), `dockerfilePath`, `startCommand`. Railway tự động cấp và inject biến `$PORT` vào tiến trình lúc chạy. | Hỗ trợ cả `runtime: docker` (`dockerfilePath: ./Dockerfile`) lẫn native runtime (`runtime: python` kèm `buildCommand` + `startCommand`), cấu hình thêm `autoDeploy: true` khi push nhánh Git. | Cả hai đều tuân thủ nguyên lý 12-Factor (inject `$PORT` động), nhưng `render.yaml` cho phép ghim rõ phiên bản runtime (`PYTHON_VERSION`), vùng địa lý (`region: singapore`) và gói tài nguyên ngay trong code. |
| **Quản lý biến môi trường & Secrets** | **Không khai báo biến môi trường/secret trong `railway.toml`**; toàn bộ biến được đặt ngoài file qua lệnh `railway variables set` hoặc trên giao diện Variables của Dashboard. | Khai báo trực tiếp danh sách `envVars` ngay trong file: biến không nhạy cảm gắn `value:`, còn secret dùng **`generateValue: true`** (Render tự sinh khóa ngẫu nhiên an toàn) hoặc **`sync: false`** (bắt buộc nhập tay trên Dashboard khi tạo Blueprint). | Tách biệt hoàn toàn giá trị bí mật khỏi lịch sử Git nhưng `render.yaml` vẫn đóng vai trò tài liệu sống (*self-documenting schema*) liệt kê đủ các biến mà ứng dụng bắt buộc phải có. |
| **Giám sát & Tự phục hồi** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, kèm chính sách tự khởi động lại `restartPolicyType = "ON_FAILURE"` và `restartPolicyMaxRetries`. | `healthCheckPath: /health` tích hợp trực tiếp vào quy trình zero-downtime deploy (chỉ chuyển traffic sang bản mới khi `/health` trả `200`). | Đảm bảo bản lỗi không bao giờ nhận traffic thật và container gặp sự cố sẽ được nền tảng tự động phục hồi. |

---

### Exercise 3.3: Mô tả Pipeline CI/CD trên GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Đọc hai file cấu hình trong `03-cloud-deployment/production-cloud-run/`, quy trình CI/CD tự động hóa từ lúc push code lên nhánh `main` tới khi phục vụ người dùng đi qua 4 bước tuần tự (`waitFor`):
1. **Kiểm thử tự động (`id: test`):** Chạy container tạm `python:3.11-slim`, cài đặt thư viện từ `requirements.txt` và chạy `pytest tests/ -v`; nếu bất kỳ test nào lỗi, pipeline dừng ngay lập tức không cho phép đóng gói image hỏng.
2. **Đóng gói Docker Image tối ưu cache (`id: build`):** Dùng `gcr.io/cloud-builders/docker` build image gắn đồng thời 2 tag là mã băm commit (`$COMMIT_SHA` để truy vết/rollback chính xác) và `latest`, kết hợp `--cache-from=...:latest` tận dụng layer cache từ lần build trước.
3. **Đẩy Image lên Registry (`id: push`):** Đẩy toàn bộ các tag của image `gcr.io/$PROJECT_ID/ai-agent` lên Google Container Registry / Artifact Registry để Cloud Run có thể kéo về triển khai.
4. **Triển khai Serverless lên Cloud Run (`id: deploy` & `service.yaml`):** Dùng `gcloud run deploy` cập nhật revision mới tại vùng `asia-southeast1` với cấu hình production trong `service.yaml`: giữ tối thiểu `minScale: 1` (tránh cold start) và tự động co giãn tối đa `maxScale: 10` (`containerConcurrency: 80`, giới hạn `1 CPU` / `512Mi` RAM), tiêm khóa bảo mật trực tiếp từ **Secret Manager** (`secretKeyRef` cho `OPENAI_API_KEY`, `AGENT_API_KEY` thay vì hardcode), và giám sát bằng bộ đôi `startupProbe` (`/ready`) + `livenessProbe` (`/health`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

- **Phân tích mã nguồn `04-api-gateway/develop/app.py`:**
  1. **API key được kiểm tra ở đâu?**
     - Hệ thống khai báo `api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36) và định nghĩa hàm dependency `verify_api_key(api_key: str = Security(api_key_header))` (dòng 39–54). Dependency này được gắn trực tiếp vào endpoint cần bảo vệ `POST /ask` thông qua `_key: str = Depends(verify_api_key)` (dòng 70), trong khi `/` và `/health` được giữ public để cloud platform kiểm tra sức khỏe container.
  2. **Điều gì xảy ra khi thiếu hoặc sai key?**
     - **Thiếu header `X-API-Key` (`not api_key`):** trả về **`401 Unauthorized`** kèm thông báo hướng dẫn `Missing API key. Include header: X-API-Key: <your-key>`.
     - **Sai giá trị key (`api_key != API_KEY`):** bản mẫu `develop/app.py` trả về **`403 Forbidden`** (`Invalid API key.`). *(Trong môi trường production thực tế và ở Part 6, nên dùng `secrets.compare_digest()` thay cho toán tử `!=` để chống tấn công đo thời gian — timing attack).*
  3. **Làm sao xoay vòng khóa (rotate key) mà không gây downtime?**
     - Thiết kế hệ thống chấp nhận **một danh sách các khóa đang hiệu lực** (ví dụ biến môi trường `AGENT_API_KEYS="key_v2_new,key_v1_old"` hoặc lưu tập khóa kèm TTL trong Redis / Secret Manager) theo quy trình 3 bước:
       1. **Dual-key phase:** Thêm `key_v2_new` vào danh sách chấp nhận song song với `key_v1_old` và reload cấu hình.
       2. **Client migration:** Cập nhật các client chuyển sang gửi `key_v2_new`, theo dõi metrics/logs cho tới khi lưu lượng dùng `key_v1_old` giảm về `0`.
       3. **Revoke old key:** Xoá `key_v1_old` khỏi danh sách hợp lệ. Toàn bộ quá trình diễn ra liền mạch, không có request hợp lệ nào bị gián đoạn.

- **Kết quả kiểm thử thực tế (`AGENT_API_KEY=secret-key-123`):**
  - **Không gửi API key (`401 Unauthorized`):**
    ```http
    HTTP/1.1 401 Unauthorized
    date: Wed, 25 Nov 2026 09:52:52 GMT
    server: uvicorn
    content-length: 67
    content-type: application/json

    {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
    ```
  - **Gửi sai API key (`403 Forbidden`):**
    ```http
    HTTP/1.1 403 Forbidden
    date: Wed, 25 Nov 2026 09:52:52 GMT
    server: uvicorn
    content-length: 29
    content-type: application/json

    {"detail":"Invalid API key."}
    ```
  - **Gửi đúng `X-API-Key: secret-key-123` (`200 OK`):**
    ```http
    HTTP/1.1 200 OK
    date: Wed, 25 Nov 2026 09:52:52 GMT
    server: uvicorn
    content-length: 145
    content-type: application/json

    {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
    ```

---

### Exercise 4.2: JWT Authentication (`04-api-gateway/production/`)

- **Giải thích luồng xác thực Stateless JWT trong `auth.py` & `app.py`:**
  1. **Đăng nhập cấp phát token (`POST /auth/token`):** Người dùng gửi `username` và `password`. Hàm `authenticate_user()` kiểm tra thông tin đăng nhập; nếu hợp lệ, `create_token()` đóng gói payload gồm `sub` (tên định danh user), `role` (`user` hoặc `admin`), `iat` (thời điểm phát hành) và `exp` (thời điểm hết hạn sau `60` phút), sau đó ký bằng thuật toán **`HS256`** với `SECRET_KEY`.
  2. **Gửi request kèm Bearer Token (`POST /ask`):** Client truyền chuỗi JWT trong header `Authorization: Bearer <token>`.
  3. **Xác minh không trạng thái (`verify_token`):** FastAPI trích xuất token qua `HTTPBearer(auto_error=False)`. Nếu thiếu header → trả `401 Unauthorized` (kèm `WWW-Authenticate: Bearer`). Nếu có token → `jwt.decode(..., SECRET_KEY, algorithms=["HS256"])` kiểm tra tính toàn vẹn chữ ký số và hạn sử dụng ngay trên CPU/RAM mà **không cần truy vấn cơ sở dữ liệu ở từng request** (quá hạn `exp` → `401 Token expired`, sai chữ ký → `403 Invalid token`), rồi trả về `{"username": ..., "role": ...}` cho các tầng kiểm soát phía sau.

- **Kết quả kiểm thử thực tế (đã che chuỗi JWT bằng `<REDACTED_JWT>`):**
  - **Gọi `POST /ask` khi chưa có Bearer token (`401 Unauthorized`):**
    ```http
    HTTP/1.1 401 Unauthorized
    date: Wed, 25 Nov 2026 09:52:59 GMT
    www-authenticate: Bearer
    content-length: 76
    content-type: application/json
    x-content-type-options: nosniff
    x-frame-options: DENY
    x-xss-protection: 1; mode=block
    referrer-policy: strict-origin-when-cross-origin

    {"detail":"Authentication required. Include: Authorization: Bearer <token>"}
    ```
  - **Lấy token tại `POST /auth/token` với tài khoản `student` / `demo123` (`200 OK`):**
    ```http
    HTTP/1.1 200 OK
    date: Wed, 25 Nov 2026 09:52:59 GMT
    content-length: 307
    content-type: application/json
    x-content-type-options: nosniff
    x-frame-options: DENY

    {"access_token":"<REDACTED_JWT>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <REDACTED_JWT>"}
    ```
  - **Gọi `POST /ask` với `Authorization: Bearer <REDACTED_JWT>` (`200 OK` — Request #1):**
    ```http
    HTTP/1.1 200 OK
    date: Wed, 25 Nov 2026 09:52:59 GMT
    content-length: 184
    content-type: application/json
    x-content-type-options: nosniff
    x-frame-options: DENY

    {"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
    ```

---

### Exercise 4.3: Rate Limiting (`04-api-gateway/production/rate_limiter.py`)

- **Phân tích cơ chế trong `rate_limiter.py`:**
  1. **Thuật toán đang sử dụng:** **Sliding Window (Cửa sổ trượt theo danh sách timestamps)** sử dụng `collections.deque` cho từng `user_id` với cửa sổ `window_seconds = 60` giây. Mỗi khi có request mới tại thời điểm `now`, hệ thống loại bỏ toàn bộ các timestamp cũ `< now - 60` ở đầu `deque` (`window.popleft()`), rồi kiểm tra số lượng request còn lại trong cửa sổ trượt. Cách này chính xác hơn Fixed Window vì ngăn được lỗi dồn gấp đôi tải ở ranh giới chuyển phút.
  2. **Giới hạn theo từng nhóm người dùng:**
     - Tài khoản thường (`role == "user"`, ví dụ `student`): dùng `rate_limiter_user` = **`10 requests / phút`**.
     - Tài khoản quản trị (`role == "admin"`, ví dụ `teacher`): dùng `rate_limiter_admin` = **`100 requests / phút`**.
  3. **Cách phân quyền hạn mức / bypass limit cho Admin:**
     - Trong `POST /ask` (`app.py`, dòng 141), ứng dụng đọc trường `role` đã được xác thực từ JWT payload để chọn bộ giới hạn tương ứng (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`). Nếu muốn nâng hạn mức hoặc miễn trừ hoàn toàn (bypass) cho tài khoản hệ thống/super-admin, chỉ cần kiểm tra role từ JWT (`if role != "superadmin": limiter.check(username)`) mà không cần query thêm DB.

- **Kết quả chạy vòng lặp 15 requests liên tiếp với token `student` (`10 req/phút`):**
  - Từ Request `#1` đến `#10` đều thành công (`200 OK`), chỉ số `requests_remaining` giảm đều từ `9` về `0`:
    ```http
    HTTP/1.1 200 OK
    date: Wed, 25 Nov 2026 09:53:00 GMT
    content-type: application/json

    {"question":"Test 10","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":0,"budget_remaining_usd":0.000188}}
    ```
  - Ngay từ **Request `#11` trở đi** (đến `#15`), hệ thống chặn trước khi gọi LLM và trả về **`429 Too Many Requests`** kèm đầy đủ các header `X-RateLimit-*` và `Retry-After`:
    ```http
    HTTP/1.1 429 Too Many Requests
    date: Wed, 25 Nov 2026 09:53:00 GMT
    x-ratelimit-limit: 10
    x-ratelimit-remaining: 0
    x-ratelimit-reset: 1795600441
    retry-after: 59
    content-length: 98
    content-type: application/json
    x-content-type-options: nosniff
    x-frame-options: DENY
    x-xss-protection: 1; mode=block
    referrer-policy: strict-origin-when-cross-origin

    {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
    ```

---

### Exercise 4.4: Thiết kế Cost Guard & Triển khai trên Redis

- **Cơ chế hoạt động trong `04-api-gateway/production/cost_guard.py`:**
  - Quy đổi lượng `input_tokens` và `output_tokens` tiêu thụ sang chi phí USD (`$0.00015 / 1K input tokens`, `$0.0006 / 1K output tokens`).
  - Trước mỗi lần gọi LLM, `check_budget(user_id)` kiểm tra hai tầng ngân sách:
    1. **Ngân sách tổng toàn hệ thống (`global_daily_budget_usd = $10.0/ngày`):** nếu vượt ngưỡng thì ghi log `CRITICAL` và trả `503 Service Unavailable` để ngắt mạch bảo vệ tài khoản cloud.
    2. **Ngân sách từng người dùng (`daily_budget_usd = $1.0/ngày`):** ghi log cảnh báo (`WARNING`) khi chạm `80%` ngân sách và chặn ngay bằng mã **`402 Payment Required`** khi chạm `100%`.
  - Sau khi gọi LLM thành công, `record_usage()` mới cộng dồn số token và chi phí thực tế (kiểm chứng qua `GET /me/usage` sau 15 lần gọi trên: chỉ đúng `10` request `200 OK` phát sinh chi phí `$0.000188`, `5` request bị chặn `429` tốn `$0`).

- **Cách triển khai Cost Guard bằng Redis cho môi trường Production (Multi-instance):**
  - Lưu biến đếm trong RAM (`self._records`) chỉ đúng khi chạy 1 process duy nhất; khi scale ngang $N$ container Agent sau Load Balancer, chi phí bị phân mảnh trên từng container và mất sạch khi container khởi động lại. Để chạy chuẩn stateless trên Redis:
    ```python
    from datetime import datetime, timezone
    from fastapi import HTTPException

    def check_and_record_budget(redis_client, user_id: str, cost_usd: float, monthly_limit: float = 10.0):
        month_str = datetime.now(timezone.utc).strftime("%Y-%m")
        key = f"budget:{user_id}:{month_str}"

        current_spent = float(redis_client.get(key) or 0.0)
        if current_spent + cost_usd > monthly_limit:
            raise HTTPException(status_code=402, detail="Monthly LLM budget exceeded")

        # Cộng dồn nguyên tử (atomic) trên Redis và tự động hết hạn sau 32 ngày
        new_total = redis_client.incrbyfloat(key, cost_usd)
        if current_spent == 0.0:
            redis_client.expire(key, 32 * 24 * 3600)
        return new_total
    ```
  - **Điểm cốt lõi:** Đặt tên key gắn theo chu kỳ thời gian (`YYYY-MM-DD` cho ngân sách ngày hoặc `YYYY-MM` cho ngân sách tháng), dùng lệnh nguyên tử **`INCRBYFLOAT`** để nhiều instance cộng tiền đồng thời không bị race condition, và đặt TTL bằng **`EXPIRE`** để Redis tự động giải phóng các key của kỳ cũ.

- **Tại sao bắt buộc phải có CẢ Rate Limit LẪN Cost Guard?**
  - Hai lớp bảo vệ giải quyết **hai chiều rủi ro độc lập** mà một lớp đơn lẻ không thể thay thế:
    1. **Rate Limit bảo vệ hiệu năng và năng lực chịu tải tức thời (tính theo giây/phút → `429`):** Nếu chỉ có Cost Guard mà bỏ Rate Limit, một client bị lỗi vòng lặp vô hạn hoặc tấn công DoS có thể bắn hàng nghìn request ngắn cùng lúc trong vài giây — làm nghẽn event loop/worker, cạn kiệt quota RPM của nhà cung cấp LLM cho toàn bộ người dùng khác, hoặc lọt đồng thời qua bước `check_budget` trước khi request đầu kịp ghi nhận tiền.
    2. **Cost Guard bảo vệ trần tài chính tích lũy (tính theo token thực tế trong ngày/tháng → `402`):** Trong bài toán AI Agent, chi phí mỗi request chênh lệch gấp hàng chục lần tùy độ dài context/output và số bước suy luận. Một user gửi đều đặn `8 requests/phút` sẽ không bao giờ chạm ngưỡng Rate Limit (`10 req/phút`), nhưng nếu mỗi request nhồi hàng chục nghìn token và chạy liên tục cả ngày (`> 11.000 requests/ngày`), chi phí API vẫn vọt lên hàng trăm USD nếu không có Cost Guard cắt ngắt ở mức tiền quy định.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Checks (`/health` vs `/ready`) & Graceful Shutdown (`SIGTERM`)

- **Phân biệt Liveness Probe (`GET /health`) và Readiness Probe (`GET /ready`) trong `05-scaling-reliability/develop/app.py`:**

| Tiêu chí | Liveness Probe (`GET /health`) | Readiness Probe (`GET /ready`) |
| :--- | :--- | :--- |
| **Câu hỏi trả lời** | *"Tiến trình container còn sống hay đã bị treo/deadlock?"* | *"Instance này đã sẵn sàng nhận traffic người dùng chưa?"* |
| **Đối tượng sử dụng** | Container Orchestrator / Cloud Platform (Docker `HEALTHCHECK`, K8s kubelet, Railway/Render). | Load Balancer / Reverse Proxy / Service Mesh (Nginx, K8s Service). |
| **Hành động khi trả lỗi (`!= 200`)** | **Kill và khởi động lại (restart)** toàn bộ container. | **Tạm ngưng định tuyến request mới** vào instance này (nhưng **không** giết container), chuyển traffic sang các instance khỏe khác. |
| **Khi nào trả lỗi?** | Chỉ khi bản thân event loop / tiến trình Python bị đơ không phản hồi. Khi phụ thuộc ngoài (như Redis/DB) tạm thời mất kết nối, `/health` **vẫn phải trả `200`** để tránh vòng lặp restart vô nghĩa (*crash-loop*). | Trả **`503 Service Unavailable`** khi đang nạp model lúc khởi động (`_is_ready == False`), đang trong quá trình tắt máy (draining), hoặc mất kết nối tới Redis/DB thiết yếu. |

- **Cơ chế xử lý Graceful Shutdown khi nhận `SIGTERM` (`develop/app.py`):**
  1. Khi triển khai bản mới hoặc scale down, nền tảng gửi tín hiệu **`SIGTERM`** (signal `15`) tới tiến trình chính (khác với `SIGKILL` — signal `9` bị hệ điều hành cưỡng bức tắt ngay lập tức).
  2. Uvicorn bắt `SIGTERM` (với `timeout_graceful_shutdown=30`), ngừng nhận kết nối mới trên socket lắng nghe và chờ các request HTTP đang xử lý dở hoàn tất trước khi kích hoạt nhánh sau `yield` của `lifespan(app)`.
  3. Middleware `track_requests` đếm chính xác số lượng request đang bay qua biến `_in_flight_requests` (`+= 1` khi vào, `-= 1` trong khối `finally`). Trong khối shutdown của `lifespan`:
     - Đặt ngay `_is_ready = False` → mọi probe `/ready` trả `503` để Load Balancer rút instance khỏi danh sách nhận tải.
     - Vòng lặp kiểm tra `while _in_flight_requests > 0 and elapsed < timeout:` đợi tối đa `30s` cho toàn bộ các tác vụ LLM đang chạy hoàn thành xong, sau đó đóng kết nối và thoát sạch với exit code `0`.

- **Kết quả kiểm thử thực tế trên `05-scaling-reliability/develop/app.py`:**
  - `GET /health` & `GET /ready` khi đang hoạt động:
    ```http
    HTTP/1.1 200 OK
    content-type: application/json

    {"status":"ok","uptime_seconds":0.9,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:57:49.377170+00:00","checks":{"memory":{"status":"ok","used_percent":16.5}}}
    ```
    ```http
    HTTP/1.1 200 OK
    content-type: application/json

    {"ready":true,"in_flight_requests":1}
    ```
  - **Thử nghiệm gửi request `POST /ask?question=Long%20running%20task` đồng thời bắn `kill -SIGTERM <PID>` ngay lập tức:**
    - Phản hồi phía client vẫn hoàn thành trọn vẹn (**`200 OK`**, không bị đứt kết nối):
      ```http
      HTTP/1.1 200 OK
      date: Wed, 25 Nov 2026 09:57:48 GMT
      server: uvicorn
      content-type: application/json

      {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
      ```
    - Log trên server ghi nhận đúng thứ tự hoàn tất request đang bay rồi mới thực hiện graceful shutdown:
      ```text
      2026-11-25 09:57:48,800 INFO ✅ Agent is ready!
      INFO:     Shutting down
      INFO:     127.0.0.1:41996 - "POST /ask?question=Long%20running%20task HTTP/1.1" 200 OK
      INFO:     Waiting for application shutdown.
      2026-11-25 09:57:51,607 INFO 🔄 Graceful shutdown initiated...
      2026-11-25 09:57:51,607 INFO ✅ Shutdown complete
      INFO:     Application shutdown complete.
      INFO:     Finished server process [18915]
      ```

---

### Exercise 5.3, 5.4 & 5.5: Stateless Design, Nginx Load Balancing & Kiểm chứng 3 Instances + Redis

- **Tại sao lưu lịch sử hội thoại trong RAM bị hỏng khi scale nhiều instance và cách Redis giải quyết:**
  - **Vấn đề Stateful trong RAM:** Mỗi container Python chạy trong một không gian bộ nhớ (RAM) độc lập. Khi Nginx phân phối tải theo vòng tròn (*Round-Robin*) qua 3 instance:
    - Lượt 1: User gửi câu hỏi đầu tiên → Nginx đẩy vào `agent-1` → lịch sử lưu trong dictionary `_memory_store` của riêng `agent-1`.
    - Lượt 2: Cùng `session_id` đó gửi câu tiếp theo → Nginx đẩy sang `agent-2` → RAM của `agent-2` hoàn toàn trống rỗng với session này nên Agent bị "mất trí nhớ" (hoặc báo `404 Session not found`). Tương tự, nếu `agent-1` restart hoặc crash, toàn bộ hội thoại của người dùng biến mất.
  - **Giải pháp Stateless với Redis (`05-scaling-reliability/production/app.py`):**
    - Tách rời hoàn toàn trạng thái ra khỏi tiến trình Agent: hàm `save_session()` tuần tự hóa JSON và lưu vào Redis chung với TTL tự động dọn dẹp (`_redis.setex(f"session:{session_id}", 3600, serialized)`), còn `load_session()` đọc lại từ `_redis.get(...)` (giữ tối đa 20 messages gần nhất).
    - Nhờ vậy, mọi container Agent trở thành **stateless & hoán đổi hoàn toàn được cho nhau**: bất kỳ instance nào nhận request từ Nginx cũng đọc/ghi cùng một nguồn dữ liệu nhất quán trên Redis, đồng thời Nginx cấu hình `proxy_next_upstream error timeout http_503;` tự động chuyển tiếp sang instance khỏe nếu 1 container gặp sự cố.

- **Lệnh khởi chạy cụm 3 instance (`k5-day14-scaling`) ở cổng `8080`:**
  ```bash
  cd 05-scaling-reliability/production
  touch .env.local
  docker compose -p k5-day14-scaling up -d --build --scale agent=3
  python test_stateless.py
  docker compose -p k5-day14-scaling down -v
  ```

- **Kết quả chạy thực tế `python test_stateless.py` trên 3 instance Agent + Redis + Nginx:**
  ```text
  ============================================================
  Stateless Scaling Demo
  ============================================================

  Session ID: eb79f6ba-37b9-40e6-8ea7-41fb0933fa7c

  Request 1: [instance-6d53e5]
    Q: What is Docker?
    A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

  Request 2: [instance-259411]
    Q: Why do we need containers?
    A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

  Request 3: [instance-6d53e5]
    Q: What is Kubernetes?
    A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

  Request 4: [instance-7c7adb]
    Q: How does load balancing work?
    A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

  Request 5: [instance-259411]
    Q: What is Redis used for?
    A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

  ------------------------------------------------------------
  Total requests: 5
  Instances used: {'instance-7c7adb', 'instance-259411', 'instance-6d53e5'}
  ✅ All requests served despite different instances!

  --- Conversation History ---
  Total messages: 10
    [user]: What is Docker?...
    [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
    [user]: Why do we need containers?...
    [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
    [user]: What is Kubernetes?...
    [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
    [user]: How does load balancing work?...
    [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
    [user]: What is Redis used for?...
    [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

  ✅ Session history preserved across all instances via Redis!
  ```

- **Kiểm chứng chịu lỗi khi dừng đột ngột 1 container Agent:**
  - Sau khi chạy `docker stop` dừng container `agent-1` (`instance-259411`), gọi tiếp `curl -i http://localhost:8080/ready` qua Nginx vẫn trả về ngay **`200 OK`** được phục vụ bởi instance khỏe còn lại (`X-Served-By: 172.21.0.3:8000`, `{"ready":true,"instance":"instance-7c7adb"}`).
  - Đã chạy `docker compose -p k5-day14-scaling down -v` và xoá `.env.local` tạm để giải phóng hoàn toàn cổng `8080`.

---

## Part 6: Final Project — Production-Ready AI Agent (`06-lab-complete/`)

### Tổng quan các thành phần đã hoàn thiện trong `06-lab-complete/`
1. **12-Factor Configuration (`app/config.py`, `.env.example`):** Đọc động toàn bộ cấu hình (`PORT`, `ENVIRONMENT`, `LOG_LEVEL`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`) qua `os.getenv`, không chứa bất kỳ secret cứng nào trong mã nguồn.
2. **Lazy Redis Client & Health/Readiness (`app/redis_client.py`, `app/main.py`):** Khởi tạo connection pool lười (`socket_connect_timeout=1.0`, không `ping()` lúc import) giúp container khởi động ngay và `GET /health` luôn trả `200 OK` kể cả khi chưa có Redis; trong khi `GET /ready` kiểm tra `redis_healthy()` thực tế và trả `503` khi mất kết nối Redis hoặc đang draining shutdown.
3. **Ba lớp bảo vệ API (`app/auth.py`, `app/rate_limiter.py`, `app/cost_guard.py`):**
   - `verify_api_key`: kiểm tra `X-API-Key` bằng `secrets.compare_digest` (chống timing attack), thiếu hoặc sai đều trả `401`.
   - `check_rate_limit`: Sliding Window 60 giây bằng Redis Sorted Set (`ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` + `EXPIRE`), vượt ngưỡng trả `429` kèm header `Retry-After` và bền vững qua restart/multi-worker.
   - `check_budget` & `record_cost`: theo dõi chi phí token theo ngày (`cost:daily:YYYY-MM-DD`) và tháng (`cost:monthly:YYYY-MM`) bằng `INCRBYFLOAT` + `EXPIRE` trên Redis, vượt ngân sách trả `402`.
4. **Structured JSON Logging & Graceful Shutdown (`app/main.py`):** `JsonFormatter` xuất mỗi bản ghi log thành đúng 1 dòng JSON hợp lệ; `lifespan` kết hợp chuỗi chuyển tiếp handler `signal.SIGTERM` của Uvicorn đảm bảo hoàn tất request đang chạy (`200 OK`) rồi thoát sạch với exit code `0`.
5. **Multi-stage Docker & Cloud Config (`Dockerfile`, `.dockerignore`, `docker-compose.yml`, `railway.toml`, `render.yaml`):** Multi-stage `python:3.11-slim` (`69 MB` < `500 MB`), chạy user `appuser` non-root, có `HEALTHCHECK`, và dùng `exec python -m uvicorn ... --port ${PORT:-8000} --workers 2` để Uvicorn là PID 1 nhận trực tiếp `SIGTERM` khi `docker stop` (`1.0s`, exit code `0`).

### Kết quả chấm tự động `python check_production_ready.py` (Chế độ đầy đủ có Docker)

```text
================================================================
  Production Readiness Check — Day 14 Lab
================================================================

✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Dockerfile tồn tại
     ✅ requirements.txt tồn tại
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 112s
     ✅ Docker: image < 500 MB — 69 MB
     ✅ Docker: container chạy được, GET /health → 200

✅ 2. docker-compose.yml (agent + redis)
     ✅ docker-compose.yml tồn tại
     ✅ Có service agent (build từ Dockerfile) + redis — services: agent, redis — đọc bằng docker compose config
     ✅ Service agent kết nối redis (REDIS_URL + depends_on)

✅ 3. .dockerignore
     ✅ .dockerignore tồn tại và có nội dung
     ✅ .dockerignore loại trừ .env (secrets)
     ✅ .dockerignore loại trừ __pycache__, venv

✅ 4. Health check endpoint (GET /health)
     ✅ Code có route /health
     ✅ Khi chạy: GET /health → 200 — uvicorn --workers 2

✅ 5. Readiness endpoint (GET /ready)
     ✅ Code có route /ready
     ✅ Khi chạy: GET /ready → 200
     ✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)

✅ 6. API Key authentication
     ✅ Code đọc header X-API-Key
     ✅ Khi chạy: thiếu / sai API key → 401
     ✅ Khi chạy: API key đúng → 200

✅ 7. Rate limiting
     ✅ Code trả HTTP 429 khi vượt giới hạn
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429

✅ 8. Cost guard
     ✅ Code trả HTTP 402 khi hết budget
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1

✅ 9. Config từ environment variables
     ✅ app/config.py đọc biến môi trường
     ✅ .env.example liệt kê đủ biến cấu hình
     ✅ .env nằm trong .gitignore
     ✅ Không hard-code secret trong code
     ✅ Khi chạy: agent dùng AGENT_API_KEY và RATE_LIMIT_PER_MINUTE từ env

✅ 10. Structured logging
     ✅ Code ghi log dạng JSON
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 12 dòng JSON

✅ 11. Graceful shutdown
     ✅ Code xử lý SIGTERM / lifespan shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 1.0s

✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI Log

Trong quá trình làm lab, mình sử dụng AI (Antigravity / Gemini) để tra cứu nhanh một số chi tiết kỹ thuật, dựng khung boilerplate và đối chiếu các edge case trong script chấm điểm; toàn bộ thông số cấu hình và kết quả chạy đều được kiểm tra trực tiếp trên môi trường WSL2 Ubuntu + Docker.

| Phần | Mình đã hỏi gì? | AI gợi ý / trả về gì? | Mình tự rà soát, chỉnh sửa & kiểm chứng thế nào? |
| :--- | :--- | :--- | :--- |
| **Part 1 (CP1)** | Nhờ đối chiếu nhanh các điểm vi phạm 12-Factor giữa `develop/app.py` và `production/app.py` để không sót ý trong bảng so sánh 1.3. | Khung phân tích các nhóm Config, Secrets, Logging, Health check và Graceful Shutdown. | Đọc trực tiếp từng dòng `develop/app.py` để ghi chính xác số dòng (dòng 17–18 hardcode secret, dòng 34 `print` lộ key, dòng 49–54 bind `localhost` + `reload=True`). Chú ý bản `develop` nhận `question` qua query string (gửi JSON như `CODE_LAB.md` sẽ bị `422`), chạy thử trên WSL2 xác nhận `200 OK`, xóa `.env` tạm sau khi test bản `production` và kiểm tra `ss -ltn` đảm bảo cổng `8000` đã đóng. |
| **Part 2 (CP2)** | Hỏi lại sự khác biệt giữa `--no-cache-dir` của `pip` với Docker layer cache, và cách đọc đúng dung lượng trên Docker CLI bản mới (Docker 29 hiển thị 2 cột `DISK USAGE` và `CONTENT SIZE`). | Giải thích quy tắc cache invalidation theo thứ tự layer và gợi ý dùng thêm `docker image inspect --format '{{.Size}}'` để lấy kích thước byte chính xác bên cạnh `docker images`. | Kiểm tra kỹ `02-docker/develop/Dockerfile` dùng `python:3.11` đầy đủ (không phải `slim`), đứng từ gốc repo để build đủ context `utils/mock_llm.py`. Tự tính % giảm trên cả hai chỉ số thực đo (`1.67 GB` → `240 MB` giảm `85.63%`; `426.32 MB` → `57.41 MB` giảm `86.53%`), tạo `.env.local` rỗng và đặt `-p k5-day14-part2` trước khi bật/tắt Compose để không đụng tên project với các bài sau. |
| **Part 3 (CP6)** | Hỏi cách phân tích sâu sự khác biệt về triết lý thiết kế giữa `railway.toml` với `render.yaml` và các điểm đáng chú ý trong Knative spec `service.yaml` của Cloud Run. | Gợi ý khung so sánh theo phạm vi quản lý tài nguyên (1 service vs multi-service Blueprint), cách truyền secret (`generateValue` / `sync: false` / Secret Manager) và giải thích các annotation `minScale`/`containerConcurrency` trên Cloud Run. | Đọc đối chiếu trực tiếp `03-cloud-deployment/railway/railway.toml`, `render/render.yaml`, `cloudbuild.yaml` và `service.yaml`; làm rõ cơ chế nối chuỗi phụ thuộc `waitFor` (`test` → `build` với `--cache-from` → `push` `$COMMIT_SHA` → `deploy`), cách tách `startupProbe` (`/ready`) với `livenessProbe` (`/health`), và kiểm tra thực tế 4 lệnh `curl` trên URL public không lộ key. |
| **Part 4 (CP3)** | Hỏi chiến lược rotate API key zero-downtime trong thực tế và mẫu thiết kế Cost Guard dùng Redis cho môi trường nhiều instance. | Gợi ý mô hình *dual-key* trong giai đoạn chuyển giao và dùng `INCRBYFLOAT` + `EXPIRE` gắn theo key ngày/tháng trên Redis, kèm so sánh vai trò của Rate Limit vs Cost Guard. | Đối chiếu lại code thật trong `04-api-gateway/production/`: phát hiện endpoint thực tế là `POST /auth/token` với user `student` / `demo123` (`10 req/phút`) chứ không phải `/token` như mẫu chung. Chạy vòng lặp 15 request bắt đúng `429` ở request `#11`, kiểm tra `/me/usage` thấy chỉ 10 request hợp lệ bị tính phí, và lọc che toàn bộ chuỗi JWT thành `<REDACTED_JWT>` trước khi đưa vào bài. |
| **Part 5 (CP4)** | Hỏi kỹ lý do `/health` không nên kiểm tra kết nối Redis (tránh crash-loop) và cách kiểm chứng thực tế graceful shutdown khi nhận `SIGTERM`. | Phân tích cơ chế orchestrator xử lý Liveness vs Load Balancer xử lý Readiness, gợi ý bắn `POST /ask` chạy nền rồi gửi ngay `kill -SIGTERM <PID>` để quan sát thứ tự log. | Chạy thực nghiệm trên WSL2 xác nhận request đang bay vẫn trả `200 OK` trước khi `lifespan` đóng tiến trình. Ở phần Compose cổng `8080` (`POST /chat`), dùng `-p k5-day14-scaling` tránh dùng nhầm image của Part 2, chạy `test_stateless.py` thấy cả 3 container cùng phục vụ 1 `session_id` giữ đủ 10 tin nhắn trên Redis, đồng thời thử `docker stop` 1 container để xác nhận Nginx tự failover sang instance còn sống. |
| **Part 6 (CP5)** | Nhờ gợi ý cấu trúc code cho `06-lab-complete/` theo bảng Hợp đồng, đặc biệt là: (1) Sliding Window bằng Redis Sorted Set, (2) đăng ký `SIGTERM` mà không làm kẹt Uvicorn `--workers 2`, và (3) viết `CMD` trong `Dockerfile` vừa nhận biến `PORT` vừa giữ Uvicorn làm PID 1. | Đề xuất khung `ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` (member gắn `timestamp:uuid` để không đè nhau trong cùng mili-giây), lưu `prev_sigterm = signal.getsignal(signal.SIGTERM)` rồi gọi nối tiếp trong handler, và dùng `CMD ["sh", "-c", "exec python -m uvicorn ... --port ${PORT:-8000}"]`. | Tự rà soát kỹ từng điều kiện trong `check_production_ready.py`: đảm bảo `redis_client.py` khởi tạo pool lười (không `ping()` lúc import để container chạy độc lập vẫn qua được `/health` `200`, còn `/ready` đặt `socket_connect_timeout=1.0` để trả `503` nhanh khi mất Redis); dùng `secrets.compare_digest` trả đúng `401` (thay vì `403`/`422`); tách logger `agent` (`propagate = False`) với `JsonFormatter` để không lẫn log text của Uvicorn; cấu hình `render.yaml` dùng `generateValue: true` không lộ secret. Chạy kiểm chứng `python check_production_ready.py` đạt `12/12` (`43/43 checks passed`, image `69 MB`, `docker stop` thoát `0` sau `1.0s`) và kiểm tra `git diff` đảm bảo `check_production_ready.py` không bị chạm vào. |
| **Part 7 Bước 1 (CP7)** | Hỏi cách chọn bucket hợp lý cho Histogram `agent_question_length_chars` và cách viết GitHub Actions workflow dùng `run_eval.py` làm quality gate. | Gợi ý dải bucket theo `max_length=2000` ký tự của `AskRequest` và mẫu workflow bật `app.py` chạy nền với `MOCK_ERROR_RATE=0` để tránh lỗi upstream ngẫu nhiên làm nhiễu kết quả chấm kiến thức. | Chạy đủ 7 kịch bản `load_test.py` trước rồi mới chạy `eval_v1.json` và `eval_v2.json` trên KB gốc (để lưu đúng baseline `91.3%` với 2 câu lỗi `security-02`, `scaling-03`). Chọn từ khóa trigger hẹp (`["jwt"]` và `["hpa", "kubernetes", "autoscal"]`) khi thêm vào `KNOWLEDGE_BASE` để không chiếm nhầm câu `basic-01` (vốn dựa vào fallback `V1_RESPONSES["deploy"]`), đồng bộ sang cả `production/utils/mock_llm.py`, khởi động lại `v2` đạt `23/23 (100%)` không regression và đối chiếu khớp 100% từng con số JSON vào `BENCHMARK_REPORT.md`. |
| **Part 7 Bước 2 (CP8)** | Hỏi nguyên nhân các request Locust đầu tiên bị lỗi `502` và cách giải thích hiện tượng `p95` không giảm mạnh khi scale từ 1 lên 3 instance trên cùng một máy Docker. | Gợi ý kiểm tra log khởi động của container `agent` và phân tích định luật Little kết hợp độ trễ I/O phía LLM upstream. | Kiểm tra `docker compose logs agent` phát hiện `production/Dockerfile` tạo user `useradd -d /app` nhưng copy gói `--user` vào `/home/agent/.local` mà thiếu `ENV PYTHONUSERBASE=/home/agent/.local` khiến `uvicorn` báo `ModuleNotFoundError`; sau khi bổ sung `PYTHONUSERBASE` và `chown`, stack chạy sạch sẽ. Tự chạy lại toàn bộ Locust headless (`scale_1`, `scale_3`), `promtool test rules`, đối chiếu `trace_id` giữa Jaeger với dòng log JSON thực tế, kích hoạt đồng thời cả 4 alert `FIRING` và dọn sạch stack bằng `down -v`. |
