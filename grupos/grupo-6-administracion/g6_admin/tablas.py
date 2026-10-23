"""Tablas del G1 que usa el G6 (Docs/sql/01_schema.sql de db_udv).

El esquema lo crea y lo cambia solo el Grupo 1: aquí no se crea ninguna tabla
en MySQL. Estas definiciones solo le dicen a SQLAlchemy qué columnas existen,
para escribir las consultas sin SQL a mano. En las pruebas se crean sobre un
SQLite temporal con `metadata.create_all`.

Si el G1 cambia una columna que aparece aquí, hay que cambiarla también aquí.
"""

from sqlalchemy import (BigInteger, Boolean, Column, Date, DateTime, Integer,
                        MetaData, SmallInteger, String, Table, Text)

metadata = MetaData()

# BIGINT en MySQL; en SQLite (pruebas) INTEGER para que sea autoincremental.
_ID_LARGO = BigInteger().with_variant(Integer, "sqlite")


def _fechas() -> list[Column]:
    # El valor lo pone el G6 al insertar, en UTC, igual en MySQL y en SQLite.
    return [Column("creado_en", DateTime), Column("actualizado_en", DateTime)]


# ── Catálogos académicos ────────────────────────────────────────────────────

facultad = Table(
    "facultad", metadata,
    Column("id", Integer, primary_key=True),
    Column("codigo", String(20), nullable=False, unique=True),
    Column("nombre", String(150), nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    *_fechas(),
)

sede = Table(
    "sede", metadata,
    Column("id", Integer, primary_key=True),
    Column("codigo", String(20), nullable=False, unique=True),
    Column("nombre", String(150), nullable=False),
    Column("direccion", String(300)),
    Column("activo", Boolean, nullable=False, default=True),
    *_fechas(),
)

unidad_academica = Table(
    "unidad_academica", metadata,
    Column("id", Integer, primary_key=True),
    Column("facultad_id", Integer, nullable=False),
    Column("sede_id", Integer, nullable=False),
    Column("codigo", String(20), nullable=False, unique=True),
    Column("nombre", String(150), nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    *_fechas(),
)

curso = Table(
    "curso", metadata,
    Column("id", Integer, primary_key=True),
    Column("codigo", String(20), nullable=False, unique=True),
    Column("nombre", String(150), nullable=False),
    Column("creditos", SmallInteger, nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    *_fechas(),
    Column("eliminado_en", DateTime),  # Eliminación lógica: no se lista.
)

periodo = Table(
    "periodo", metadata,
    Column("id", Integer, primary_key=True),
    Column("codigo", String(20), nullable=False, unique=True),
    Column("anio", SmallInteger, nullable=False),
    Column("ciclo", SmallInteger, nullable=False),
    Column("fecha_inicio", Date, nullable=False),
    Column("fecha_fin", Date, nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    Column("creado_en", DateTime),  # periodo no tiene actualizado_en
)

modalidad = Table(
    "modalidad", metadata,
    Column("id", Integer, primary_key=True),
    Column("codigo", String(20), nullable=False, unique=True),
    Column("nombre", String(100), nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    *_fechas(),
)

area = Table(
    "area", metadata,
    Column("id", Integer, primary_key=True),
    Column("codigo", String(20), nullable=False, unique=True),
    Column("nombre", String(100), nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    *_fechas(),
)

# ── Auditoría (solo INSERT: el G1 bloquea UPDATE y DELETE con triggers) ─────

auditoria = Table(
    "auditoria", metadata,
    Column("id", _ID_LARGO, primary_key=True),
    Column("tabla", String(64), nullable=False),
    Column("registro_id", String(64), nullable=False),
    Column("accion", String(20), nullable=False),
    Column("actor_id", Integer),
    Column("ip_origen", String(45)),
    Column("detalle", Text),  # JSON
    Column("creado_en", DateTime),
)

# ── Eventos y notificaciones ────────────────────────────────────────────────

evento = Table(
    "evento", metadata,
    Column("id", _ID_LARGO, primary_key=True),
    Column("nombre", String(40), nullable=False),
    Column("clave_unica", String(120), nullable=False, unique=True),
    Column("tarea_id", Integer),
    Column("tarea_destinatario_id", Integer),
    Column("programa_version_id", Integer),
    Column("actor_id", Integer),
    Column("payload", Text),  # JSON
    Column("creado_en", DateTime),
    Column("procesado_en", DateTime),
)

notificacion = Table(
    "notificacion", metadata,
    Column("id", _ID_LARGO, primary_key=True),
    Column("usuario_id", Integer, nullable=False),
    Column("tipo", String(40), nullable=False),
    Column("titulo", String(200), nullable=False),
    Column("mensaje", String(1000), nullable=False),
    Column("tarea_destinatario_id", Integer),
    Column("programa_version_id", Integer),
    Column("evento_id", _ID_LARGO),
    Column("leida_en", DateTime),
    Column("creado_en", DateTime),
)

# ── Lo que se lee de otros grupos para saber a quién avisar (solo lectura) ──

tarea = Table(
    "tarea", metadata,
    Column("id", Integer, primary_key=True),
    Column("titulo", String(200), nullable=False),
    Column("estado_codigo", String(20)),
    Column("creado_por", Integer),
    Column("revisor_id", Integer),
    Column("fecha_limite", DateTime),
    Column("eliminado_en", DateTime),
)

tarea_destinatario = Table(
    "tarea_destinatario", metadata,
    Column("id", Integer, primary_key=True),
    Column("tarea_id", Integer, nullable=False),
    Column("usuario_id", Integer, nullable=False),
    Column("estado_codigo", String(20)),
    Column("fecha_limite", DateTime),
    Column("revisor_id", Integer),
)

programa_version = Table(
    "programa_version", metadata,
    Column("id", Integer, primary_key=True),
    Column("nombre", String(200), nullable=False),
    Column("creado_por", Integer),
    Column("docente_responsable_id", Integer),
)

rol = Table(
    "rol", metadata,
    Column("id", Integer, primary_key=True),
    Column("codigo", String(30), nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
)

usuario_rol = Table(
    "usuario_rol", metadata,
    Column("usuario_id", Integer, primary_key=True),
    Column("rol_id", Integer, primary_key=True),
)

usuario = Table(
    "usuario", metadata,
    Column("id", Integer, primary_key=True),
    Column("activo", Boolean, nullable=False, default=True),
)
