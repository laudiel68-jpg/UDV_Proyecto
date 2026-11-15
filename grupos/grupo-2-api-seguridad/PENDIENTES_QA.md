## Pendientes del QA — Grupo 2 (Update No. 3 · 05-nov-2026 · estado al 15-nov-2026)

Resumen de los informes de Allison Espaderos (QA: Informe No. 1, Update No. 2 e Informe de Retest No. 2) y quién corrige cada cosa. Cada quien toca **solo sus archivos**. Los números G2-xx son los escenarios del plan de QA.

Prioridad: **Alta** → **Media** → **Baja**. El Planner de Allison tiene tres tareas (Alta, Media y Baja) con puntos por escenario; están sin responsable y con fecha 21/10. El detalle está en `GUIA_GRUPO2.md`, sección 8.

## Avisos del PM y de QA (12 y 14-nov)

| Aviso | Quién | Estado al 15-nov |
|-|-|-|
| Pantalla de login apuntaba a `localhost` y no guardaba el token | Robert (archivo de Fulvio) | 🔵 `script.js`: ruta relativa `/api/v1/auth/login`, `sessionStorage.setItem("udv_token", ...)` y redirección a `/app/`. Falta que Fulvio lo revise y el PR 14-nov: QA probó el login integrado en Railway y dio 5/5 PASS (portal, autenticación, `udv_token`, acceso a G4 y logout). |
| Avisar en el grupo antes de cambiar algo compartido (errores, auth, Swagger); el cambio de formato rompió 3 pruebas del G6 | Todos (Edgar, Randy, Daniel) | ⏳ Regla para la semana 6 |
| El bloqueo tras 5 intentos no estaba en Swagger ni decía cuánto falta | Robert | 🔵 `openapi_docs.py`: login documenta 200, 401, 422 y 429 (5 fallos = 15 minutos, mensaje con los minutos que faltan); `tests/test_openapi.py` al día |
| `.env.example` sin valores reales | Robert | 🔵 Solo marcadores (`TU_USUARIO`, `TU_CLAVE`, `TU_HOST`, `TU_PUERTO`, `TU_CLAVE_SECRETA`) |
| MySQL antes del PR, convención única de pantalla (`udv_token`, rutas relativas, `udv.css`) y avisar cada PR | Daniel y todos | 🔵 `index.html` carga `/udv-styles/udv.css`. Falta `pytest` contra MySQL y el PR (Daniel) |
| G2-33: confirmar si ya está arreglado para actualizar la hoja de QA | Robert y PM | 🔵 Corregido (06-nov) y el PM ya lo activó en la raíz (PR #24 en `main`). Falta el despliegue y que Allison repita G2-33 14-nov: QA confirmó que Railway ya muestra la documentación corregida; quedó solo H-04 (ver la fila siguiente). |
| G2-33, H-04: el ejemplo 200 de `GET /me` traía `creado_en` y `actualizado_en` y la API real no los devuelve | Robert | 🔵 Corregido el 15-nov en `openapi_docs.py` (ejemplo sin fechas); `tests/test_openapi.py` lo compara con la respuesta real. Falta el PR (Daniel) y que Allison repita G2-33 |
| Descarga de archivos: la descripción de Swagger solo mencionaba al dueño y al admin | Robert | 🔵 Alineada con la regla nueva del PM (dueño, admin o rol no docente con `files.download`); README al día. QA confirmó la regla en Railway: revisor 200, docente ajeno 403 |
| Retest complementario (14-nov): 7 hallazgos de integración del PM | Todos | ✅ PASS en descarga por revisor, 422 en usuarios y roles, correo inválido, Coordinación en `GET /users` y mensaje al rechazar un formato; archivo eliminado PASS en prueba aislada (1/1). `UPLOAD_DIR`: PASS en código, sin verificar el volumen de Railway. H-02 (201): PASS documental, no se creó un usuario nuevo para no modificar la base compartida |

`pytest` completo en `grupo-2` (15-nov): **130 pasan**.

## Retest No. 3 (05-nov) · estado al 09-nov

Allison repitió G2-21, G2-31, G2-32 y G2-33 contra la API desplegada en Railway (informe consolidado del 05-nov; los PDF están en `qa/`). Resultado de los 38 escenarios: **37 PASS y 1 FAIL (G2-33)**. En el Planner quedan completas las tareas de prioridad Alta y Baja; solo sigue abierta la de prioridad Media (OpenAPI).

| Escenario | Resultado de QA (05-nov) | Quién | Estado al 09-nov |
|-|-|-|-|
| G2-21 | ✅ PASS 4/4: el dueño y el admin descargan (200), otro usuario recibe 403 | Fulvio | ✅ Cerrado. Ya está en `main` (PR #20; el PM montó `/files` en el PR #22) |
| G2-31 | ✅ PASS 22/22: `page` y `per_page` de 1 a 100, 422 fuera de rango | Randy | ✅ Cerrado |
| G2-32 | ✅ PASS 8/8: 32 fechas en ISO 8601 y UTC con `Z` | Randy | ✅ Cerrado |
| G2-33 | ❌ FAIL documental: Swagger de Railway no coincide con la API (H-01 a H-05) | Robert | 🔵 Corregido en `grupo-2` el 06-nov. El PM ya lo activó en el `main.py` de la raíz (PR #24, 12-nov); falta confirmar el despliegue y el retest. Ya está comentado «listo para retest» en el Planner 14-nov: el retest dejó solo H-04 (ejemplo de `GET /me` con fechas); corregido el 15-nov. |

**Por qué falló G2-33.** Los códigos HTTP y los ejemplos de Swagger estaban en `g2_api/main.py`, pero Railway ejecuta el `main.py` de la raíz, que solo monta los routers y nunca cargaba esa documentación. Las pruebas pasaban porque usan la app de `g2_api`; QA veía la de la raíz. Las respuestas reales de la API estaban bien.

| ID de QA | Hallazgo | Corrección (Robert, 06-nov) |
|-|-|-|
| H-01 | `POST /users` sin 409 | 409 documentado con el formato común de error |
| H-02 | `POST /users` con `"string"` en el 201 | Ejemplo con el objeto del usuario creado |
| H-03 | 422 con el esquema genérico de FastAPI | 422 con `ErrorResponse` (`error.code`, `error.message`, `error.details` como objeto) |
| H-04 | `GET /me` con `"string"` en el 200 | Ejemplo con el usuario, sus roles y permisos |
| H-05 | `GET /users` con `"string"` en el 200 y sin 403 | Ejemplo paginado (`page`, `per_page`, `total`, `data`) y 403 documentado |

**Cambio (Robert, solo `grupos/grupo-2-api-seguridad/`):** la documentación pasó a `g2_api/openapi_docs.py` (`completar_openapi(app)`), que usan `g2_api/main.py` y cualquier otra app. Solo toca las rutas del G2. `tests/test_openapi.py` ahora también prueba una app armada como la de la raíz; `pytest` completo: **107 pasan**. Se comprobó además con una copia del `main.py` de la raíz: `POST /users` da 201, 401, 403, 409 y 422; `GET /users` da 200, 401 y 403; `GET /me` da 200 y 401, todos con ejemplos de objeto. Commits en `grupo-2`: `b58a863` (`main.py`), `bddbf20` (`openapi_docs.py`), `71a0dca` (`tests/test_openapi.py`) y `a4c8232` (`README.md`).

**Falta para cerrar G2-33 (en este orden):**
1. Daniel abre el PR `grupo-2` → `main` con estos cambios.
2. El PM agrega dos líneas al `main.py` de la raíz, después de montar los routers: `from g2_api.openapi_docs import completar_openapi` y `completar_openapi(app)`. Ese archivo es del PM y el G2 no lo toca (CONTRATO.md §5).
3. El PM despliega en Railway y avisa a Allison; ella repite G2-33.

**Estado al 09-nov:** `pytest` completo pasa 115 (los 107 del 06-nov más las 8 pruebas de `tests/test_file.py`, que Fulvio subió el 08-nov).

Los estados «Falta retest» de las tablas siguientes son del retest No. 2 y quedaron cerrados arriba, salvo G2-33.

## Retest No. 2 (23 y 24-oct) · estado al 02-nov (histórico, superado por el retest No. 3)

34 PASS, 2 FAIL, 1 PARCIAL y 1 PASS histórico con retest pendiente. `pytest` en `grupo-2` (04-nov): 103 pasan, sin fallas. `test_campo_obligatorio_faltante_422` en `tests/test_users.py` ya lee `details` como objeto con un campo por llave (Randy y Robert, 04-nov; Randy también agregó `test_password_fuera_de_largo_422` y quitó el `xfail`). El `details` del 422 ya sale como objeto y el xfail de `tests/test_openapi.py` se quitó; la contraseña de 8 a 64 al crear usuario ya pasa.

| Escenario | Resultado de QA | Quién | Archivo | Estado al 02-nov |
|-|-|-|-|-|
| G2-21 | FAIL (crítico): un docente descarga el archivo de un admin | Fulvio | `routers/files.py` | 🔵 Subido el 28-oct (`6982c15`): `GET /files/{id}` da 403 si no es el dueño ni un admin y 404 si no existe; el archivo se registra en la tabla `archivo`. 31-oct (`7ffa69c`): el admin también descarga, como confirmó el PM (01-nov). ✅ PASS 4/4 en el retest del 05-nov. Ya está en `main` (PR #20 y PR #22 del PM) |
| G2-31 | FAIL: `GET /users` sin paginación | Randy | `routers/users.py` | ✅ Ya pagina desde el 24-oct. PASS 22/22 en el retest del 05-nov |
| G2-33 | PARCIAL: faltaban 409, 403 y ejemplos reales | Robert | `main.py` | 🔵 Hecho el 27 y 28-oct y probado en `tests/test_openapi.py`; ejemplos al día con el PM el 01-nov (fechas, `details` como objeto, 403 en archivos). 04-nov: el usuario de ejemplo pasó a `Carlos Maeda` (`e593976`). ❌ FAIL documental en el retest del 05-nov (Railway no usaba esta documentación); corregido el 06-nov, ver el retest No. 3 |
| G2-32 | PASS histórico, retest pendiente: ya no salen `creado_en` ni `actualizado_en` | Randy y PM | `routers/users.py` | 🔵 Subido el 02-nov (`9205344`): salen de solo lectura, en ISO 8601 y en UTC con `Z` (por ejemplo `2026-10-29T21:30:00Z`), como pidió el PM (01-nov). ✅ PASS 8/8 en el retest del 05-nov |
| G2-36 | PASS de QA y del PM (retest del 23-oct). Antes el PM avisó que el login fallido se guardaba dos veces | Daniel y Edgar | `routers/auth.py`, `utils/registro.py` | ✅ PASS de QA. 02-nov: `registro_id = 0` otra vez con correo inexistente (Daniel); 03-nov: queda igual en `registro.py` (Edgar) |
| Limpieza | Aviso del PM | Daniel | `routers/auth.py` | ✅ Hecho (02-nov): se quitó la carga de `usuarios_prueba.json` y la carpeta `datos_prueba/` |
| Aviso del Grupo 1 (28-oct) | `set_actor_id()` en `registro.py` (línea 61) manda `@actor_id = 0` cuando no hay usuario y la llave foránea hace fallar la auditoría. Hoy ninguna ruta la llama | Edgar | `utils/registro.py` | ✅ Corregido el 30-oct: manda NULL (`f5b2d35`). Aparte, `users.py` ya pasa `request.client.host` a `fijar_actor` (Randy, 02-nov) |

Ese PR ya entró a `main` el 04-nov (PR #20), con G2-21, las fechas, `details` y el JSON de prueba. El siguiente PR (solo Daniel) lleva la corrección de G2-33: antes, merge de `main` en `grupo-2` y `pytest` completo.

## Update No. 2 e Informe de Retest No. 2 del QA (23 y 24-oct)

Allison evaluó los 38 escenarios con las cuentas QA (admin, coordinador, docente, revisor, autoridad y auditor). Resultado general: **satisfactorio con hallazgos pendientes de corrección**. El QA no recomienda cerrar la evaluación hasta corregir los fallos y repetir lo pendiente en la versión integrada a `main`.

| Estado | Cantidad |
|-|-|
| PASS | 34 |
| FAIL | 2 (G2-21 y G2-31) |
| PARCIAL | 1 (G2-33) |
| PASS histórico, retest pendiente | 1 (G2-32) |
| Total | 38 |

| Prioridad | Escenario | Resultado de QA | Nota |
|-|-|-|-|
| 🔴 Alta | G2-01 | PASS | Login de la cuenta admin QA: 200 y JWT de 7200 s; el JWT abre `/me` |
| 🔴 Alta | G2-02 | PASS | Contraseña incorrecta: 401 genérico, sin token |
| 🔴 Alta | G2-05 | PASS | Logout revoca el token: al reusarlo da 401 |
| 🔴 Alta | G2-06 | PASS | `GET /users` sin token da 401 (antes 422) |
| 🔴 Alta | G2-08 | PASS | Docente en `GET /users`: 403 |
| 🔴 Alta | G2-09 | PASS | Docente en funciones de admin: 403 |
| 🔴 Alta | G2-10 | PASS | El encabezado `usuario-actual` falsificado ya no sirve |
| 🔴 Alta | G2-15 | PASS (caso evaluado) | XSS guardado en `nombres`: se muestra como texto, no se ejecuta |
| 🔴 Alta | G2-16 | PASS (caso evaluado) | SQL Injection en el login: 401 y consultas con SQLAlchemy |
| 🔴 Alta | G2-17 | PASS | Docente no puede modificar al admin con `PATCH /users/{id}`: 403 |
| 🔴 Alta | G2-19 | PASS | TXT y TXT renombrado a .pdf: 400 |
| 🔴 Alta | G2-20 | PASS | Archivo de 6 MB: 400 (límite de 5 MB) |
| 🔴 Alta | G2-21 | FAIL | Un docente descargó con 200 el archivo de un admin (posible IDOR) |
| 🔴 Alta | G2-22 | PASS | Rutas manipuladas: 404; nombre interno con UUID |
| 🔴 Alta | G2-23 | PASS (casos evaluados) | Errores sin SQL, rutas ni trazas |
| 🔴 Alta | G2-24 | PASS | Respuestas sin contraseñas, hashes ni tokens |
| 🔴 Alta | G2-35 | PASS | `.gitignore` y `.env.example` sin credenciales reales |
| 🔴 Alta | G2-37 | PASS | Token vencido: 401 |
| 🔴 Alta | G2-38 | PASS | Token alterado: 401 |
| 🟡 Media | G2-03 | PASS | Usuario inexistente: 401 genérico, en API y en el frontend |
| 🟡 Media | G2-04 | PASS (con observación) | Campos vacíos: QA vio 401 en vez de 422. Daniel lo corrigió el 23-oct (`""` da 422): pedir que se repita |
| 🟡 Media | G2-07 | PASS | `/me` con JWT: 200 con rol y permisos; sin token 401 |
| 🟡 Media | G2-11 | PASS | `GET /users/{id}`: 200 para admin, 403 para docente |
| 🟡 Media | G2-12 | PASS | ID inexistente: 404 |
| 🟡 Media | G2-13 | PASS | Campos obligatorios ausentes: 422 |
| 🟡 Media | G2-14 | PASS | Tipos incorrectos: 422 |
| 🟡 Media | G2-18 | PASS (con observación) | PDF válido: devuelve `file_id` y se descarga. Swagger pedía `file_id` en query en vez de `{id}`: la ruta ya usa `{id}` |
| 🟡 Media | G2-25 | PASS | Crear usuario: 201 con admin, 403 con docente, 401 sin token |
| 🟡 Media | G2-26 | PASS | Usuario inexistente: 404 en GET y en PATCH |
| 🟡 Media | G2-27 | PASS | Correo repetido: 409 y no se duplica |
| 🟡 Media | G2-28 | PASS | Error de validación: 422 con el campo `correo` |
| 🟡 Media | G2-29 | PASS | JSON mal formado: 422 con estructura uniforme |
| 🟡 Media | G2-30 | PASS (errores evaluados) | 400, 401, 403, 404 y 422 con `error`, `code`, `message` y `details` |
| 🟡 Media | G2-33 | PARCIAL | Faltaban 409 y 403, y los ejemplos eran `string`; ver la tabla del retest |
| ⚪ Baja | G2-31 | FAIL | `GET /users` devolvía un arreglo sin `page`, `per_page`, `total` ni `data` |
| ⚪ Baja | G2-32 | PASS histórico, retest pendiente | Las consultas ya no traen fechas; falta confirmar el contrato con el PM |
| ⚪ Baja | G2-34 | PASS | 5 intentos: 4 veces 401 y la quinta 429; con la clave correcta sigue bloqueado y a los 15 minutos entra |
| ⚪ Baja | G2-36 | PASS | Login con correo inexistente queda como LOGIN_FALLIDO; el PATCH de usuario queda con actor y registro |

**Orden de atención que recomienda el QA:** 1) G2-21 (archivos, crítico), 2) G2-36 (confirmar la auditoría en la versión de `main`, porque el PM reportó otra cosa), 3) G2-31 (paginación), 4) G2-33 (OpenAPI), 5) G2-32 (fechas). Además, una nueva regresión después de integrar `grupo-2` a `main`.

