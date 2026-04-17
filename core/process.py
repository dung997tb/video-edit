from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Callable

from core.exceptions import JobCancelledError


class SubprocessExecutionError(RuntimeError):
    pass


@dataclass(slots=True)
class SubprocessResult:
    command: list[str]
    pid: int
    returncode: int
    stdout: str
    stderr: str


class ProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def register(self, job_id: str, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes[job_id] = process

    def unregister(self, job_id: str) -> None:
        with self._lock:
            self._processes.pop(job_id, None)

    def get(self, job_id: str) -> subprocess.Popen[str] | None:
        with self._lock:
            return self._processes.get(job_id)

    def cancel(self, job_id: str, grace_seconds: float) -> bool:
        process = self.get(job_id)
        if process is None or process.poll() is not None:
            return False
        process.terminate()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=grace_seconds)
        return True


def run_subprocess(
    command: list[str],
    *,
    job_id: str,
    job_manager: Any,
    process_registry: ProcessRegistry,
    cancel_check: Callable[[], bool],
    grace_seconds: float,
    cwd: str | None = None,
) -> SubprocessResult:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        cwd=cwd,
    )
    process_registry.register(job_id, process)
    job_manager.set_pid(job_id, process.pid)
    stdout = ""
    stderr = ""
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel_check():
                    process_registry.cancel(job_id, grace_seconds)
                    raise JobCancelledError(f"job {job_id} cancelled while running: {' '.join(command)}")
        result = SubprocessResult(
            command=command,
            pid=process.pid,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        if process.returncode != 0:
            raise SubprocessExecutionError(
                f"command failed with code {process.returncode}: {' '.join(command)}\n{stderr}"
            )
        return result
    finally:
        process_registry.unregister(job_id)
