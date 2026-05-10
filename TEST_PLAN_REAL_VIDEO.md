# TEST PLAN REAL VIDEO - FULL FEATURE INVENTORY

> Cap nhat sau khi quet code ngay 2026-05-08.
> Muc tieu: moi chuc nang duoc test bang mot job rieng, co `output_name` rieng, va voi cac chuc nang video/low-level thi ket qua chinh la mot video rieng trong `output/<output_name>/final.mp4`.

## 1. Nguon quet

Danh sach nay duoc lay tu code that trong:

- `orchestrators/factory.py`: cac pipeline nguoi dung goi truc tiep.
- `modules/video/low_level.py`: cac low-level operation.
- `core/workflow/registry.py`: cac workflow node/noi bo co the goi qua DAG.
- `pipelines/examples/`: cac config mau da co san.

## 2. Tai san test can chuan bi

Dung video that, khong dung video synthetic, neu muon danh gia chat luong thuc:

| Bien | Bat buoc | Mo ta |
|---|---:|---|
| `MAIN_VIDEO` | Co | Video 60-120s, co loi noi ro, co mat nguoi, co vai khoang lang. |
| `AUX_VIDEO` | Co | Video phu 15-60s de test concat, hstack, split_screen, grid, chromakey background. |
| `BROLL_VIDEO` | Co | Clip B-roll ngan, dung cho auto_broll va overlay-like checks. |
| `WATERMARK_IMAGE` | Co | PNG logo nen trong suot, dung cho watermark. |
| `OVERLAY_IMAGE` | Co | PNG/JPG de test overlay. Co the dung chung voi watermark. |
| `GREEN_SCREEN_VIDEO` | Khuyen nghi | Video co nen xanh de test chromakey chat luong that. Neu khong co, test chi xac nhan pipeline render khong crash. |

Quy uoc lenh CLI:

```powershell
$INPUT = "C:\path\to\MAIN_VIDEO.mp4"
python main.py run $INPUT --config-file .\test_runs\real_video_configs\RV_L01_cut.json
```

Moi config phai co:

```json
{
  "pipeline_type": "...",
  "payload": {
    "output_name": "RV_...",
    "...": "..."
  }
}
```

## 3. Nguyen tac ket qua

| Loai chuc nang | Yeu cau output |
|---|---|
| Low-level video operation | Moi operation la 1 job rieng, output `final.mp4` rieng. |
| Low-level audio operation | Moi operation la 1 job rieng, finalizer remux audio vao video goc, output `final.mp4` rieng. |
| Pipeline video | Moi pipeline la 1 job rieng, output `final.mp4` rieng. |
| `multilang-dubbing` | Fan-out tao nhieu child job; moi ngon ngu la 1 video rieng. |
| `split_video` | Tao nhieu video segment; day la dac thu cua chuc nang, khong phai 1 file duy nhat. |
| `audio-extract` | Ban chat tra ve audio. Neu bat buoc video-only, dung nhom low-level audio ops de co video remux; van test `audio-extract` rieng nhu artifact audio. |
| `extract_frames` | Ban chat tra ve anh frame. Neu bat buoc video-only, can them wrapper tao slideshow/video preview tu frames. |

## 4. Danh sach pipeline goi truc tiep

| ID | Pipeline | Alias | Chuc nang | Output chinh | Video-only |
|---|---|---|---|---|---|
| P01 | `dubbing` | | Long tieng AI, dich, TTS, voice sync, remux | Video | Co |
| P02 | `low_level` | | Chay danh sach operation FFmpeg/visual/audio | Video | Co |
| P03 | `subtitle` | `subtitle-only` | Transcript, translate, subtitle, optional burn | Video neu burn, SRT neu khong burn | Co khi `burn_subtitles=true` |
| P04 | `audio-extract` | `audio_extract` | Tach audio tu video | Audio | Khong |
| P05 | `multilang-dubbing` | `multilang_dubbing` | Tao child job dubbing cho nhieu ngon ngu | Nhieu video con | Co, fan-out |
| P06 | `ad_video` | | Tao ad video tu text, TTS, subtitle burn | Video | Co |
| P07 | `workflow` | | Chay DAG JSON tuy bien | Tuy node, co the video | Co neu DAG ket thuc `media.finalize` |
| P08 | `semantic_edit` | | Cat highlight/semantic edit; cung ho tro `command=silence_cut` | Video | Co |
| P09 | `silence_cut` | | Cat khoang lang bang FFmpeg silencedetect | Video | Co |
| P10 | `split_video` | | Cat video thanh cac segment | Nhieu video | Co, nhieu file |
| P11 | `extract_frames` | | Trich frame theo interval | Anh | Khong |
| P12 | `face_track_portrait` | | Reframe doc 9:16 theo face/center fallback | Video | Co |
| P13 | `auto_broll` | | Chen B-roll theo keyword transcript | Video | Co |