**Lo que ya mejoró frente al Informe No. 1:** JWT en endpoints protegidos, encabezado `usuario-actual` sin efecto, permisos por rol, consulta individual de usuarios, logout con revocación, tokens vencidos y alterados rechazados, validación de tipo y tamaño de archivos, formato uniforme de errores, bloqueo por intentos y auditoría.

## Avisos del PM por prioridad (retest del 23-oct) y qué se puede probar

| Prioridad | Escenario | Aviso del PM (retest del 23-oct) | Qué probar antes de avisar | ¿Se puede comentar en el Planner? |
|-|-|-|-|-|
| 🔴 Alta | G2-21 | Un docente descargó con HTTP 200 un PDF cargado por un admin: `GET /files/{id}` pedía token pero no revisaba al dueño. Debe dar 403 o 404 sin revelar el archivo | Subir un PDF con un usuario y copiar el `file_id`; pedir `GET /files/{id}` con otro usuario (debe dar **403**), con el dueño o un admin (**200**), con un id que no existe (**404**) y sin token (**401**) | Sí, como «corregido, listo para retest» (commit `6982c15`, 28-oct). No marcarlo completado hasta que Allison repita G2-21 |
| 🟡 Media | G2-07, G2-12, G2-26 | PASS los tres (`/me`, consulta individual y recursos inexistentes) | Nada más | Ya están cerrados. Se puede comentar «PASS confirmado por el PM» |
| 🟡 Media | G2-33 | PARCIAL: Swagger no coincidía con `POST /users`, `GET /me` y `GET /users` (faltaban códigos HTTP y los ejemplos JSON eran incorrectos) | En `/api/v1/docs` revisar `POST /users` (201, 401, 403, 409, 422), `GET /me` (200 con objeto y 401), `GET /users` (200 con `page`, `per_page`, `total`, `data`, 401 y 403) y `files` con `{id}`; correr `pytest tests/test_openapi.py` | Sí, listo para retest (Robert, 27 y 28-oct) |
| ⚪ Baja | G2-34, G2-36 | PASS los dos (bloqueo temporal y registro de auditoría) | Nada más; solo confirmar antes del PR que el login fallido se guarda una vez | Ya están cerrados |
| ⚪ Baja | G2-31 | FAIL: `GET /users` no paginaba. Debe devolver `page`, `per_page`, `total` y `data` | `GET /users?page=1&per_page=5` con admin: revisar los cuatro campos y el máximo de 100 por página | Sí, listo para retest (Randy, 24-oct, con `tests/test_users.py`) |
| ⚪ Baja | G2-32 | PASS histórico, retest pendiente: las consultas de usuarios ya no traen `creado_en` ni `actualizado_en` | Revisar que `GET /users` y `GET /users/{id}` traigan `creado_en` y `actualizado_en` en ISO 8601 con zona horaria (PM, 01-nov) | Sí, listo para retest (Randy, 02-nov, `9205344`) |

