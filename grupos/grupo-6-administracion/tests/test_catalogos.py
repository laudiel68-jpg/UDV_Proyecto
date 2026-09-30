"""Pruebas de catálogos: escenarios G6-01, G6-02, G6-03 y G6-21 a G6-25."""

import pytest
from fastapi.testclient import TestClient

from g6_admin.app_demo import crear_app_demo
from g6_admin.catalogos import CATALOGOS, RepositorioEnMemoria, ServicioCatalogos
from g6_admin.errores import ErrorApi
from g6_admin.seguridad import USUARIOS_DEMO

ADMIN = {"X-Demo-Role": "admin"}
DOCENTE = {"X-Demo-Role": "teacher"}
RECURSOS = list(CATALOGOS)
VALIDO = {"code": "NORTE", "name": "Sede Norte"}


def crear(cliente, recurso="campuses", datos=None, encabezados=ADMIN):
    return cliente.post(f"/api/v1/{recurso}", json=VALIDO if datos is None else datos,
                       headers=encabezados)


# ── G6-01 y G6-21 a G6-25: administración crea y el registro aparece ──────

@pytest.mark.parametrize("recurso", RECURSOS)
def test_admin_crea_registro_y_aparece_en_la_lista(cliente, recurso):
    respuesta = crear(cliente, recurso, {"code": " norte-1 ", "name": "  Sede   Norte "})

    assert respuesta.status_code == 201
    creado = respuesta.json()
    assert creado["code"] == "NORTE-1"
    assert creado["name"] == "Sede Norte"
    assert creado["is_active"] is True

    lista = cliente.get(f"/api/v1/{recurso}", headers=ADMIN).json()
    assert lista["total"] == 1
    assert lista["data"][0]["id"] == creado["id"]


def test_admin_puede_crear_registro_inactivo(cliente):
    respuesta = crear(cliente, datos={**VALIDO, "is_active": False})
    assert respuesta.status_code == 201
    assert respuesta.json()["is_active"] is False


# ── G6-02 y G6-03: sin permiso de administración se rechaza en el servidor ──

@pytest.mark.parametrize("recurso", RECURSOS)
def test_docente_no_puede_modificar_catalogo(cliente, recurso):
    respuesta = crear(cliente, recurso, encabezados=DOCENTE)

    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "FORBIDDEN"
    assert cliente.get(f"/api/v1/{recurso}", headers=ADMIN).json()["total"] == 0


def test_docente_sin_permiso_recibe_403_antes_que_errores_de_validacion(cliente):
    # Aunque el cuerpo sea inválido, primero se revisa el permiso.
    respuesta = crear(cliente, datos={"code": "x"}, encabezados=DOCENTE)
    assert respuesta.status_code == 403


def test_docente_puede_consultar_catalogos(cliente):
    crear(cliente)
    respuesta = cliente.get("/api/v1/campuses", headers=DOCENTE)
    assert respuesta.status_code == 200
    assert respuesta.json()["total"] == 1


@pytest.mark.parametrize("metodo", ["get", "post"])
def test_sin_sesion_responde_401(cliente, metodo):
    respuesta = getattr(cliente, metodo)("/api/v1/campuses", **(
        {"json": VALIDO} if metodo == "post" else {}))
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "UNAUTHENTICATED"


def test_rol_desconocido_responde_401(cliente):
    assert crear(cliente, encabezados={"X-Demo-Role": "superusuario"}).status_code == 401


def test_fuera_de_la_demo_el_encabezado_de_prueba_no_da_acceso():
    cliente = TestClient(crear_app_demo(auth_demo=False, datos_ejemplo=False))
    assert crear(cliente).status_code == 401
    assert cliente.get("/api/v1/campuses", headers=ADMIN).status_code == 401


def test_servicio_rechaza_docente_sin_pasar_por_http():
    servicio = ServicioCatalogos(RepositorioEnMemoria())
    with pytest.raises(ErrorApi) as error:
        servicio.crear("campuses", VALIDO, USUARIOS_DEMO["teacher"])
    assert error.value.estado_http == 403


# ── Validación (422), conflicto (409) y solicitud mal formada (400) ────────

def test_campos_obligatorios_dan_422_con_detalle_por_campo(cliente):
    respuesta = crear(cliente, datos={})
    assert respuesta.status_code == 422
    error = respuesta.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert set(error["details"]) == {"code", "name"}


@pytest.mark.parametrize("codigo", ["A", "CON ESPACIO", "SEDE-Ñ", "X" * 21, "-NORTE"])
def test_codigo_con_formato_invalido(cliente, codigo):
    respuesta = crear(cliente, datos={"code": codigo, "name": "Sede"})
    assert respuesta.status_code == 422
    assert "code" in respuesta.json()["error"]["details"]


