# Grupo 6: Administración, notificaciones, pruebas y despliegue

Módulo `g6_admin`. Este README explica qué existe, cómo se conecta con los
demás grupos y cómo probarlo (CONTRATO.md del G6 §5). Para instalar todo desde
cero sigue [`docs/instalacion.md`](docs/instalacion.md).

## Qué hay por ahora

| Pieza | Ruta | Escenarios QA |
|---|---|---|
| Catálogos: listar (con sesión), agregar y modificar (solo administración) | `GET` y `POST` en `/api/v1/<catálogo>` y `PATCH` en `/api/v1/<catálogo>/{id}`; catálogos `academic-units`, `campuses`, `courses`, `periods`, `modalities` y `areas` | G6-01 a G6-03, G6-21 a G6-25 |
| Facultades (para elegir al crear una unidad académica) | `GET /api/v1/faculties` | G6-21 |
| Pantalla de catálogos, con inicio de sesión del G2 | `g6_admin/pantallas/catalogos.html` | G6-01, G6-02 |
| Notificaciones: las propias, paginadas, y marcar como leída | `GET /api/v1/notifications` (`?unread=true`) y `PATCH /api/v1/notifications/{id}/read` | G6-04 a G6-13 |
| Eventos de G3, G4 y G5 → notificaciones | Automático al listar; `POST /api/v1/notifications/process` (administración) | G6-17 |
| Auditoría: consulta filtrada (solo administración) | `GET /api/v1/audit` con `user_id`, `from`, `to`, `entity` y `action` | G6-14, G6-15, G6-30 a G6-33 |
| Nada queda a medias si algo falla | Transacción por operación y por evento | G6-18 |
| Estado del servicio | `GET /api/v1/health` | G6-34, G6-36 |
| Revisión de ambientes | `python -m g6_admin.ambiente` ([`docs/ambientes.md`](docs/ambientes.md)) | G6-35 |
| Instalación desde cero | [`docs/instalacion.md`](docs/instalacion.md) y [evidencia](docs/evidencia_instalacion.md) | G6-19 |
| Revisión de seguridad de datos semilla | [`docs/revision_seguridad.md`](docs/revision_seguridad.md) y `tests/test_seguridad.py` | G6-20 |

**Quién puede hacer qué**

| Rol (código del G1) | Consultar catálogos | Agregar o modificar registros | Consultar auditoría |
|---|---|---|---|
| Administración (`admin`) | Sí | Sí | Sí |
| Docente (`teacher`) y demás roles | Sí | No: 403 | No: 403 |
| Sin sesión | No: 401 | No: 401 | No: 401 |

Cada persona ve y marca solo sus propias notificaciones (la de otra responde
404).

## Campos de cada catálogo

Son las columnas de las tablas del G1 (`01_schema.sql`). Todos tienen `code`
(2 a 20 caracteres, se guarda en mayúsculas) e `is_active` (opcional,
`true` por defecto).

| Catálogo | Tabla del G1 | Campos propios |
|---|---|---|
| `academic-units` | `unidad_academica` | `name` (hasta 150), `faculty_id`, `campus_id` (deben existir) |
| `campuses` | `sede` | `name` (hasta 150), `address` (opcional, hasta 300) |
| `courses` | `curso` | `name` (hasta 150), `credits` (1 a 30). Lo eliminado por el G1 no se lista |
| `periods` | `periodo` | `year` (2000 a 2100), `cycle` (1 a 4), `start_date` y `end_date` (`AAAA-MM-DD`, fin después del inicio). Año y ciclo no se repiten (409). La respuesta trae un `name` armado, por ejemplo "Ciclo 1 de 2027" |
| `modalities` | `modalidad` | `name` (hasta 100) |
| `areas` | `area` | `name` (hasta 100) |

## Qué usamos de otros grupos

**Grupo 1 (base de datos).** El G6 no crea ni altera tablas: lee y escribe
las del G1 con SQLAlchemy. `g6_admin/tablas.py` describe solo las columnas que
usa el G6; si el G1 cambia una, se cambia ahí.

