import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_amrutam.db")
os.environ["JWT_SECRET"] = "amrutam-test-only-jwt-secret-key-2026-not-for-production"
from cryptography.fernet import Fernet
os.environ["MFA_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine
import app.rate_limit as rate_limit_module
from app.rate_limit import reset_rate_limits

@pytest.fixture()
def client(monkeypatch):
    # Keep endpoint tests isolated from any configured external Redis.
    monkeypatch.setattr(rate_limit_module, '_redis', None)
    reset_rate_limits()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)
