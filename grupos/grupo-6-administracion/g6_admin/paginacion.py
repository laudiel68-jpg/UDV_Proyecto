"""Paginación con la forma del contrato común: page, per_page, total, data.

TEMPORAL: la utilidad de paginación y el máximo de per_page son del G2
(CONTRATO.md del G2 §3). Cuando la publiquen, se importa desde g2_api.
"""

from typing import Any

from .errores import validacion

PER_PAGE_PREDETERMINADO = 20
PER_PAGE_MAXIMO = 100  # Provisional hasta que el G2 lo documente en el OpenAPI.


def _es_entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def paginar(elementos: list[Any], page: int, per_page: int) -> dict[str, Any]:
    errores = {}
    if not _es_entero(page) or page < 1:
        errores["page"] = "Debe ser un número entero mayor o igual a 1."
    if not _es_entero(per_page) or not 1 <= per_page <= PER_PAGE_MAXIMO:
        errores["per_page"] = f"Debe estar entre 1 y {PER_PAGE_MAXIMO}."
    if errores:
        raise validacion(errores)

    inicio = (page - 1) * per_page
    return {
        "page": page,
        "per_page": per_page,
        "total": len(elementos),
        "data": elementos[inicio:inicio + per_page],
    }
