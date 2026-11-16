# Pruebas de OpenAPI (G2-33, Persona 5): Swagger debe coincidir con lo que responde la API.
from datetime import datetime

from g2_api.main import app
from tests.test_users import headers_admin, sembrado  # noqa: F401  (fixtures de la base de prueba)

def _resp(ruta, metodo):
    return app.openapi()["paths"][ruta][metodo]["responses"]

def test_post_users_documenta_401_403_409_y_422():
    r = _resp("/api/v1/users", "post")
    for codigo in ("201", "401", "403", "409", "422"):
        assert codigo in r

def test_get_users_documenta_403_y_ejemplo_paginado():
    r = _resp("/api/v1/users", "get")
    assert "403" in r
    ejemplo = r["200"]["content"]["application/json"]["example"]
    assert set(ejemplo) == {"page", "per_page", "total", "data"}

def test_me_documenta_401_y_ejemplo_objeto():
    r = _resp("/api/v1/me", "get")
    assert "401" in r
    assert isinstance(r["200"]["content"]["application/json"]["example"], dict)

def test_me_ejemplo_coincide_con_la_respuesta_real_y_no_trae_fechas(client, headers_admin):
    ejemplo = _resp("/api/v1/me", "get")["200"]["content"]["application/json"]["example"]
    real = client.get("/api/v1/me", headers=headers_admin).json()
    assert set(ejemplo) == set(real)
    assert "creado_en" not in ejemplo and "actualizado_en" not in ejemplo

def test_descarga_de_archivos_documenta_la_regla_de_permisos():
    descripcion = _resp("/api/v1/files/{id}", "get")["200"]["description"]
    for texto in ("dueño", "admin", "files.download", "docente"):
        assert texto in descripcion

def test_422_usa_el_formato_comun_de_errores():
    ejemplo = _resp("/api/v1/users", "post")["422"]["content"]["application/json"]["example"]
    assert set(ejemplo["error"]) == {"code", "message", "details"}

def test_422_documenta_details_como_objeto_con_un_campo_por_llave():
    ejemplo = _resp("/api/v1/users", "post")["422"]["content"]["application/json"]["example"]
    detalles = ejemplo["error"]["details"]
    assert isinstance(detalles, dict) and detalles
    assert all(isinstance(mensaje, str) for mensaje in detalles.values())

def test_ejemplo_de_usuario_trae_fechas_iso_con_zona_horaria():
    ejemplo = _resp("/api/v1/users/{usuario_id}", "get")["200"]["content"]["application/json"]["example"]
    for campo in ("creado_en", "actualizado_en"):
        assert datetime.fromisoformat(ejemplo[campo].replace("Z", "+00:00")).tzinfo is not None

def test_login_documenta_el_bloqueo_429_con_los_minutos_que_faltan():
    r = _resp("/api/v1/auth/login", "post")
    assert {"200", "401", "422", "429"} <= set(r)
    ejemplo = r["429"]["content"]["application/json"]["example"]
    assert ejemplo["error"]["code"] == "TOO_MANY_REQUESTS"
    assert "minutos" in ejemplo["error"]["message"]
    assert "15" in r["429"]["description"] and "5" in r["429"]["description"]

def test_login_documenta_el_200_con_token_y_usuario():
    ejemplo = _resp("/api/v1/auth/login", "post")["200"]["content"]["application/json"]["example"]
    assert {"access_token", "token_type", "expires_in", "usuario"} <= set(ejemplo)

def test_rutas_con_id_documentan_404():
    assert "404" in _resp("/api/v1/users/{usuario_id}", "get")
    assert "404" in _resp("/api/v1/files/{id}", "get")

def test_descarga_de_archivos_documenta_403_y_subida_devuelve_file_id_numerico():
    assert "403" in _resp("/api/v1/files/{id}", "get")
    ejemplo = _resp("/api/v1/files", "post")["200"]["content"]["application/json"]["example"]
    assert isinstance(ejemplo["file_id"], int)

def test_422_real_devuelve_details_como_objeto_con_un_campo_por_llave(client):
    r = client.post("/api/v1/auth/login", json={"correo": "", "password": ""})
    assert r.status_code == 422
    detalles = r.json()["error"]["details"]
    assert "correo" in detalles and isinstance(detalles["correo"], str)


# --- App de la raiz (La que despliega Railway) ---------------------------------------
# El main.py de la raiz monta los routers del G2 en su propia app, sin pasar por
# g2_api/main.py. Aqui se comprueba que completar_openapi() sirve para cualquier app.
def _app_de_la_raiz():
    from fastapi import FastAPI

    from g2_api.openapi_docs import completar_openapi
    from g2_api.routers import auth, files, roles, users

    raiz = FastAPI(title="UDV", docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")
    for r in (auth.router, auth.me_router, users.router, roles.router, files.router):
        raiz.include_router(r)

    @raiz.get("/api/v1/tasks") # Ruta de otro grupo: no debe cambiar
    def tareas():
        return []

    completar_openapi(raiz)
    return raiz

def test_app_de_la_raiz_documenta_lo_mismo_que_la_del_grupo():
    r = _app_de_la_raiz().openapi()["paths"]
    assert {"201", "401", "403", "409", "422"} <= set(r["/api/v1/users"]["post"]["responses"])
    assert {"200", "401", "403"} <= set(r["/api/v1/users"]["get"]["responses"])
    assert {"200", "401"} <= set(r["/api/v1/me"]["get"]["responses"])

def test_app_de_la_raiz_no_muestra_string_en_los_ejemplos_200_y_201():
    r = _app_de_la_raiz().openapi()["paths"]
    for ruta, metodo, codigo in (("/api/v1/me", "get", "200"), ("/api/v1/users", "get", "200"),
                                 ("/api/v1/users", "post", "201")):
        ejemplo = r[ruta][metodo]["responses"][codigo]["content"]["application/json"]["example"]
        assert isinstance(ejemplo, dict)

def test_app_de_la_raiz_422_usa_el_modelo_de_error_real_y_no_el_de_fastapi():
    r = _app_de_la_raiz().openapi()["paths"]["/api/v1/users"]["post"]["responses"]["422"]
    assert r["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}

def test_completar_openapi_no_toca_las_rutas_de_otros_grupos():
    r = _app_de_la_raiz().openapi()["paths"]["/api/v1/tasks"]["get"]["responses"]
    assert set(r) == {"200"}

