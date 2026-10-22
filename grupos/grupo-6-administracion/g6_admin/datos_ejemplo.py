"""Registros de ejemplo para ver la pantalla con contenido.

Son ficticios: no son datos oficiales de la universidad ni contienen
información personal. Los datos semilla reales son del G1; el escenario de
demostración del G6 se cargará encima de ellos cuando existan.
"""

from .catalogos import ServicioCatalogos
from .notificaciones import ServicioNotificaciones

EJEMPLOS: dict[str, list[tuple[str, str, bool]]] = {
    "academic-units": [
        ("FAC-ING", "Facultad de Ingeniería", True),
        ("FAC-CE", "Facultad de Ciencias Económicas", True),
    ],
    "campuses": [
        ("CENTRAL", "Campus Central", True),
        ("VIRTUAL", "Campus Virtual", True),
    ],
    "courses": [
        ("PW-01", "Programación Web", True),
        ("BD-01", "Bases de Datos", True),
    ],
    "periods": [
        ("2025-S2", "Segundo semestre 2025", False),
        ("2026-S1", "Primer semestre 2026", True),
        ("2026-S2", "Segundo semestre 2026", True),
    ],
    "modalities": [
        ("PRES", "Presencial", True),
        ("VIRT", "Virtual", True),
        ("HIB", "Híbrida", True),
    ],
    "areas": [
        ("SIS", "Sistemas y computación", True),
        ("MAT", "Matemática", True),
    ],
}


def cargar_datos_ejemplo(servicio: ServicioCatalogos) -> None:
    for recurso, filas in EJEMPLOS.items():
        for code, name, is_active in filas:
            servicio.repositorio.agregar(recurso, code=code, name=name,
                                         is_active=is_active, autor_id=None)


# Destinatarios: 1 es administración y 2 es el docente de USUARIOS_DEMO.
EVENTOS_EJEMPLO = [
    {"id": "demo-1", "name": "task.published", "recipients": [2],
     "data": {"task_title": "Planificación del curso", "due_date": "2026-11-15"}},
    {"id": "demo-2", "name": "assignment.returned", "recipients": [2],
     "data": {"task_title": "Sílabo de Programación Web",
              "comment": "Falta la bibliografía."}},
    {"id": "demo-3", "name": "assignment.approved", "recipients": [2, 1],
     "data": {"task_title": "Sílabo de Bases de Datos"}},
]


def cargar_notificaciones_ejemplo(servicio: ServicioNotificaciones) -> None:
    for evento in EVENTOS_EJEMPLO:
        servicio.procesar_evento(evento)
