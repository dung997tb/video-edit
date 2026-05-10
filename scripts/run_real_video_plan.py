from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS_FFMPEG = ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1-essentials_build" / "bin" / "ffmpeg.exe"
TOOLS_FFPROBE = ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1-essentials_build" / "bin" / "ffprobe.exe"


def _resolve_tool(env_name: str, binary_name: str, bundled: Path) -> Path:
    from_path = os.environ.get(env_name)
    candidates = []
    if from_path:
        candidates.append(Path(from_path))
    candidates.append(bundled)
    found = shutil.which(binary_name)
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"{binary_name} not found. Set {env_name} or install tools/ffmpeg.")


FFMPEG = _resolve_tool("FFMPEG_PATH", "ffmpeg", TOOLS_FFMPEG)
FFPROBE = _resolve_tool("FFPROBE_PATH", "ffprobe", TOOLS_FFPROBE)
os.environ.setdefault("FFMPEG_PATH", str(FFMPEG))
os.environ.setdefault("FFPROBE_PATH", str(FFPROBE))

sys.path.insert(0, str(ROOT))

from config import settings as default_settings  # noqa: E402
from core.cache import hash_file  # noqa: E402
from core.models import JobStatus  # noqa: E402
from core.pipeline import PipelineRunner  # noqa: E402
from core.runtime import build_services  # noqa: E402


@dataclass
class Case:
    id: str
    pipeline_type: str
    payload: dict[str, Any]
    expected: str = "video"
    input_path: str | None = None


@dataclass
class CaseResult:
    id: str
    pipeline_type: str
    output_name: str
    status: str
    elapsed_seconds: float
    output_path: str | None = None
    output_exists: bool = False
    verification: str = "not_checked"
    duration: float | None = None
    has_video: bool | None = None
    has_audio: bool | None = None
    artifact_count: int | None = None
    child_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def run_command(command: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=True,
    )


def ffprobe_json(path: str | Path) -> dict[str, Any]:
    result = run_command(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_streams",
            "-of",
            "json",
            path,
        ],
        timeout=60,
    )
    return json.loads(result.stdout or "{}")


def video_info(path: str | Path) -> tuple[float | None, bool, bool]:
    payload = ffprobe_json(path)
    streams = payload.get("streams", [])
    duration = payload.get("format", {}).get("duration")
    return (
        float(duration) if duration not in (None, "N/A") else None,
        any(stream.get("codec_type") == "video" for stream in streams),
        any(stream.get("codec_type") == "audio" for stream in streams),
    )


def _ffmpeg_asset(command: list[str]) -> None:
    run_command([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *command], timeout=120)


def prepare_assets(input_path: Path) -> dict[str, str]:
    asset_dir = ROOT / "test_runs" / "real_video_assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    aux_video = asset_dir / "aux_from_test.mp4"
    broll_video = asset_dir / "broll_from_test.mp4"
    overlay_image = asset_dir / "overlay_frame.jpg"
    watermark_image = asset_dir / "watermark.png"

    _ffmpeg_asset(["-ss", "5", "-i", input_path, "-t", "25", "-c", "copy", aux_video])
    _ffmpeg_asset(["-ss", "15", "-i", input_path, "-t", "8", "-c", "copy", broll_video])
    _ffmpeg_asset(["-ss", "1", "-i", input_path, "-frames:v", "1", "-vf", "scale=320:-1", overlay_image])
    _ffmpeg_asset(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=white@0.0:s=320x120:d=1",
            "-vf",
            "format=rgba,drawbox=x=0:y=0:w=320:h=120:color=0x1A73E8@0.75:t=fill,drawbox=x=14:y=14:w=292:h=92:color=white@0.35:t=4",
            "-frames:v",
            "1",
            watermark_image,
        ]
    )

    return {
        "MAIN_VIDEO": str(input_path),
        "AUX_VIDEO": str(aux_video),
        "BROLL_VIDEO": str(broll_video),
        "OVERLAY_IMAGE": str(overlay_image),
        "WATERMARK_IMAGE": str(watermark_image),
    }


