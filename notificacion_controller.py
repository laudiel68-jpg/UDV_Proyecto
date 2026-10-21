# notificacion_controller.py

class NotificacionController:
    def __init__(self, conexion_db):
        """
        Inicializa el controlador con la conexión a la base de datos (ej. sqlite3, pymysql, etc.)
        """
        self.db = conexion_db

    def _guardar_notificacion(self, usuario_id, tipo, mensaje):
        """
        Método auxiliar para guardar la notificación en la BD
        """
        cursor = self.db.cursor()
        sql = "INSERT INTO notificaciones (usuario_id, tipo, mensaje) VALUES (%s, %s, %s)"
        cursor.execute(sql, (usuario_id, tipo, mensaje))
        self.db.commit()
        return cursor.rowcount > 0

    def notificar_devolucion_entrega(self, docente_id, titulo_tarea):
        """
        PUNTO 7: El revisor devuelve una entrega (assignment.returned)
        Notifica al docente correspondiente.
        """
        tipo = 'assignment.returned'
        mensaje = f"Tu entrega para la tarea '{titulo_tarea}' ha sido devuelta por el revisor para correcciones."
        return self._guardar_notificacion(docente_id, tipo, mensaje)

    def notificar_aprobacion_entrega(self, docente_id, coordinador_id, titulo_tarea):
        """
        PUNTO 8: Una entrega es aprobada (assignment.approved)
        Notifica tanto al docente como al coordinador.
        """
        tipo = 'assignment.approved'
        mensaje = f"La entrega '{titulo_tarea}' ha sido aprobada exitosamente."
        
        # Notificar al docente y al coordinador
        self._guardar_notificacion(docente_id, tipo, mensaje)
        return self._guardar_notificacion(coordinador_id, tipo, mensaje)

    def notificar_autorizacion_programa(self, docente_id, coordinador_id, nombre_programa):
        """
        PUNTO 9: Un programa es autorizado (program.authorized)
        Notifica tanto al docente como a la coordinación.
        """
        tipo = 'program.authorized'
        mensaje = f"El programa académico '{nombre_programa}' ha sido autorizado oficialmente."
        
        # Notificar al docente y al coordinador
        self._guardar_notificacion(docente_id, tipo, mensaje)
        return self._guardar_notificacion(coordinador_id, tipo, mensaje)

    def obtener_pendientes_por_usuario(self, usuario_id):
        """
        Obtiene las notificaciones pendientes de leer para el usuario actual
        """
        cursor = self.db.cursor(dictionary=True) # Dependiendo del conector SQL
        sql = "SELECT id, tipo, mensaje, created_at FROM notificaciones WHERE usuario_id = %s AND leida = 0 ORDER BY created_at DESC"
        cursor.execute(sql, (usuario_id,))
        return cursor.fetchall()