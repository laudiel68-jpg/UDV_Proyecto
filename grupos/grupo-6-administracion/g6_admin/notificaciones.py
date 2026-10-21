"""
Módulo de notificaciones - Grupo 6
Proyecto Integrador - Programación Web
Universidad Da Vinci de Guatemala

Escenarios:
G6-04: publicación de una tarea.
G6-05: tarea próxima a vencer.
G6-06: entrega de una tarea.

Implementación inicial en memoria. No persiste datos al reiniciar
el proceso y aún requiere integración con la API y eventos de otros grupos.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Optional


EVENTOS_PERMITIDOS = {
    "task.published",
    "assignment.due_soon",
    "assignment.submitted",
}


class ErrorNotificacion(ValueError):
    """Error de validación en el servicio de notificaciones."""


@dataclass
class Notificacion:
    id: int
    usuario_id: int
    evento: str
    titulo: str
    mensaje: str
    fecha_creacion: str
    leida: bool = False
    datos: Optional[dict[str, Any]] = None

    def como_dict(self) -> dict[str, Any]:
        """Convierte la notificación a un diccionario."""
        return asdict(self)


class ServicioNotificaciones:
    """Crea, consulta y marca como leídas las notificaciones."""

    def __init__(self) -> None:
        self._notificaciones: list[Notificacion] = []
        self._siguiente_id = 1
        self._lock = Lock()

    @staticmethod
    def _validar_usuario_id(usuario_id: Any) -> int:
        if (
            isinstance(usuario_id, bool)
            or not isinstance(usuario_id, int)
            or usuario_id <= 0
        ):
            raise ErrorNotificacion(
                "El usuario_id debe ser un entero positivo."
            )
        return usuario_id

    @staticmethod
    def _texto(valor: Any, campo: str) -> str:
        if not isinstance(valor, str) or not valor.strip():
            raise ErrorNotificacion(
                f"El campo '{campo}' es obligatorio."
            )
        return valor.strip()

    def crear(
        self,
        usuario_id: int,
        evento: str,
        titulo: str,
        mensaje: str,
        datos: Optional[dict[str, Any]] = None,
    ) -> Notificacion:
        usuario_id = self._validar_usuario_id(usuario_id)
        evento = self._texto(evento, "evento")
        titulo = self._texto(titulo, "titulo")
        mensaje = self._texto(mensaje, "mensaje")

        if evento not in EVENTOS_PERMITIDOS:
            raise ErrorNotificacion(f"Evento no permitido: {evento}.")

        if datos is not None and not isinstance(datos, dict):
            raise ErrorNotificacion("'datos' debe ser un diccionario.")

        with self._lock:
            notificacion = Notificacion(
                id=self._siguiente_id,
                usuario_id=usuario_id,
                evento=evento,
                titulo=titulo,
                mensaje=mensaje,
                fecha_creacion=datetime.now(timezone.utc).isoformat(),
                leida=False,
                datos=datos.copy() if datos else {},
            )
            self._notificaciones.append(notificacion)
            self._siguiente_id += 1
            return notificacion

    def procesar_evento(
        self, evento: str, datos: dict[str, Any]
    ) -> Notificacion:
        """Convierte uno de los eventos acordados en una notificación.

        task.published y assignment.due_soon esperan:
            usuario_id, nombre_tarea, fecha_limite

        assignment.submitted espera:
            revisor_id, nombre_tarea y opcionalmente nombre_docente
        """
        if not isinstance(datos, dict):
            raise ErrorNotificacion("Los datos del evento deben ser un diccionario.")

        if evento in {"task.published", "assignment.due_soon"}:
            usuario_id = datos.get("usuario_id")
            nombre_tarea = self._texto(
                datos.get("nombre_tarea"), "nombre_tarea"
            )
            fecha_limite = self._texto(
                datos.get("fecha_limite"), "fecha_limite"
            )

            if evento == "task.published":
                titulo = "Nueva tarea publicada"
                mensaje = (
                    f"Se ha publicado la tarea '{nombre_tarea}'. "
                    f"Fecha límite: {fecha_limite}."
                )
            else:
                titulo = "Tarea próxima a vencer"
                mensaje = (
                    f"La tarea '{nombre_tarea}' está próxima a vencer. "
                    f"Fecha límite: {fecha_limite}."
                )

            return self.crear(
                usuario_id=usuario_id,
                evento=evento,
                titulo=titulo,
                mensaje=mensaje,
                datos=datos,
            )

        if evento == "assignment.submitted":
            revisor_id = datos.get("revisor_id")
            nombre_tarea = self._texto(
                datos.get("nombre_tarea"), "nombre_tarea"
            )
            nombre_docente = datos.get("nombre_docente", "Un docente")
            if not isinstance(nombre_docente, str) or not nombre_docente.strip():
                raise ErrorNotificacion(
                    "'nombre_docente' debe ser texto no vacío."
                )

            return self.crear(
                usuario_id=revisor_id,
                evento=evento,
                titulo="Nueva entrega recibida",
                mensaje=(
                    f"{nombre_docente.strip()} ha entregado la tarea "
                    f"'{nombre_tarea}' para revisión."
                ),
                datos=datos,
            )

        raise ErrorNotificacion(f"Evento no permitido: {evento}.")

    def listar(
        self, usuario_id: int, solo_no_leidas: bool = False
    ) -> list[dict[str, Any]]:
        usuario_id = self._validar_usuario_id(usuario_id)
        if not isinstance(solo_no_leidas, bool):
            raise ErrorNotificacion(
                "'solo_no_leidas' debe ser verdadero o falso."
            )

        with self._lock:
            return [
                notificacion.como_dict()
                for notificacion in self._notificaciones
                if notificacion.usuario_id == usuario_id
                and (not solo_no_leidas or not notificacion.leida)
            ]

    def marcar_como_leida(
        self, notificacion_id: int, usuario_id: int
    ) -> dict[str, Any]:
        if (
            isinstance(notificacion_id, bool)
            or not isinstance(notificacion_id, int)
            or notificacion_id <= 0
        ):
            raise ErrorNotificacion(
                "El notificacion_id debe ser un entero positivo."
            )
        usuario_id = self._validar_usuario_id(usuario_id)

        with self._lock:
            for notificacion in self._notificaciones:
                if (
                    notificacion.id == notificacion_id
                    and notificacion.usuario_id == usuario_id
                ):
                    notificacion.leida = True
                    return notificacion.como_dict()

        raise ErrorNotificacion(
            "La notificación no existe o no pertenece al usuario."
        )

    def contar_no_leidas(self, usuario_id: int) -> int:
        usuario_id = self._validar_usuario_id(usuario_id)
        with self._lock:
            return sum(
                1
                for notificacion in self._notificaciones
                if notificacion.usuario_id == usuario_id
                and not notificacion.leida
            )

    def limpiar(self) -> None:
        """Limpia el almacenamiento en memoria; útil para pruebas."""
        with self._lock:
            self._notificaciones.clear()
            self._siguiente_id = 1
