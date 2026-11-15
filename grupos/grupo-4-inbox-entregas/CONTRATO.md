# CONTRATO.md — Grupo 4 · Inbox y entregas docentes

> **Nivel 3 de la jerarquía de fuentes de verdad** (README §0). Por encima:
> README y CONTRATO_COMUN.md. Por debajo: el .docx de esta carpeta. Si el
> .docx y este contrato se contradicen, gana este contrato; lo que el .docx
> exige y aquí no aparece sigue siendo obligatorio. Este contrato es lo que
> se revisa en cada PR. Cambios: se piden al PM por escrito y quedan en el
> historial.

## 1. El equipo

| Rol | Nombre | Usuario GitHub |
|---|---|---|
| Coordinador (abre los PRs) | Juan Eduardo Chopen Morales | eduardo150618-sudo |
| Dev | Jorge Isai Velasquez Cux  | jVELAS4 |
| Dev | Elmer Josue Ajtun Tepet | Josue17AJ |
| Dev |  | |

## 2. Alcance del módulo

La experiencia del docente y del revisor: inbox con contadores,
búsqueda, filtros, orden y paginación; detalle de asignación con
instrucciones, plazo, prioridad, archivos, comentarios e historial; iniciar,
entregar (formulario según tipo de tarea), borradores de formulario, adjuntos
múltiples, comentarios, devolución y reenvío; pantalla del revisor;
adaptación a escritorio y teléfono.

Paquete Python: `g4_inbox` (README §2).

## 3. Contrato de endpoints 🔒

Todas las rutas llevan el prefijo `/api/v1` (CONTRATO_COMUN.md §1).

| Método | Ruta | Uso |
|---|---|---|
| GET | /inbox | Asignaciones del usuario autenticado (paginado) |
| GET | /inbox/summary | Contadores por estado y vencimiento |
| GET | /assignments/{id} | Detalle y acciones permitidas |
| PUT | /assignments/{id}/submission-draft | Guarda el borrador del formulario sin entregar |
| POST | /assignments/{id}/start | Inicia la actividad |
| POST | /assignments/{id}/submit | Entrega evidencia o formulario |
| POST | /assignments/{id}/resubmit | Reenvía una corrección |
| POST | /assignments/{id}/review | Toma la revisión |
| POST | /assignments/{id}/return | Devuelve con observación |
| POST | /assignments/{id}/approve | Aprueba la entrega |
| GET/POST | /assignments/{id}/comments | Comentarios |
| POST | /assignments/{id}/files | Vincula archivos cargados (vía G2) |

**Relación con el G3.** Los endpoints `start`, `submit`, `resubmit`,
`review`, `return` y `approve` los implementa este grupo, pero **el cambio de
estado lo hace el servicio de transiciones del G3** (`g3_workflow`): este
grupo lo llama, nunca actualiza el estado por su cuenta. Las "acciones
permitidas" de `GET /assignments/{id}` también salen de ese servicio. Ver la
tabla de transiciones en el CONTRATO.md del G3.

**Relación con el G5.** Cuando la entrega corresponde a un programa de curso,
`submit` / `resubmit` envían `program_version_id`.

## 4. Reglas duras del módulo

- El inbox SOLO muestra asignaciones visibles para el usuario autenticado:
  dos docentes no pueden ver la asignación privada del otro.
- Cada tarjeta muestra tipo, título, estado, prioridad y vencimiento.
- Las acciones visibles salen de las transiciones válidas del G3 — la UI
  jamás ofrece un botón que la máquina de estados rechazaría, y la API vuelve
  a validarlas.
- Vencidas/próximas a vencer se distinguen sin depender solo del color.
- No se entrega si falta un archivo, campo o programa requerido (422).
- Los borradores de formulario se guardan sin entregar.
- La devolución muestra claramente observación y fecha.
- El reenvío conserva las entregas anteriores para auditoría; nunca borra
  evidencia.
