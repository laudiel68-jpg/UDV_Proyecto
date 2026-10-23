"""Pruebas de catálogos: escenarios G6-01, G6-02, G6-03 y G6-21 a G6-25."""

import pytest
from g2_api.utils.paginacion import PER_PAGE_MAX
from sqlalchemy import insert, select

from g6_admin import tablas
from g6_admin.catalogos import CATALOGOS

RECURSOS = list(CATALOGOS)
VALIDO = {"code": "NORTE", "name": "Sede Norte"}

# Un registro válido de cada catálogo, con los campos de su tabla del G1.
EJEMPLOS = {
    "academic-units": {"code": "UA-ING-N", "name": "Ingeniería - Sede Norte",
                       "faculty_id": 1, "campus_id": 1},
    "campuses": VALIDO,
    "courses": {"code": "ISW-301", "name": "Programación Web", "credits": 4},
    "periods": {"code": "2027-1", "year": 2027, "cycle": 1,
                "start_date": "2027-01-11", "end_date": "2027-06-11"},
    "modalities": {"code": "PRESENCIAL", "name": "Presencial"},
    "areas": {"code": "DES-SW", "name": "Desarrollo de software"},
}
# Un cambio de cada catálogo y cómo debe quedar guardado.
CAMBIOS = {r: ({"name": " Nombre   nuevo "}, {"name": "Nombre nuevo"}) for r in EJEMPLOS}
CAMBIOS["periods"] = ({"end_date": "2027-06-30"}, {"end_date": "2027-06-30"})


@pytest.fixture(autouse=True)
def _sede_para_unidades(fabrica):
    """Las unidades académicas apuntan a una sede (sede_id). Va con id 1000
    para no chocar con las que crean las pruebas de sedes."""
    with fabrica.begin() as sesion:
        sesion.execute(insert(tablas.sede).values(id=1000, codigo="BASE", nombre="Sede base"))
    EJEMPLOS["academic-units"]["campus_id"] = 1000


def crear(cliente, recurso="campuses", datos=None):
    return cliente.post(f"/api/v1/{recurso}",
                        json=EJEMPLOS[recurso] if datos is None else datos)


def sedes(cliente, consulta=""):
    """Sedes creadas por la prueba (sin la sede base de las unidades)."""
    datos = cliente.get(f"/api/v1/campuses{consulta}").json()
    return [r for r in datos["data"] if r["code"] != "BASE"]


def modificar(cliente, registro_id, datos, recurso="campuses"):
    return cliente.patch(f"/api/v1/{recurso}/{registro_id}", json=datos)


def campos_con_error(respuesta) -> set[str]:
    detalles = respuesta.json()["error"]["details"]
    # El G2 usa dos formas: los errores que arma cada grupo llegan como
    # {"items": [{"field": ...}]} y los de Pydantic (tipo de dato, campo no
    # reconocido) como {"campos": [{"campo": ...}]}.
    if isinstance(detalles, dict):
        return ({d["field"] for d in detalles.get("items", [])}
                | {d["campo"] for d in detalles.get("campos", [])})
    return {d["field"] for d in detalles}


# ── G6-01 y G6-21 a G6-25: administración agrega y el registro aparece ────

@pytest.mark.parametrize("recurso", RECURSOS)
def test_admin_agrega_registro_y_el_docente_lo_ve(admin, docente, recurso):
    datos = {**EJEMPLOS[recurso], "code": " norte-1 "}
    if "name" in datos:
        datos["name"] = "  Nombre   con espacios "
    respuesta = crear(admin, recurso, datos)

    assert respuesta.status_code == 201
    creado = respuesta.json()
    assert creado["code"] == "NORTE-1"
    if recurso != "periods":
        assert creado["name"] == "Nombre con espacios"
    assert creado["is_active"] is True

    lista = docente.get(f"/api/v1/{recurso}?q=norte-1").json()
    assert lista["total"] == 1
    assert lista["data"][0] == creado


def test_admin_puede_agregar_registro_inactivo(admin):
    respuesta = crear(admin, datos={**VALIDO, "is_active": False})
    assert respuesta.status_code == 201
    assert respuesta.json()["is_active"] is False


def test_se_guarda_quien_agrego_el_registro(admin):
    creado = crear(admin).json()
    [registro] = admin.get("/api/v1/audit?entity=sede").json()["data"]
    assert (registro["actor_id"], registro["entity_id"]) == (1, creado["id"])


