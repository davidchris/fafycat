"""A model file this version cannot load is reported as incompatible, not as missing."""

import io
import pickle
from pathlib import Path

import pytest

from fafycat.core.config import MLConfig
from fafycat.core.database import TransactionORM
from fafycat.ml.ensemble_categorizer import EnsembleCategorizer, IncompatibleModelError

LEGACY_ENSEMBLE = {
    "model_version": "1.0-ensemble",
    "lgbm_model_data": {"calibrated_classifier": None, "model_version": "1.0"},
    "nb_component": None,
    "ensemble_weights": {"lgbm": 0.5, "nb": 0.3, "rule": 0.2},
    "cv_results": {},
}
# A pickle that names a module the stacked ensemble removed.
REMOVED_MODULE = b"cfafycat.ml.cross_validation\nStratifiedKFoldValidator\n."
# The current version tag, but written before a key the loader needs existed.
MISSING_KEYS = {"model_version": "2.0-stack", "lgbm_model_data": {}}


def write_legacy_model(model_dir: Path) -> None:
    """Write a 1.0-ensemble model file where the app looks for the ensemble."""
    (model_dir / "ensemble_categorizer.pkl").write_bytes(pickle.dumps(LEGACY_ENSEMBLE))


@pytest.mark.parametrize(
    "payload",
    [pickle.dumps(LEGACY_ENSEMBLE), REMOVED_MODULE, pickle.dumps(MISSING_KEYS)],
    ids=["legacy-version", "removed-module", "missing-keys"],
)
def test_loading_an_incompatible_model_raises_the_typed_error(db_session, tmp_path, payload):
    model_path = tmp_path / "ensemble_categorizer.pkl"
    model_path.write_bytes(payload)
    ensemble = EnsembleCategorizer(db_session, MLConfig())

    with pytest.raises(IncompatibleModelError, match="[Rr]etrain"):
        ensemble.load_model(model_path)

    assert ensemble.is_trained is False


def test_prediction_endpoints_report_the_incompatible_model_every_time(test_client, tmp_data_dir):
    write_legacy_model(tmp_data_dir / "models")

    # The second call must not get a half-loaded Categorizer from the cache.
    for _ in range(2):
        response = test_client.post("/api/ml/predict/batch-unpredicted")
        assert response.status_code == 503
        assert "1.0-ensemble" in response.json()["detail"]

    status = test_client.get("/api/ml/status").json()
    assert status["can_predict"] is False
    assert "1.0-ensemble" in status["status"]


class TestUploadWithIncompatibleModel:
    CSV = b"Date,Description,Amount\n2024-01-01,Test Transaction,-10.50\n"

    def test_htmx_upload_imports_and_asks_for_a_retrain(self, test_client, db_session, tmp_data_dir):
        write_legacy_model(tmp_data_dir / "models")

        response = test_client.post("/api/upload/csv-htmx", files={"file": ("t.csv", io.BytesIO(self.CSV))})

        assert response.status_code == 200
        html = response.text
        assert "Successfully imported 1 new transactions" in html
        assert "No trained model available" not in html
        assert "1.0-ensemble" in html
        assert 'href="/settings"' in html
        assert db_session.query(TransactionORM).count() == 1

    def test_json_upload_imports_and_reports_the_prediction_error(self, test_client, db_session, tmp_data_dir):
        write_legacy_model(tmp_data_dir / "models")

        response = test_client.post("/api/upload/csv", files={"file": ("t.csv", io.BytesIO(self.CSV))})

        assert response.status_code == 200
        body = response.json()
        assert body["transactions_imported"] == 1
        assert body["predictions_made"] == 0
        assert "1.0-ensemble" in body["prediction_error"]
        assert db_session.query(TransactionORM).count() == 1

    def test_upload_without_a_model_reports_no_prediction_error(self, test_client):
        response = test_client.post("/api/upload/csv", files={"file": ("t.csv", io.BytesIO(self.CSV))})

        assert response.status_code == 200
        assert response.json()["prediction_error"] is None
