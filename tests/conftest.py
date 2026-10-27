import os
os.environ["DATABASE_URL"] = "sqlite:///./test_amrutam.db"
os.environ["JWT_SECRET"] = "amrutam-test-only-jwt-secret-key-2026-not-for-production"
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine

@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)