def test_se_guarda_en_la_tabla_del_g1(admin, sesion):
    creado = crear(admin, "courses").json()
    fila = sesion.execute(select(tablas.curso).where(tablas.curso.c.id == creado["id"])).one()
    assert (fila.codigo, fila.nombre, fila.creditos, fila.activo) == (
        "ISW-301", "Programación Web", 4, True)


# ── G6-02 y G6-03: el docente solo consulta; el servidor lo hace cumplir ──

@pytest.mark.parametrize("recurso", RECURSOS)
def test_docente_no_puede_agregar(admin, docente, recurso):
    respuesta = crear(docente, recurso)

    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "FORBIDDEN"
    assert admin.get(f"/api/v1/{recurso}?q={EJEMPLOS[recurso]['code']}").json()["total"] == 0


def test_docente_recibe_403_antes_que_errores_de_validacion(docente):
    # Aunque el cuerpo sea inválido, primero se revisa el permiso.
    assert crear(docente, datos={"code": "x"}).status_code == 403
    assert crear(docente, datos={"code": 123}).status_code == 403


def test_docente_puede_consultar(admin, docente):
    crear(admin)
    respuesta = docente.get("/api/v1/campuses")
    assert respuesta.status_code == 200
    assert len(sedes(docente)) == 1


@pytest.mark.parametrize("metodo", ["get", "post"])
def test_sin_sesion_responde_401(sin_sesion, metodo):
    respuesta = getattr(sin_sesion, metodo)(
        "/api/v1/campuses", **({"json": VALIDO} if metodo == "post" else {}))
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "UNAUTHORIZED"


# ── G6-01 a G6-03: modificar un registro (PATCH) ──────────────────────────

@pytest.mark.parametrize("recurso", RECURSOS)
def test_admin_modifica_registro_y_el_cambio_se_guarda(admin, docente, recurso):
    creado = crear(admin, recurso).json()
    cambio, esperado = CAMBIOS[recurso]

    respuesta = modificar(admin, creado["id"], cambio, recurso)

    assert respuesta.status_code == 200
    modificado = respuesta.json()
    assert modificado == {**creado, **esperado}
    lista = docente.get(f"/api/v1/{recurso}?q={creado['code']}").json()["data"]
    assert lista == [modificado]


def test_admin_puede_desactivar_y_cambiar_codigo(admin):
    creado = crear(admin).json()
    respuesta = modificar(admin, creado["id"], {"code": "norte-2", "is_active": False})
    assert respuesta.status_code == 200
    assert (respuesta.json()["code"], respuesta.json()["is_active"]) == ("NORTE-2", False)


@pytest.mark.parametrize("recurso", RECURSOS)
def test_docente_no_puede_modificar(admin, docente, recurso):
    creado = crear(admin, recurso).json()

    respuesta = modificar(docente, creado["id"], CAMBIOS[recurso][0], recurso)

    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "FORBIDDEN"
    assert admin.get(f"/api/v1/{recurso}?q={creado['code']}").json()["data"] == [creado]


def test_docente_recibe_403_al_modificar_antes_que_404_o_422(docente):
    # Un docente no puede averiguar qué registros existen ni probar datos.
    assert modificar(docente, 999, {"name": "x"}).status_code == 403
    assert modificar(docente, 999, {}).status_code == 403


def test_sin_sesion_no_puede_modificar(admin, sin_sesion):
    creado = crear(admin).json()
    respuesta = modificar(sin_sesion, creado["id"], {"name": "Sin sesión"})
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "UNAUTHORIZED"


def test_modificar_registro_inexistente_da_404(admin):
    respuesta = modificar(admin, 999, {"name": "No existe"})
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "NOT_FOUND"


def test_registro_de_otro_catalogo_da_404(admin):
    creado = crear(admin, "campuses").json()
    assert modificar(admin, creado["id"], {"name": "Otra"}, "areas").status_code == 404


def test_modificar_sin_campos_da_422(admin):
    creado = crear(admin).json()
    respuesta = modificar(admin, creado["id"], {})
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "EMPTY_UPDATE"


def test_modificar_valida_los_campos_enviados(admin):
    creado = crear(admin).json()
    respuesta = modificar(admin, creado["id"], {"code": "A", "name": None})
    assert respuesta.status_code == 422
    assert campos_con_error(respuesta) == {"code", "name"}
    assert sedes(admin)[0]["code"] == "NORTE"


