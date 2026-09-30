import pytest
from fastapi.testclient import TestClient

from g6_admin.app_demo import crear_app_demo


@pytest.fixture
def cliente() -> TestClient:
    """App de demostración vacía: cada prueba empieza sin registros."""
    return TestClient(crear_app_demo(auth_demo=True, datos_ejemplo=False))