## 5. Danh sach 35 low-level operation

| ID | Operation | Nhom | Chuc nang |
|---|---|---|---|
| L01 | `cut` | Video | Cat doan theo start/end/duration. |
| L02 | `speed` | Video+Audio | Tang/giam toc video va audio. |
| L03 | `flip` | Video | Lat ngang/doc/ca hai. |
| L04 | `crop` | Video | Cat khung theo width/height/x/y. |
| L05 | `rotate` | Video | Xoay theo do. |
| L06 | `scale` | Video | Doi kich thuoc/resolution. |
| L07 | `concat` | Video | Noi video hien tai voi input khac. |
| L08 | `overlay` | Video | Chen anh/video overlay len video. |
| L09 | `watermark` | Video | Chen logo watermark voi opacity. |
| L10 | `denoise` | Video | Khu nhieu bang hqdn3d. |
| L11 | `color_grade` | Video | Chinh brightness/contrast/saturation/gamma. |
| L12 | `pad_border` | Video | Them vien mau quanh video. |
| L13 | `blur_bg_portrait` | Video | Tao video doc 9:16 voi nen mo. |
| L14 | `loop` | Video | Lap video N lan bang concat demuxer. |
| L15 | `filter_duration` | Guard | Kiem tra duration min/max, sau do export video goc. |
| L16 | `delogo` | Video | Blur/delogo mot vung. |
| L17 | `content_variant` | Video+Audio | Tao bien the nhe: grain, hue, saturation, speed/pitch. |
| L18 | `hstack` | Multi-input | Ghép hai video ngang/doc. |
| L19 | `split_screen` | Multi-input | Chia man hinh doc TikTok. |
| L20 | `chromakey` | Multi-input | Key nen xanh va overlay len background. |
| L21 | `grid` | Multi-input | Ghép nhieu video thanh luoi. |
| L22 | `convert` | Format | Doi dinh dang. Test video-only dung `output_format=mp4`. |
| L23 | `random_mirror` | Video | Lat guong ngau nhien theo segment. |
| L24 | `platform_reframe` | Video | Reframe theo preset 9:16, 1:1, 16:9. |
| L25 | `auto_zoom` | Video | Zoom nhe theo chu ky. |
| L26 | `audio_trim` | Audio | Cat audio roi remux vao video. |
| L27 | `audio_speed` | Audio | Doi toc do audio roi remux vao video. |
| L28 | `audio_volume` | Audio | Doi am luong roi remux vao video. |
| L29 | `audio_fade` | Audio | Fade in/out roi remux vao video. |
| L30 | `audio_normalize` | Audio | Loudness normalize roi remux vao video. |
| L31 | `audio_pitch` | Audio | Doi cao do roi remux vao video. |
| L32 | `visual_blur` | Visual | Lam mo hinh. |
| L33 | `visual_sharpen` | Visual | Lam net hinh. |
| L34 | `visual_grayscale` | Visual | Chuyen trang den. |
| L35 | `visual_vignette` | Visual | Tao vignette toi goc. |

## 6. Workflow/internal node co the goi qua `workflow`

Cac node nay khong phai pipeline public rieng, nhung co the xuat hien trong DAG:

| Node type | Module | Cach test chinh |
|---|---|---|
| `ai.transcribe` | Transcript | Qua `dubbing`, `subtitle`, `auto_broll`, hoac DAG P07. |
| `ai.translate` | Translate | Qua `dubbing`, `subtitle`, hoac DAG P07. |
| `ai.segment` | Segmenter | Qua `dubbing`, `subtitle`. |
| `ai.semantic_edit` | Semantic edit | Qua `semantic_edit`. |
| `ai.subtitle` | Subtitle SRT | Qua `subtitle`. |
| `ai.karaoke_subtitle` | Karaoke subtitle | Qua `subtitle` voi `subtitle_style=karaoke`. |
| `ai.subtitle_export` | Subtitle export | Qua `subtitle`. |
| `ai.tts` | Text-to-speech | Qua `dubbing`, `ad_video`. |
| `ai.voice_sync` | Voice sync | Qua `dubbing`, `ad_video`. |
| `ai.voice_sync_retry` | Voice sync retry | Qua `dubbing`. |
| `ai.audio_mixer` | Audio mix/ducking | Qua `dubbing`. |
| `ai.multilang_fanout` | Fanout child jobs | Qua `multilang-dubbing`. |
| `ai.silence_remover` | Silence cut | Qua `silence_cut`. |
| `ai.face_tracker` | Face track portrait | Qua `face_track_portrait`. |
| `ai.broll_injector` | Auto B-roll | Qua `auto_broll`. |
| `audio.extract`, `media.extract_audio` | Extract audio | Qua `audio-extract`, `dubbing`, `subtitle`. |
| `audio.export` | Export audio artifact | Qua `audio-extract`. |
| `media.subtitle_burn` | Burn subtitle | Qua `subtitle`/`dubbing` khi burn enabled. |
| `media.remux_audio` | Remux final audio/video | Qua `dubbing`, `ad_video`. |
| `media.finalize` | Export final video | Qua `low_level` hoac DAG P07. |
| `media.<operation>`, `video.<operation>` | Low-level operation aliases | Qua `workflow` DAG hoac `low_level`. |

## 7. Test plan pipeline video thuc te

Tat ca test case duoi day la job rieng. Moi `output_name` rieng.

| ID | Pipeline | Config payload chinh | Output ky vong |
|---|---|---|---|
| RV_P01 | `dubbing` | `output_name=RV_P01_dubbing_vi`, `target_language=vi`, `source_language=auto`, `burn_subtitles=false` | `output/RV_P01_dubbing_vi/final.mp4` co voice AI moi. |
| RV_P02 | `dubbing` | `output_name=RV_P02_dubbing_burned`, `target_language=vi`, `burn_subtitles=true` | Video dubbing co subtitle burn. |
| RV_P03 | `subtitle` | `output_name=RV_P03_subtitle_burned`, `target_language=vi`, `burn_subtitles=true` | Video co subtitle hardcoded. |
| RV_P04 | `subtitle` | `output_name=RV_P04_subtitle_karaoke`, `subtitle_style=karaoke`, `burn_subtitles=true` | Video subtitle karaoke. |
| RV_P05 | `silence_cut` | `output_name=RV_P05_silence_cut`, `min_silence_duration=0.5`, `silence_threshold_db=-35` | Video ngan hon neu co khoang lang. |
| RV_P06 | `semantic_edit` | `output_name=RV_P06_semantic_edit`, `command=make_tiktok_short`, `target_duration=30` | Video highlight/cut ngan. |
| RV_P07 | `semantic_edit` | `output_name=RV_P07_semantic_silence_cut`, `command=silence_cut` | Video da cat silence qua semantic route. |
| RV_P08 | `face_track_portrait` | `output_name=RV_P08_face_track_portrait`, `output_width=1080`, `output_height=1920` | Video doc 9:16. |
| RV_P09 | `auto_broll` | `output_name=RV_P09_auto_broll`, `keyword_map={"<tu_trong_video>":"BROLL_VIDEO"}` | Video co B-roll overlay khi match keyword. |
| RV_P10 | `ad_video` | `output_name=RV_P10_ad_video`, `ad_text="..."`, `tts_voice=vi-VN-HoaiMyNeural` | Video co TTS ad + subtitle burn. |
| RV_P11 | `workflow` | DAG: `video.pad_border` -> `media.finalize`, `output_name=RV_P11_workflow_dag` | Video chung minh DAG chay duoc. |
| RV_P12 | `multilang-dubbing` | `output_name=RV_P12_multilang`, `target_languages=["vi","ja","ko"]` | 3 child job, moi ngon ngu mot video. |
| RV_P13 | `split_video` | `output_name=RV_P13_split_video`, `segment_seconds=30` | Nhieu segment `.mp4`. |
| RV_P14 | `audio-extract` | `output_name=RV_P14_audio_extract`, `sample_rate=44100` | Audio artifact; khong video by design. |
| RV_P15 | `extract_frames` | `output_name=RV_P15_extract_frames`, `interval_seconds=5` | Anh frame; khong video by design. |

## 8. Test plan low-level: moi operation mot video rieng

Moi config co dang:

```json
{
  "pipeline_type": "low_level",
  "payload": {
    "output_name": "RV_Lxx_<operation>",
    "operations": [
      { "name": "<operation>", "...": "..." }
    ]
  }
}
```

