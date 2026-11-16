# Documentacion OpenAPI del Grupo 2 (G2-33, Persona 5).
# Swagger debe mostrar lo mismo que responde la API. Los routers son de otras personas,
# asi que aqui se completan los codigos HTTP y los ejemplos sin tocar sus archivos.

# Esta funcion se puede usar en cualquier app de FastAPI: la del grupo (g2_api/main.py) y
# la de la raiz que despliega Railway (main.py del PM). Solo toca las rutas cuyo codigo
# vive en g2_api.routers, asi que no cambia la documentacion de los grupos 3 a 6.
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from g2_api import config

_ERRORES = {
    400: ("BAD_REQUEST", "Solicitud inválida."),
    401: ("UNAUTHORIZED", "Falta el token de autenticación."),
    403: ("FORBIDDEN", "No tienes permisos necesarios para realizar esta acción."),
    404: ("NOT_FOUND", "Recurso no encontrado."),
    409: ("CONFLICT", "El correo ya está registrado."),
    422: ("VALIDATION_ERROR", "Datos de entrada inválidos."),
    429: ("TOO_MANY_REQUESTS", "Cuenta bloqueada por intentos fallidos. Intenta de nuevo en 15 minutos."),
}
# Las fechas son de solo lectura, en ISO 8601 y en UTC (terminan en Z).
_USUARIO = {
    "id": 12, "correo": "docente@udv.edu.gt", "nombres": "Carlos", "apellidos": "Maeda",
    "activo": True, "roles": ["teacher"],
    "creado_en": "2026-10-29T21:30:00Z", "actualizado_en": "2026-10-29T21:30:00Z",
}
# GET /me no devuelve las fechas, así que su ejemplo es el usuario sin ellas (H-04, retest del 14-nov).
_USUARIO_ME = {k: v for k, v in _USUARIO.items() if k not in ("creado_en", "actualizado_en")}


def _resp_error(codigo: int, mensaje: str | None = None):
    code, msg = _ERRORES[codigo]
    msg = mensaje or msg
    detalles = {}
    if codigo == 422:
        # Los detalles son un objeto con un campo por llave.
        detalles = {"correo": "Formato de correo inválido", "password": "Mínimo 8 caracteres"}
    return {
        "description": msg,
        "content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
            "example": {"error": {"code": code, "message": msg, "details": detalles}},
        }},
    }


def _resp_ok(descripcion: str, ejemplo, esquema: dict | None = None):
    cuerpo = {"example": ejemplo}
    if esquema:
        cuerpo["schema"] = esquema
    return {"description": descripcion, "content": {"application/json": cuerpo}}


def _rutas_del_g2():
    # Rutas de los routers del G2. Se leen de los routers y no de la app, porque asi
    # funciona igual en cualquier version de FastAPI y con cualquier prefijo de montaje.
    from g2_api.routers import auth, files, roles, users

    routers = [auth.router, users.router, roles.router, files.router]
    if hasattr(auth, "me_router"):
        routers.append(auth.me_router)
    return {r.path for router in routers for r in router.routes if isinstance(r, APIRoute)}


def completar_openapi(app: FastAPI):
    # Deja en 'app.openapi' el esquema con los codigos HTTP y ejemplos reales del G2.

    def _construir():
        if app.openapi_schema:
            return app.openapi_schema
        esquema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        esquema.setdefault("components", {}).setdefault("schemas", {})["ErrorResponse"] = {
            "type": "object",
            "required": ["error"],
            "properties": {"error": {
                "type": "object",
                "required": ["code", "message", "details"],
                "properties": {
                    "code": {"type": "string", "example": "VALIDATION_ERROR"},
                    "message": {"type": "string"},
                    "details": {"type": "object", "description": "Un campo por llave; vacío ({}) si no hay detalle."},
                },
            }},
        }
        pagina = {"page": 1, "per_page": 20, "total": 1, "data": [_USUARIO]}
        propias = _rutas_del_g2()
        for ruta, metodos in esquema["paths"].items():
            if ruta not in propias:
                continue
            for metodo, op in metodos.items():
                r = op["responses"]
                publica = ruta.endswith("/auth/login")
                admin = "/users" in ruta or "/roles" in ruta
                if not publica:
                    r["401"] = _resp_error(401)
                if admin:
                    r["403"] = _resp_error(403)
                if "{" in ruta:
                    r["404"] = _resp_error(404)
                if ruta.endswith("/users") and metodo == "post" or (ruta.endswith("{usuario_id}") and metodo == "patch"):
                    r["409"] = _resp_error(409)
                if ruta.endswith("/auth/login") and metodo == "post":
                    # Bloqueo: tras LOGIN_MAX_INTENTOS fallos seguidos, 429 por LOGIN_BLOQUEO_MINUTOS.
                    r["401"] = _resp_error(401, "Correo o contraseña incorrectos.")
                    r["429"] = _resp_error(429)
                    r["429"]["description"] = (
                        f"Cuenta bloqueada: {config.LOGIN_MAX_INTENTOS} intentos fallidos seguidos bloquean "
                        f"el acceso {config.LOGIN_BLOQUEO_MINUTOS} minutos. El mensaje indica cuántos minutos faltan "
                        "y el bloqueo aplica aunque la contraseña sea correcta."
                    )
                    r["200"] = _resp_ok("Sesión iniciada: token y datos del usuario.", {
                        "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer", "expires_in": 7200,
                        "usuario": {"id": 12, "correo": "docente@udv.edu.gt", "nombres": "Carlos",
                                    "apellidos": "Maeda", "roles": ["teacher"]}})
                if ruta.endswith("/files") and metodo == "post":
                    r["400"] = _resp_error(400)
                if ruta.endswith("/files/{id}") and metodo == "get":
                    # Lo descarga su dueño, un admin o un rol que no sea docente con files.download.
                    r["403"] = _resp_error(403, "No tienes permiso para acceder a este archivo")
                    if "200" in r:
                        r["200"]["description"] = (
                            "Archivo descargado. Lo descarga su dueño, un admin o un rol con el permiso "
                            "files.download que no sea docente (revisor, coordinación, autoridad o auditoría). "
                            "Cualquier otro usuario recibe 403."
                        )
                if "422" in r:
                    r["422"] = _resp_error(422)
                # Ejemplos reales (antes Swagger mostraba un "string" generico).
                if ruta.endswith("/users") and metodo == "get":
                    r["200"] = _resp_ok("Lista paginada de usuarios.", pagina)
                elif ruta.endswith("/users") and metodo == "post":
                    r["201"] = _resp_ok("Usuario creado.", _USUARIO)
                elif ruta.endswith("{usuario_id}"):
                    r["200"] = _resp_ok("Usuario.", _USUARIO)
                elif ruta.endswith("/me"):
                    r["200"] = _resp_ok("Usuario autenticado con sus roles y permisos.",
                                        {**_USUARIO_ME, "permisos": ["users.read"]})
                elif ruta.endswith("/files") and metodo == "post":
                    r["200"] = _resp_ok("Archivo aceptado.", {
                        "file_id": 177, "nombre_interno": "3f2a9c1e-0000-4000-8000-000000000000.pdf"})
        app.openapi_schema = esquema
        return esquema

    app.openapi = _construir

