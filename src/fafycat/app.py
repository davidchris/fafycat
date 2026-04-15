"""FastAPI + FastHTML application entry point."""

import logging
import time
from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager

_PACKAGE_DIR = Path(__file__).resolve().parent


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
        version="0.1.0",
    )

    # Initialize app configuration and database
    config = AppConfig()
    config.ensure_dirs()

    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    # Store in app state
    app.state.config = config
    app.state.db_manager = db_manager

    # Add performance monitoring middleware
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)

        # Log slow requests
        if process_time > 0.1:  # Log requests taking more than 100ms
            logging.warning("SLOW REQUEST: %s %s took %.3fs", request.method, request.url.path, process_time)
        elif process_time > 0.05:  # Log requests taking more than 50ms
            logging.info("Request %s %s took %.3fs", request.method, request.url.path, process_time)

        return response

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


app = create_app()


if __name__ == "__main__":
    uvicorn.run("fafycat.app:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