## Lo más urgente (crítico)

El middleware de usuarios y roles todavía lee el encabezado `usuario-actual` y una lista JSON temporal, en vez del JWT. Por eso cualquiera puede hacerse pasar por administrador (G2-10) y el login real no sirve para entrar a `/users` ni `/roles`. Esto bloquea G2-06, 08, 09, 17, 37 y 38.

**Cómo leer los estados:** ✅ Cumple (PASS de QA) · 🔵 Implementado, pendiente de validación o retest de QA · 🟡 En proceso · ⏳ Pendiente de implementar.

## Estado al 23-oct

- **Actualización 23-oct (tarde, commit 7750106):** `pytest` completo en **40 de 40**. Hecho: bloqueo de 5 intentos por 15 minutos (G2-34), contraseña de 8 a 64 y `""` da 422 (G2-04), login fallido con correo inexistente queda en auditoría (G2-36) y `POST /files` ya no da 500 con token (G2-18).
- **Aviso del PM (22-oct):** G2 arregló el manejador de errores y los 401, 403 y 404 ya responden bien. Daniel agregó `obtener_usuario_actual()` desde la base, con `@actor_id` para la auditoría. El PM contó 28 pruebas que pasan y 4 que fallan (en la mañana fallaban 15).
- **Retest de QA: viernes 23-oct**, después del PR del jueves. Prioridad: G2-10 (suplantación por header), G2-04 (422), G2-07 (`/me`) y login con las cuentas `qa.*`.
- **Lo que se pidió antes del PR del jueves y cómo está en `grupo-2` (revisado el 23-oct):**
  1. `registro.py` (Edgar): de 4 pruebas fallando quedó 1. `pytest` completo: **33 pasan y 1 falla** (`test_login_fallido_queda_en_auditoria`). Falla porque, cuando el correo no existe o viene vacío, el login fallido intenta guardar `registro_id` en NULL y la base lo rechaza (NOT NULL), así que ese intento no queda registrado.
  2. `auth_middleware.py` (Randy): ya no lee el JSON. Usa `obtener_usuario_actual()` de `auth.py` (commit del 22-oct). Sin token da 401, con el header `usuario-actual` también da 401 y sin rol da 403.
  3. `users.py` y `roles.py` (Randy): ya usan el rol `admin` y leen de la base. `GET /users/{id}` da 404 si no existe.
