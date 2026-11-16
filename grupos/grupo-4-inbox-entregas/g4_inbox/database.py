"""
g4_inbox.database — Conexión real a MySQL (reemplaza datos_ejemplo.py / DETALLE_EXTRA)

Lee de las vistas que ya publicó G1: v_inbox, v_panel_tarea, v_historial_tarea,
más las tablas base (tarea, tarea_destinatario, entrega_borrador, comentario,
archivo, entrega) para el detalle completo.

VERSIÓN 2 — ajustada al aviso del PM del 14 de octubre:
- Usa SQLAlchemy con DATABASE_URL (.env), igual que g2_api/database.py —
  no una conexión manual con pymysql como en la primera versión.
- SET @actor_id se ejecuta en cada conexión que haga escrituras, para que
  los triggers de auditoría de G1 registren quién hizo cada cambio (la
  lectura no lo necesita, pero queda listo para cuando las transiciones
  empiecen a escribir en la base real).

VERSIÓN 3 — hallazgos de QA del 12 y 13 de noviembre:
- Comentarios y borrador se guardan en la base (comentario, entrega_borrador),
  ya no en memoria.
- Vincular un archivo valida que exista en archivo (sin eliminar), busca o
  crea la fila de entrega del intento actual y le pone archivo.entrega_id.
- @actor_id se limpia al devolver cada conexión al pool, como en G2.
- La entrega que crea G4 lleva el texto del borrador, como la que crea G3.
"""

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .config import DATABASE_URL
from .inbox import Asignacion

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# Estados en los que el docente todavía puede cambiar su entrega. Es el mismo
# criterio del trigger trg_entrega_borrador_bi de G1.
ESTADOS_PENDIENTES = ("assigned", "in_progress", "returned")


class ErrorConflicto(Exception):
    """La base rechazó el cambio por el estado de la asignación (se responde 409)."""


class ArchivoNoEncontrado(Exception):
    """El archivo no existe, está eliminado o no es del usuario (se responde 404)."""


if engine.dialect.name == "mysql":
    # Zona horaria: G4 NO fija time_zone y usa la del servidor, igual que G3.
    # G3 decide el intento actual comparando tarea_transicion.creado_en (que
    # escribe G3) con entrega.entregado_en (que puede escribir G4): las dos
    # fechas tienen que estar en la misma zona para poder compararse.

    @event.listens_for(engine, "checkin")
    def _limpiar_actor(conexion_dbapi, _registro):
        # @actor_id vive en la conexión y el pool la reutiliza en otra petición:
        # se limpia para que la auditoría nunca culpe al usuario equivocado.
        try:
            cursor = conexion_dbapi.cursor()
            cursor.execute("SET @actor_id = NULL")
            cursor.close()
        except Exception:
            pass

_ACCION_POR_TRANSICION = {
    ("assigned", "in_progress"): "start",
    ("in_progress", "submitted"): "submit",
    ("returned", "submitted"): "resubmit",
    ("submitted", "under_review"): "review",
    ("under_review", "returned"): "return",
    ("under_review", "approved"): "approve",
}


def _sesion(actor_id: Optional[int] = None):
    sesion = SessionLocal()
    if actor_id is not None:
        sesion.execute(text("SET @actor_id = :actor_id"), {"actor_id": actor_id})
    return sesion


def fetch_asignaciones_inbox(usuario_id: Optional[int] = None) -> List[Asignacion]:
    sql = """
        SELECT asignacion_id, usuario_id, tarea_id, titulo, tipo_codigo,
               estado_codigo, prioridad, fecha_limite
        FROM v_inbox
    """
    parametros = {}
    if usuario_id is not None:
        sql += " WHERE usuario_id = :usuario_id"
        parametros["usuario_id"] = usuario_id

    sesion = _sesion()
    try:
        filas = sesion.execute(text(sql), parametros).mappings().all()
    finally:
        sesion.close()

    resultado = []
    for fila in filas:
        fecha = fila["fecha_limite"]
        due_at = fecha.date() if isinstance(fecha, (date, datetime)) else None
        resultado.append(Asignacion(
            id=fila["asignacion_id"],
            assignee_id=fila["usuario_id"],
            title=fila["titulo"],
            task_type=fila["tipo_codigo"],
            status=fila["estado_codigo"],
            priority=fila["prioridad"],
            due_at=due_at,
        ))
    return resultado


