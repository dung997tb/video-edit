from __future__ import annotations

import subprocess
import threading
import time
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
        self._processes: dict[str, dict[int, subprocess.Popen[str]]] = {}

    def register(self, job_id: str, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes.setdefault(job_id, {})[process.pid] = process

    def unregister(self, job_id: str, process: subprocess.Popen[str] | None = None) -> None:
        with self._lock:
            if process is None:
                self._processes.pop(job_id, None)
                return
            processes = self._processes.get(job_id)
            if not processes:
                return
            processes.pop(process.pid, None)
            if not processes:
                self._processes.pop(job_id, None)

    def get(self, job_id: str) -> subprocess.Popen[str] | None:
        with self._lock:
            processes = self._processes.get(job_id, {})
            for process in processes.values():
                if process.poll() is None:
                    return process
            return next(iter(processes.values()), None)

    def list(self, job_id: str) -> list[subprocess.Popen[str]]:
        with self._lock:
            return list(self._processes.get(job_id, {}).values())

    def cancel(self, job_id: str, grace_seconds: float) -> bool:
        processes = [process for process in self.list(job_id) if process.poll() is None]
        if not processes:
            return False
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
        for process in processes:
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                pass
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
    timeout: float | None = None,
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
    started_at = time.monotonic()
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel_check():
                    process_registry.cancel(job_id, grace_seconds)
                    raise JobCancelledError(f"job {job_id} cancelled while running: {' '.join(command)}")
                if timeout is not None and time.monotonic() - started_at >= timeout:
                    process_registry.cancel(job_id, grace_seconds)
                    raise SubprocessExecutionError(
                        f"command timed out after {timeout:.1f}s: {' '.join(command)}"
                    )
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
        process_registry.unregister(job_id, process)