| Para qué | Tablas |
|---|---|
| Catálogos | `facultad` (solo lectura), `sede`, `unidad_academica`, `curso`, `periodo`, `modalidad`, `area` |
| Auditoría | `auditoria` (solo INSERT; sus triggers bloquean UPDATE y DELETE) |
| Notificaciones | `evento`, `notificacion` (llave única `evento_id` + `usuario_id`) |
| Saber a quién avisar (solo lectura) | `tarea`, `tarea_destinatario`, `programa_version`, `usuario`, `usuario_rol`, `rol` |

**Grupo 2 (API y seguridad).** El G6 no tiene login, usuarios ni formato de
error propios:

| Para qué | Qué se importa |
|---|---|
| Sesión de base de datos por petición | `g2_api.database.get_db` |
| Saber quién inició sesión | `obtener_usuario_actual` (lee `Authorization: Bearer`) |
| Permitir agregar y modificar solo a administración | `requerir_rol(["admin"])` |
| Formato de error (401, 403, 404, 409, 422) | `api_error` y `register_error_handlers` |
| Paginación y máximo de `per_page` | `params_paginacion` |
| Revisar la base en `/api/v1/health` | `probar_conexion` |

La pantalla inicia sesión con `POST /api/v1/auth/login` del G2, guarda el
token en `sessionStorage` con la clave `udv_token` y pregunta los roles a
`GET /api/v1/me`. Si la pantalla de login del G2 guarda el token con esa
misma clave, la sesión se comparte.

## Cómo llegan las notificaciones (G6-04 a G6-11 y G6-17)

Los grupos 3, 4 y 5 **no tienen que llamar al G6**. Cuando cambian una tarea,
una entrega o un programa, los triggers del G1 escriben una fila en `evento`.
El G6 procesa los eventos pendientes cada vez que alguien lista sus
notificaciones (o con `POST /api/v1/notifications/process`), guarda un aviso
por destinatario y marca el evento como procesado.

| Evento (lo crea el G1 cuando…) | A quién avisa el G6 |
|---|---|
| `task.published` (la tarea pasa de `draft` a `assigned`) | Destinatarios de la tarea |
| `assignment.due_soon` (procedimiento `sp_generar_eventos_vencimiento`) | El docente de esa asignación |
| `assignment.submitted` (transición a `submitted`) | El revisor de la asignación o de la tarea |
| `assignment.returned` (transición a `returned`) | El docente, con el comentario |
| `assignment.approved` (transición a `approved`) | El docente y quien creó la tarea |
| `program.authorized` (la versión pasa a `authorized`) | El docente responsable y los usuarios con rol `coordinator` |
| `task.cancelled` (la tarea pasa a `cancelled`) | Destinatarios de la tarea |

Procesar dos veces no duplica nada. Cada evento va en su propia transacción:
si uno falla, queda pendiente y los demás siguen. Este es el transporte de
eventos que el G6 propone al PM (README §5, "Transporte de eventos").

Para un evento que no sale de un trigger, se puede usar
`notificaciones_para(db).procesar_evento({...})` de `g6_admin.api`.

## Cómo registran sus transiciones el G3 y el G5 (G6-15)

La tabla `tarea_transicion` del G1 ya guarda el historial de las tareas. Si
además quieren dejarlo en la auditoría transversal, usan la misma sesión de
su operación y hacen un solo commit:

```python
from g6_admin.api import auditoria_para

auditoria_para(db).registrar_transicion(
    actor_id=12,                     # quién hizo el cambio
    entidad="tarea_destinatario",    # tarea, tarea_destinatario o programa_version
    entidad_id=58,
    estado_anterior="in_progress",
    estado_nuevo="submitted",
    comentario="Entrego la planificación.",  # opcional, hasta 1000 caracteres
)
db.commit()
```

Solo se aceptan los estados oficiales de CONTRATO_COMUN.md §2. La consulta
`GET /api/v1/audit` muestra todo lo de la tabla `auditoria`: lo que registra
el G6 (altas y cambios de catálogos), lo de los triggers del G1 (tareas,
programas y usuarios) y los inicios de sesión del G2. `entity` es el nombre de
la tabla (`sede`, `curso`, `tarea`, `usuario`...) y `action` puede ser
`insert`, `update`, `soft_delete`, `transition`, `LOGIN_OK`, etc.

