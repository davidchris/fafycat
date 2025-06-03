"""FastAPI + FastHTML application entry point."""

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import DatabaseManager


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
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

    # Mount static files
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # Include API routes
    from api.categories import router as categories_router
    from api.ml import router as ml_router
    from api.transactions import router as transactions_router
    from api.upload import router as upload_router

    app.include_router(transactions_router, prefix="/api")
    app.include_router(categories_router, prefix="/api")
    app.include_router(upload_router, prefix="/api")
    app.include_router(ml_router, prefix="/api")

    # Include web routes (FastHTML)
    from web.routes import router as web_router

    app.include_router(web_router)

    # Root redirect to main app
    @app.get("/")
    async def root():
        return RedirectResponse(url="/app", status_code=302)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