def test_modificar_a_un_codigo_ya_usado_da_409(admin):
    crear(admin)
    otro = crear(admin, datos={"code": "SUR", "name": "Sede Sur"}).json()

    respuesta = modificar(admin, otro["id"], {"code": "norte"})

    assert respuesta.status_code == 409
    assert campos_con_error(respuesta) == {"code"}


def test_modificar_conservando_su_propio_codigo(admin):
    creado = crear(admin).json()
    assert modificar(admin, creado["id"], {"code": "NORTE", "name": "Norte"}).status_code == 200


# ── Validación (422) y conflicto (409) ────────────────────────────────────

def test_campos_obligatorios_dan_422_con_detalle_por_campo(admin):
    respuesta = crear(admin, datos={})
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "VALIDATION_ERROR"
    assert campos_con_error(respuesta) == {"code", "name"}


@pytest.mark.parametrize("codigo", ["A", "CON ESPACIO", "SEDE-Ñ", "X" * 21, "-NORTE"])
def test_codigo_con_formato_invalido(admin, codigo):
    respuesta = crear(admin, datos={"code": codigo, "name": "Sede"})
    assert respuesta.status_code == 422
    assert "code" in campos_con_error(respuesta)


@pytest.mark.parametrize("recurso, largo", [("campuses", 151), ("areas", 101)])
def test_nombre_demasiado_largo(admin, recurso, largo):
    # El largo máximo es el de la columna nombre del G1.
    respuesta = crear(admin, recurso, {"code": "LARGO", "name": "a" * largo})
    assert respuesta.status_code == 422
    assert "name" in campos_con_error(respuesta)
    assert crear(admin, recurso, {"code": "LARGO", "name": "a" * (largo - 1)}).status_code == 201


# ── Campos propios de cada tabla del G1 ────────────────────────────────────

@pytest.mark.parametrize("recurso, faltan", [
    ("academic-units", {"code", "name", "faculty_id", "campus_id"}),
    ("courses", {"code", "name", "credits"}),
    ("periods", {"code", "year", "cycle", "start_date", "end_date"}),
])
def test_campos_obligatorios_de_cada_catalogo(admin, recurso, faltan):
    respuesta = crear(admin, recurso, {})
    assert respuesta.status_code == 422
    assert campos_con_error(respuesta) == faltan


def test_unidad_con_facultad_o_sede_inexistente_da_422(admin):
    respuesta = crear(admin, "academic-units",
                      {**EJEMPLOS["academic-units"], "faculty_id": 99, "campus_id": 98})
    assert respuesta.status_code == 422
    assert campos_con_error(respuesta) == {"faculty_id", "campus_id"}


@pytest.mark.parametrize("cambio, campo", [
    ({"credits": 0}, "credits"), ({"credits": 31}, "credits"), ({"credits": "x"}, "credits")])
def test_creditos_fuera_de_rango(admin, cambio, campo):
    respuesta = crear(admin, "courses", {**EJEMPLOS["courses"], **cambio})
    assert respuesta.status_code == 422
    assert campo in campos_con_error(respuesta)


@pytest.mark.parametrize("cambio, campo", [
    ({"end_date": "2027-01-01"}, "end_date"),       # termina antes de empezar
    ({"start_date": "11/01/2027"}, "start_date"),   # formato
    ({"cycle": 5}, "cycle"),
    ({"year": 1999}, "year"),
])
def test_periodo_invalido(admin, cambio, campo):
    respuesta = crear(admin, "periods", {**EJEMPLOS["periods"], **cambio})
    assert respuesta.status_code == 422
    assert campo in campos_con_error(respuesta)


def test_periodo_con_el_mismo_anio_y_ciclo_da_409(admin):
    crear(admin, "periods")
    respuesta = crear(admin, "periods", {**EJEMPLOS["periods"], "code": "OTRO"})
    assert respuesta.status_code == 409
    assert campos_con_error(respuesta) == {"cycle"}


def test_cambiar_solo_la_fecha_final_revisa_contra_la_inicial(admin):
    creado = crear(admin, "periods").json()
    respuesta = modificar(admin, creado["id"], {"end_date": "2026-12-31"}, "periods")
    assert respuesta.status_code == 422
    assert campos_con_error(respuesta) == {"end_date"}


def test_periodo_muestra_un_nombre_armado(admin):
    assert crear(admin, "periods").json()["name"] == "Ciclo 1 de 2027"


def test_sede_con_direccion_opcional(admin):
    creado = crear(admin, datos={**VALIDO, "address": "  Zona 10  "}).json()
    assert creado["address"] == "Zona 10"
    assert modificar(admin, creado["id"], {"address": None}).json()["address"] is None