- Un error de carga no pierde los datos ya escritos.
- El revisor solo actúa sobre asignaciones asignadas o permitidas.
- Los archivos se cargan por el servicio del G2, nunca por rutas propias.

## 4.1 Comentarios, borrador, archivos y entrega

Acuerdo con el PM del 13 de noviembre (aplica a G3 y G4).

- `POST /assignments/{id}/comments` guarda en la tabla `comentario`.
- `PUT /assignments/{id}/submission-draft` guarda en `entrega_borrador` (una
  fila por asignación; se reemplaza). Si la asignación ya no está pendiente
  (`assigned`, `in_progress` o `returned`), responde 409.
- `POST /assignments/{id}/files` recibe el `file_id` que devolvió
  `POST /api/v1/files` de G2 y hace esto en una sola transacción:
  1. El archivo debe existir en `archivo`, con `eliminado_en IS NULL` y
     subido por el mismo usuario. Si no, 404.
  2. La asignación debe estar pendiente. Si no, 409.
  3. Busca el intento actual. Si no hay, crea la fila de `entrega` con
     `numero_intento = MAX + 1`. Si ya hay, la usa.
  4. `UPDATE archivo SET entrega_id = <entrega del intento actual>`.
- Intento actual: la última fila de `entrega` de esa asignación que no tenga
  una transición `submitted` posterior en `tarea_transicion`. Nunca se crean
  dos intentos para un mismo envío.
- Cómo lo aplica G4: cuenta envíos en vez de comparar fechas. Cada
  `submitted` (submit o resubmit) cierra un intento, así que el intento N
  sigue abierto mientras haya menos de N envíos. Da lo mismo que la regla
  del PM sin depender de la zona horaria.
- G3 sí compara fechas (`tarea_transicion.creado_en >= entrega.entregado_en`).
  Para que eso funcione, G4 no fija `time_zone` y escribe en la zona del
  servidor, igual que G3. Con el docker-compose (`TZ: America/Guatemala`), si
  uno escribe en UTC y el otro no, hay 6 horas de diferencia.
- La entrega que crea G4 lleva `contenido_texto` y `programa_version_id` del
  borrador, igual que cuando la crea G3, porque G1 no deja modificarla
  después. La pantalla guarda el borrador antes de subir el archivo.
- El revisor solo ve y comenta las asignaciones de las tareas donde es el
  revisor designado (`tarea.revisor_id`). Coordinación y admin ven todas.

## 5. Definición de HECHO (checklist de cada PR)

- [ ] Corre desde cero con `pip install -r requirements.txt` (raíz) en una
      máquina que no es la de ustedes.
- [ ] Respeta el CONTRATO_COMUN.md (prefijo, formato de error, códigos,
      paginación).
- [ ] Pruebas de permisos y validaciones, y pasan (acceso de otro docente,
      entrega vacía, revisor no asignado).
- [ ] Filtros y paginación devuelven resultados correctos.
- [ ] Sus endpoints aparecen en el OpenAPI y coinciden con este contrato.
- [ ] Probado en pantalla de escritorio Y de teléfono.
- [ ] Ningún archivo fuera de la carpeta del grupo fue tocado.
- [ ] Sin credenciales ni datos personales reales en el código.
- [ ] El README del grupo dice cómo correr y probar el módulo.

## 6. Historial de cambios

| Fecha | Qué cambió | Quién lo pidió | Aprobado por |
|---|---|---|---|
| 2026-09-26 | Versión inicial | — | PM |
| 2026-09-28 | Jerarquía de fuentes; prefijo `/api/v1`; **nuevo** `PUT /assignments/{id}/submission-draft` (el .docx exige borradores y no había ruta); reparto de responsabilidades con el G3; `program_version_id` con el G5; reglas del .docx que faltaban; checklist con pruebas y OpenAPI | PM | PM |
| 2026-11-14 | Sección 4.1: comentarios y borrador en la base, validación de archivos, fila de entrega por intento, revisor designado | PM y QA | Pendiente |