def even_at_most(value: int, maximum: int) -> int:
    value = max(2, min(value, maximum))
    return value if value % 2 == 0 else value - 1


def build_cases(assets: dict[str, str], probe: dict[str, Any]) -> list[Case]:
    main = assets["MAIN_VIDEO"]
    aux = assets["AUX_VIDEO"]
    broll = assets["BROLL_VIDEO"]
    overlay = assets["OVERLAY_IMAGE"]
    watermark = assets["WATERMARK_IMAGE"]

    video_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), {})
    width = int(video_stream.get("width") or 480)
    height = int(video_stream.get("height") or 854)
    crop_w = even_at_most(width, 960)
    crop_h = even_at_most(height, 540)

    low_level_ops = [
        ("RV_L01", "cut", {"start": 0, "end": 15}),
        ("RV_L02", "speed", {"factor": 1.25}),
        ("RV_L03", "flip", {"mode": "horizontal"}),
        ("RV_L04", "crop", {"width": crop_w, "height": crop_h, "x": 0, "y": 0}),
        ("RV_L05", "rotate", {"degrees": 8}),
        ("RV_L06", "scale", {"width": 1280, "height": 720}),
        ("RV_L07", "concat", {"inputs": [aux], "include_current": True}),
        ("RV_L08", "overlay", {"overlay_path": overlay, "x": 30, "y": 30, "overlay_width": 240}),
        ("RV_L09", "watermark", {"watermark_path": watermark, "x": 32, "y": 32, "opacity": 0.7}),
        ("RV_L10", "denoise", {"luma_spatial": 4, "chroma_spatial": 3}),
        ("RV_L11", "color_grade", {"brightness": 0.05, "contrast": 1.1, "saturation": 1.15}),
        ("RV_L12", "pad_border", {"size": 30, "color": "white"}),
        ("RV_L13", "blur_bg_portrait", {"output_width": 1080, "output_height": 1920}),
        ("RV_L14", "loop", {"times": 2}),
        ("RV_L15", "filter_duration", {"min_seconds": 1, "max_seconds": 600}),
        ("RV_L16", "delogo", {"x": 0, "y": 0, "w": min(200, width), "h": min(80, height), "mode": "blur"}),
        ("RV_L17", "content_variant", {"grain": 3, "hue_shift": 2.0, "sat_factor": 1.02}),
        ("RV_L18", "hstack", {"second_video": aux, "layout": "horizontal"}),
        ("RV_L19", "split_screen", {"b_roll_video": aux, "audio_source": "mix"}),
        ("RV_L20", "chromakey", {"background_video": aux, "color": "#00FF00", "similarity": 0.3, "blend": 0.1}),
        ("RV_L21", "grid", {"videos": [aux, aux, aux], "cols": 2, "rows": 2}),
        ("RV_L22", "convert", {"output_format": "mp4"}),
        ("RV_L23", "random_mirror", {"flip_probability": 0.4, "segment_duration": 3.0, "seed": 42}),
        ("RV_L24", "platform_reframe", {"preset": "9:16"}),
        ("RV_L25", "auto_zoom", {"interval_seconds": 4, "zoom_factor": 1.1, "output_width": width, "output_height": height}),
        ("RV_L26", "audio_trim", {"start": 0, "duration": 10}),
        ("RV_L27", "audio_speed", {"factor": 1.15}),
        ("RV_L28", "audio_volume", {"volume": 0.6}),
        ("RV_L29", "audio_fade", {"type": "in", "duration": 1.0}),
        ("RV_L30", "audio_normalize", {"i": -16, "tp": -1.5, "lra": 11}),
        ("RV_L31", "audio_pitch", {"semitones": 2, "preserve_tempo": True}),
        ("RV_L32", "visual_blur", {"luma_radius": 3, "luma_power": 1}),
        ("RV_L33", "visual_sharpen", {"luma_msize_x": 5, "luma_msize_y": 5, "luma_amount": 1.2}),
        ("RV_L34", "visual_grayscale", {}),
        ("RV_L35", "visual_vignette", {"angle": "PI/5"}),
    ]

    cases = [
        Case(
            id=case_id,
            pipeline_type="low_level",
            payload={
                "output_name": f"{case_id}_{op_name}",
                "operations": [{"name": op_name, **params}],
                "cache_bust": True,
            },
        )
        for case_id, op_name, params in low_level_ops
    ]

    cases.extend(
        [
            Case(
                "RV_P01",
                "dubbing",
                {
                    "output_name": "RV_P01_dubbing_vi",
                    "target_language": "vi",
                    "source_language": "auto",
                    "burn_subtitles": False,
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P02",
                "dubbing",
                {
                    "output_name": "RV_P02_dubbing_burned",
                    "target_language": "vi",
                    "source_language": "auto",
                    "burn_subtitles": True,
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P03",
                "subtitle",
                {
                    "output_name": "RV_P03_subtitle_burned",
                    "target_language": "vi",
                    "source_language": "auto",
                    "burn_subtitles": True,
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P04",
                "subtitle",
                {
                    "output_name": "RV_P04_subtitle_karaoke",
                    "target_language": "vi",
                    "source_language": "auto",
                    "subtitle_style": "karaoke",
                    "burn_subtitles": True,
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P05",
                "silence_cut",
                {
                    "output_name": "RV_P05_silence_cut",
                    "min_silence_duration": 0.5,
                    "silence_threshold_db": -35,
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P06",
                "semantic_edit",
                {
                    "output_name": "RV_P06_semantic_edit",
                    "command": "make_tiktok_short",
                    "target_duration": 30,
                    "source_language": "auto",
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P07",
                "semantic_edit",
                {
                    "output_name": "RV_P07_semantic_silence_cut",
                    "command": "silence_cut",
                    "min_silence_duration": 0.5,
                    "silence_threshold_db": -35,
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P08",
                "face_track_portrait",
                {"output_name": "RV_P08_face_track_portrait", "output_width": 1080, "output_height": 1920, "cache_bust": True},
            ),
            Case(
                "RV_P09",
                "auto_broll",
                {
                    "output_name": "RV_P09_auto_broll",
                    "source_language": "auto",
                    "keyword_map": {"": broll},
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P10",
                "ad_video",
                {
                    "output_name": "RV_P10_ad_video",
                    "ad_text": "Day la video quang cao thu nghiem cho bo test real video.",
                    "tts_voice": "vi-VN-HoaiMyNeural",
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P11",
                "workflow",
                {
                    "output_name": "RV_P11_workflow_dag",
                    "workflow": {
                        "nodes": {
                            "border": {
                                "type": "video.pad_border",
                                "params": {"size": 12, "color": "white"},
                            },
                            "export": {
                                "type": "media.finalize",
                                "depends_on": ["border"],
                            },
                        }
                    },
                    "cache_bust": True,
                },
            ),
            Case(
                "RV_P12",
                "multilang-dubbing",
                {
                    "output_name": "RV_P12_multilang",
                    "source_language": "auto",
                    "target_languages": ["vi", "ja", "ko"],
                    "segment_retry_on_overflow": False,
                    "cache_bust": True,
                },
                expected="fanout",
            ),
            Case(
                "RV_P13",
                "split_video",
                {"output_name": "RV_P13_split_video", "segment_seconds": 30, "cache_bust": True},
                expected="segments",
            ),
            Case(
                "RV_P14",
                "audio-extract",
                {"output_name": "RV_P14_audio_extract", "sample_rate": 44100, "cache_bust": True},
                expected="audio",
            ),
            Case(
                "RV_P15",
                "extract_frames",
                {"output_name": "RV_P15_extract_frames", "interval_seconds": 5, "cache_bust": True},
                expected="frames",
            ),
        ]
    )
    return cases


def save_configs(cases: list[Case]) -> Path:
    config_dir = ROOT / "test_runs" / "real_video_configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        output_name = str(case.payload.get("output_name", case.id))
        path = config_dir / f"{output_name}.json"
        path.write_text(
            json.dumps({"pipeline_type": case.pipeline_type, "payload": case.payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return config_dir


def make_services():
    return build_services(
        default_settings.with_overrides(
            job_backend="memory",
            artifact_store_backend="local",
            ffmpeg_path=str(FFMPEG),
            ffprobe_path=str(FFPROBE),
            output_dir=ROOT / "output",
            temp_dir=ROOT / "temp",
            cache_dir=ROOT / "cache",
            tts_parallel_workers=1,
        )
    )


def _output_path_for(output_name: str, expected: str) -> Path:
    base = ROOT / "output" / output_name
    if expected == "segments":
        return base / "segments"
    if expected == "frames":
        return base / "frames"
    return base / "final.mp4"


def verify_result(case: Case, context_output: str | None, started_at: float) -> tuple[str, str | None, bool, float | None, bool | None, bool | None, int | None]:
    output_name = str(case.payload.get("output_name", case.id))
    expected_path = _output_path_for(output_name, case.expected)

    if case.expected == "audio":
        if not context_output:
            return ("missing_audio_path", None, False, None, None, None, None)
        path = Path(context_output)
        exists = path.exists() and path.stat().st_mtime >= started_at - 2
        return ("ok" if exists else "missing_or_stale_audio", str(path), exists, None, None, None, 1 if exists else 0)

    if case.expected == "frames":
        frames = sorted(expected_path.glob("frame_*.jpg")) if expected_path.exists() else []
        fresh = [item for item in frames if item.stat().st_mtime >= started_at - 2]
        return (
            "ok" if fresh else "missing_or_stale_frames",
            str(expected_path),
            bool(fresh),
            None,
            None,
            None,
            len(fresh),
        )

    if case.expected == "segments":
        segments = sorted(expected_path.glob("segment_*.mp4")) if expected_path.exists() else []
        fresh = [item for item in segments if item.stat().st_mtime >= started_at - 2]
        if not fresh:
            return ("missing_or_stale_segments", str(expected_path), False, None, None, None, 0)
        bad = []
        for segment in fresh:
            try:
                _, has_video, _ = video_info(segment)
                if not has_video:
                    bad.append(str(segment))
            except Exception:
                bad.append(str(segment))
        return ("ok" if not bad else "bad_segment_video", str(expected_path), not bad, None, None, None, len(fresh))

    path = Path(context_output) if context_output else expected_path
    exists = path.exists() and path.stat().st_mtime >= started_at - 2
    if not exists:
        return ("missing_or_stale_video", str(path), False, None, None, None, None)
    try:
        duration, has_video, has_audio = video_info(path)
    except Exception as exc:
        return (f"ffprobe_failed: {exc}", str(path), True, None, None, None, None)
    if not has_video:
        return ("no_video_stream", str(path), True, duration, has_video, has_audio, None)
    return ("ok", str(path), True, duration, has_video, has_audio, None)


class RealVideoRunner:
    def __init__(self, input_path: Path) -> None:
        self.input_path = input_path
        self.services = make_services()
        self.pipeline_runner = PipelineRunner(self.services)
        self.source_sha256 = hash_file(input_path)

    def run_case(self, case: Case) -> CaseResult:
        output_name = str(case.payload.get("output_name", case.id))
        print(f"[{case.id}] {case.pipeline_type} -> {output_name}", flush=True)
        started = time.time()
        job = self.services.job_manager.create_job(
            pipeline_type=case.pipeline_type,
            source_sha256=self.source_sha256,
            payload=dict(case.payload),
            input_path=case.input_path or str(self.input_path),
        )
        context_output: str | None = None
        error = None
        status = "failed"
        child_results: list[dict[str, Any]] = []
        try:
            context = self.pipeline_runner.run_job(job)
            context_output = context.output_video
            status = "done"
            if case.expected == "fanout":
                child_results = self.run_pending_children(parent_job_id=job.id)
        except Exception as exc:
            error = str(exc)
            error = error[:4000]
            traceback.print_exc()
        elapsed = time.time() - started

        if case.expected == "fanout" and status == "done":
            unique_outputs = {item.get("output_path") for item in child_results if item.get("status") == "done"}
            child_status = "ok" if len(child_results) == 3 and len(unique_outputs) == 3 else "fanout_children_incomplete_or_not_unique"
            return CaseResult(
                id=case.id,
                pipeline_type=case.pipeline_type,
                output_name=output_name,
                status=status,
                elapsed_seconds=elapsed,
                output_path=context_output,
                output_exists=child_status == "ok",
                verification=child_status,
                artifact_count=len(child_results),
                child_results=child_results,
                error=error,
            )

        verification, output_path, exists, duration, has_video, has_audio, artifact_count = verify_result(case, context_output, started)
        if status == "done" and verification != "ok":
            status = "failed"
        return CaseResult(
            id=case.id,
            pipeline_type=case.pipeline_type,
            output_name=output_name,
            status=status,
            elapsed_seconds=elapsed,
            output_path=output_path,
            output_exists=exists,
            verification=verification,
            duration=duration,
            has_video=has_video,
            has_audio=has_audio,
            artifact_count=artifact_count,
            child_results=child_results,
            error=error,
        )

    def run_pending_children(self, *, parent_job_id: str) -> list[dict[str, Any]]:
        pending = [
            job
            for job in self.services.job_manager.list_jobs(status=JobStatus.PENDING, limit=100)
            if job.payload.get("parent_job_id") == parent_job_id
        ]
        results = []
        for child in pending:
            started = time.time()
            language = child.payload.get("target_language")
            print(f"  [child {language}] dubbing -> {child.payload.get('output_name')}", flush=True)
            error = None
            context_output = None
            status = "failed"
            try:
                context = self.pipeline_runner.run_job(child)
                context_output = context.output_video
                status = "done"
            except Exception as exc:
                error = str(exc)[:4000]
                traceback.print_exc()
            output_name = str(child.payload.get("output_name", child.id))
            expected_path = ROOT / "output" / output_name / "final.mp4"
            output_path = Path(context_output) if context_output else expected_path
            exists = output_path.exists() and output_path.stat().st_mtime >= started - 2
            duration = None
            has_video = None
            has_audio = None
            if exists:
                try:
                    duration, has_video, has_audio = video_info(output_path)
                except Exception:
                    pass
            results.append(
                {
                    "job_id": child.id,
                    "language": language,
                    "status": status,
                    "output_name": output_name,
                    "output_path": str(output_path),
                    "output_exists": exists,
                    "duration": duration,
                    "has_video": has_video,
                    "has_audio": has_audio,
                    "error": error,
                }
            )
        return results


def write_reports(
    results: list[CaseResult],
    *,
    input_path: Path,
    config_dir: Path,
    assets: dict[str, str],
    report_prefix: str | None = None,
) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT / "test_runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    prefix = report_prefix or f"real_video_results_{stamp}"
    json_path = report_dir / f"{prefix}.json"
    md_path = report_dir / f"{prefix}.md"
    payload = {
        "input_path": str(input_path),
        "ffmpeg": str(FFMPEG),
        "ffprobe": str(FFPROBE),
        "config_dir": str(config_dir),
        "assets": assets,
        "summary": {
            "total": len(results),
            "done": sum(1 for item in results if item.status == "done" and item.verification == "ok"),
            "failed": sum(1 for item in results if item.status != "done" or item.verification != "ok"),
        },
        "results": [asdict(item) for item in results],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Real Video Test Results",
        "",
        f"- Input: `{input_path}`",
        f"- Configs: `{config_dir}`",
        f"- Passed: {payload['summary']['done']}/{payload['summary']['total']}",
        "",
        "| ID | Pipeline | Status | Verification | Output |",
        "|---|---|---|---|---|",
    ]
    for item in results:
        output = item.output_path or ""
        lines.append(f"| {item.id} | {item.pipeline_type} | {item.status} | {item.verification} | `{output}` |")
    failures = [item for item in results if item.status != "done" or item.verification != "ok"]
    if failures:
        lines.extend(["", "## Failures", ""])
        for item in failures:
            lines.append(f"### {item.id} {item.pipeline_type}")
            lines.append("")
            lines.append(f"- Verification: `{item.verification}`")
            if item.error:
                lines.append(f"- Error: `{item.error[:1000]}`")
            if item.child_results:
                lines.append(f"- Children: `{json.dumps(item.child_results, ensure_ascii=False)[:1000]}`")
            lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TEST_PLAN_REAL_VIDEO.md against a real input video.")
    parser.add_argument("input", nargs="?", default=str(ROOT / "test.mp4"))
    parser.add_argument(
        "--only",
        choices=["all", "low-level", "pipeline", "ai", "artifacts"],
        default="all",
        help="Run a subset of the generated cases.",
    )
    parser.add_argument(
        "--cases",
        default="",
        help="Comma-separated case IDs to run, for example RV_P01,RV_P03,RV_P12.",
    )
    parser.add_argument(
        "--supervise",
        action="store_true",
        help="Run each selected case in its own child process and keep an incremental report.",
    )
    parser.add_argument(
        "--case-timeout-seconds",
        type=float,
        default=900.0,
        help="Per-case timeout when --supervise is used. Use 0 to disable.",
    )
    parser.add_argument(
        "--report-prefix",
        default="",
        help="Fixed report filename prefix under test_runs, without extension.",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Remove cache_bust/bypass_cache from generated payloads so expensive AI steps can reuse cached artifacts.",
    )
    return parser.parse_args()


def filter_cases(cases: list[Case], only: str, case_ids: str = "") -> list[Case]:
    if case_ids.strip():
        wanted = {item.strip() for item in case_ids.split(",") if item.strip()}
        return [case for case in cases if case.id in wanted]
    if only == "all":
        return cases
    if only == "low-level":
        return [case for case in cases if case.id.startswith("RV_L")]
    if only == "artifacts":
        return [case for case in cases if case.expected in {"audio", "frames", "segments"}]
    if only == "ai":
        return [case for case in cases if case.id in {"RV_P01", "RV_P02", "RV_P03", "RV_P04", "RV_P06", "RV_P09", "RV_P10", "RV_P12"}]
    if only == "pipeline":
        return [case for case in cases if case.id.startswith("RV_P") and case.expected not in {"audio", "frames", "segments"}]
    return cases


def enable_cache(cases: list[Case]) -> None:
    for case in cases:
        case.payload.pop("cache_bust", None)
        case.payload.pop("bypass_cache", None)


def _timeout_result(case: Case, elapsed: float, log_path: Path) -> CaseResult:
    output_name = str(case.payload.get("output_name", case.id))
    return CaseResult(
        id=case.id,
        pipeline_type=case.pipeline_type,
        output_name=output_name,
        status="failed",
        elapsed_seconds=elapsed,
        output_path=str(_output_path_for(output_name, case.expected)),
        output_exists=False,
        verification="timeout",
        error=f"case exceeded timeout; child log: {log_path}",
    )


def _child_failure_result(case: Case, elapsed: float, message: str, log_path: Path) -> CaseResult:
    output_name = str(case.payload.get("output_name", case.id))
    return CaseResult(
        id=case.id,
        pipeline_type=case.pipeline_type,
        output_name=output_name,
        status="failed",
        elapsed_seconds=elapsed,
        output_path=str(_output_path_for(output_name, case.expected)),
        output_exists=False,
        verification="child_process_failed",
        error=f"{message}; child log: {log_path}",
    )


def _kill_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def supervise_cases(
    *,
    input_path: Path,
    cases: list[Case],
    config_dir: Path,
    assets: dict[str, str],
    report_prefix: str,
    case_timeout_seconds: float,
) -> list[CaseResult]:
    report_dir = ROOT / "test_runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    progress_path = report_dir / f"{report_prefix}.progress.jsonl"
    results: list[CaseResult] = []
    timeout = case_timeout_seconds if case_timeout_seconds > 0 else None
    for case in cases:
        child_prefix = f"{report_prefix}_{case.id}"
        log_path = report_dir / f"{child_prefix}.log"
        child_json = report_dir / f"{child_prefix}.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            str(input_path),
            "--cases",
            case.id,
            "--report-prefix",
            child_prefix,
        ]
        if "cache_bust" not in case.payload and "bypass_cache" not in case.payload:
            command.append("--use-cache")
        started = time.time()
        progress_path.write_text("", encoding="utf-8") if not progress_path.exists() else None
        with progress_path.open("a", encoding="utf-8") as progress:
            progress.write(json.dumps({"event": "start", "case": case.id, "time": datetime.now().isoformat()}) + "\n")
        print(f"[supervisor] start {case.id} timeout={timeout or 'none'}s", flush=True)
        proc = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        timed_out = False
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc.pid)
            try:
                stdout, _ = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                stdout = ""
        elapsed = time.time() - started
        log_path.write_text(stdout or "", encoding="utf-8")

        if timed_out:
            result = _timeout_result(case, elapsed, log_path)
        elif child_json.exists():
            try:
                child_payload = json.loads(child_json.read_text(encoding="utf-8"))
                raw_results = child_payload.get("results", [])
                result = CaseResult(**raw_results[0]) if raw_results else _child_failure_result(case, elapsed, "child report has no result", log_path)
                if proc.returncode != 0 and result.status == "done" and result.verification == "ok":
                    result.status = "failed"
                    result.verification = "child_returned_nonzero"
                    result.error = f"child exited {proc.returncode}; child log: {log_path}"
            except Exception as exc:
                result = _child_failure_result(case, elapsed, f"could not parse child report: {exc}", log_path)
        else:
            result = _child_failure_result(case, elapsed, f"child exited {proc.returncode} without report", log_path)

        results.append(result)
        with progress_path.open("a", encoding="utf-8") as progress:
            progress.write(
                json.dumps(
                    {
                        "event": "done",
                        "case": case.id,
                        "status": result.status,
                        "verification": result.verification,
                        "elapsed_seconds": elapsed,
                        "time": datetime.now().isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        write_reports(results, input_path=input_path, config_dir=config_dir, assets=assets, report_prefix=report_prefix)
        marker = "PASS" if result.status == "done" and result.verification == "ok" else "FAIL"
        print(f"[supervisor] {marker} {case.id}: {result.verification} ({elapsed:.1f}s)", flush=True)
    return results


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"input video not found: {input_path}", file=sys.stderr)
        return 2

    probe = ffprobe_json(input_path)
    assets = prepare_assets(input_path)
    cases = filter_cases(build_cases(assets, probe), args.only, args.cases)
    if args.use_cache:
        enable_cache(cases)
    config_dir = save_configs(cases)
    report_prefix = args.report_prefix.strip() or f"real_video_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if args.supervise:
        results = supervise_cases(
            input_path=input_path,
            cases=cases,
            config_dir=config_dir,
            assets=assets,
            report_prefix=report_prefix,
            case_timeout_seconds=float(args.case_timeout_seconds),
        )
        passed = sum(1 for item in results if item.status == "done" and item.verification == "ok")
        print(f"\nDone: {passed}/{len(results)} passed")
        print(f"JSON report: {ROOT / 'test_runs' / (report_prefix + '.json')}")
        print(f"Markdown report: {ROOT / 'test_runs' / (report_prefix + '.md')}")
        print(f"Progress: {ROOT / 'test_runs' / (report_prefix + '.progress.jsonl')}")
        return 0 if passed == len(results) else 1

    runner = RealVideoRunner(input_path)

    results: list[CaseResult] = []
    for case in cases:
        result = runner.run_case(case)
        results.append(result)
        marker = "PASS" if result.status == "done" and result.verification == "ok" else "FAIL"
        print(f"  {marker}: {result.verification} ({result.elapsed_seconds:.1f}s)", flush=True)

    json_report, md_report = write_reports(
        results,
        input_path=input_path,
        config_dir=config_dir,
        assets=assets,
        report_prefix=args.report_prefix.strip() or None,
    )
    passed = sum(1 for item in results if item.status == "done" and item.verification == "ok")
    print(f"\nDone: {passed}/{len(results)} passed")
    print(f"JSON report: {json_report}")
    print(f"Markdown report: {md_report}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
