"""Dependency injection for API routes."""

from collections.abc import Generator

from fastapi import Request

from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import DatabaseManager


def get_config(request: Request) -> AppConfig:
    """Get application configuration from app state."""
    return request.app.state.config


def get_db_manager(request: Request) -> DatabaseManager:
    """Get database manager from app state."""
    return request.app.state.db_manager


def get_db_session(request: Request) -> Generator:
    """Get database session."""
    db_manager = get_db_manager(request)
    with db_manager.get_session() as session:
        yield session