def test_curso_eliminado_por_el_g1_no_se_lista(admin, fabrica):
    creado = crear(admin, "courses").json()
    with fabrica.begin() as sesion:
        sesion.execute(tablas.curso.update().values(eliminado_en=tablas.curso.c.creado_en))
    assert admin.get("/api/v1/courses").json()["total"] == 0
    assert modificar(admin, creado["id"], {"credits": 3}, "courses").status_code == 404


def test_facultades_para_elegir(docente):
    facultades = docente.get("/api/v1/faculties").json()
    assert [f["code"] for f in facultades] == ["FCE", "FING"]


def test_campo_no_reconocido(admin):
    respuesta = crear(admin, datos={**VALIDO, "color": "azul"})
    assert respuesta.status_code == 422
    assert "color" in campos_con_error(respuesta)


def test_tipo_de_dato_incorrecto(admin):
    respuesta = crear(admin, datos={"code": 123, "name": "Sede"})
    assert respuesta.status_code == 422
    assert "code" in campos_con_error(respuesta)


def test_codigo_duplicado_da_409_sin_importar_mayusculas(admin):
    assert crear(admin).status_code == 201
    respuesta = crear(admin, datos={"code": "norte", "name": "Otra sede"})
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["code"] == "CONFLICT"
    assert campos_con_error(respuesta) == {"code"}


def test_mismo_codigo_se_permite_en_otro_catalogo(admin):
    assert crear(admin, "campuses").status_code == 201
    assert crear(admin, "areas").status_code == 201


def test_todo_error_usa_el_formato_comun(admin, docente, sin_sesion):
    respuestas = [
        crear(admin, datos={}),                  # 422
        crear(admin, datos={"code": 1}),         # 422 de tipo de dato
        crear(docente),                          # 403
        sin_sesion.get("/api/v1/campuses"),      # 401
        admin.get("/api/v1/no-existe"),          # 404
    ]
    for respuesta in respuestas:
        assert {"code", "message", "details"} <= set(respuesta.json()["error"])


# ── Listado: paginación, búsqueda, filtro y orden ─────────────────────────

def test_paginacion_con_la_forma_del_contrato(admin):
    for numero in range(25):
        crear(admin, datos={"code": f"S-{numero:02d}", "name": f"Sede {numero:02d}"})

    pagina = admin.get("/api/v1/campuses?q=S-&page=3&per_page=10").json()
    assert set(pagina) == {"page", "per_page", "total", "data"}
    assert (pagina["page"], pagina["per_page"], pagina["total"]) == (3, 10, 25)
    assert len(pagina["data"]) == 5


@pytest.mark.parametrize("consulta", [f"per_page={PER_PAGE_MAX + 1}", "per_page=0", "page=0"])
def test_parametros_de_paginacion_fuera_de_rango(admin, consulta):
    assert admin.get(f"/api/v1/campuses?{consulta}").status_code == 422


def test_busqueda_ignora_mayusculas_y_tildes(admin):
    crear(admin, "areas", {"code": "ING", "name": "Ingeniería"})
    crear(admin, "areas", {"code": "ECO", "name": "Economía"})

    resultado = admin.get("/api/v1/areas?q=INGENIERIA").json()
    assert [r["code"] for r in resultado["data"]] == ["ING"]


def test_filtro_por_activos(admin):
    crear(admin, datos={"code": "ACTIVA", "name": "Activa"})
    crear(admin, datos={"code": "CERRADA", "name": "Cerrada", "is_active": False})

    resultado = sedes(admin, "?active=false")
    assert [r["code"] for r in resultado] == ["CERRADA"]


def test_lista_ordenada_por_nombre(admin):
    for code, name in [("C", "Zacapa"), ("A", "Antigua"), ("B", "Escuintla")]:
        crear(admin, datos={"code": f"{code}{code}", "name": name})
    nombres = [r["name"] for r in sedes(admin)]
    assert nombres == ["Antigua", "Escuintla", "Zacapa"]


# ── OpenAPI: las rutas coinciden con el CONTRATO.md del G6 ────────────────

def test_openapi_incluye_las_rutas_de_catalogos_del_contrato(admin):
    rutas = admin.get("/openapi.json").json()["paths"]
    for recurso in RECURSOS:
        assert {"get", "post"} <= set(rutas[f"/api/v1/{recurso}"])
        assert "patch" in rutas[f"/api/v1/{recurso}/{{registro_id}}"]
