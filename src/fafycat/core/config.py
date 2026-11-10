"""Configuration settings for FafyCat."""

import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from platformdirs import user_data_dir
from pydantic import BaseModel, Field
from sqlalchemy.engine import make_url

from fafycat.core.config_file import load_config_file

PROD_DB_FILENAME = "fafycat_prod.db"
"""The production database inside the data dir. ``fafycat serve`` has always used this file."""

DEV_DB_FILENAME = "fafycat_dev.db"
"""The development database inside the data dir (``--dev``), seeded with synthetic data."""

LEGACY_DB_FILENAME = "fafycat.db"
"""Up to 0.3, ``fafycat import`` and the query commands defaulted to this file, which ``serve`` never opened."""


DB_SOURCE_FLAG = "--data-dir/--dev flag"
DB_SOURCE_ENV = "FAFYCAT_DB_URL"
DB_SOURCE_CONFIG_FILE = "config file db_url"
DB_SOURCE_LEGACY_CWD = "legacy ./data/fafycat_prod.db"
DB_SOURCE_DATA_DIR = "data dir"


class DataLocationError(ValueError):
    """The configured data location cannot be used."""


def database_filename(*, dev: bool) -> str:
    """Return the database file name for the development or production mode."""
    return DEV_DB_FILENAME if dev else PROD_DB_FILENAME


def sqlite_url(path: Path) -> str:
    """Return the SQLAlchemy URL of a SQLite database file.

    Raises:
        DataLocationError: The path contains ``?`` or ``#``, which a SQLAlchemy URL would cut off,
            so the URL would name a different file.
    """
    url = f"sqlite:///{path}"
    if sqlite_path(url) != path:
        raise DataLocationError(f"FafyCat cannot keep a database at {path}: the path must not contain '?' or '#'")
    return url


def sqlite_path(url: str) -> Path | None:
    """Return the file behind a SQLite URL, or None for other databases and in-memory SQLite.

    Handles both ``sqlite:///path`` and the URI form ``sqlite:///file:path?uri=true``.
    """
    parsed = make_url(url)
    database = parsed.database
    if not parsed.drivername.startswith("sqlite") or database in (None, "", ":memory:"):
        return None
    if database.startswith("file:") and str(parsed.query.get("uri", "")).lower() == "true":
        database = unquote(urlparse(database).path)
        if database in ("", ":memory:"):
            return None
    return Path(database)


def legacy_cwd_database() -> Path:
    """Return ``./data/fafycat_prod.db``, the database the repo scripts and old ``serve`` used from a checkout."""
    return (Path.cwd() / "data" / PROD_DB_FILENAME).resolve()


def _default_data_dir() -> Path:
    """Return the default application data directory."""
    env = os.getenv("FAFYCAT_DATA_DIR")
    if env:
        return Path(env).expanduser()
    cfg = load_config_file(None)
    if "data_dir" in cfg:
        return Path(cfg["data_dir"]).expanduser()
    return Path(user_data_dir("fafycat"))


def _default_database_url() -> str:
    """Return the default database URL."""
    env = os.getenv("FAFYCAT_DB_URL")
    if env:
        return env
    cfg = load_config_file(None)
    if "db_url" in cfg:
        return cfg["db_url"]
    return sqlite_url(_default_data_dir() / PROD_DB_FILENAME)


def _default_model_dir() -> Path:
    """Return the default model directory."""
    env = os.getenv("FAFYCAT_MODEL_DIR")
    if env:
        return Path(env)
    cfg = load_config_file(None)
    if "model_dir" in cfg:
        return Path(cfg["model_dir"])
    return _default_data_dir() / "models"


def training_threads() -> int:
    """Threads for model training: about 90% of the cores, at least one.

    Retraining runs as a background job and may take a minute, so it should
    use nearly the whole machine without starving the web server.
    """
    return max(1, int((os.cpu_count() or 1) * 0.9))