def test_nombre_demasiado_largo(cliente):
    respuesta = crear(cliente, datos={"code": "LARGO", "name": "a" * 121})
    assert respuesta.status_code == 422
    assert "name" in respuesta.json()["error"]["details"]


def test_campo_no_reconocido(cliente):
    respuesta = crear(cliente, datos={**VALIDO, "color": "azul"})
    assert respuesta.status_code == 422
    assert "color" in respuesta.json()["error"]["details"]


def test_tipo_de_dato_incorrecto(cliente):
    respuesta = crear(cliente, datos={"code": 123, "name": "Sede"})
    assert respuesta.status_code == 422
    assert "code" in respuesta.json()["error"]["details"]


def test_codigo_duplicado_da_409_sin_importar_mayusculas(cliente):
    assert crear(cliente).status_code == 201
    respuesta = crear(cliente, datos={"code": "norte", "name": "Otra sede"})
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["code"] == "CONFLICT"


def test_mismo_codigo_se_permite_en_otro_catalogo(cliente):
    assert crear(cliente, "campuses").status_code == 201
    assert crear(cliente, "areas").status_code == 201


def test_json_mal_formado_da_400(cliente):
    respuesta = cliente.post("/api/v1/campuses", content="{sin cerrar",
                             headers={**ADMIN, "Content-Type": "application/json"})
    assert respuesta.status_code == 400
    assert respuesta.json()["error"]["code"] == "BAD_REQUEST"


def test_todo_error_usa_el_formato_comun(cliente):
    respuestas = [
        crear(cliente, datos={}),                    # 422
        crear(cliente, encabezados=DOCENTE),         # 403
        cliente.get("/api/v1/campuses"),             # 401
        cliente.get("/api/v1/no-existe", headers=ADMIN),  # 404
    ]
    for respuesta in respuestas:
        assert set(respuesta.json()) == {"error"}
        assert set(respuesta.json()["error"]) == {"code", "message", "details"}


# ── Listado: paginación, búsqueda, filtro y orden ─────────────────────────

def test_paginacion_con_la_forma_del_contrato(cliente):
    for numero in range(25):
        crear(cliente, datos={"code": f"S-{numero:02d}", "name": f"Sede {numero:02d}"})

    pagina = cliente.get("/api/v1/campuses?page=3&per_page=10", headers=ADMIN).json()
    assert set(pagina) == {"page", "per_page", "total", "data"}
    assert (pagina["page"], pagina["per_page"], pagina["total"]) == (3, 10, 25)
    assert len(pagina["data"]) == 5


@pytest.mark.parametrize("consulta", ["per_page=101", "per_page=0", "page=0"])
def test_parametros_de_paginacion_fuera_de_rango(cliente, consulta):
    respuesta = cliente.get(f"/api/v1/campuses?{consulta}", headers=ADMIN)
    assert respuesta.status_code == 422


def test_busqueda_ignora_mayusculas_y_tildes(cliente):
    crear(cliente, "periods", {"code": "2026-S1", "name": "Primer período 2026"})
    crear(cliente, "periods", {"code": "2026-S2", "name": "Segundo período 2026"})

    resultado = cliente.get("/api/v1/periods?q=PRIMER periodo", headers=ADMIN).json()
    assert [r["code"] for r in resultado["data"]] == ["2026-S1"]


def test_filtro_por_activos(cliente):
    crear(cliente, datos={"code": "ACTIVA", "name": "Activa"})
    crear(cliente, datos={"code": "CERRADA", "name": "Cerrada", "is_active": False})

    resultado = cliente.get("/api/v1/campuses?active=false", headers=ADMIN).json()
    assert [r["code"] for r in resultado["data"]] == ["CERRADA"]


def test_lista_ordenada_por_nombre(cliente):
    for code, name in [("C", "Zacapa"), ("A", "Antigua"), ("B", "Escuintla")]:
        crear(cliente, datos={"code": f"{code}{code}", "name": name})
    nombres = [r["name"] for r in cliente.get("/api/v1/campuses", headers=ADMIN).json()["data"]]
    assert nombres == ["Antigua", "Escuintla", "Zacapa"]


# ── OpenAPI: las rutas coinciden con el CONTRATO.md del G6 ────────────────

def test_openapi_incluye_las_rutas_de_catalogos_del_contrato(cliente):
    rutas = cliente.get("/openapi.json").json()["paths"]
    for recurso in RECURSOS:
        assert {"get", "post"} <= set(rutas[f"/api/v1/{recurso}"])
