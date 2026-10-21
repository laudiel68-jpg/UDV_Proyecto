<?php
// NotificacionController.php

class NotificacionController {
    private $pdo;

    public function __construct($conexionPdo) {
        $this->pdo = $conexionPdo;
    }

    /**
     * Auxiliar para guardar la notificación en la BD
     */
    private function guardarNotificacion($usuarioId, $tipo, $mensaje) {
        $sql = "INSERT INTO notificaciones (usuario_id, tipo, mensaje) VALUES (?, ?, ?)";
        $stmt = $this->pdo->prepare($sql);
        return $stmt->execute([$usuarioId, $tipo, $mensaje]);
    }

    /**
     * PUNTO 7: El revisor devuelve una entrega (assignment.returned)
     * Notifica al docente correspondiente.
     */
    public function notificarDevolucionEntrega($docenteId, $tituloTarea) {
        $tipo = 'assignment.returned';
        $mensaje = "Tu entrega para la tarea '{$tituloTarea}' ha sido devuelta por el revisor para correcciones.";
        return $this->guardarNotificacion($docenteId, $tipo, $mensaje);
    }

    /**
     * PUNTO 8: Una entrega es aprobada (assignment.approved)
     * Notifica tanto al docente como al coordinador.
     */
    public function notificarAprobacionEntrega($docenteId, $coordinadorId, $tituloTarea) {
        $tipo = 'assignment.approved';
        $mensaje = "La entrega '{$tituloTarea}' ha sido aprobada exitosamente.";
        
        // Notificar al docente
        $this->guardarNotificacion($docenteId, $tipo, $mensaje);
        // Notificar al coordinador
        return $this->guardarNotificacion($coordinadorId, $tipo, $mensaje);
    }

    /**
     * PUNTO 9: Un programa es autorizado (program.authorized)
     * Notifica tanto al docente como a la coordinación.
     */
    public function notificarAutorizacionPrograma($docenteId, $coordinadorId, $nombrePrograma) {
        $tipo = 'program.authorized';
        $mensaje = "El programa académico '{$nombrePrograma}' ha sido autorizado oficialmente.";
        
        // Notificar al docente
        $this->guardarNotificacion($docenteId, $tipo, $mensaje);
        // Notificar a la coordinación
        return $this->guardarNotificacion($coordinadorId, $tipo, $mensaje);
    }

    /**
     * Obtener notificaciones pendientes para el usuario conectado
     */
    public function obtenerPendientesPorUsuario($usuarioId) {
        $sql = "SELECT id, tipo, mensaje, created_at FROM notificaciones WHERE usuario_id = ? AND leida = 0 ORDER BY created_at DESC";
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute([$usuarioId]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }
}
?>