- **Daniel** (`auth.py`): login, logout y `/me` funcionan con la base. El token cerrado con logout ya no entra (401). El login con campos ausentes da 422, pero con cadenas vacías (`""`) todavía da 401: falta `min_length=1` en los campos del login (G2-04).
- **Robert**: `main.py`, `database.py` (UTC y `fijar_actor`), `models.py`, `.env.example` y `README.md` quedaron listos el 20 y 22-oct.
- **Siguen pendientes:** paginación en `GET /users`, contraseña de 8 a 64 al crear usuarios, documentación OpenAPI (401 y 409 en `POST /users`), `test_users.py` (Randy) y `GET /files/{id}`, tabla `archivo` y `test_files.py` (Fulvio).

## Por persona

### Daniel · Persona 1 · Autenticación
| Escenario | Prioridad | Qué falta | Archivo | Estado |
|-|-|-|-|-|
| G2-05 | Alta | El QA no lo encontró. Ya está subido (20-oct): `POST /auth/logout` pone `revocado_en` en `sesion_token` y el token revocado ya da 401. | `routers/auth.py` | 🔵 Listo para retest |
| G2-07 | Media | El QA recibió 404. Ya está subido (20-oct): `GET /me` con `me_router`. Responde 200 con JWT válido y 401 sin token o con token inválido. | `routers/auth.py` | 🔵 Listo para retest |
| G2-34 | Baja | El login no usa el contador ni el bloqueo (5 fallos = 15 min). `registro.py` ya trae `esta_bloqueado()`, falta llamarlo. | `routers/auth.py` | ✅ Hecho (23-oct): 5 fallos = 429 por 15 minutos, con `intentos_fallidos` y `bloqueado_hasta`. Listo para retest |
| G2-36 | Baja | Login correcto, login fallido y logout ya llaman a `registro.py`. Falta que el login fallido con correo inexistente o vacío se guarde (`registro_id` no puede ir NULL). | `routers/auth.py`, `utils/registro.py` | ✅ Hecho (23-oct): con correo inexistente guarda `registro_id = 0`. Listo para retest |
| G2-04 | Media | Con campos vacíos devuelve 401; el QA esperaba 422. El PM confirmó (22-oct): **422** con detalle por campo; el 401 queda solo para credenciales incorrectas. Hoy da 422 si el campo falta, pero 401 si viene como `""`. | `routers/auth.py` | ✅ Hecho (23-oct): `""` da 422 y la contraseña debe tener de 8 a 64. Listo para retest |
| G2-33 | Media | Documentar 401 en el login (`responses=`). | `routers/auth.py` | 🔵 Login documenta 401 y 422; logout y `/me` documentan 401 |

