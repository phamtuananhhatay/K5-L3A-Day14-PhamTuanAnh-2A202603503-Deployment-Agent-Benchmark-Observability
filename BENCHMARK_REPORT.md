# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được trích xuất trực tiếp từ các file báo cáo thực nghiệm trong `reports/` và `benchmark-results/`.

**Họ tên:** Phạm Tuấn Anh (MSSV: 2A202603503)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 + WSL2 Ubuntu 24.04 (`Python 3.12.3`, `os.name = posix`), Docker Engine `29.1.3` & Docker Compose `v2.40.3`

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `≤ 500 ms` | Với ứng dụng hỏi đáp RAG/Agent tương tác trực tiếp, độ trễ dưới `0.5s` cho 95% người dùng giữ cảm giác phản hồi tức thì, đồng thời vẫn đủ dư địa cho bước retrieval (~`20ms`) + suy luận model nhỏ (~`150–220ms`) mà không bị nhiễu bởi 3% request tail latency bất thường. |
| Error rate `/ask` | `≤ 2.0 %` | Nhà cung cấp LLM upstream trong thực tế luôn tồn tại tỉ lệ lỗi thoáng qua (`429`/`503` khoảng `0.5%–1%`). Ngưỡng `≤ 2.0%` tạo **error budget `2%`** hợp lý để phân biệt nhiễu ngẫu nhiên của upstream với sự cố hệ thống thực sự. |
| Accuracy trên golden dataset | `≥ 85 %` *(CI gate)* / `100 %` *(sau khi vá KB)* | Đảm bảo tối thiểu 85% câu hỏi cốt lõi trong tập kiểm chuẩn đạt điểm từ khóa `≥ 0.6` và tuyệt đối **không có regression** nào so với phiên bản baseline trước khi cho phép merge PR / deploy. |

> **Ghi chú Exercise 7.1 (Instrumentation & Cardinality trong `develop/app.py`):**
> - **3 loại Prometheus metrics đang dùng:**
>   - **Counter** (chỉ tăng, dùng với `rate()`): `http_requests_total`, `llm_requests_total`, `llm_tokens_total`, `llm_cost_usd_total`.
>   - **Gauge** (tăng/giảm tức thời): `agent_in_flight_requests`, `agent_info`.
>   - **Histogram** (phân phối theo bucket, dùng với `histogram_quantile()`): `http_request_duration_seconds`, `llm_request_duration_seconds`, và metric mới bổ sung **`agent_question_length_chars`** (`buckets=(20, 50, 100, 200, 500, 1000, 2000)`).
> - **Tại sao `observe_requests` dùng `route.path` thay vì `request.url.path`?** Nếu gắn URL thô (`request.url.path`) vào label `route`, khi bot/scanner quét hàng chục nghìn đường dẫn ngẫu nhiên (`/wp-admin`, `/.env`, `/user/98765`, `/a1b2c3...`), mỗi đường dẫn tạo ra một tổ hợp label mới → **cardinality explosion** (bùng nổ hàng trăm nghìn time series) làm Prometheus tràn RAM (OOM). Dùng `route.path` gom toàn bộ URL lạ về một nhãn duy nhất `route="unmatched"`, giữ số lượng time series luôn hữu hạn và cố định.

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2 — `300` requests/lần chạy)

