"""G6-18: si algo falla a mitad de una operación, no quedan datos a medias.

Se simula que la auditoría no se puede guardar (por ejemplo, se cayó la base)
justo después de guardar el registro del catálogo. El registro no debe quedar
sin su auditoría: o se guardan los dos, o ninguno.
"""

import pytest
from conftest import ADMINISTRACION, _cliente

from g6_admin.auditoria import RepositorioAuditoriaEnMemoria, ServicioAuditoria
from g6_admin.catalogos import RepositorioEnMemoria, ServicioCatalogos


class AuditoriaQueFalla(RepositorioAuditoriaEnMemoria):
    """Guarda normal hasta que se le pide fallar."""

    def __init__(self) -> None:
        super().__init__()
        self.fallar = False

    def agregar(self, **datos):
        if self.fallar:
            raise ConnectionError("la base no responde")
        return super().agregar(**datos)


@pytest.fixture
def repo_auditoria() -> AuditoriaQueFalla:
    return AuditoriaQueFalla()


@pytest.fixture
def servicio_fragil(repo_auditoria) -> ServicioCatalogos:
    return ServicioCatalogos(RepositorioEnMemoria(), ServicioAuditoria(repo_auditoria))


@pytest.fixture
def cliente(servicio_fragil, notificaciones):
    return _cliente(servicio_fragil, ADMINISTRACION, notificaciones,
                    levantar_errores=False)


def test_alta_sin_auditoria_no_deja_el_registro(cliente, servicio_fragil, repo_auditoria):
    repo_auditoria.fallar = True
    respuesta = cliente.post("/api/v1/campuses", json={"code": "CEN", "name": "Central"})

    assert respuesta.status_code == 500
    assert servicio_fragil.listar("campuses") == []
    assert repo_auditoria.listar() == []


def test_alta_fallida_no_gasta_el_id(cliente, servicio_fragil, repo_auditoria):
    repo_auditoria.fallar = True
    cliente.post("/api/v1/campuses", json={"code": "CEN", "name": "Central"})
    repo_auditoria.fallar = False

    respuesta = cliente.post("/api/v1/campuses", json={"code": "CEN", "name": "Central"})
    # El código ya se puede volver a usar y el registro sale con el primer id.
    assert respuesta.status_code == 201
    assert respuesta.json()["id"] == 1


def test_cambio_sin_auditoria_deja_el_registro_como_estaba(cliente, servicio_fragil,
                                                           repo_auditoria):
    creado = cliente.post("/api/v1/courses", json={"code": "PW", "name": "Programación Web"})
    registro_id = creado.json()["id"]

    repo_auditoria.fallar = True
    respuesta = cliente.patch(f"/api/v1/courses/{registro_id}",
                              json={"code": "PW2", "name": "Otro nombre", "is_active": False})

    assert respuesta.status_code == 500
    [registro] = servicio_fragil.listar("courses")
    assert (registro["code"], registro["name"], registro["is_active"]) == (
        "PW", "Programación Web", True)
    # Solo queda la auditoría del alta, no la del cambio que falló.
    assert [r.accion for r in repo_auditoria.listar()] == ["create"]


def test_el_500_no_muestra_el_error_interno(cliente, repo_auditoria):
    repo_auditoria.fallar = True
    respuesta = cliente.post("/api/v1/periods", json={"code": "2026-2", "name": "Segundo 2026"})

    assert respuesta.status_code == 500
    assert "la base no responde" not in respuesta.text
    assert respuesta.json()["error"]["code"] == "INTERNAL_ERROR"


def test_un_rechazo_tampoco_deja_nada(servicio_fragil, repo_auditoria):
    """Un 409 a mitad de la operación tampoco deja cambios ni auditoría."""
    servicio_fragil.crear("areas", {"code": "ING", "name": "Ingeniería"}, ADMINISTRACION.id)
    servicio_fragil.crear("areas", {"code": "SAL", "name": "Salud"}, ADMINISTRACION.id)

    with pytest.raises(Exception):
        servicio_fragil.modificar("areas", 2, {"code": "ING"}, ADMINISTRACION.id)

    assert {r["code"] for r in servicio_fragil.listar("areas")} == {"ING", "SAL"}
    assert len(repo_auditoria.listar()) == 2