| ID | Operation | Payload operation de test | Output video |
|---|---|---|---|
| RV_L01 | `cut` | `{ "name":"cut", "start":0, "end":15 }` | `output/RV_L01_cut/final.mp4` |
| RV_L02 | `speed` | `{ "name":"speed", "factor":1.25 }` | `output/RV_L02_speed/final.mp4` |
| RV_L03 | `flip` | `{ "name":"flip", "mode":"horizontal" }` | `output/RV_L03_flip/final.mp4` |
| RV_L04 | `crop` | `{ "name":"crop", "width":960, "height":540, "x":0, "y":0 }` | `output/RV_L04_crop/final.mp4` |
| RV_L05 | `rotate` | `{ "name":"rotate", "degrees":8 }` | `output/RV_L05_rotate/final.mp4` |
| RV_L06 | `scale` | `{ "name":"scale", "width":1280, "height":720 }` | `output/RV_L06_scale/final.mp4` |
| RV_L07 | `concat` | `{ "name":"concat", "inputs":["AUX_VIDEO"], "include_current":true }` | `output/RV_L07_concat/final.mp4` |
| RV_L08 | `overlay` | `{ "name":"overlay", "overlay_path":"OVERLAY_IMAGE", "x":30, "y":30, "overlay_width":240 }` | `output/RV_L08_overlay/final.mp4` |
| RV_L09 | `watermark` | `{ "name":"watermark", "watermark_path":"WATERMARK_IMAGE", "x":32, "y":32, "opacity":0.7 }` | `output/RV_L09_watermark/final.mp4` |
| RV_L10 | `denoise` | `{ "name":"denoise", "luma_spatial":4, "chroma_spatial":3 }` | `output/RV_L10_denoise/final.mp4` |
| RV_L11 | `color_grade` | `{ "name":"color_grade", "brightness":0.05, "contrast":1.1, "saturation":1.15 }` | `output/RV_L11_color_grade/final.mp4` |
| RV_L12 | `pad_border` | `{ "name":"pad_border", "size":30, "color":"white" }` | `output/RV_L12_pad_border/final.mp4` |
| RV_L13 | `blur_bg_portrait` | `{ "name":"blur_bg_portrait", "output_width":1080, "output_height":1920 }` | `output/RV_L13_blur_bg_portrait/final.mp4` |
| RV_L14 | `loop` | `{ "name":"loop", "times":2 }` | `output/RV_L14_loop/final.mp4` |
| RV_L15 | `filter_duration` | `{ "name":"filter_duration", "min_seconds":1, "max_seconds":600 }` | `output/RV_L15_filter_duration/final.mp4` |
| RV_L16 | `delogo` | `{ "name":"delogo", "x":0, "y":0, "w":200, "h":80, "mode":"blur" }` | `output/RV_L16_delogo/final.mp4` |
| RV_L17 | `content_variant` | `{ "name":"content_variant", "grain":3, "hue_shift":2.0, "sat_factor":1.02 }` | `output/RV_L17_content_variant/final.mp4` |
| RV_L18 | `hstack` | `{ "name":"hstack", "second_video":"AUX_VIDEO", "layout":"horizontal" }` | `output/RV_L18_hstack/final.mp4` |
| RV_L19 | `split_screen` | `{ "name":"split_screen", "b_roll_video":"AUX_VIDEO", "audio_source":"mix" }` | `output/RV_L19_split_screen/final.mp4` |
| RV_L20 | `chromakey` | `{ "name":"chromakey", "background_video":"AUX_VIDEO", "color":"#00FF00", "similarity":0.3, "blend":0.1 }` | `output/RV_L20_chromakey/final.mp4` |
| RV_L21 | `grid` | `{ "name":"grid", "videos":["AUX_VIDEO","AUX_VIDEO","AUX_VIDEO"], "cols":2, "rows":2 }` | `output/RV_L21_grid/final.mp4` |
| RV_L22 | `convert` | `{ "name":"convert", "output_format":"mp4" }` | `output/RV_L22_convert/final.mp4` |
| RV_L23 | `random_mirror` | `{ "name":"random_mirror", "flip_probability":0.4, "segment_duration":3.0, "seed":42 }` | `output/RV_L23_random_mirror/final.mp4` |
| RV_L24 | `platform_reframe` | `{ "name":"platform_reframe", "preset":"9:16" }` | `output/RV_L24_platform_reframe/final.mp4` |
| RV_L25 | `auto_zoom` | `{ "name":"auto_zoom", "interval_seconds":4, "zoom_factor":1.1 }` | `output/RV_L25_auto_zoom/final.mp4` |
| RV_L26 | `audio_trim` | `{ "name":"audio_trim", "start":0, "duration":10 }` | `output/RV_L26_audio_trim/final.mp4` |
| RV_L27 | `audio_speed` | `{ "name":"audio_speed", "factor":1.15 }` | `output/RV_L27_audio_speed/final.mp4` |
| RV_L28 | `audio_volume` | `{ "name":"audio_volume", "volume":0.6 }` | `output/RV_L28_audio_volume/final.mp4` |
| RV_L29 | `audio_fade` | `{ "name":"audio_fade", "type":"in", "duration":1.0 }` | `output/RV_L29_audio_fade/final.mp4` |
| RV_L30 | `audio_normalize` | `{ "name":"audio_normalize", "i":-16, "tp":-1.5, "lra":11 }` | `output/RV_L30_audio_normalize/final.mp4` |
| RV_L31 | `audio_pitch` | `{ "name":"audio_pitch", "semitones":2, "preserve_tempo":true }` | `output/RV_L31_audio_pitch/final.mp4` |
| RV_L32 | `visual_blur` | `{ "name":"visual_blur", "luma_radius":3, "luma_power":1 }` | `output/RV_L32_visual_blur/final.mp4` |
| RV_L33 | `visual_sharpen` | `{ "name":"visual_sharpen", "luma_msize_x":5, "luma_msize_y":5, "luma_amount":1.2 }` | `output/RV_L33_visual_sharpen/final.mp4` |
| RV_L34 | `visual_grayscale` | `{ "name":"visual_grayscale" }` | `output/RV_L34_visual_grayscale/final.mp4` |
| RV_L35 | `visual_vignette` | `{ "name":"visual_vignette", "angle":"PI/5" }` | `output/RV_L35_visual_vignette/final.mp4` |

