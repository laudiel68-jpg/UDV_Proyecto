# Cambios del Grupo 6

La versión es la de `g6_admin/__init__.py` y la que muestra
`GET /api/v1/health` si no se define `APP_VERSION`.

## 0.4.2 (16-nov-2026), Planner No.5

- **Panel:** "por vencer" y "vencidas" se calculan con la hora de la base
  (`NOW(3)`), la misma de la vista `v_panel_tarea` y de los avisos de
  vencimiento del G1, y no con la del servidor de la app. Las fechas de la
  respuesta llevan la zona de la base (`Z` o `-06:00`).
- **Notificaciones:** el README y Swagger explican que se procesan al llamar
  `POST /api/v1/notifications/process` (y al listar); no hay proceso en
  segundo plano.
- **Prueba de punta a punta (G6-09 y G6-16):** ahora también adjunta la
  evidencia (G2 y G4), autoriza una versión de programa (G5), revisa los avisos
  y descarga el PDF. Evidencia en `docs/evidencia_planner5.md`.

## 0.4.1 (04-nov-2026), retest de QA

- **G6-15:** `GET /api/v1/audit` también muestra el historial de asignaciones
  del G3 (tabla `tarea_transicion`) como acción `transition`. Cada registro
  dice de dónde sale en `source`. El G3 no tiene que escribirlo dos veces.
- **Planner No.3:** prueba de punta a punta `tests/integracion/test_flujo_e2e.py`
  con el workflow real del G3 (G6-04 a G6-16 y G6-18). Evidencia en
  `docs/evidencia_planner3.md`.
- Los errores 422 aceptan el nuevo formato de `details` del G2
  (`{"campo": "mensaje"}`) en las pruebas y en la pantalla de catálogos.

## 0.4.0 (28-oct-2026), Planner No.2

- **Panel de indicadores** `GET /api/v1/dashboard` y pantalla `panel.html`:
  tareas y asignaciones por estado, vencidas, próximas a vencer y
  cumplimiento (G6-26 a G6-29). Lo ven admin, coordinator, authority y auditor.
- **Auditoría:** también la consulta el rol `auditor` (permiso `audit.read` del
  G1); cada registro dice el correo y el nombre de quien hizo la acción; nueva
  ruta `GET /api/v1/audit/filters`; pantalla `auditoria.html` (G6-30 a G6-33).
- **Salud:** `/api/v1/health` muestra el commit desplegado (G6-39).
- **Cierre técnico:** `python -m g6_admin.regresion` (G6-40),
  `python -m g6_admin.persistencia` (G6-37), y las guías `recuperacion.md`
  (G6-38) y `version_final.md` (G6-39).
- `python -m g6_admin.ambiente` exige `UPLOAD_DIR` absoluto en demostración.
- Retest de QA del 25-oct: clave de las pruebas de 32 caracteres o más
  (hallazgo 06) e instalación con comandos de PowerShell, CMD y Mac (hallazgo 03).

## 0.3.0 (23-oct-2026), Planner No.1

- Catálogos, auditoría y notificaciones sobre las tablas del G1 (MySQL), con el
  login y los roles del G2.
- Los eventos de los triggers del G1 se convierten en notificaciones (G6-17).
- Pantalla de catálogos con inicio de sesión.
- Revisión de ambientes (G6-35), instalación desde cero (G6-19) y revisión de
  seguridad (G6-20).
