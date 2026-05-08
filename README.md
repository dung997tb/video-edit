# 🎬 AI Video Automation Engine (v2.0)

Một hệ thống tự động hóa xử lý video bằng AI chuẩn **Production-Ready**, hỗ trợ kiến trúc phân tán (multi-replica), quản lý hàng đợi bằng Supabase, tính năng phục hồi lỗi theo từng bước (step-level idempotency) và quản trị tiến trình FFmpeg an toàn.

---

## 🌟 Tính Năng Nổi Bật

- **API & Worker Độc Lập:** Cung cấp FastAPI Server để quản lý Job và Worker chạy nền chuyên dụng với cơ chế `ThreadPoolExecutor` (có thể gộp chung hoặc chạy khác server).
- **Phục Hồi Lỗi Thông Minh (Caching):** Tự động băm (hash) theo mã SHA-256 để lưu cache từng bước nhỏ. Nếu Job thất bại do rớt mạng, khi chạy lại nó sẽ **bỏ qua các bước đã hoàn thành**, tiết kiệm tối đa chi phí gọi API.
- **Quản Lý Tiến Trình An Toàn:** Kiểm soát triệt để FFmpeg/FFprobe, tự động thu dọn dẹp các "zombie processes" khi người dùng yêu cầu Hủy Job (Cancel).
- **Giám Sát & Đo Lường (Observability):** Hỗ trợ theo dõi tiến độ Real-time qua **SSE** (Server-Sent Events) và cung cấp endpoint `/metrics` cho **Prometheus/Grafana**.
- **Lưu Trữ Tùy Biến (Custom Output):** Đặt tên thư mục thành phẩm theo ý muốn thay vì bị ép buộc dùng UUID.

---

## 📚 Tài Liệu Hướng Dẫn (Documentation)

Hệ thống đi kèm với 2 bộ tài liệu chi tiết (Tiếng Việt) để bạn dễ dàng nắm bắt:

1. 📖 **[Hướng Dẫn Sử Dụng (USAGE_GUIDE.md)](USAGE_GUIDE.md)**: Hướng dẫn cài đặt cấu hình `.env`, chạy qua Local CLI, khởi động Server và giải thích các Payload.
2. 📡 **[Tài Liệu API (API_REFERENCE.md)](API_REFERENCE.md)**: Chứa toàn bộ các endpoints, Request/Response mẫu, mã lỗi HTTP và ví dụ dùng cURL/JavaScript.

---

## 🚀 Các Luồng Xử Lý (Pipelines)

Hệ thống có sẵn các "dây chuyền" sản xuất video độc lập:

- **`dubbing`:** Lồng tiếng tiêu chuẩn (Bóc băng → Dịch → Đọc AI → Khớp khẩu hình).
- **`multilang_dubbing`:** Tạo cùng lúc nhiều Job lồng tiếng ra nhiều thứ tiếng khác nhau (Fan-out).
- **`subtitle`:** Chỉ tạo phụ đề `.srt` hoặc đóng cứng (burn) lên video.
- **`audio_extract`:** Trích xuất và cân bằng âm lượng (Loudness Normalization) chuyên dùng cho Podcast.
- **`ad_video`:** Dựng video/âm thanh quảng cáo trực tiếp từ ảnh tĩnh + kịch bản text.
- **`low_level`:** Các thao tác video cơ bản (Cắt, ghép, tăng tốc, filter màu, làm mờ, v.v.).

---

## 🧠 Các AI Backends Hỗ Trợ

- **Text-to-Speech (TTS):** 
  - `edge-tts` (Mặc định - Miễn phí)
  - `openai` (Cần `OPENAI_API_KEY`)
  - `google-cloud` (Cần `GOOGLE_CLOUD_TTS_KEY`)
- **Dịch thuật (Translator):**
  - `google` (Mặc định)
  - `deepl` 
  - `libretranslate`
- **Nhận dạng giọng nói (STT):**
  - `Whisper` (Tùy chỉnh model `tiny`, `base`, `large` qua cấu hình).

---

## 🛠️ Triển Khai (Deployment)

### Local (Dev Mode)
Dùng bộ nhớ RAM và ổ cứng máy cá nhân để chạy. Không cần Database.
```env
JOB_BACKEND=memory
ARTIFACT_STORE_BACKEND=local
```

### Production (Supabase)
Sử dụng Supabase làm Database lưu hàng đợi (PostgreSQL) và Storage. An toàn cho môi trường có nhiều máy chủ cùng chạy (Multi-node).
```env
JOB_BACKEND=supabase
ARTIFACT_STORE_BACKEND=supabase
SUPABASE_URL=https://<your-id>.supabase.co
SUPABASE_KEY=<your-service-role-key>
```
> **Lưu ý:** Chạy `python main.py preflight-db` hoặc thực thi file `supabase/schema.sql` vào cơ sở dữ liệu Supabase của bạn trước khi bắt đầu.

---

## 🛡️ Bảo Mật
- Các Endpoint được bảo vệ bằng `X-API-Key`.
- Giao thức nhận dạng đầu vào giới hạn khắt khe qua `API_ALLOWED_INPUT_URI_SCHEMES` (tránh SSRF).
- Tích hợp Rate Limiting và chặn truy cập file hệ thống (`API_ALLOW_INPUT_PATH=false`).

---

*Phát triển bởi đội ngũ Kỹ sư AI Video - Đạt chuẩn mức độ ổn định Production v2.0.*