def fetch_detalle_asignacion(assignment_id: int) -> Optional[dict]:
    sesion = _sesion()
    try:
        # tarea no se une directo con tipo_tarea — pasa por workflow:
        # tarea.workflow_id -> workflow.tipo_tarea_id -> tipo_tarea.id
        cabecera = sesion.execute(text("""
            SELECT td.id AS asignacion_id, td.usuario_id, td.estado_codigo,
                   t.id AS tarea_id, t.titulo, t.descripcion, t.prioridad,
                   t.programa_version_id, t.revisor_id, tt.codigo AS tipo_codigo,
                   tt.requiere_archivo,
                   COALESCE(td.fecha_limite, t.fecha_limite) AS fecha_limite
            FROM tarea_destinatario td
            JOIN tarea t ON t.id = td.tarea_id
            JOIN workflow w ON w.id = t.workflow_id
            JOIN tipo_tarea tt ON tt.id = w.tipo_tarea_id
            WHERE td.id = :id
        """), {"id": assignment_id}).mappings().first()
        if cabecera is None:
            return None

        borrador = sesion.execute(text("""
            SELECT contenido_texto FROM entrega_borrador
            WHERE tarea_destinatario_id = :id
        """), {"id": assignment_id}).mappings().first()

        comentarios = sesion.execute(text("""
            SELECT autor_id AS author, contenido AS text
            FROM comentario
            WHERE tarea_destinatario_id = :id AND eliminado_en IS NULL
            ORDER BY creado_en
        """), {"id": assignment_id}).mappings().all()

        archivos = sesion.execute(text("""
            SELECT a.id AS file_id, a.nombre_original AS name, a.tipo_mime AS mime,
                   a.tamano_bytes AS size, a.creado_en AS uploaded_at,
                   e.numero_intento AS attempt
            FROM archivo a
            JOIN entrega e ON e.id = a.entrega_id
            WHERE e.tarea_destinatario_id = :id AND a.eliminado_en IS NULL
            ORDER BY e.numero_intento, a.id
        """), {"id": assignment_id}).mappings().all()

        # Se ordena por id y no por fecha: la semilla de G1 y G3 no guardan
        # las fechas en la misma zona horaria, y por fecha el orden sale mal.
        historial = sesion.execute(text("""
            SELECT estado_anterior, estado_nuevo, actor, comentario, creado_en
            FROM v_historial_tarea
            WHERE asignacion_id = :id
            ORDER BY transicion_id
        """), {"id": assignment_id}).mappings().all()
    finally:
        sesion.close()

    fecha = cabecera["fecha_limite"]
    due_at = fecha.isoformat() if isinstance(fecha, (date, datetime)) else None

    def _iso(valor):
        return valor.isoformat(timespec="minutes") if isinstance(valor, datetime) else None

    # El comentario de la última devolución o aprobación. G3 lo guarda en el
    # historial de transiciones (tarea_transicion.comentario), no en la tabla
    # comentario.
    def _ultima(estado):
        filas = [h for h in historial if h["estado_nuevo"] == estado]
        if not filas:
            return None
        h = filas[-1]
        return {"comment": h["comentario"], "at": _iso(h["creado_en"]), "actor": h["actor"]}

    ultima_devolucion = _ultima("returned")
    ultima_aprobacion = _ultima("approved")

    return {
        "id": cabecera["asignacion_id"],
        "assignee_id": cabecera["usuario_id"],
        "reviewer_id": cabecera["revisor_id"],
        "title": cabecera["titulo"],
        "task_type": cabecera["tipo_codigo"],
        "requiere_archivo": bool(cabecera["requiere_archivo"]),
        "status": cabecera["estado_codigo"],
        "priority": cabecera["prioridad"],
        "due_at": due_at,
        "instructions": cabecera["descripcion"] or "",
        "program_version_id": cabecera["programa_version_id"],
        "draft_comment": borrador["contenido_texto"] if borrador else None,
        "comments": [{"author": str(c["author"]), "text": c["text"]} for c in comentarios],
        # Con sus datos, para que el revisor vea qué se entregó en cada intento.
        "files": [{"file_id": str(f["file_id"]), "name": f["name"], "mime": f["mime"],
                   "size": f["size"], "uploaded_at": _iso(f["uploaded_at"]),
                   "attempt": f["attempt"]} for f in archivos],
        "history": [
            {
                "action": _ACCION_POR_TRANSICION.get((h["estado_anterior"], h["estado_nuevo"])),
                "new_status": h["estado_nuevo"],
                "actor": h["actor"],
                "comment": h["comentario"],
                "at": _iso(h["creado_en"]),
            }
            for h in historial
        ],
        "last_return": ultima_devolucion,
        "last_approval": ultima_aprobacion,
    }