### Randy · Persona 2 · Usuarios y roles
| Escenario | Prioridad | Qué falta | Archivo | Estado |
|-|-|-|-|-|
| G2-10, 06, 08, 09, 17, 37, 38 | Alta | Leer `Authorization: Bearer` con `verificar_token()` de Daniel y dejar de usar `usuario-actual`. Sin token = 401; sin permiso = 403. | `middleware/auth_middleware.py`, `routers/users.py`, `routers/roles.py` | 🔵 Hecho (22-oct): usa `obtener_usuario_actual()` desde la base; sin token 401, `usuario-actual` ya no sirve y sin rol 403. Falta retest de QA |
| G2-11, 12, 26 | Media | `GET /users/{id}` no existía (daba 405); debe dar 404 si no existe. | `routers/users.py` | 🔵 Lee de la base y da 404; falta retest |
| G2-31 | Baja | La lista de usuarios no paginaba; `GET /users` devolvía todos. | `routers/users.py` | 🔵 Ya pagina (24-oct) con `paginacion.py` y `tests/test_users.py`. ✅ PASS 22/22 (05-nov) |
| G2-33 | Media | Documentar 401, 403 y 409 en `POST /users`; el ejemplo del 201 era un string. | `routers/users.py` | 🔵 Cubierto desde la documentación común (Robert, 27 y 28-oct; desde el 06-nov en `openapi_docs.py`). G2-33 sigue en FAIL hasta que la raíz la cargue |
| G2-32 | Baja | Las respuestas de usuarios no traen `creado_en` ni `actualizado_en`; el PM pidió incluirlos (01-nov), solo de lectura, en ISO 8601 con zona horaria. | `routers/users.py` | 🔵 Subido el 02-nov (`9205344`): salen en UTC con `Z`, de solo lectura. ✅ PASS 8/8 (05-nov) |
| Auditoría | Baja | `fijar_actor(db, actual.id)` en las líneas 109 y 130 va sin IP; pasar `request.client.host` (aviso del Grupo 1). | `routers/users.py` | ✅ Hecho (02-nov, `9205344`): `fijar_actor(db, actual.id, _ip(request))` pasa la IP |
| Roles | Media | El código del rol es `admin` en la lista pero `requerir_rol(["administrador"])` en el POST. El PM confirmó `admin` (22-oct): cambiarlo en `users.py` y `roles.py`. | `routers/users.py`, `routers/roles.py` | ✅ Hecho: ambos usan `admin` |

