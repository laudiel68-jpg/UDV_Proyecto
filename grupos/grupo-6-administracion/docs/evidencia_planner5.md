# Evidencia del Planner No.5 (16-nov-2026)

Se probó con `main` del repositorio original en `ad7bf8a`, que ya monta los
routers de G2 (con archivos), G3, G4, G5 y G6, más los cambios de esta versión
del G6 (0.4.2). MySQL 8.0 vacío, base creada con `python -m g1_bd crear`.

## Pendientes de QA del Planner No.4

| Escenario | Qué faltaba | Cómo quedó |
|---|---|---|
| G6-09 | No se podía autorizar un programa: la autoridad recibía 403 en la ruta del G5 | El G5 lo corrigió (PR #30). `test_flujo_e2e.py` abre una versión nueva del programa de la semilla, la envía, revisa, aprueba y autoriza con `direccion@`. Al docente y a coordinación les llega un aviso `program.authorized`, una sola vez, y a otro docente ninguno |
| G6-16 | No se podía descargar el PDF ni ver el archivo de la asignación | El G4 ya guarda el archivo en la entrega (PR #33). La prueba sube la evidencia (`POST /api/v1/files`), la adjunta (`POST /api/v1/assignments/{id}/files`), entrega, y el revisor la ve en `GET /api/v1/assignments/{id}` y la descarga con `GET /api/v1/files/{id}`. Al final baja el PDF del programa autorizado con `GET /api/v1/program-versions/{id}/pdf` |

## Arreglos pedidos

| Arreglo | Qué se hizo | Cómo se probó |
|---|---|---|
| Calcular "por vencer" con la hora de la base | El panel toma "ahora" de la base (`NOW(3)`), igual que la vista `v_panel_tarea` y el procedimiento de avisos de vencimiento del G1. Las fechas de la respuesta llevan la zona de la base | `test_panel.py`: con una base en UTC-6 cuyo reloj marca otro día, el panel usa esa hora y responde `-06:00`. `test_mysql_g1.py`: con una sesión de MySQL en `-06:00`, el panel coincide con la vista del G1 |
| Documentar que las notificaciones se procesan con `POST /notifications/process` | README ("Cuándo se procesan") y la descripción de las rutas en Swagger: no hay proceso en segundo plano; se procesan al llamar esa ruta o al listar | Revisión del texto en `/api/v1/docs` |

## Pruebas automáticas

| Conjunto | Resultado |
|---|---|
| `python -m pytest` (sin MySQL) | 253 pasan, 23 se omiten (las de MySQL y una del G2) |
| `python -m pytest tests/integracion` con `G6_MYSQL_URL` | 22 pasan en una base nueva. Si se repite en la misma base, la de crear un período se omite |
| `python -m g6_admin.regresion` contra `uvicorn main:app` | 24 de 24 |

## Cómo lo repite QA en Railway

1. Hacer la acción en el G3, G4 o G5 (por ejemplo, autorizar con
   `direccion@demo.udv.edu.gt` en `POST /api/v1/program-versions/{id}/authorize`).
2. Con un usuario de administración, `POST /api/v1/notifications/process`.
3. Con el usuario que debe recibir el aviso, `GET /api/v1/notifications`.
4. El PDF: `GET /api/v1/program-versions/{id}/pdf` con una versión autorizada.
   El archivo de una entrega: su `file_id` sale en `GET /api/v1/assignments/{id}`
   y se descarga con `GET /api/v1/files/{file_id}`.
