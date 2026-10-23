"""Preparación de las pruebas del G6.

Las rutas se prueban con el formato de error y el control de roles reales del
G2. Lo único que se reemplaza es quién inició sesión, con la herramienta de
FastAPI para pruebas (dependency_overrides): así cada prueba elige si actúa
como administración, como docente o sin sesión.

Las tablas son las del G1 (g6_admin/tablas.py) creadas en un SQLite en
memoria, nuevo en cada prueba. Las pruebas contra el MySQL real del G1 están
en tests/integracion/ y corren solo si se define G6_MYSQL_URL.
"""

import os
import tempfile
from types import SimpleNamespace

# g2_api lee su configuración al importarse: valores solo para pruebas, igual
# que en el conftest del G2. La base es un SQLite temporal, nunca MySQL.
_carpeta = tempfile.mkdtemp()
os.environ["SECRET_KEY"] = "clave-solo-para-pruebas-g6"
os.environ["DATABASE_URL"] = f"sqlite:///{_carpeta}/pruebas_g6.db"

import pytest  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from g2_api.database import get_db  # noqa: E402
from g2_api.middleware.auth_middleware import obtener_usuario_actual  # noqa: E402
from g2_api.middleware.error_handler import register_error_handlers  # noqa: E402
from sqlalchemy import create_engine, insert  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from g6_admin import api, tablas  # noqa: E402
from g6_admin.auditoria import RepositorioAuditoria, ServicioAuditoria  # noqa: E402
from g6_admin.catalogos import RepositorioCatalogos, ServicioCatalogos  # noqa: E402
from g6_admin.notificaciones import (  # noqa: E402
    RepositorioNotificaciones, ServicioNotificaciones)


def _usuario(id_: int, correo: str, rol: str) -> SimpleNamespace:
    """Usuario ficticio con la forma del modelo `Usuario` del G2.

    Desde el 22-oct `obtener_usuario_actual` devuelve el registro de la base
    (no un diccionario) y `requerir_rol` lee `usuario.roles[i].codigo`.
    """
    return SimpleNamespace(id=id_, correo=correo, activo=True,
                           roles=[SimpleNamespace(codigo=rol)])


# Usuarios ficticios con los códigos de rol de la tabla `rol` del G1.
ADMINISTRACION = _usuario(1, "admin@ejemplo.test", "admin")
DOCENTE = _usuario(2, "docente@ejemplo.test", "teacher")


def _cliente(fabrica: sessionmaker, usuario: SimpleNamespace | None, *,
             levantar_errores: bool = True) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)          # formato de error del G2
    app.include_router(api.router)        # igual que lo monta main.py

    def usuario_de_prueba():
        if usuario is None:
            raise HTTPException(status_code=401, detail="Usuario no autenticado")
        return usuario

    def sesion_de_prueba():
        with fabrica() as sesion:
            yield sesion

    app.dependency_overrides[obtener_usuario_actual] = usuario_de_prueba
    app.dependency_overrides[get_db] = sesion_de_prueba
    # levantar_errores=False deja ver el 500 que recibe el cliente.
    return TestClient(app, raise_server_exceptions=levantar_errores)


@pytest.fixture
def fabrica() -> sessionmaker:
    """Base vacía con las tablas del G1 y dos facultades (las siembra el G1)."""
    motor = create_engine("sqlite://", poolclass=StaticPool,
                          connect_args={"check_same_thread": False})
    tablas.metadata.create_all(motor)
    with motor.begin() as conexion:
        conexion.execute(insert(tablas.facultad), [
            {"id": 1, "codigo": "FING", "nombre": "Facultad de Ingeniería"},
            {"id": 2, "codigo": "FCE", "nombre": "Facultad de Ciencias Económicas"}])
    return sessionmaker(bind=motor)


@pytest.fixture
def sesion(fabrica) -> Session:
    with fabrica() as s:
        yield s


@pytest.fixture
def auditoria(sesion) -> ServicioAuditoria:
    return ServicioAuditoria(RepositorioAuditoria(sesion))


@pytest.fixture
def servicio(sesion, auditoria) -> ServicioCatalogos:
    return ServicioCatalogos(RepositorioCatalogos(sesion), auditoria)


@pytest.fixture
def notificaciones(sesion) -> ServicioNotificaciones:
    return ServicioNotificaciones(RepositorioNotificaciones(sesion))


@pytest.fixture
def admin(fabrica) -> TestClient:
    return _cliente(fabrica, ADMINISTRACION)


@pytest.fixture
def docente(fabrica) -> TestClient:
    return _cliente(fabrica, DOCENTE)


@pytest.fixture
def sin_sesion(fabrica) -> TestClient:
    return _cliente(fabrica, None)