### Edgar · Persona 3 · Errores, paginación y registro
| Escenario | Prioridad | Qué falta | Archivo | Estado |
|-|-|-|-|-|
| Pruebas | Alta | `error_handler.py` ya quedó arreglado: los 401, 403 y 404 responden bien (PM, 22-oct) y pasan 28 pruebas. Con los cambios del 23-oct pasan 33 y falla 1: el login fallido con correo inexistente no se guarda porque `registro_id` queda NULL. Corre `pytest` otra vez después de corregir. | `utils/registro.py`, `tests/test_errores.py` | ✅ `pytest` 40 de 40 (23-oct). Queda quitar las funciones que ya no se usan |
| G2-36 | Baja | `registro.py` ya usa `tabla`, `registro_id` e `ip_origen` (20-oct). Login, login fallido y logout ya lo llaman. En los registros de `pytest` aparece «No se pudo registrar la accion»: la causa es que `tabla` y `registro_id` no pueden ir vacíos en la base (NOT NULL) y que `detalle` debe ser JSON válido (ya lo cubre `models.py`). El PM pidió escribir a mano solo login, login fallido y logout. | `utils/registro.py` | ✅ Corregido (02 y 03-nov): con correo inexistente o vacío guarda `registro_id = 0` y la base lo acepta |
| G2-30 | Media | Dio PASS con el formato anterior. El manejador ahora responde `{"error": {...}}` como el contrato común: repetir 401, 403, 404, 409 y 422. El PM confirmó (01-nov) que `details` es un objeto con un campo por llave (no una lista); ya lo ajustó Edgar. | `middleware/error_handler.py` | 🔵 Hecho el 03-nov: `details` sale como objeto (`{"correo": "..."}`) y `{}` sin detalle; `tests/test_errores.py` al día. Falta retest QA |

### Fulvio · Persona 4 · Archivos y frontend
| Escenario | Prioridad | Qué falta | Archivo | Estado |
|-|-|-|-|-|
| G2-18 a G2-22 | Alta | `POST /files` valida el tipo real con `puremagic` y guarda en la tabla `archivo` con SHA-256 y `autor_id`. `GET /files/{id}` con token, 404 si no existe y 403 si no es el dueño ni un admin (28 y 31-oct). Las pruebas de G2-19, G2-20 y G2-21 ya están en `tests/test_file.py` (Fulvio, 08-nov). | `routers/files.py` | 🔵 Subido (el admin también descarga desde el 31-oct, `7ffa69c`). ✅ PASS 4/4 en el retest del 05-nov 14-nov: la descarga ahora sigue la regla del PM (dueño, admin o rol no docente con `files.download`); revisor 200 y docente ajeno 403 en el retest de QA. |
| G2-18 | Media | `POST /files` ya exige token, pero con un token válido responde 500 (`usuario_actual["correo"]` y el usuario ya no es un diccionario). | `routers/files.py` | 🔵 Corregido (23-oct): `usuario_actual.correo`. Listo para retest |
| Pruebas | Media | Pruebas de archivos: tipo no permitido, archivo muy grande, descarga sin token, 404 y 403. | `tests/test_file.py` | ✅ Subido el 08-nov: 8 pruebas; `pytest` completo pasa 115 |

### Robert · Persona 5 · Base del proyecto e integración
| Semana | Escenario QA | Qué toca | Archivo | Estado (02-nov) |
|-|-|-|-|-|
| 1 | G2-30 | `main.py` conecta `error_handler`; `GUIA_GRUPO2.md` en la carpeta del grupo | `main.py`, `GUIA_GRUPO2.md` | ✅ Hecho |
| 2 | G2-18 a G2-22, G2-33 | `main.py` con los routers `roles` y `files` | `main.py` | ✅ Hecho. `/me` ya queda conectado: Daniel subió `me_router` el 20-oct |
| 3 | G2-01 | Conexión del login a la base compartida: `DATABASE_URL` y driver PyMySQL | `.env.example`, `requirements.txt`, `database.py` | ✅ Probada el 28-oct con su `.env`: `probar_conexion()` devolvió `True` |
| 3 | G2-35 | `.env.example` solo con el formato, sin claves; `.gitignore` con `.env`, `grupo-2.txt` y `semilla_local.py` | `.env.example`, `.gitignore` | 🔵 `.env.example` sin clave. Antes de cada commit: `git status` y `git diff`. `semilla_local.py` ya no aparece en el repo (copia del 22-oct) y está en el `.gitignore`: si lo tienes local, no lo agregues |
| 3 | G2-34 | Las columnas `intentos_fallidos` y `bloqueado_hasta` coinciden con el script del Grupo 1 | `models.py` | ✅ Revisado contra `01_schema.sql`. Falta que el login las use (Daniel) |
| 3 | G2-36 | `auditoria.detalle` guarda JSON válido (`JSON_VALID` de G1) y `fijar_actor(db, actor_id, ip)` llena `@actor_id` e `@ip_origen` | `models.py`, `database.py` | 🔵 Hecho el 22-oct. Daniel y Randy tienen que llamar a `fijar_actor` |
| 3 | G2-32 | Fechas en UTC: cada conexión nueva a MySQL usa `time_zone = '+00:00'` | `database.py` | 🔵 Hecho el 22-oct |
| 4 | G2-33 | `README.md` con títulos y tablas; revisar `/api/v1/docs` cuando todos terminen | `README.md`, `main.py` | 🔵 README corregido el 22-oct. Ejemplos de `main.py` al día con el PM el 01-nov. Revisión final de OpenAPI (semana 5) hecha el 03-nov, con Randy y Edgar ya subidos: se quitó el xfail y `tests/test_openapi.py` pasa 9 de 9. 05-nov: FAIL documental porque Railway usa el `main.py` de la raíz. 06-nov: `openapi_docs.py` y pruebas con una app como la de la raíz (107 pasan). 09-nov: revisión final sin claves y `pytest` pasa 115; falta que el PM la active y el retest 15-nov: H-04 corregido en `openapi_docs.py` y la descripción de la descarga de archivos al día; falta el PR y el retest. |
| 4 | G2-35 | El README explica `.env`, la base compartida y la auditoría, sin ningún dato real | `README.md` | 🔵 Hecho el 22-oct |
| 4 | Pruebas | `pytest` corre para todos con SQLite temporal | `tests/conftest.py` | ✅ Sin cambios. Revisado el 23-oct: pasan 40 de 40 |
| QA | G2-35 | Que el repositorio no tenga contraseñas ni variables sensibles | `.gitignore` | PASS de QA. Para mantenerlo: `grupo-2.txt` y `.env` nunca se suben, y `.env.example` solo lleva el formato |

