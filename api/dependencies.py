"""Dependency injection for API routes."""

from typing import Generator
from fastapi import Depends, Request

from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import DatabaseManager


def get_config(request: Request) -> AppConfig:
    """Get application configuration from app state."""
    return request.app.state.config


def get_db_manager(request: Request) -> DatabaseManager:
    """Get database manager from app state."""
    return request.app.state.db_manager


def get_db_session(db_manager: DatabaseManager = Depends(get_db_manager)) -> Generator:
    """Get database session."""
    session = db_manager.get_session()
    try:
        yield session
    finally:
        session.close()