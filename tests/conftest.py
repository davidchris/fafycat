"""Pytest configuration and shared fixtures."""

import os
import sys
from pathlib import Path
import tempfile
import shutil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add src and project root to Python path for imports
src_path = Path(__file__).parent.parent / "src"
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(src_path))
sys.path.insert(0, str(project_root))

# Import after path setup
from src.fafycat.core.database import Base
from src.fafycat.core.config import AppConfig


@pytest.fixture(scope="session")
def test_data_dir():
    """Return the test data directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="function")
def temp_db():
    """Create a temporary database for testing."""
    # Create temporary database file
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    # Set up database engine
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)

    yield engine

    # Cleanup
    os.unlink(db_path)


@pytest.fixture(scope="function")
def db_session(temp_db):
    """Create a database session for testing."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=temp_db)
    session = SessionLocal()

    yield session

    session.close()


@pytest.fixture(scope="function")
def test_client(temp_db, db_session):
    """Create a test client with temporary database."""
    # Create temporary model directory
    temp_model_dir = tempfile.mkdtemp()

    # Set test environment variables
    os.environ["FAFYCAT_DB_URL"] = f"sqlite:///{temp_db.url.database}"
    os.environ["FAFYCAT_ENV"] = "testing"
    os.environ["FAFYCAT_MODEL_DIR"] = temp_model_dir

    # Import app after setting env vars
    from main import app

    # Override database dependency
    from api.dependencies import get_db_session

    def override_get_db_session():
        return db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    # Clear any cached categorizer instances
    import api.ml

    api.ml._categorizer = None
    api.ml._config = None

    client = TestClient(app)

    yield client

    # Cleanup
    app.dependency_overrides.clear()
    shutil.rmtree(temp_model_dir)