## Estado de los escenarios (histórico: Informe No. 1 del 17-oct, ya superado por el retest No. 2)

- **PASS:** G2-02, 03, 04, 13, 14, 15, 16, 23, 24, 25, 27, 28, 29, 30, 32, 35.
- **Bloqueados o fallan:** G2-05, 06, 07, 08, 09, 10, 12, 37, 38.
- **Parcial:** G2-11, 17, 26, 33, 36.
- **Implementados, esperan retest de QA:** G2-05 (logout), G2-07 (`/me`) y G2-30 (formato de errores nuevo).
- **No cumple / pendiente:** G2-34 (bloqueo), G2-31 (paginación), G2-18 a G2-22 (archivos).
- **En proceso:** G2-01 (falta probar el JWT en endpoints protegidos).


**Orden recomendado** (unos dependen de otros): Edgar (`registro.py`) → Randy (`auth_middleware.py`) → Daniel (`auth.py`) → Randy (`users.py`, `roles.py`) → Fulvio (`files.py`) → Robert (`main.py`, `config.py`, `.env.example`, `.gitignore`).

| Quién | Archivo | Qué cambia |
|-|-|-|
| Edgar | `utils/registro.py` | `registrar_accion()` usaba columnas que no existen (`entidad`, `entidad_id`, `ip`). Ya quedó con `tabla`, `registro_id` e `ip_origen` (20-oct). Falta que login y logout lo llamen; sin eso el conteo de intentos sigue en 0. |
| Edgar | `middleware/error_handler.py`, `tests/test_errores.py` | Ya responde bien (PM, 22-oct). `registro.py` ya quedó (`registro_id = 0`) y `details` es un objeto, como confirmó el PM (01-nov); todo hecho el 03-nov. |
| Randy | `middleware/auth_middleware.py` | Lee el token Bearer, valida firma, vencimiento y sesión no revocada; 401 si falla, 403 si no tiene rol. |
| Randy | `routers/users.py`, `routers/roles.py` | Pasan a la base; `GET /users/{id}` con 404; paginación; roles con los códigos del Grupo 1 (`admin`, `teacher`…); 401, 403, 404 y 409 documentados. |
| Daniel | `routers/auth.py` | `POST /auth/logout`, `GET /me`, bloqueo de 5 intentos por 15 minutos, auditoría y 422 con campos vacíos. |
| Fulvio | `routers/files.py` | Token obligatorio, archivo guardado con nombre aleatorio, `GET /files/{id}` solo para el autor o un administrador, sin salir de la carpeta. |
| Robert | `main.py`, `config.py`, `database.py`, `models.py`, `.env.example`, `.gitignore` | Hecho el 20-oct: `main.py` incluye `auth.me_router` (Daniel ya subió `auth.py`) y `config.py` trae `UPLOAD_DIR`. Hecho el 22-oct: `database.py` (UTC y `fijar_actor`), `models.py` (`auditoria.detalle` en JSON) y `.env.example`. |

**Importante:**
- El código del rol en la base es `admin` (no `administrador`). Ya está alineado en la solución.
- Al crear usuarios el cuerpo ahora lleva `correo`, `password`, `nombres`, `apellidos` y `rol` (la base exige nombres y apellidos).
- Después de subir todo, la lista JSON de prueba (`datos_prueba/usuarios_prueba.json`) ya no se usa y se puede borrar.

### Formato de errores frente al contrato común (Edgar)
Antes, `error_handler.py` respondía `{"status", "error", "meta"}` con `details` como lista, y el CONTRATO_COMUN pide `{"error": {"code", "message", "details": {}}}`. Con el cambio del 20-oct el manejador ya responde en el formato del contrato (`details` como diccionario), así que la decisión con el PM queda en cambiar el manejador, no el contrato. Como el PASS de G2-30 fue con el formato anterior, hay que repetirlo. Respuesta posterior del PM: se queda el formato actual de G2 (`error.code`, `error.message` y `error.details`, más `status` y `meta`), con `details` como lista de objetos por campo (`field`, `code`, `message`), y él actualiza el `CONTRATO_COMUN`. Respuesta final del PM (01-nov): `details` es un objeto (diccionario) con un campo por llave, como el `CONTRATO_COMUN`, y `{}` cuando no hay detalle (nunca null); la lista de objetos queda sin efecto. Edgar lo ajustó el 03-nov: hoy devuelve `{"correo": "..."}` (un campo por llave).

### Pruebas automáticas y auditoría
- `pytest` completo: el 22-oct (aviso del PM) pasaban 28 y fallaban 4 (antes 15). Revisado el 23-oct: pasan 33 y falla 1, la de `registro.py` con el correo inexistente.
- En la auditoría, `registro.py` ya usa las columnas reales. Login, login fallido y logout ya lo llaman; falta el caso del correo inexistente (G2-36). El PM pidió escribir a mano solo login, login fallido y logout; los cambios de datos los registran los triggers de G1 con `@actor_id` (ver `fijar_actor` en `database.py`).
- La base exige `tabla` y `registro_id` (NOT NULL) y `detalle` como JSON válido (ver `01_schema.sql`).

