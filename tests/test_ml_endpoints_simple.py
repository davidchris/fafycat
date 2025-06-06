"""Simple tests to verify ML endpoints are accessible."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Add root directory to path so we can import main
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_ml_status_endpoint_exists():
    """Test that ML status endpoint exists and returns valid response."""
    from main import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/ml/status")

        # Should return 200 regardless of whether model is loaded
        assert response.status_code == 200

        data = response.json()
        assert "model_loaded" in data
        assert "can_predict" in data
        assert "status" in data





def test_ml_retrain_endpoint_exists():
    """Test that ML retrain endpoint exists."""
    from main import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/ml/retrain")

        # Should not return 404 (endpoint exists)
        # May return 400, 500, or 503 depending on model state
        assert response.status_code != 404


def test_ml_batch_unpredicted_endpoint_exists():
    """Test that ML batch unpredicted endpoint exists."""
    from main import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/ml/predict/batch-unpredicted")

        # Should not return 404 (endpoint exists)
        # May return 503 if no model is available
        assert response.status_code != 404


if __name__ == "__main__":
    pytest.main([__file__])
