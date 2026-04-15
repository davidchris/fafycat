"""Simple tests to verify ML endpoints are accessible."""

import pytest


def test_ml_status_endpoint_exists(test_client):
    """ML status endpoint exists and returns valid response."""
    response = test_client.get("/api/ml/status")
    assert response.status_code == 200
    data = response.json()
    assert "model_loaded" in data
    assert "can_predict" in data
    assert "status" in data


def test_ml_retrain_endpoint_exists(test_client):
    """ML retrain endpoint exists (may return any non-404 status)."""
    response = test_client.post("/api/ml/retrain")
    assert response.status_code != 404


def test_ml_batch_unpredicted_endpoint_exists(test_client):
    """ML batch-unpredicted endpoint exists (may return 503 if no model)."""
    response = test_client.post("/api/ml/predict/batch-unpredicted")
    assert response.status_code != 404


if __name__ == "__main__":
    pytest.main([__file__])