### Notas de integración (Robert)
- Versión de la base: el PM carga y actualiza la base de Railway (README §5), así que no hay que correr la migración. Se revisa con `SELECT * FROM schema_migracion;`: si aparece 1.2.0 está al día; si no, se avisa al PM.
- Integración con la base: el login y la sesión (`sesion_token`) ya usan la base compartida. `users.py` y `auth_middleware.py` ya leen de la base (22-oct). El JSON ya no autentica a nadie; el PM confirmó (01-nov) que se borra y Daniel lo quita de `auth.py`.
- `models.py` coincide con el diagrama del Grupo 1 (G2_Autenticacion.pdf): usuario, rol, permiso, usuario_rol, rol_permiso, sesion_token, archivo y auditoría.
- El Grupo 1 ya subió su script SQL a la rama `grupo-1` (`01_schema.sql` y `02_seed.sql`, en `grupos/grupo-1-base-de-datos/Docs/sql/`) y `models.py` se revisó contra él: coinciden las tablas y columnas de seguridad. Falta probar la conexión real con tu `.env`.
- `semilla_local.py` ya no aparece en el repo (copia del 22-oct) y está en el `.gitignore`. Si lo tienes en tu carpeta local, no lo agregues con `git add`.


## Planner: qué se puede marcar (estado al 09-nov)

*Esta tabla es del 09-nov y reemplaza a la del 23-oct. El detalle de cada aviso del PM está en la sección «Avisos del PM por prioridad».*

Allison revisa lo que se marque como completado en el Planner. Marca solo lo que ya esté subido a `grupo-2` y probado. Lo que está pendiente de retest se comenta como «listo para retest» y no se marca completado hasta que Allison lo repita.

| Prioridad | Punto | Escenarios | ¿Se puede marcar? |
|-|-|-|-|
| 🔴 Alta | 1. Autenticación y autorización JWT: integrar la validación JWT en los endpoints protegidos, eliminar la dependencia del encabezado `usuario-actual` y verificar respuestas HTTP 401 y 403 según corresponda | G2-06, 08, 09, 10, 37, 38 | Ya cerrado: PASS de QA (retest del 23-oct) |
| 🔴 Alta | 2. Cierre de sesión: implementar el endpoint de logout y asegurar que los tokens revocados no puedan seguir utilizándose | G2-05 | Ya cerrado: PASS de QA |
| 🔴 Alta | 3. Control de acceso a recursos: verificar las restricciones de acceso por usuario y rol para evitar consultas o modificaciones no autorizadas | G2-17, G2-21 | Ya cerrado: PASS de QA (G2-17 el 23-oct; G2-21 4/4 el 05-nov, Fulvio, commits `6982c15` y `7ffa69c`) |
| 🟡 Media | 1. Consulta del usuario autenticado: implementar el endpoint `/me` para recuperar la identidad y los roles del usuario autenticado | G2-07 | Ya cerrado: PASS confirmado por el PM |
| 🟡 Media | 2. Consulta individual de usuarios: revisar la disponibilidad del endpoint GET por ID y devolver HTTP 404 cuando el usuario no exista | G2-12 (y G2-11) | Ya cerrado: PASS confirmado por el PM |
| 🟡 Media | 3. Manejo de recursos inexistentes: revisar las rutas requeridas para garantizar respuestas HTTP apropiadas cuando un recurso no exista | G2-26 | Ya cerrado: PASS confirmado por el PM |
| 🟡 Media | 4. Documentación OpenAPI/Swagger: actualizar la documentación de los endpoints, sus esquemas y las respuestas HTTP 401, 409 y demás códigos aplicables | G2-33 | Sigue abierto: FAIL documental el 05-nov. Corregido el 06-nov (Robert, `openapi_docs.py`): ya está comentado «listo para retest» en el Planner. No marcarlo completado hasta que el PM lo active en el `main.py` de la raíz, despliegue y Allison repita G2-33 14-nov: QA dejó solo H-04; corregido el 15-nov y comentado «listo para retest». |
| ⚪ Baja | 1. Paginación de usuarios: revisar la implementación de paginación en el listado de usuarios | G2-31 | Ya cerrado: PASS de QA (22/22, retest del 05-nov) |
| ⚪ Baja | 2. Fechas `creado_en` y `actualizado_en`: confirmar si se incluyen en las respuestas de usuarios y su formato | G2-32 | Ya cerrado: PASS de QA (8/8, retest del 05-nov) |
| ⚪ Baja | 3. Bloqueo por intentos fallidos: integrar el bloqueo de 15 minutos después de cinco intentos fallidos de autenticación | G2-34 | Ya cerrado: PASS del PM y del QA |
| ⚪ Baja | 4. Registro de auditoría: integrar las funciones de auditoría con las operaciones correspondientes, incluyendo intentos fallidos de autenticación y acciones sensibles | G2-36 | Ya cerrado: PASS del PM y del QA. Antes del PR, confirmar que el login fallido se guarda una sola vez |


## Fechas

Semana 2 · martes 20-oct · Semana 3 · martes 27-oct · Semana 4 · martes 03-nov · Semana 5 · martes 10-nov (revisión de los 36 escenarios y PR `grupo-2 → main`, solo Daniel). **PR de correcciones: jueves 22-oct. Retest de QA: viernes 23-oct.**

*Nota: el resumen sale de los PDF del QA (Lista inicial, Updt_1 e Informe no. 1), del Planner de Allison y de los avisos del PM.*