*(Nguồn dữ liệu: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO (`p95 ≤ 500ms`, `err ≤ 2%`) |
|---|---:|---:|---:|---:|---:|---|
| 1 | `4.33` | `192.9` | `222.6` | `1717.1` | `2.00%` (`6/300` lỗi `503`) | ✅ PASS |
| 10 | `38.47` | `190.7` | `221.7` | `1677.6` | `1.33%` (`4/300` lỗi `503`) | ✅ PASS |
| 50 | `104.73` | `199.3` | `297.4` | `1717.4` | `1.00%` (`3/300` lỗi `503`) | ✅ PASS |
| 100 | `68.94` | `327.7` | `2397.8` | `2613.3` | `1.33%` (`4/300` lỗi `503`) | ❌ FAIL *(vi phạm p95)* |

**Nhận xét:** RPS **không** tăng tuyến tính mãi theo concurrency:
- Giai đoạn `c = 1 → 10`: RPS tăng gần tuyến tính (`4.33` → `38.47 req/s`, gấp `8.88×`) trong khi `p50` (`~191ms`) và `p95` (`~222ms`) hầu như giữ nguyên vì tác vụ gọi LLM chủ yếu là non-blocking I/O (`asyncio.sleep`), event loop hoàn toàn rảnh để xử lý đan xen các coroutine.
- Giai đoạn `c = 10 → 50`: RPS tiếp tục tăng lên đỉnh **`104.73 req/s`**, nhưng chỉ tăng `2.72×` thay vì `5×` và `p95` bắt đầu nhích lên `297.4ms` do chi phí chuyển ngữ cảnh coroutine, tuần tự hóa JSON, ghi log đồng bộ (`logger.info` ra stdout/file) và chia sẻ duy nhất 1 Uvicorn worker.
- Giai đoạn `c = 50 → 100`: Xảy ra hiện tượng **quá tải hàng đợi (queueing saturation)** trên 1 tiến trình đơn: 100 kết nối TCP/HTTP dồn dập cùng lúc khiến hàng đợi socket backlog & event loop bị nghẽn, kéo `p50` lên `327.7ms`, **`p95` vọt lên `2397.8ms`** (vi phạm SLO `500ms`) và thông lượng thực tế tụt ngược xuống `68.94 req/s` (theo định luật Little và đường cong suy thoái Universal Scalability Law).

### 2.2 Tail latency (`concurrency = 20`, `300` requests/lần chạy)

*(Nguồn dữ liệu: `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json`)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | `191.5` | `220.6` | `236.1` |
| 0.03 (mặc định) | `240.6` | `225.5` | `1699.6` |
| 0.1 | `321.8` | `1680.2` | `1726.3` |

**Nhận xét:**
- **Chỉ số nhạy nhất với sự xuất hiện ban đầu của request chậm là `p99` (và `p95` khi tỉ lệ chậm vượt ngưỡng 5%):**
  - Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (chỉ 3% request bị cộng thêm `1500ms`), `avg` chỉ nhích nhẹ từ `191.5ms` lên **`240.6ms`** (+25.6%) và `p95` gần như đứng yên (`225.5ms` vì 95% request đầu vẫn nhanh), nhưng **`p99` nhảy vọt gấp `7.2×` từ `236.1ms` lên `1699.6ms`**!
  - Khi `MOCK_SLOW_RATE` lên `0.1` (10% request chậm `> 5%`), cả **`p95` cũng nổ vọt lên `1680.2ms`** (làm FAIL SLO `500ms`), trong khi **`avg` vẫn chỉ là `321.8ms`** — thấp hơn rất xa ngưỡng `500ms`!
- **Vì sao SLO tuyệt đối không đặt theo `average`?** Trung bình cộng bị phần lớn các request nhanh kéo thấp xuống, làm "phẳng" và che giấu hoàn toàn trải nghiệm tệ hại ở phần đuôi phân phối (*tail latency*). Nếu đặt SLO `avg ≤ 500ms`, ở mức `MOCK_SLOW_RATE = 0.1` hệ thống báo `321.8ms` ("vẫn xanh"), trong khi thực tế **cứ 10 khách hàng thì có 1 người phải chờ gần 1,7 giây**. Đặt SLO theo `p95` / `p99` buộc hệ thống đảm bảo trải nghiệm thực tế cho 95%–99% tổng số lượt gọi.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Nguồn dữ liệu: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json` trên bộ 23 câu `golden_dataset.jsonl`)*

| Chỉ số | Agent v1 (`eval_v1.json`) | Agent v2 (`eval_v2.json`) | Agent v2 sau khi sửa KB (`eval_v2_fixed.json`) |
|---|---:|---:|---:|
| Accuracy | `4.3%` (`1/23`) | `91.3%` (`21/23`) | **`100.0%` (`23/23`)** |
| Avg tokens / câu | `56.9` | `109.1` | `114.1` |
| Tổng cost (USD) | `$0.000402` | `$0.000762` | `$0.000794` |
| Cost / câu đúng (USD) | `$0.00040155` | `$0.00003627` | **`$0.00003453`** |
| Quality gate | ❌ FAIL *(min 80%)* | ✅ PASS *(min 80%, 0 regression)* | **✅ PASS *(min 100%, 0 regression)*** |

**Những câu v2 trả lời sai ban đầu và cách sửa trong `utils/mock_llm.py` (`KNOWLEDGE_BASE`):**

| ID | Keyword bị thiếu | Cách sửa trong `KNOWLEDGE_BASE` |
|---|---|---|
| `security-02` | `['token', 'hết hạn', 'chữ ký']` | Thêm mục kiến thức với từ khóa kích hoạt `["jwt"]` giải thích sự khác biệt giữa API key tĩnh và JWT (`token` tự chứa thông tin người dùng, có thời điểm `hết hạn` và `chữ ký` số xác thực stateless). |
| `scaling-03` | `['cpu', 'memory', 'custom metrics']` | Thêm mục kiến thức với từ khóa kích hoạt `["hpa", "kubernetes", "autoscal"]` giải thích Kubernetes HPA tự động co giãn số pod dựa trên `CPU`, `memory` hoặc `custom metrics` (như RPS, độ dài hàng đợi). |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2 & Cơ chế CI Quality Gate:**
- **Trade-off RAG thực tế:** Agent `v2` (có bước tìm kiếm tài liệu đưa vào prompt) tiêu thụ lượng token trung bình cao gấp ~`2.0×` so với `v1` (`114.1` vs `56.9` tokens/câu), tổng tiền cho 23 câu tăng từ `$0.000402` lên `$0.000794`, và độ trễ `p50` tăng nhẹ khoảng `~24ms` (`187.3ms` vs `163.1ms`) do thêm bước `search_knowledge_base`. Tuy nhiên, độ chính xác nhảy vọt từ **`4.3%` (`1/23`) lên `100.0%` (`23/23`)**! Nếu xét trên chỉ số kinh tế thực chất là **`Cost / câu trả lời đúng`**, `v2` chỉ tốn **`$0.00003453`/câu đúng** — **rẻ hơn `11.6 lần`** so với `v1` (`$0.00040155`/câu đúng, vì 22/23 câu của `v1` vừa tốn tiền token vô ích vừa trả lời sai).
- **Chặn Regression tự động trên CI (`.github/workflows/eval.yml`):** Khi thử chạy `run_eval.py` cho `v1` đối chiếu với `--baseline reports/eval_v2.json`, script phát hiện ngay `20` câu bị regression và thoát với **`exit code = 1`**. Trong workflow `.github/workflows/eval.yml`, mỗi Pull Request tự động bật Agent ở chế độ `MOCK_ERROR_RATE=0` và gọi `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline ../../../reports/eval_v2.json`: bất kỳ thay đổi prompt/code/KB nào làm giảm accuracy xuống dưới `85%` hoặc làm hỏng câu từng đúng đều trả exit code khác `0`, khiến GitHub Actions đánh dấu đỏ. Để bắt buộc chặn merge, cần đặt job này thành required status check trong branch protection của GitHub.

---

## 4. Observability stack (production)

### 4.1 Screenshot & Quan sát Dashboard dưới tải thực (Exercise 7.4)

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) — [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`) — [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với cả 4 alert đang **firing** — [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Trả lời 4 câu hỏi quan sát dưới tải thực (`30 users`, `ramp up 5`, `2 instances`):**
1. **`p95` và `avg` đang là bao nhiêu? Khoảng cách giữa chúng nói lên điều gì?**
   - Truy vấn trực tiếp trên Prometheus khi chạy 30 users ổn định: **`avg = 266.4 ms`** (`0.266s`) trong khi **`p95 = 433.3 ms`** (`0.433s`, và vọt lên `671.80 ms` lúc ramp-up tải mới; `p99 ≈ 1.8s`). Khoảng cách rõ rệt giữa `avg` và `p95`/`p99` phản ánh phân phối lệch phải (*long-tail latency*): đa số request hoàn thành quanh ~`200ms`, nhưng nhóm ~`3%` request chậm (`+1500ms` từ LLM upstream) kéo phần đuôi vọt cao mà số trung bình cộng không phản ánh hết.
2. **Panel "Requests/s theo instance": Nginx có chia đều traffic cho 2 instance không?**
   - **Có, khá đồng đều:** Prometheus ghi nhận `172.21.0.3:8000` nhận **`5.60 req/s`** và `172.21.0.2:8000` nhận **`5.29 req/s`** (tương ứng `51.4%` và `48.6%` tổng traffic, lệch khoảng `2.8` điểm phần trăm; chênh lệch tương đối so với trung bình khoảng `5.7%`).
3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`?**
   - Thực đo trên Prometheus: **`input = 830.9 tokens/s`**, gần gấp đôi **`output = 434.2 tokens/s`** (`~1.91×`). Lý do là ở Agent `v2` (RAG), mỗi lần gọi LLM đều phải gửi toàn bộ `SYSTEM_PROMPT` + đoạn tài liệu truy xuất từ `KNOWLEDGE_BASE` + câu hỏi của người dùng làm đầu vào (`~80–95 input tokens`), trong khi câu trả lời tóm tắt sinh ra ngắn gọn hơn (`~44–55 output tokens`).
4. **`curl -i http://localhost:8080/metrics` trả về gì? Vì sao?**
   - Trả về **`HTTP/1.1 404 Not Found`** từ Nginx. Endpoint `/metrics` bị chặn chủ đích ở tầng Reverse Proxy để người ngoài Internet không đọc trộm được lưu lượng kinh doanh, chi phí LLM, phiên bản nội bộ hay cấu trúc route của hệ thống; chỉ duy nhất Prometheus nằm bên trong mạng nội bộ Docker `obs_net` mới được phép scrape trực tiếp `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống" & Unit Test Alert Rules (Exercise 7.6)

- **Unit test `alert_rules_test.yml` bằng `promtool`:** `Processing test file: /p/alert_rules_test.yml → SUCCESS`.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` *(chạy `0.25`)* | `AgentHighErrorRate` (`for: 1m`, `severity: critical`) | **`88.5s`** *(vào `pending` lúc `25.7s`)* | **Error rate** (hàng Golden Signals đổi đỏ `> 5%`) & **Requests/s theo status code** (đường `503` tăng vọt) |
| B | `MOCK_SLOW_RATE=0.3` *(chạy `0.35`)* | `AgentHighLatencyP95` (`for: 2m`, `severity: warning`) | **`97.3s`–`126s`** *(đủ cửa sổ `for: 2m`)* | **Latency p95** & biểu đồ **Latency /ask — p50 / p95 / p99** (đường `p95` vượt vạch đỏ `1s`) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, `severity: warning`) | **`~150s`** *(vào `pending` lúc `29.5s`, chờ cửa sổ `rate(...[5m])` + `for: 2m`)* | **Cost burn rate (USD/giờ)** & **LLM cost (1h)** (tăng ~`16×` so với `mock-llm-small`) |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`for: 30s`, `severity: critical`) | **`20.7s`–`35s`** *(vào `pending` lúc `5.6s`)* | **Instances up** (tụt từ `2` xuống `1`) & **Requests/s theo instance** (1 đường rơi về `0`) |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | `N/A` *(không kích hoạt)* | **Retrieval hit ratio (agent v2)** (mất/về `0`), **Tokens/s** giảm một nửa, bảng **Agent version** đổi sang `v1` |

