"""FastAPI + FastHTML application entry point."""

import logging
import time
from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from fafycat import __version__
from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager
from fafycat.core.security import BrowserSecurityMiddleware, allowed_hosts_from_env

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent

_SLOW_REQUEST_SECONDS = 1.0
# Import, training and batch prediction take seconds by design; they are logged at INFO, not WARNING.
_LONG_RUNNING_PATHS = ("/api/upload", "/upload-csv", "/api/ml/retrain", "/api/ml/predict/batch")


class _TrainingStatusAccessLogFilter(logging.Filter):
    """Drop uvicorn access-log lines for the training-status poll endpoint."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/ml/training-status" not in record.getMessage()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    logging.getLogger("uvicorn.access").addFilter(_TrainingStatusAccessLogFilter())

    app = FastAPI(
        title="FafyCat - Family Finance Categorizer",
        description="Local-first transaction categorization tool",
        version=__version__,
    )

    # Initialize app configuration and database
    config = AppConfig()
    config.ensure_dirs()

    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    # Older databases predate merchant_pattern; fill it in before serving.
    from fafycat.data.merchant_pattern import backfill_merchant_patterns

    with db_manager.get_session() as session:
        backfill_merchant_patterns(session)

    # Store in app state
    app.state.config = config
    app.state.db_manager = db_manager

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        process_time = time.perf_counter() - start_time
        response.headers["X-Process-Time"] = f"{process_time:.4f}"
        if process_time > _SLOW_REQUEST_SECONDS:
            path = request.url.path
            level = logging.INFO if path.startswith(_LONG_RUNNING_PATHS) else logging.WARNING
            logger.log(level, "Slow request: %s %s took %.2fs", request.method, path, process_time)
        return response

    # Added last so it runs first: nothing else sees a foreign Host or a cross-origin write.
    app.add_middleware(BrowserSecurityMiddleware, allowed_hosts=allowed_hosts_from_env())

    # Mount static files
    app.mount("/static", StaticFiles(directory=_PACKAGE_DIR / "static"), name="static")

    # Include API routes
    from fafycat.api.analytics import router as analytics_router
    from fafycat.api.budgets import router as budgets_router
    from fafycat.api.categories import router as categories_router
    from fafycat.api.export import router as export_router
    from fafycat.api.ml import router as ml_router
    from fafycat.api.transactions import router as transactions_router
    from fafycat.api.upload import router as upload_router

    app.include_router(transactions_router, prefix="/api")
    app.include_router(categories_router, prefix="/api")
    app.include_router(upload_router, prefix="/api")
    app.include_router(ml_router, prefix="/api")
    app.include_router(export_router, prefix="/api")
    app.include_router(budgets_router)
    app.include_router(analytics_router)

    # Include web routes (FastHTML)
    from fafycat.web.routes import router as web_router

    app.include_router(web_router)

    return app


# No module-level ``app``: building it opens the configured database and runs
# schema upgrades, which must not happen as an import side effect (pytest
# collection, tooling). uvicorn gets the factory instead.
if __name__ == "__main__":
    uvicorn.run("fafycat.app:create_app", factory=True, host="127.0.0.1", port=8000, log_level="info")