## 9. Acceptance checklist cho moi video output

Moi test case video phai dat:

- [ ] Job thoat ma loi 0 khi chay CLI hoac status `done` khi chay API.
- [ ] Output path ton tai trong dung folder `output/<output_name>/`.
- [ ] File video mo duoc bang VLC/ffprobe.
- [ ] Duration hop ly so voi feature: cut ngan hon, loop dai hon, speed thay doi duration, filter_duration giu nguyen.
- [ ] Video stream khong bi den/toan mau loi.
- [ ] Audio stream van ton tai voi cac feature khong co y dinh xoa audio.
- [ ] Feature co dau hieu hieu ung ro: border, blur, crop, watermark, portrait, subtitle, v.v.

Lenh ffprobe goi y:

```powershell
ffprobe -v error -show_entries format=duration -show_streams output\RV_L01_cut\final.mp4
```

## 10. Thu tu chay de giam rui ro

1. Chay nhom low-level don gian: L01-L06, L10-L17, L22-L25, L32-L35.
2. Chay nhom audio remux: L26-L31.
3. Chay nhom multi-input can asset phu: L07-L09, L18-L21.
4. Chay pipeline video nhe: P05, P06, P08, P11.
5. Chay pipeline AI nang: P01-P04, P09-P10.
6. Chay fanout/artifact: P12-P15.

## 11. Bang tong hop so luong

| Nhom | So luong | Video rieng bat buoc |
|---|---:|---:|
| Public pipeline/orchestrator | 13 | 10 video cases + 1 fanout multi-video + 2 artifact-only |
| Low-level operation | 35 | 35 video cases |
| Workflow/internal node | 20+ | Test gian tiep qua pipeline/DAG |

Tong video-output test toi thieu:

- 35 video low-level.
- 10 video pipeline truc tiep.
- 3 video child cho multilang fanout neu test `vi`, `ja`, `ko`.
- Nhieu segment video cho `split_video`.

Tong artifact-only can ghi nhan rieng:

- `audio-extract`: audio file.
- `extract_frames`: image frames.

## 12. Ghi chu quan trong

- `low_level` dung field `payload.operations`, khong dung `payload.operation`.
- De moi chuc nang co video rieng, khong gom nhieu operation vao mot config khi test coverage tung feature.
- `chromakey` can video foreground co nen xanh de danh gia chat luong that; neu dung video binh thuong, chi test duoc viec pipeline render.
- `auto_broll` can `keyword_map` co keyword xuat hien trong transcript. Neu khong match keyword, output se la ban copy cua video goc.
- `audio-extract` va `extract_frames` khong the ep thanh mot video rieng ma khong them wrapper moi, vi day la dung thiet ke hien tai cua codebase.
