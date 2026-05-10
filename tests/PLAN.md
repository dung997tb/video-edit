# Kế Hoạch Nâng Cấp API Và Sửa Các Lỗi Test Video Thật

## Summary
- Giữ API hiện tại `/jobs` và `/jobs/upload`, nhưng chuẩn hóa `payload` để n8n/UI có thể gửi yêu cầu, thông số, vùng thời gian, AI provider, và nhận lại `result_items` rõ ràng trong `job.metadata`.
- Nếu không gửi thông số thì dùng mặc định hiện tại. Nếu có gửi `request`, `time_range`, `operations`, `providers` thì module sẽ chạy theo yêu cầu đó.
- Sửa các lỗi quan sát được: video bị đứng hình khi ghép, mất đoạn đầu video phụ, audio cut nằm sai chỗ, các hiệu ứng quá khó thấy, crop/reframe chưa đủ tùy chỉnh, dubbing/translation audio lỗi hoặc thiếu điều khiển.

## API Changes
- Chuẩn hóa `payload` mới:
  - `request`: mô tả tự nhiên, ví dụ `"cắt highlight đoạn người nói mạnh nhất"`.
  - `time_range`: `{ "start": 5, "end": 20 }` hoặc `{ "start": 5, "duration": 15 }`.
  - `operations`: danh sách item rõ ràng, mỗi item có `id`, `type`, `params`, `time_range`, `inputs`, `output_name`.
  - `providers`: cấu hình AI theo từng job, ví dụ `translation`, `tts`, `highlight`, `vision`.
- Cho phép gửi API key theo từng lần gọi tool/job:
  - Ví dụ `payload.providers.tts.api_key`.
  - Không lưu raw key vào log, metadata, cache, summary.
  - Chỉ lưu dạng đã che như `key_source: "request"` và `api_key_hint: "***abcd"`.
  - Nếu không gửi key thì dùng env/default/local provider hiện có.
- `GET /jobs/{id}` trả thêm:
  - `metadata.result_items`: danh sách artifact cho UI/n8n.
  - Mỗi item có `id`, `operation_id`, `kind`, `label`, `path`, `media_type`, `duration`, `width`, `height`, `language`, `role`, `metadata`.

## Implementation Changes
- Video compose:
  - Sửa `hstack`, `split_screen`, `grid` để không bị đứng hình ngoài ý muốn và không tự mất đoạn đầu.
  - Thêm `duration_mode`: `hold_last` mặc định để giữ tương thích, thêm `loop`, `trim`, `shortest`.
  - Thêm `input_start`, `input_end`, `input_duration` cho từng input.
  - Thêm seam blur cho video ghép: `seam_blur.enabled`, `target`, `start`, `end`, `width`, `strength`.
- Crop/reframe/effects:
  - Thêm crop tự do qua API: tỷ lệ `ratio`, `width`, `height`, `x`, `y`, `anchor`, `safe_area`.
  - `delogo/blur` nhận `x`, `y`, `w`, `h`, `strength`, `mode`, `time_range`.
  - `auto_zoom` nhận timeline custom: số lần zoom, thời gian, tâm zoom, mức zoom, duration.
  - `content_variant`, `random_mirror`, `chromakey`, `convert`, `loop` trả metadata giải thích tác dụng và cảnh báo khi output gần giống input.
  - Sửa `blur_bg_portrait` để foreground không làm filter graph bị freeze khi video gốc đã là 9:16.
- Audio, dubbing, translation:
  - `audio_export/audio_cut` luôn copy artifact cuối vào thư mục output của job.
  - Cho phép extract/cut audio trực tiếp bằng API với `start`, `end`, `duration`, `format`.
  - `split_video` và `extract_frames` nhận `start`, `end`, `count`, hoặc danh sách segment/frame timestamp.
  - Dubbing nhận `original_volume`, `translated_volume`, `ducking`, `voice`, `rate`, `language`, `provider`.
  - Thêm provider adapter cho ElevenLabs TTS và generic HTTP provider cho TTS/translation/highlight nếu user gửi API config.
  - Translation AI có thể nhận transcript/video context, chia câu, trả câu dịch kèm timestamp rồi remux lại.
  - Highlight AI nhận `prompt` + video/transcript/frame metadata, trả một hoặc nhiều time ranges để cắt/ghép highlight.
- B-roll:
  - `auto_broll` nhận item custom qua API: thời gian xuất hiện, vị trí, kích thước, duration, fade, asset hoặc prompt.
  - Nếu không gửi item custom thì vẫn dùng keyword/default hiện tại.

## Test Plan
- Unit test:
  - Parse/validate payload mới.
  - Default behavior khi không gửi request/params.
  - Redact provider API key khỏi logs, metadata, result manifest.
  - Sinh `metadata.result_items` đúng schema.
- API test:
  - `/jobs` với structured `operations`.
  - `/jobs/upload` với video thật và payload có `time_range`.
  - `GET /jobs/{id}` có result items dùng được cho n8n/UI.
- Real video regression:
  - Chạy lại các case lỗi ở `TEST_PLAN_REAL_VIDEO.md`: L88, L93, L96-L102, L105-L106, L151-L153, L160-L162.
  - Kiểm bằng `ffprobe`: duration, audio stream, frame count, resolution.
  - Kiểm visual bằng frame sampling ở nhiều timestamp để phát hiện freeze/still frame.
  - Thêm case dùng source không phải 9:16 để crop/reframe thấy rõ.
  - Thêm case compose với `duration_mode: loop` để xác nhận video phụ không đứng ở 24s.

## Assumptions
- Không tạo endpoint mới nếu chưa cần; mở rộng `/jobs` bằng payload chuẩn là đủ.
- `hold_last` vẫn là mặc định cho compose để tránh phá workflow cũ, nhưng test mới sẽ dùng `loop` hoặc `trim` khi cần output không đứng hình.
- API key gửi kèm mỗi job là hướng phù hợp cho n8n, nhưng phải được redact tuyệt đối khỏi mọi artifact/log.
- Những feature “nhìn giống video gốc” sẽ được giữ lại nếu đúng chức năng, nhưng phải có metadata/cảnh báo rõ để user biết đó là no-op, chuyển format, hoặc hiệu ứng quá nhẹ.
