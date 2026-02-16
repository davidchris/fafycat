"""Configuration settings for FafyCat."""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """Database configuration."""

    url: str = Field(default_factory=lambda: os.getenv("FAFYCAT_DB_URL", "sqlite:///data/fafycat.db"))
    echo: bool = Field(default_factory=lambda: os.getenv("FAFYCAT_DB_ECHO", "false").lower() == "true")


class MLConfig(BaseModel):
    """Machine learning configuration."""

    # Ensemble settings
    use_ensemble: bool = True
    ensemble_cv_folds: int = 5

    # LightGBM parameters (Optuna-tuned, 5x5 CV macro F1: 0.8549 vs 0.8466 baseline)
    lgbm_params: dict[str, Any] = Field(
        default_factory=lambda: {
            "n_estimators": 1000,
            "num_leaves": 97,
            "max_depth": 8,
            "learning_rate": 0.043,
            "feature_fraction": 0.475,
            "bagging_fraction": 0.92,
            "bagging_freq": 9,
            "min_child_samples": 13,
            "reg_alpha": 3.3e-05,
            "reg_lambda": 7.0e-05,
            "class_weight": "balanced",
            "random_state": 42,
            "n_jobs": -1,
        }
    )

    # TF-IDF parameters for LightGBM (char + word vectorizers with SVD)
    tfidf_char_params: dict[str, Any] = Field(
        default_factory=lambda: {
            "max_features": 1000,
            "analyzer": "char_wb",
            "ngram_range": (3, 5),
            "min_df": 2,
            "max_df": 0.95,
        }
    )
    tfidf_word_params: dict[str, Any] = Field(
        default_factory=lambda: {
            "max_features": 500,
            "analyzer": "word",
            "ngram_range": (1, 2),
            "min_df": 2,
            "max_df": 0.95,
        }
    )
    svd_n_components: int = 100

    # Naive Bayes parameters
    nb_alpha: float = 1.0
    nb_use_complement: bool = True
    nb_max_features: int = 2000

    confidence_thresholds: dict[str, float] = Field(default_factory=lambda: {"high": 0.9, "medium": 0.7, "low": 0.5})

    auto_approve_threshold: float = 0.95

    model_dir: Path = Field(default_factory=lambda: Path(os.getenv("FAFYCAT_MODEL_DIR", "data/models")))
    min_training_samples: int = 50


class AppConfig(BaseModel):
    """Application configuration."""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    ml: MLConfig = Field(default_factory=MLConfig)

    data_dir: Path = Field(default_factory=lambda: Path(os.getenv("FAFYCAT_DATA_DIR", "data")))
    export_dir: Path = Field(default_factory=lambda: Path(os.getenv("FAFYCAT_EXPORT_DIR", "data/exports")))

    max_import_batch_size: int = 10000
    default_currency: str = "EUR"

    def ensure_dirs(self) -> None:
        """Create necessary directories."""
        self.data_dir.mkdir(exist_ok=True)
        self.export_dir.mkdir(exist_ok=True)
        self.ml.model_dir.mkdir(exist_ok=True)
