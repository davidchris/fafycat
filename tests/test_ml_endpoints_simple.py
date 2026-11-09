"""Contract tests for the ML endpoints that need no trained model."""

import threading

import pytest

import fafycat.api.ml as ml_api
from fafycat.api.ml_training_job import complete_job, create_training_job, fail_job, get_current_job, set_job_running


@pytest.fixture
def no_running_job():
    """Start and end each test without a running training job in the process-wide slot."""
    fail_job("cleared before test")
    yield
    fail_job("cleared after test")


def test_ml_status_endpoint_exists(test_client):
    """ML status endpoint exists and returns valid response."""
    response = test_client.get("/api/ml/status")
    assert response.status_code == 200
    data = response.json()
    assert "model_loaded" in data
    assert "can_predict" in data
    assert "status" in data


def test_retrain_starts_a_background_job(test_client, monkeypatch, no_running_job):
    """POST /retrain creates a job, runs training on the executor, and reports it as started."""
    ran = threading.Event()
    seen_jobs = []

    def fake_training() -> None:
        seen_jobs.append(get_current_job())
        complete_job({})
        ran.set()

    monkeypatch.setattr(ml_api, "_run_training_sync", fake_training)

    response = test_client.post("/api/ml/retrain")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["message"] == "Training job started"
    assert ran.wait(timeout=5), "the endpoint never handed training to the executor"
    assert [job.job_id for job in seen_jobs] == [body["job_id"]]


def test_retrain_rejects_a_second_job_while_one_runs(test_client, no_running_job):
    """A retrain request during a running job gets 409 naming the running job."""
    running = create_training_job()
    set_job_running()

    response = test_client.post("/api/ml/retrain")

    assert response.status_code == 409
    assert response.json()["detail"] == {"message": "Training already in progress", "job_id": running.job_id}


def test_batch_unpredicted_without_a_model_is_unavailable(test_client):
    """With no trained model the batch endpoint answers 503 and asks for training."""
    response = test_client.post("/api/ml/predict/batch-unpredicted")

    assert response.status_code == 503
    assert "train" in response.json()["detail"].lower()