def probar_conexion() -> bool:
    try:
        sesion = _sesion()
        sesion.execute(text("SELECT 1"))
        sesion.close()
        return True
    except Exception:
        return False


def fetch_orden_prioridades() -> dict:
    """{codigo: orden} del catálogo prioridad_tarea de G1 (low=1 ... urgent=4).

    La prioridad solo desempata el orden del inbox, así que si el catálogo
    no se puede leer (por ejemplo una base de la versión anterior) devolvemos
    {} y listar_inbox usa su copia por defecto, en vez de tumbar el inbox."""
    sesion = _sesion()
    try:
        filas = sesion.execute(
            text("SELECT codigo, orden FROM prioridad_tarea WHERE activo = 1")
        ).mappings().all()
    except SQLAlchemyError:
        return {}
    finally:
        sesion.close()
    return {fila["codigo"]: int(fila["orden"]) for fila in filas}


# ============================================================================
# ESCRITURAS (hallazgos #3 y #4 de QA)
# Cada una abre su sesión con @actor_id para que la auditoría de G1 sepa quién
# hizo el cambio, y hace commit o rollback completo: nunca queda a medias.
# ============================================================================
def _es_signal_de_g1(error: DBAPIError) -> bool:
    """True si el error viene de un SIGNAL SQLSTATE '45000' de un trigger de G1."""
    codigo = getattr(error.orig, "args", [None])[0]
    return codigo == 1644


def guardar_borrador(assignment_id: int, texto: Optional[str], actor_id: int) -> None:
    """Crea o reemplaza el borrador (hay uno solo por asignación: uq_entrega_borrador_td)."""
    sesion = _sesion(actor_id)
    try:
        sesion.execute(text("""
            INSERT INTO entrega_borrador (tarea_destinatario_id, contenido_texto, guardado_por)
            VALUES (:id, :texto, :actor)
            ON DUPLICATE KEY UPDATE contenido_texto = VALUES(contenido_texto),
                                    guardado_por = VALUES(guardado_por)
        """), {"id": assignment_id, "texto": texto, "actor": actor_id})
        sesion.commit()
    except DBAPIError as e:
        sesion.rollback()
        if _es_signal_de_g1(e):
            # trg_entrega_borrador_bi/bu: la asignación ya no está pendiente
            raise ErrorConflicto("Solo se guarda borrador de una asignación pendiente") from e
        raise
    finally:
        sesion.close()


def crear_comentario(assignment_id: int, autor_id: int, texto: str) -> dict:
    sesion = _sesion(autor_id)
    try:
        sesion.execute(text("""
            INSERT INTO comentario (autor_id, tarea_destinatario_id, contenido)
            VALUES (:autor, :id, :texto)
        """), {"autor": autor_id, "id": assignment_id, "texto": texto})
        sesion.commit()
    except DBAPIError:
        sesion.rollback()
        raise
    finally:
        sesion.close()
    return {"author": str(autor_id), "text": texto}


def _envios(sesion, assignment_id: int) -> int:
    """Cuántas veces se envió la asignación (submit y resubmit terminan en 'submitted')."""
    return sesion.execute(text("""
        SELECT COUNT(*) FROM tarea_transicion
        WHERE tarea_destinatario_id = :id AND estado_nuevo = 'submitted'
    """), {"id": assignment_id}).scalar()