*(Ghi chú kỹ thuật ở thí nghiệm D: Phải dùng `docker pause` thay vì `docker stop` vì Prometheus dùng Docker DNS Service Discovery `dns_sd_configs` — container bị `stop` sẽ rút khỏi bản ghi DNS làm target biến mất hoàn toàn, trong khi `pause` giữ nguyên IP trong DNS nhưng treo phản hồi `/metrics` khiến `up{job="agent"} == 0`).*

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Sự cố suy giảm chất lượng trả lời (*silent quality degradation* — trả lời sai kiến thức, ảo giác, rớt pipeline RAG về fallback chung chung) vẫn trả mã HTTP `200 OK`, tốc độ thậm chí còn nhanh hơn và tốn ít token hơn nên mọi alert hạ tầng truyền thống (Error rate, Latency, CPU/RAM, Cost) đều báo xanh. Để phát hiện trong production cần kết hợp **3 lớp kiểm soát chuyên biệt cho AI**:
1. **Pre-deploy / CI Eval Gate:** Chạy bộ `golden_dataset.jsonl` tự động trên mỗi PR vào `main` (`.github/workflows/eval.yml`) chặn ngay bản build có accuracy tụt hoặc dính regression trước khi ra môi trường thật.
2. **Domain-specific Business Metrics & Anomaly Alerts:** Đặt cảnh báo khi chỉ số nghiệp vụ thay đổi bất thường, ví dụ `rate(agent_retrieval_hits_total{result="hit"}[5m]) == 0` (RAG đột ngột ngừng truy xuất tài liệu) hoặc `avg_input_tokens` sụt giảm đột ngột `> 40%`.
3. **Online Evaluation & User Feedback:** Lấy mẫu định kỳ một tỉ lệ nhỏ (vd `1%–5%`) cặp `question`/`answer` từ log/trace thực tế chấm tự động bằng **LLM-as-a-Judge** bất đồng bộ (xuất metric `agent_online_eval_score`), kết hợp theo dõi tỉ lệ người dùng bấm *Thumbs-down / Regenerate*.