## Cómo correr las pruebas

```bash
cd grupos/grupo-6-administracion
python -m pytest
```

Necesitan la carpeta del G2 (`grupos/grupo-2-api-seguridad/`). No usan MySQL:
crean las tablas del G1 en un SQLite en memoria, nuevo en cada prueba, y solo
reemplazan quién inició sesión (`dependency_overrides`). Las de
`tests/integracion/` corren contra MySQL real si se define `G6_MYSQL_URL`
(ver `docs/instalacion.md`, paso 6); usan el login real del G2 y los
triggers reales del G1.

| Archivo | Qué prueba |
|---|---|
| `test_catalogos.py` | G6-01 a G6-03, G6-21 a G6-25 y los campos de cada tabla |
| `test_notificaciones.py` | G6-04 a G6-13 |
| `test_eventos.py` | G6-17: eventos del G1 → avisos |
| `test_auditoria.py` | G6-14, G6-15, G6-30 a G6-33 |
| `test_transacciones.py` | G6-18 |
| `test_salud.py` | G6-34, G6-36 |
| `test_ambiente.py` | G6-35 |
| `test_seguridad.py` | G6-20, G6-36 |
| `integracion/test_mysql_g1.py` | Todo lo anterior contra MySQL y el login del G2 |

## Cómo se integra a la aplicación

El G6 no levanta su propia app (CONTRATO_COMUN §1). Lo integra el PM en el
`main.py` de la raíz. **Pedidos al PM:**

1. Activar la línea `("g6_admin.api", "router")` en `ROUTERS`.
2. Montar también `("g2_api.routers.auth", "me_router")`: sin él,
   `GET /api/v1/me` da 404.
3. Servir la pantalla: `g6_admin/pantallas/` en `/g6` y `grupos/udv-styles/`
   en `/udv-styles`. La pantalla queda en `/g6/catalogos.html`.
4. Agregar `APP_ENV` y `APP_VERSION` al `.env.example`.
5. `docker-compose.yml` carga `db_udv_completo.sql`, que el G1 ya no tiene:
   ahora son `01_schema.sql` y `02_seed.sql`.
6. Aprobar el transporte de eventos por la tabla `evento` (sección de
   notificaciones).

## Cómo está organizado

| Archivo | Qué hace |
|---|---|
| `g6_admin/api.py` | Rutas `/api/v1/...` en `router`, que monta el `main.py` de la raíz |
| `g6_admin/tablas.py` | Las columnas de las tablas del G1 que usa el G6 |
| `g6_admin/catalogos.py` | Reglas de catálogos: campos, validación, búsqueda y orden |
| `g6_admin/notificaciones.py` | Eventos, destinatarios y marcas de lectura |
| `g6_admin/auditoria.py` | Registro y consulta de la auditoría |
| `g6_admin/salud.py` | Respuesta de `/api/v1/health`, sin detalles internos |
| `g6_admin/ambiente.py` | Revisión de variables de cada ambiente |
| `g6_admin/pantallas/catalogos.html` | Pantalla con los estilos de `grupos/udv-styles/udv.css` |
| `docs/` | Instalación, ambientes, evidencia y revisión de seguridad |
| `tests/` | Pruebas automáticas |

## Variables de entorno

| Variable | Uso | Valor por defecto |
|---|---|---|
| `DATABASE_URL` | Conexión a `db_udv` (la lee el G2) | Sin valor: `/health` dice `not_configured` |
| `SECRET_KEY` | Firma de los tokens del G2 | Obligatoria |
| `APP_ENV` | `desarrollo` o `demostracion`; lo muestra `/api/v1/health` | `desarrollo` |
| `APP_VERSION` | Versión que muestra `/api/v1/health` | La versión de `g6_admin` |
| `G6_MYSQL_URL` | Solo para `tests/integracion` | Sin valor: se omiten |
