import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


Converter = Callable[[str, str, dict, Callable[[int, str], None]], tuple[int, int]]
ConfigLoader = Callable[[], dict]


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ConversionJob:
    id: str
    filename: str
    upload_path: str
    output_path: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    step: str = "等待中"
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    created_at: float = 0
    updated_at: float = 0
    cancel_requested: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status.value,
            "progress": self.progress,
            "step": self.step,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error": self.error,
            "download_url": f"/api/jobs/{self.id}/download" if self.status == JobStatus.COMPLETED else None,
        }


class JobManager:
    def __init__(
        self,
        storage_dir: str | os.PathLike[str],
        converter: Converter,
        config_loader: ConfigLoader,
        auto_start: bool = True,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.upload_dir = self.storage_dir / "uploads"
        self.output_dir = self.storage_dir / "outputs"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.converter = converter
        self.config_loader = config_loader
        self.auto_start = auto_start
        self.max_workers = max(1, int(config_loader().get("max_workers", 3)))
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._jobs: dict[str, ConversionJob] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.RLock()

    def configure(self, max_workers: int) -> None:
        max_workers = max(1, int(max_workers))
        with self._lock:
            if max_workers == self.max_workers:
                return
            old_executor = self.executor
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
            self.max_workers = max_workers
        old_executor.shutdown(wait=False, cancel_futures=False)

    def create_job(self, filename: str, content: bytes) -> ConversionJob:
        job_id = uuid.uuid4().hex
        safe_name = Path(filename or "image").name
        upload_path = self.upload_dir / f"{job_id}_{safe_name}"
        output_path = self.output_dir / f"{job_id}.docx"
        upload_path.write_bytes(content)
        now = time.time()
        job = ConversionJob(
            id=job_id,
            filename=safe_name,
            upload_path=str(upload_path),
            output_path=str(output_path),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job_id] = job
            if self.auto_start:
                self._futures[job_id] = self.executor.submit(self._run_job, job_id)
        return job

    def list_jobs(self) -> list[ConversionJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at)

    def get_job(self, job_id: str) -> ConversionJob:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id]

    def cancel_job(self, job_id: str) -> ConversionJob:
        with self._lock:
            job = self.get_job(job_id)
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return job
            job.cancel_requested = True
            future = self._futures.get(job_id)
            if future is None or future.cancel() or job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.step = "已取消"
            else:
                job.status = JobStatus.CANCELLED
                job.step = "正在停止"
            job.updated_at = time.time()
            return job

    def cancel_all(self) -> list[ConversionJob]:
        with self._lock:
            ids = list(self._jobs)
        return [self.cancel_job(job_id) for job_id in ids]

    def clear_jobs(self) -> list[ConversionJob]:
        with self._lock:
            active = {JobStatus.QUEUED, JobStatus.RUNNING}
            if any(job.status in active for job in self._jobs.values()):
                raise RuntimeError("仍有任务在转换中，请先取消或等待完成")
            self._jobs.clear()
            self._futures.clear()
            return []

    def wait_for_job(self, job_id: str, timeout: float | None = None) -> ConversionJob:
        future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get_job(job_id)

    def _update_progress(self, job_id: str, pct: int, label: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.cancel_requested:
                return
            job.progress = max(0, min(100, int(pct)))
            job.step = label
            job.updated_at = time.time()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.cancel_requested:
                job.status = JobStatus.CANCELLED
                job.step = "已取消"
                return
            job.status = JobStatus.RUNNING
            job.step = "准备处理"
            job.updated_at = time.time()

        def cb(pct: int, label: str) -> None:
            self._update_progress(job_id, pct, label)

        try:
            cfg = self.config_loader()
            input_tokens, output_tokens = self.converter(job.upload_path, job.output_path, cfg, cb)
            with self._lock:
                job = self._jobs[job_id]
                if job.cancel_requested or job.status == JobStatus.CANCELLED:
                    job.status = JobStatus.CANCELLED
                    job.step = "已取消"
                else:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100
                    job.step = "转换完成"
                    job.input_tokens = input_tokens
                    job.output_tokens = output_tokens
                job.updated_at = time.time()
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                if job.cancel_requested:
                    job.status = JobStatus.CANCELLED
                    job.step = "已取消"
                else:
                    job.status = JobStatus.FAILED
                    job.error = str(exc)
                    job.step = "转换失败"
                job.updated_at = time.time()