### 4.3 Debug bằng trace (Exercise 7.5)

- **Trace chậm nhất tìm được trên Jaeger ([screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)):**
  - `trace_id`: `c784ceae5b5103a34d7f0ac01503dbb9`
  - Tổng thời gian (`POST /ask`): **`1702.1 ms`** (`1.70s` trên Jaeger UI, gồm 4 spans độ sâu 3: `POST /ask` → `agent.run` → `agent.retrieve_context` + `chat mock-llm-small`)
  - Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**`1679.5 ms`**, chiếm **`98.67%`** tổng thời gian toàn request; trong khi bước `agent.retrieve_context` chỉ mất ~`20ms` → xác định chính xác độ trễ nằm ở phía nhà cung cấp LLM upstream chứ không phải code Python hay truy vấn KB).
  - Dòng log JSON tương ứng đối chiếu theo đúng `trace_id` từ `docker compose -p k5-day14-observability logs agent`:

```json
{"ts": "2026-11-25T15:18:14.657535+00:00", "level": "INFO", "service": "observable-agent", "instance": "96f95683d56d", "event": "llm_call", "trace_id": "c784ceae5b5103a34d7f0ac01503dbb9", "span_id": "e790d645b9951883", "request_id": "6a76d8958492", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1679.5}
{"ts": "2026-11-25T15:18:14.658413+00:00", "level": "INFO", "service": "observable-agent", "instance": "96f95683d56d", "event": "http_request", "trace_id": "c784ceae5b5103a34d7f0ac01503dbb9", "span_id": "e790d645b9951883", "request_id": "6a76d8958492", "method": "POST", "route": "/ask", "status": 200, "ms": 1702.1}
```

