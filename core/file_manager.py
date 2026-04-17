from __future__ import annotations

from pathlib import Path


STEP_NAMES = {
    "extract_audio": "01_extract_audio.wav",
    "transcript": "02_transcript.json",
    "translate": "03_translate.json",
    "subtitle": "04_subtitle.srt",
    "tts_{n}": "05_tts_{n:03d}.wav",
    "synced_audio": "06_synced.wav",
    "mixed_audio": "07_mixed.wav",
    "burned_video": "08_burned.mp4",
    "final": "final.mp4",
}


class FileManager:
    def __init__(self, temp_root: Path, output_root: Path, job_id: str) -> None:
        self.temp_root = Path(temp_root)
        self.output_root = Path(output_root)
        self.job_id = job_id
        self.job_temp_dir = self.temp_root / job_id
        self.job_output_dir = self.output_root / job_id

    def ensure_dirs(self) -> None:
        self.job_temp_dir.mkdir(parents=True, exist_ok=True)
        self.job_output_dir.mkdir(parents=True, exist_ok=True)

    def temp(self, name: str) -> Path:
        self.ensure_dirs()
        return self.job_temp_dir / name

    def output(self, name: str) -> Path:
        self.ensure_dirs()
        return self.job_output_dir / name

    def step_file(self, step_name: str, n: int | None = None) -> Path:
        if step_name == "tts" and n is None:
            raise ValueError("tts step file requires n")
        if step_name == "tts":
            template = STEP_NAMES["tts_{n}"]
            return self.temp(template.format(n=n))
        template = STEP_NAMES.get(step_name, step_name)
        if step_name == "final":
            return self.output(template)
        return self.temp(template)

    def resolve_artifact_path(self, kind: str, relative_path: str) -> Path:
        if kind == "output":
            return self.output(relative_path)
        return self.temp(relative_path)

    def classify_path(self, path: str | Path) -> tuple[str, str]:
        candidate = Path(path).resolve()
        temp_root = self.job_temp_dir.resolve()
        output_root = self.job_output_dir.resolve()
        if candidate.is_relative_to(temp_root):
            return "temp", str(candidate.relative_to(temp_root))
        if candidate.is_relative_to(output_root):
            return "output", str(candidate.relative_to(output_root))
        raise ValueError(f"path {candidate} is outside job roots")