def _intento_actual(sesion, assignment_id: int) -> Optional[dict]:
    """La última entrega de la asignación, si todavía no se envió.

    Regla común del PM (13-nov): el intento actual es la última fila de entrega
    que no tenga una transición 'submitted' posterior en tarea_transicion.

    No se comparan fechas: G3 guarda creado_en en la zona horaria del servidor
    y G2/G4 en UTC, y con el docker-compose (TZ America/Guatemala) la
    diferencia es de 6 horas. En su lugar se cuentan los envíos: cada envío
    cierra un intento, así que el intento N sigue abierto mientras haya menos
    de N envíos.
    """
    ultima = sesion.execute(text("""
        SELECT id, numero_intento FROM entrega
        WHERE tarea_destinatario_id = :id
        ORDER BY numero_intento DESC LIMIT 1
    """), {"id": assignment_id}).mappings().first()
    if ultima is None or _envios(sesion, assignment_id) >= ultima["numero_intento"]:
        return None
    return dict(ultima)


def vincular_archivo(assignment_id: int, file_id: str, actor_id: int) -> dict:
    """Vincula un archivo ya subido por G2 al intento actual de la asignación.

    1. El archivo debe existir, no estar eliminado y ser del usuario (si no, 404).
    2. Usa la entrega del intento actual o crea una con numero_intento = MAX + 1.
    3. UPDATE archivo SET entrega_id (G1 no deja modificar entrega, sí archivo).
    Devuelve {"entrega_id", "numero_intento"}.
    """
    try:
        archivo_id = int(file_id)
    except (TypeError, ValueError):
        raise ArchivoNoEncontrado("Archivo no encontrado")

    sesion = _sesion(actor_id)
    try:
        # Bloquea la asignación hasta el commit: dos vinculaciones al mismo
        # tiempo no pueden crear dos intentos para el mismo envío.
        asignacion = sesion.execute(text("""
            SELECT estado_codigo FROM tarea_destinatario WHERE id = :id FOR UPDATE
        """), {"id": assignment_id}).mappings().first()
        if asignacion is None:
            raise ArchivoNoEncontrado("Asignación no encontrada")
        if asignacion["estado_codigo"] not in ESTADOS_PENDIENTES:
            raise ErrorConflicto("Solo se adjuntan archivos a una asignación pendiente")

        archivo = sesion.execute(text("""
            SELECT id, autor_id, entrega_id, comentario_id, programa_version_id
            FROM archivo WHERE id = :f AND eliminado_en IS NULL
        """), {"f": archivo_id}).mappings().first()
        # Un archivo de otro usuario se trata igual que uno que no existe,
        # para no confirmar que ese id existe.
        if archivo is None or archivo["autor_id"] != actor_id:
            raise ArchivoNoEncontrado("Archivo no encontrado")

        intento = _intento_actual(sesion, assignment_id)
        if archivo["comentario_id"] or archivo["programa_version_id"] or (
                archivo["entrega_id"] and (intento is None or archivo["entrega_id"] != intento["id"])):
            raise ErrorConflicto("El archivo ya está vinculado a otro registro")

        if intento is None:
            # MAX + 1, como acordó el PM. Si alguna vez se envió sin crear fila
            # de entrega (G3 todavía no la crea en el submit), se numera por
            # envíos para que el número siga siendo "el envío que viene".
            maximo = sesion.execute(text("""
                SELECT COALESCE(MAX(numero_intento), 0) FROM entrega
                WHERE tarea_destinatario_id = :id
            """), {"id": assignment_id}).scalar()
            numero = max(maximo, _envios(sesion, assignment_id)) + 1
            # Lleva el texto del borrador, igual que cuando la crea G3: G1 no
            # deja modificar una entrega, así que el texto tiene que ir desde
            # el principio. La pantalla guarda el borrador antes de subir.
            nuevo_id = sesion.execute(text("""
                INSERT INTO entrega (tarea_destinatario_id, numero_intento, entregado_por,
                                     contenido_texto, programa_version_id)
                SELECT :id, :n, :actor,
                       (SELECT contenido_texto FROM entrega_borrador WHERE tarea_destinatario_id = :id),
                       (SELECT programa_version_id FROM entrega_borrador WHERE tarea_destinatario_id = :id)
            """), {"id": assignment_id, "n": numero, "actor": actor_id}).lastrowid
            intento = {"id": nuevo_id, "numero_intento": numero}

        sesion.execute(text("UPDATE archivo SET entrega_id = :e WHERE id = :f"),
                       {"e": intento["id"], "f": archivo_id})
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()
    return {"entrega_id": intento["id"], "numero_intento": intento["numero_intento"]}
