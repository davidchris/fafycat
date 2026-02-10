"""Background ML training job management."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class TrainingPhase(StrEnum):
    PENDING = "pending"
    PREPARING_DATA = "preparing_data"
    TRAINING_LGBM = "training_lgbm"
    TRAINING_NB = "training_nb"
    OPTIMIZING_WEIGHTS = "optimizing_weights"
    SAVING_MODEL = "saving_model"
    DONE = "done"
    ERROR = "error"


PHASE_DESCRIPTIONS = {
    TrainingPhase.PENDING: "Waiting to start...",
    TrainingPhase.PREPARING_DATA: "Preparing training data from database...",
    TrainingPhase.TRAINING_LGBM: "Training LightGBM model...",
    TrainingPhase.TRAINING_NB: "Training Naive Bayes model...",
    TrainingPhase.OPTIMIZING_WEIGHTS: "Optimizing ensemble weights...",
    TrainingPhase.SAVING_MODEL: "Saving trained model...",
    TrainingPhase.DONE: "Training completed successfully!",
    TrainingPhase.ERROR: "Training failed",
}

PHASE_PROGRESS = {
    TrainingPhase.PENDING: 0,
    TrainingPhase.PREPARING_DATA: 10,
    TrainingPhase.TRAINING_LGBM: 30,
    TrainingPhase.TRAINING_NB: 55,
    TrainingPhase.OPTIMIZING_WEIGHTS: 75,
    TrainingPhase.SAVING_MODEL: 90,
    TrainingPhase.DONE: 100,
    TrainingPhase.ERROR: 0,
}


@dataclass
class TrainingJob:
    job_id: str
    status: str = "pending"  # pending, running, completed, failed
    phase: TrainingPhase = TrainingPhase.PENDING
    started_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "phase": self.phase.value,
            "phase_description": PHASE_DESCRIPTIONS.get(self.phase, ""),
            "progress": PHASE_PROGRESS.get(self.phase, 0),
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
        }


# Global job storage (single job at a time for simplicity)
_current_job: TrainingJob | None = None
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ml_training")
_job_lock = threading.Lock()  # Protects _current_job access across threads


def get_current_job() -> TrainingJob | None:
    with _job_lock:
        return _current_job


def get_job_by_id(job_id: str) -> TrainingJob | None:
    with _job_lock:
        if _current_job and _current_job.job_id == job_id:
            return _current_job
        return None


def is_training_in_progress() -> bool:
    with _job_lock:
        return _current_job is not None and _current_job.status == "running"


def create_training_job() -> TrainingJob:
    global _current_job
    with _job_lock:
        _current_job = TrainingJob(job_id=str(uuid.uuid4()))
        return _current_job


def update_job_phase(phase: TrainingPhase) -> None:
    with _job_lock:
        if _current_job:
            _current_job.phase = phase
            _current_job.updated_at = _utc_now()


def set_job_running() -> None:
    with _job_lock:
        if _current_job:
            _current_job.status = "running"
            _current_job.updated_at = _utc_now()


def complete_job(result: dict[str, Any]) -> None:
    with _job_lock:
        if _current_job:
            _current_job.status = "completed"
            _current_job.phase = TrainingPhase.DONE
            _current_job.result = result
            _current_job.completed_at = _utc_now()
            _current_job.updated_at = _utc_now()


def fail_job(error: str) -> None:
    with _job_lock:
        if _current_job:
            _current_job.status = "failed"
            _current_job.phase = TrainingPhase.ERROR
            _current_job.error = error
            _current_job.completed_at = _utc_now()
            _current_job.updated_at = _utc_now()


def get_executor() -> ThreadPoolExecutor:
    return _executor
