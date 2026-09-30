"""Estado técnico del servicio para GET /api/v1/health (escenario G6-34).

No depende del framework web. Nunca devuelve detalles internos: si una
verificación falla, solo informa "error" (RNF 06 y escenario G6-36).
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

registro = logging.getLogger(__name__)

NOMBRE_SERVICIO = "udv-workflow-docente"
RESULTADOS_VALIDOS = {"ok", "error", "not_configured"}

Verificacion = Callable[[], str]


def verificar_base_de_datos() -> str:
    # PENDIENTE: G1 y G2 aún no definen el motor ni la conexión (README §5).
    # Cuando exista, aquí se hace una consulta mínima (por ejemplo SELECT 1) y
    # se devuelve "ok"; si la consulta falla, basta con dejar que lance error.
    return "not_configured"


VERIFICACIONES_PREDETERMINADAS: dict[str, Verificacion] = {
    "database": verificar_base_de_datos,
}


def estado_del_servicio(*, iniciado_en: float, entorno: str, version: str,
                        verificaciones: dict[str, Verificacion] | None = None
                        ) -> dict[str, Any]:
    if verificaciones is None:
        verificaciones = VERIFICACIONES_PREDETERMINADAS

    resultados: dict[str, str] = {}
    for nombre, verificar in verificaciones.items():
        try:
            resultado = verificar()
        except Exception as error:  # noqa: BLE001 - se reporta sin detalles
            registro.warning("La verificación de salud '%s' falló (%s).",
                             nombre, type(error).__name__)
            resultado = "error"
        resultados[nombre] = resultado if resultado in RESULTADOS_VALIDOS else "error"

    return {
        "status": "degraded" if "error" in resultados.values() else "ok",
        "service": NOMBRE_SERVICIO,
        "version": version,
        "environment": entorno,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uptime_seconds": int(time.monotonic() - iniciado_en),
        "checks": resultados,
    }