- **Đối chiếu thêm Trace lỗi `503` ([screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)):**
  - `trace_id`: `91345e7afb8d782087916f49846298f5` (`Duration: 92.3ms`, span `chat mock-llm-small` mất `71.1ms`, gắn tag `error.type = upstream_unavailable` và `Events (1)` chứa `exception`).
  - Dòng log JSON khớp `trace_id`:
    ```json
    {"ts": "2026-11-25T15:12:22.778247+00:00", "level": "INFO", "service": "observable-agent", "instance": "fa3e0b798708", "event": "llm_error", "trace_id": "91345e7afb8d782087916f49846298f5", "span_id": "89830873ba5503a6", "request_id": "c97c7e65a1e8", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
    ```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Nguồn dữ liệu: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`)*

| Số instance | Dòng thống kê CSV | Tổng requests | RPS (`Requests/s`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---:|---:|---:|---:|---:|---:|
| **1** (`scale_1_stats.csv`) | **`Aggregated`** | `5913` | **`51.94`** | **`220`** | **`2200`** | **`6800`** | **`57`** (`0.96%`) |
| *(chi tiết `/ask` của `scale_1`)* | `POST /ask` | `5338` | `46.89` | `220` | `2200` | `7000` | `57` (`1.07%`) |
| **3** (`scale_3_stats.csv`) | **`Aggregated`** | `6017` | **`53.55`** | **`210`** | **`2600`** | **`7800`** | **`46`** (`0.76%`) |
| *(chi tiết `/ask` của `scale_3`)* | `POST /ask` | `5487` | `48.84` | `220` | `2700` | `8000` | `46` (`0.84%`) |

**Giải thích kết quả:**
- **Scale từ 1 lên 3 instance giúp giảm latency phân vị trung gian (`p75` của `/ask` giảm từ `510ms` xuống `360ms`, `p80` giảm từ `700ms` xuống `480ms`, `Aggregated p50` giảm từ `220ms` xuống `210ms`) và nhích nhẹ RPS (`51.94 → 53.55 req/s`), nhưng KHÔNG làm giảm mạnh `p95` / `p99` vì 3 nguyên nhân cốt lõi:**
  1. **Nút thắt chính nằm ở độ trễ I/O của dịch vụ LLM bên ngoài (External LLM Latency & Tail Latency):** Mỗi instance Python dùng `async/await` (non-blocking I/O) nên không bị nghẽn CPU khi chờ LLM, nhưng bản thân mỗi cuộc gọi `mock-llm` luôn mất cứng `~150–200ms` cộng thêm `3%` tỉ lệ chậm `1500ms`. Tăng số lượng container FastAPI chỉ giúp chia tải xử lý HTTP/JSON/OTel spans, hoàn toàn không thể rút ngắn thời gian suy luận của model phía sau.
  2. **Trần thông lượng từ kịch bản người dùng ảo (Think-time bound):** Trong `locustfile.py`, 100 users nghỉ `wait_time = between(0.5, 2)` giây (trung bình `1.25s`) giữa hai câu hỏi. Theo định luật Little ($RPS = \frac{N}{W + R}$), với $N = 100$ và $W + R \approx 1.25s + 0.61s = 1.86s$, tốc độ bơm tải tối đa của chính Locust chỉ xoay quanh **`~53–55 req/s`** dù phía sau có bao nhiêu replica.
  3. **Tranh chấp tài nguyên cục bộ trên cùng một máy host Docker + OTel export:** Cả 3 container Agent (giới hạn `cpus: "0.5"`), Nginx, Prometheus, Grafana, Jaeger và chính container Locust cùng chia sẻ chung CPU/network bridge của một máy WSL2 duy nhất, khiến một vài chu kỳ flush `BatchSpanProcessor` / GC tạo đuôi `p95`/`p99` vài giây ở tải 100 users.

---

## 6. Kết luận

- **3 điều quan trọng nhất học được về Benchmark & Observability cho AI Agent:**
  1. **Không bao giờ đánh giá độ trễ qua số trung bình (`average`) và không đánh giá chi phí qua `cost / request`:** Trung bình cộng che giấu hoàn toàn *tail latency* (`p95`/`p99`) của những khách hàng xui xẻo nhất, còn `cost / câu trả lời đúng` mới phản ánh hiệu quả kinh tế thực tế khi so sánh kiến trúc RAG (`v2` đắt gấp đôi trên mỗi câu nhưng rẻ hơn `11.6×` cho mỗi câu trả lời đúng so với `v1`).
  2. **Ba trụ cột Metrics – Traces – Logs phải được khâu nối bằng `trace_id`:** Metrics (Prometheus/Grafana) báo động *"hệ thống đang chậm/lỗi"*, Distributed Tracing (OpenTelemetry/Jaeger) chỉ điểm chính xác *"chậm `98.7%` tại span `chat mock-llm-small` chứ không phải ở bước retrieval"*, và Structured JSON Logs chứa `trace_id` cung cấp ngữ cảnh chi tiết của chính request đó trong tích tắc.
  3. **Giám sát hạ tầng "xanh" không đồng nghĩa AI Agent đang trả lời đúng:** Sự cố tụt chất lượng mô hình/prompt/RAG (như Thí nghiệm E — `AGENT_VERSION=v1`) không gây lỗi `5xx` hay tăng latency; bắt buộc phải kết hợp **Offline CI Eval Quality Gate** trước khi deploy và **Online Eval / Business Metrics** trong lúc vận hành.

- **Nếu đưa agent này lên môi trường Production thật, các metric & alert cần bổ sung thêm:**
  1. **Giám sát ở tầng Edge / Load Balancer (`nginx_http_requests_total`, `upstream_response_time`):** Bắt trọn các lỗi `502`/`504 Gateway Timeout` khi container Agent bị treo hoặc bị `pause` mà bản thân tiến trình Python bên trong không thể tự đếm được.
  2. **LLM Guardrails & Quality Metrics:**
     - `agent_retrieval_hits_total{status="miss"}` → Alert khi tỉ lệ không tìm thấy ngữ cảnh RAG vượt ngưỡng (vd `> 40%` trong `10m`), báo hiệu thiếu tài liệu hoặc lỗi embedding/vector DB.
     - `llm_time_to_first_token_seconds` (**TTFT** Histogram) cho trải nghiệm streaming và `llm_upstream_ratelimit_total` (đếm riêng mã `429` từ OpenAI/Anthropic để tự động fallback sang model dự phòng).
     - `agent_online_eval_faithfulness_score` (chấm mẫu tự động bất đồng bộ) kèm cảnh báo khi điểm độ trung thực với ngữ cảnh (faithfulness/hallucination) tụt dưới ngưỡng an toàn.

