"""G6-18: si algo falla a mitad de una operación, no quedan datos a medias.

Se simula que la auditoría no se puede guardar (por ejemplo, se cayó la base)
justo después de guardar el registro del catálogo. El registro no debe quedar
sin su auditoría: o se guardan los dos, o ninguno.
"""

import pytest
from conftest import ADMINISTRACION, _cliente
from sqlalchemy import func, select

from g6_admin import api, tablas
from g6_admin.auditoria import RepositorioAuditoria, ServicioAuditoria
from g6_admin.catalogos import RepositorioCatalogos, ServicioCatalogos

NUEVO = {"code": "CEN", "name": "Central"}


class AuditoriaQueFalla(RepositorioAuditoria):
    """Guarda normal hasta que se le pide fallar."""

    fallar = False

    def agregar(self, **datos):
        if AuditoriaQueFalla.fallar:
            raise ConnectionError("la base no responde")
        return super().agregar(**datos)


@pytest.fixture(autouse=True)
def _reiniciar():
    AuditoriaQueFalla.fallar = False


@pytest.fixture
def cliente(fabrica):
    cliente = _cliente(fabrica, ADMINISTRACION, levantar_errores=False)

    def servicio_fragil(db: api.Sesion) -> ServicioCatalogos:
        return ServicioCatalogos(RepositorioCatalogos(db),
                                 ServicioAuditoria(AuditoriaQueFalla(db)))

    cliente.app.dependency_overrides[api.obtener_servicio] = servicio_fragil
    return cliente


def contar(sesion, tabla) -> int:
    return sesion.execute(select(func.count()).select_from(tabla)).scalar_one()


def test_alta_sin_auditoria_no_deja_el_registro(cliente, sesion):
    AuditoriaQueFalla.fallar = True
    respuesta = cliente.post("/api/v1/campuses", json=NUEVO)

    assert respuesta.status_code == 500
    assert contar(sesion, tablas.sede) == 0
    assert contar(sesion, tablas.auditoria) == 0


def test_alta_fallida_no_deja_ocupado_el_codigo(cliente):
    AuditoriaQueFalla.fallar = True
    cliente.post("/api/v1/campuses", json=NUEVO)
    AuditoriaQueFalla.fallar = False

    respuesta = cliente.post("/api/v1/campuses", json=NUEVO)
    assert respuesta.status_code == 201


def test_cambio_sin_auditoria_deja_el_registro_como_estaba(cliente, sesion):
    creado = cliente.post("/api/v1/courses",
                          json={"code": "PW", "name": "Programación Web", "credits": 4})
    registro_id = creado.json()["id"]

    AuditoriaQueFalla.fallar = True
    respuesta = cliente.patch(f"/api/v1/courses/{registro_id}",
                              json={"code": "PW2", "name": "Otro nombre", "is_active": False})

    assert respuesta.status_code == 500
    fila = sesion.execute(select(tablas.curso)).one()
    assert (fila.codigo, fila.nombre, fila.activo) == ("PW", "Programación Web", True)
    # Solo queda la auditoría del alta, no la del cambio que falló.
    acciones = sesion.execute(select(tablas.auditoria.c.accion)).scalars().all()
    assert acciones == ["insert"]


def test_el_500_no_muestra_el_error_interno(cliente):
    AuditoriaQueFalla.fallar = True
    respuesta = cliente.post("/api/v1/modalities", json={"code": "VIR", "name": "Virtual"})

    assert respuesta.status_code == 500
    assert "la base no responde" not in respuesta.text
    assert respuesta.json()["error"]["code"] == "INTERNAL_ERROR"


def test_un_rechazo_tampoco_deja_nada(cliente, sesion):
    """Un 409 a mitad de la operación tampoco deja cambios ni auditoría."""
    cliente.post("/api/v1/areas", json={"code": "ING", "name": "Ingeniería"})
    segunda = cliente.post("/api/v1/areas", json={"code": "SAL", "name": "Salud"}).json()

    respuesta = cliente.patch(f"/api/v1/areas/{segunda['id']}",
                              json={"code": "ING", "name": "Otro"})

    assert respuesta.status_code == 409
    assert set(sesion.execute(select(tablas.area.c.codigo)).scalars()) == {"ING", "SAL"}
    assert contar(sesion, tablas.auditoria) == 2
