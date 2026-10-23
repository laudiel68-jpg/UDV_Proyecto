"""Preparación de las pruebas del G6.

Las rutas se prueban con el formato de error y el control de roles reales del
G2. Lo único que se reemplaza es quién inició sesión, con la herramienta de
FastAPI para pruebas (dependency_overrides): así cada prueba elige si actúa
como administración, como docente o sin sesión, sin tocar la base de datos.
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
from g2_api.middleware.auth_middleware import obtener_usuario_actual  # noqa: E402
from g2_api.middleware.error_handler import register_error_handlers  # noqa: E402

from g6_admin import api  # noqa: E402
from g6_admin.auditoria import RepositorioAuditoriaEnMemoria, ServicioAuditoria  # noqa: E402
from g6_admin.catalogos import RepositorioEnMemoria, ServicioCatalogos  # noqa: E402
from g6_admin.notificaciones import (  # noqa: E402
    RepositorioNotificacionesEnMemoria, ServicioNotificaciones)



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


def _cliente(servicio: ServicioCatalogos, usuario: SimpleNamespace | None,
             notificaciones: ServicioNotificaciones, *,
             levantar_errores: bool = True) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)          # formato de error del G2
    app.include_router(api.router)        # igual que lo monta main.py

    def usuario_de_prueba():
        if usuario is None:
            raise HTTPException(status_code=401, detail="Usuario no autenticado")
        return usuario

    app.dependency_overrides[obtener_usuario_actual] = usuario_de_prueba
    app.dependency_overrides[api.obtener_servicio] = lambda: servicio
    app.dependency_overrides[api.obtener_auditoria] = lambda: servicio.auditoria
    app.dependency_overrides[api.obtener_notificaciones] = lambda: notificaciones
    # levantar_errores=False deja ver el 500 que recibe el cliente.
    return TestClient(app, raise_server_exceptions=levantar_errores)


@pytest.fixture
def auditoria() -> ServicioAuditoria:
    return ServicioAuditoria(RepositorioAuditoriaEnMemoria())


@pytest.fixture
def servicio(auditoria) -> ServicioCatalogos:
    """Catálogos vacíos: cada prueba empieza sin registros ni auditoría."""
    return ServicioCatalogos(RepositorioEnMemoria(), auditoria)


@pytest.fixture
def notificaciones() -> ServicioNotificaciones:
    return ServicioNotificaciones(RepositorioNotificacionesEnMemoria())


@pytest.fixture
def admin(servicio, notificaciones) -> TestClient:
    return _cliente(servicio, ADMINISTRACION, notificaciones)


@pytest.fixture
def docente(servicio, notificaciones) -> TestClient:
    return _cliente(servicio, DOCENTE, notificaciones)


@pytest.fixture
def sin_sesion(servicio, notificaciones) -> TestClient:
    return _cliente(servicio, None, notificaciones)