class DatabaseConfig(BaseModel):
    """Database configuration."""

    url: str = Field(default_factory=_default_database_url)
    echo: bool = Field(default_factory=lambda: os.getenv("FAFYCAT_DB_ECHO", "false").lower() == "true")
    source: str = ""
    """Which setting chose ``url``; filled in by ``resolve_config`` and shown by ``fafycat status``."""


class MLConfig(BaseModel):
    """Machine learning configuration."""

    # Ensemble settings
    use_ensemble: bool = True
    ensemble_cv_folds: int = 5

    # LightGBM parameters. Optuna-tuned for the shape (5x5 CV macro F1), then
    # cut to size in experiments/00-lgbm-capacity: on ~3k rows the log-loss
    # bottoms out near 80 trees; 1000 was 13x past that point. Re-derive
    # n_estimators when the labelled set grows a lot.
    lgbm_params: dict[str, Any] = Field(
        default_factory=lambda: {
            "n_estimators": 80,
            "num_leaves": 63,
            "max_depth": 8,
            "learning_rate": 0.043,
            "feature_fraction": 0.475,
            "bagging_fraction": 0.92,
            "bagging_freq": 9,
            "min_child_samples": 30,
            "reg_alpha": 3.3e-05,
            "reg_lambda": 7.0e-05,
            "class_weight": "balanced",
            "random_state": 42,
            "n_jobs": training_threads(),
            "verbose": -1,
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

    # L2 strength of the stacked ensemble's logistic regression. Chosen by
    # 3-fold log-loss over {0.03, 0.1, 0.3, 1.0} in experiments/02-stacked-gate.
    stack_l2_c: float = 0.03

    confidence_thresholds: dict[str, float] = Field(default_factory=lambda: {"high": 0.9, "medium": 0.7, "low": 0.5})

    # Measured on real review history: the 0.8-0.95 band was corrected 0 times
    # in 62 reviews, so 0.90 costs nothing and removes a lot of manual work.
    # The DB setting `auto_approve_threshold` overrides this.
    auto_approve_threshold: float = 0.90

    model_dir: Path = Field(default_factory=_default_model_dir)
    min_training_samples: int = 50

    @property
    def model_path(self) -> Path:
        """The saved Categorizer file that the server loads."""
        return self.model_dir / ("ensemble_categorizer.pkl" if self.use_ensemble else "categorizer.pkl")


class AppConfig(BaseModel):
    """Application configuration."""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    ml: MLConfig = Field(default_factory=MLConfig)

    data_dir: Path = Field(default_factory=_default_data_dir)
    export_dir: Path | None = Field(default=None)

    max_import_batch_size: int = 10000
    default_currency: str = "EUR"

    def model_post_init(self, __context: Any) -> None:
        """Derive dependent paths after initialization."""
        file_cfg = load_config_file(None)

        if "database" not in self.model_fields_set and "FAFYCAT_DB_URL" not in os.environ and "db_url" not in file_cfg:
            self.database.url = sqlite_url(self.data_dir / PROD_DB_FILENAME)

        if "ml" not in self.model_fields_set and "FAFYCAT_MODEL_DIR" not in os.environ and "model_dir" not in file_cfg:
            self.ml.model_dir = self.data_dir / "models"

        no_explicit_export_dir = "export_dir" not in self.model_fields_set and "FAFYCAT_EXPORT_DIR" not in os.environ
        if no_explicit_export_dir and "export_dir" not in file_cfg:
            self.export_dir = self.data_dir / "exports"
        elif self.export_dir is None:
            if "FAFYCAT_EXPORT_DIR" in os.environ:
                self.export_dir = Path(os.environ["FAFYCAT_EXPORT_DIR"])
            elif "export_dir" in file_cfg:
                self.export_dir = Path(file_cfg["export_dir"])
            else:
                self.export_dir = self.data_dir / "exports"

    def ensure_dirs(self) -> None:
        """Create necessary directories."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        export_dir = self.export_dir
        if export_dir is None:
            export_dir = self.data_dir / "exports"
            self.export_dir = export_dir
        export_dir.mkdir(parents=True, exist_ok=True)
        self.ml.model_dir.mkdir(parents=True, exist_ok=True)


def resolve_config(data_dir: Path | None = None, *, dev: bool = False) -> AppConfig:
    """Decide where FafyCat keeps its data; every entry point (server, CLI, scripts) calls this.

    Precedence is command-line flag > environment > config file > default. The database is
    the first of:

    1. ``<data dir>/fafycat_prod.db`` (``fafycat_dev.db`` with ``dev``) when ``data_dir`` or
       ``dev`` is given: the flags beat ``FAFYCAT_DB_URL`` and ``[paths] db_url``.
    2. ``FAFYCAT_DB_URL``.
    3. ``[paths] db_url`` in the config file.
    4. ``./data/fafycat_prod.db`` when it exists and nothing at all is configured. Older
       checkouts kept the real database there; ``fafycat status`` warns when it is in use.
    5. ``<data dir>/fafycat_prod.db``.

    The data dir is ``data_dir``, else ``FAFYCAT_DATA_DIR``, else ``[paths] data_dir``, else the
    platform user-data dir. An explicit ``data_dir`` also puts the model and export dirs under it,
    over ``FAFYCAT_MODEL_DIR`` / ``FAFYCAT_EXPORT_DIR`` and the config file.

    ``config.database.source`` records which rule chose the database.

    Args:
        data_dir: The ``--data-dir`` flag, or None.
        dev: The ``--dev`` flag: use the development database.

    Returns:
        The configuration. Nothing is created on disk.

    Raises:
        ConfigFileError: The config file exists but is not valid TOML.
        DataLocationError: The database path cannot be written as a SQLite URL.
    """
    file_cfg = load_config_file(None)
    resolved_dir = data_dir.expanduser().resolve() if data_dir is not None else _default_data_dir()

    if data_dir is not None or dev:
        url, source = sqlite_url(resolved_dir / database_filename(dev=dev)), DB_SOURCE_FLAG
    elif "FAFYCAT_DB_URL" in os.environ:
        url, source = os.environ["FAFYCAT_DB_URL"], DB_SOURCE_ENV
    elif "db_url" in file_cfg:
        url, source = file_cfg["db_url"], DB_SOURCE_CONFIG_FILE
    elif _nothing_configured(file_cfg) and legacy_cwd_database().exists():
        url, source = sqlite_url(legacy_cwd_database()), DB_SOURCE_LEGACY_CWD
    else:
        url, source = sqlite_url(resolved_dir / PROD_DB_FILENAME), DB_SOURCE_DATA_DIR

    config = AppConfig(data_dir=resolved_dir, database=DatabaseConfig(url=url, source=source))
    if data_dir is not None:
        config.ml.model_dir = resolved_dir / "models"
        config.export_dir = resolved_dir / "exports"
    return config


def _nothing_configured(file_cfg: dict[str, str]) -> bool:
    """True when no env var or config-file path names a data location."""
    return "FAFYCAT_DATA_DIR" not in os.environ and "data_dir" not in file_cfg


def export_to_environ(config: AppConfig) -> None:
    """Publish a resolved configuration through ``FAFYCAT_*`` env vars.

    The server process (and uvicorn's reload worker) and the import path build
    ``AppConfig()`` in many places; with these set, each of them gets the same
    paths as ``config``.
    """
    os.environ["FAFYCAT_DATA_DIR"] = str(config.data_dir)
    os.environ["FAFYCAT_DB_URL"] = config.database.url
    os.environ["FAFYCAT_MODEL_DIR"] = str(config.ml.model_dir)
    if config.export_dir is not None:
        os.environ["FAFYCAT_EXPORT_DIR"] = str(config.export_dir)
