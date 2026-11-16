# Panel de indicadores (G6-26 a G6-29)

`GET /api/v1/dashboard` y la pantalla `pantallas/panel.html`. Lo ven los roles
con el permiso `tasks.monitor` de la semilla del G1: `admin`, `coordinator`,
`authority` y `auditor`. Un docente o un revisor recibe 403.

Los números se calculan en el momento con las tablas del G1, sin guardar
copias. Por eso el panel siempre coincide con la base, y QA puede comprobar
cada número con las consultas de abajo.

## Qué significa cada número

| Indicador | Escenario | Regla |
|---|---|---|
| Tareas por estado | G6-26 | `tarea.estado_codigo`, sin las tareas con `eliminado_en` |
| Asignaciones por estado | G6-26 | `tarea_destinatario.estado_codigo` de esas mismas tareas |
| Vencidas | G6-27 | Asignación pendiente (`assigned`, `in_progress` o `returned`) cuya fecha límite ya pasó |
| Próximas a vencer | G6-28 | Asignación pendiente que vence entre ahora y los próximos N días. N es el parámetro `dias_aviso_vencimiento` del G1 (3 en la semilla) |
| Cumplimiento | G6-29 | Asignaciones `submitted`, `under_review`, `approved` o `closed`, dividido entre todas las que no están `cancelled`, en porcentaje con un decimal |

- La **fecha límite** de una asignación es la suya; si no tiene, se usa la de
  su tarea.
- **Ahora** es la hora de la base (`NOW(3)` en MySQL), no la del servidor de
  la app. Es la misma que usan la vista `v_panel_tarea` y el procedimiento de
  avisos de vencimiento del G1, y la misma zona en que el G1 guarda sus fechas.
- Las fechas de la respuesta (`generated_at` y `due_date`) llevan la
  diferencia de la base con UTC: terminan en `Z` si la base está en UTC, o en
  `-06:00` si está en hora de Guatemala.
- Las listas de vencidas y próximas muestran hasta `limit` asignaciones (20
  por defecto, máximo 100), ordenadas por fecha. Los totales cuentan todas.

Son las mismas reglas de la vista `v_panel_tarea` del G1, con una diferencia:
si la tarea ya está `cancelled` o `closed`, sus asignaciones no salen como
vencidas ni próximas, aunque alguna se haya quedado en un estado pendiente. El
G1 no cambia las asignaciones cuando se cancela la tarea, y una tarea
cancelada ya no tiene nada que entregar.

## Cómo comprobarlo en la base (MySQL)

Correr en `db_udv` y comparar con la respuesta de `GET /api/v1/dashboard`.
Lo mismo hace `tests/integracion/test_mysql_g1.py`.

```sql
-- G6-26: tareas por estado (tasks.by_state)
SELECT estado_codigo, COUNT(*) FROM tarea
WHERE eliminado_en IS NULL GROUP BY estado_codigo;

-- G6-26: asignaciones por estado (assignments.by_state)
SELECT td.estado_codigo, COUNT(*) FROM tarea_destinatario td
JOIN tarea t ON t.id = td.tarea_id
WHERE t.eliminado_en IS NULL GROUP BY td.estado_codigo;

-- G6-27 y G6-28: vencidas y próximas (overdue.total y due_soon.total)
SELECT SUM(vencidas) AS vencidas, SUM(proximas_a_vencer) AS proximas
FROM v_panel_tarea WHERE estado_tarea NOT IN ('cancelled', 'closed');

-- G6-29: cumplimiento (compliance)
SELECT SUM(entregadas + en_revision + aprobadas) AS completed,
       SUM(total_asignaciones - canceladas)      AS expected
FROM v_panel_tarea;
```

La vista y el panel calculan "ahora" con el mismo `NOW(3)` de la base, así
que coinciden aunque el servidor MySQL no esté en UTC (el `docker-compose.yml`
de la raíz pone `TZ: America/Guatemala`). `tests/integracion/test_mysql_g1.py`
lo comprueba con una sesión en `-06:00`.

## Ejemplo de respuesta

```json
{
  "generated_at": "2026-11-02T12:00:00Z",
  "due_soon_days": 3,
  "tasks": {"total": 4, "by_state": {"draft": 1, "assigned": 1, "in_progress": 1, "submitted": 0,
            "under_review": 0, "returned": 0, "approved": 0, "closed": 1, "cancelled": 0}},
  "assignments": {"total": 8, "by_state": {"...": 0}},
  "overdue": {"total": 1, "items": [{"assignment_id": 1, "task_id": 1, "task_title": "Planificación",
              "user_id": 3, "user_email": "docente1@demo.udv.edu.gt", "user_name": "Diana Pérez",
              "state": "assigned", "due_date": "2026-11-01T12:00:00Z"}]},
  "due_soon": {"total": 1, "items": ["..."]},
  "compliance": {"percentage": 42.9, "completed": 3, "expected": 7}
}
```

Todos los estados oficiales aparecen siempre, aunque sea con 0, en el orden
del flujo. Sin asignaciones, `compliance.percentage` es `null`.
