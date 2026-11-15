"""Modelos de entrada para documentar los cuerpos de las rutas de G5."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


PositiveId = int


class G5Request(BaseModel):
    model_config = ConfigDict(extra="allow")


class SeccionPrograma(G5Request):
    contenido: dict[str, Any] | list[dict[str, Any]]


class ResponsablesContenido(G5Request):
    docente: str | None = None
    decanatura: str | None = None
    coordinador: str | None = None
    docente_responsable_id: PositiveId | None = Field(
        default=None,
        gt=0,
        description="Usuario docente asignado al curso, período y sede en G1.",
    )


class ResponsablesSeccion(G5Request):
    contenido: ResponsablesContenido


class ProgramaNuevo(G5Request):
    curso_id: PositiveId = Field(gt=0, description="ID del curso en el catálogo de G1.")
    sede_id: PositiveId = Field(gt=0, description="ID de la sede en el catálogo de G1.")
    modalidad_id: PositiveId = Field(gt=0, description="ID de la modalidad en el catálogo de G1.")
    periodo_id: PositiveId = Field(gt=0, description="ID del período académico en G1.")
    docente_responsable_id: PositiveId | None = Field(
        default=None,
        gt=0,
        description="Usuario docente asignado al curso, período y sede en G1.",
    )
    nombre: str | None = None
    asignatura: str | None = None
    descripcion: str | None = None
    programa_academico: str | None = None
    departamento: str | None = None
    nivel: str | None = None
    pensum: str | None = None
    horas_clase_semanal: int | None = None
    tarea_destinatario_origen_id: PositiveId | None = Field(default=None, gt=0)
    secciones: dict[str, SeccionPrograma] | None = None


class VersionNueva(G5Request):
    periodo_id: PositiveId = Field(gt=0, description="ID del período académico en G1.")
    clonar: bool = True
    resumen_cambios: str | None = None
    tarea_destinatario_origen_id: PositiveId | None = Field(default=None, gt=0)


class EncabezadoVersion(G5Request):
    resumen_cambios: str | None = None
    secciones: dict[str, SeccionPrograma] | None = None


class EvaluacionItem(G5Request):
    nombre: str = Field(description="Nombre de la actividad de evaluación.")
    ponderacion: float = Field(description="Porcentaje asignado a la actividad.")
    semana: int | None = None
    descripcion: str | None = None
    orden: int | None = None


class EvaluacionSeccion(G5Request):
    contenido: dict[str, Any] | list[EvaluacionItem] = Field(
        json_schema_extra={
            "examples": [
                [
                    {"nombre": "Parcial 1", "ponderacion": 30, "semana": 5},
                ]
            ]
        }
    )


class TransicionVersion(G5Request):
    comentario: str | None = None
    observacion: str | None = None


class SeccionActualizacion(G5Request):
    contenido: dict[str, Any] | list[dict[str, Any]] = Field(
        json_schema_extra={
            "examples": [
                {"texto": "Descripción del programa"},
                [{"nombre": "Parcial 1", "ponderacion": 30, "semana": 5}],
            ]
        }
    )
