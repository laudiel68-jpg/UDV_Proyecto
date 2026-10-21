"""Punto de entrada de la aplicación (mantenido por el PM, README §4).

Hace importables los paquetes de cada grupo (g1_bd, g2_api, ...) y monta sus
routers en una sola app FastAPI. Un router que todavía no existe en la rama se
omite y aparece en /health, para que el deploy no se caiga mientras los
grupos integran su trabajo.

Convención para los grupos: cada router declara su ruta completa con el
prefijo /api/v1 (por ejemplo APIRouter(prefix="/api/v1/auth")).

Correr local:  uvicorn main:app --reload
"""
import importlib
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI

RAIZ = Path(__file__).resolve().parent
log = logging.getLogger("udv")

# Las carpetas de grupo llevan guiones y no se importan directo:
# se agregan al path para poder hacer `from g2_api import ...`.
for carpeta in sorted((RAIZ / "grupos").glob("grupo-*")):
    if carpeta.is_dir() and str(carpeta) not in sys.path:
        sys.path.insert(0, str(carpeta))

# Routers registrados. Para sumar uno: agregar ("paquete.modulo", "variable").
ROUTERS = [
    ("g2_api.routers.auth", "router"),
    ("g2_api.routers.users", "router"),
    ("g2_api.routers.roles", "router"),
    # ("g3_workflow.api", "router"),
    # ("g4_inbox.api", "router"),
    # ("g5_programas.api", "router"),
    # ("g6_admin.api", "router"),
]

app = FastAPI(
    title="UDV · Workflow docente",
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    redoc_url=None,
)

# Formato de error común: servicio compartido del G2 (CONTRATO_COMUN §1).
try:
    from g2_api.middleware.error_handler import register_error_handlers
    register_error_handlers(app)
except ImportError as exc:
    log.warning("Manejador de errores del G2 no disponible: %s", exc)

montados, pendientes = [], {}
for modulo, nombre in ROUTERS:
    try:
        app.include_router(getattr(importlib.import_module(modulo), nombre))
        montados.append(modulo)
    except Exception as exc:  # el grupo aún no integró ese módulo a esta rama
        pendientes[modulo] = f"{type(exc).__name__}: {exc}"
        log.warning("Router omitido %s -> %s", modulo, exc)


@app.get("/health", tags=["Sistema"])
def health():
    """Estado de la app y de los routers. No requiere base de datos."""
    return {"status": "ok", "routers": montados, "pendientes": pendientes}


@app.get("/health/db", tags=["Sistema"])
def health_db():
    """Comprueba la conexión a MySQL usando DATABASE_URL."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return {"status": "sin_configurar", "detalle": "Falta DATABASE_URL"}
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            tablas = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
            )).scalar()
        engine.dispose()
        return {"status": "ok", "version": version, "tablas": tablas}
    except Exception as exc:
        return {"status": "error", "detalle": f"{type(exc).__name__}: {exc}"}
