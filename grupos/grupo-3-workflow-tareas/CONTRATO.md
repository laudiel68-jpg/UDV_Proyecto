# CONTRATO.md — Grupo 3 · Workflow y creación de tareas

> **Nivel 3 de la jerarquía de fuentes de verdad** (README §0). Por encima:
> README y CONTRATO_COMUN.md. Por debajo: el .docx de esta carpeta. Si el
> .docx y este contrato se contradicen, gana este contrato; lo que el .docx
> exige y aquí no aparece sigue siendo obligatorio. Este contrato es lo que
> se revisa en cada PR. Cambios: se piden al PM por escrito y quedan en el
> historial.

## 1. El equipo

| Rol | Nombre | Usuario GitHub |
|---|---|---|
| Coordinador (abre los PRs) | | |
| Dev | | |
| Dev | | |
| Dev | | |

## 2. Alcance del módulo

Núcleo del workflow: catálogo de tipos de tarea, creación/edición/
cancelación de borradores, asignación (individual, lista, todos o filtro),
publicación transaccional, fechas límite y prioridades, **motor de
transiciones válidas**, historial inmutable y consulta administrativa por
estado.

Paquete Python: `g3_workflow` (README §2).

## 3. Contrato de endpoints y tabla de transiciones 🔒

Todas las rutas llevan el prefijo `/api/v1` (CONTRATO_COMUN.md §1).

| Método | Ruta | Uso |
|---|---|---|
| GET/POST | /task-types | Consultar o crear tipos |
| GET/POST | /tasks | Listar o crear tarea |
| GET/PATCH | /tasks/{id} | Detalle o edición de borrador |
| POST | /tasks/{id}/recipients | Configurar destinatarios |
| POST | /tasks/{id}/publish | Publicar y crear asignaciones |
| POST | /tasks/{id}/cancel | Cancelar según reglas |
| GET | /tasks/{id}/assignments | Monitorear destinatarios (individual y agregado) |
| POST | /assignments/{id}/close | Cerrar una asignación aprobada |
| GET | /assignments/{id}/history | Historial de transiciones |

Transiciones válidas (la máquina de estados es LEY — el Grupo 4 pinta lo que
esta tabla permite, nunca más):

| Estado actual | Acción | Estado nuevo | Actor | Endpoint dueño |
|---|---|---|---|---|
| draft | publish | assigned | Coordinador | G3 `/tasks/{id}/publish` |
| assigned | start | in_progress | Docente destinatario | G4 `/assignments/{id}/start` |
| in_progress | submit | submitted | Docente destinatario | G4 `/assignments/{id}/submit` |
| submitted | review | under_review | Revisor | G4 `/assignments/{id}/review` |
| under_review | return | returned | Revisor | G4 `/assignments/{id}/return` |
| returned | resubmit | submitted | Docente destinatario | G4 `/assignments/{id}/resubmit` |
| under_review | approve | approved | Revisor o autoridad | G4 `/assignments/{id}/approve` |
| approved | close | closed | Coordinador o sistema | G3 `/assignments/{id}/close` |
| draft/assigned | cancel | cancelled | Coordinador autorizado | G3 `/tasks/{id}/cancel` |

**Quién hace qué.** El G3 es dueño del **servicio de transiciones** (en
`g3_workflow`): valida estado, actor y permisos, ejecuta la transición en una
transacción, escribe el historial y emite el evento. Los endpoints del G4
solo reciben la petición y llaman a ese servicio; nunca cambian el estado por
su cuenta. El mismo servicio responde qué acciones están permitidas para un
usuario y una asignación (lo usa `GET /assignments/{id}` del G4).

**Tarea vs. asignación.** `draft` existe solo a nivel de tarea; al publicar,
cada destinatario recibe su asignación en `assigned`. En la semana 1 el G3
documenta en su matriz de estados (entregable 3 del .docx) qué pasa con las
asignaciones cuando se cancela una tarea publicada.

**Eventos que emite este módulo** (nombres en el CONTRATO.md del G6):
`task.published`, `task.cancelled`, `assignment.submitted`,
`assignment.returned`, `assignment.approved`.

## 4. Reglas duras del módulo

- Una tarea en borrador NUNCA aparece en el inbox.
- Publicar es transaccional: o se crean todas las asignaciones o ninguna.
- Publicar a todos crea exactamente una asignación por docente elegible.
- Publicar dos veces no duplica asignaciones: es idempotente o responde 409.
- Cada destinatario avanza de manera independiente.
- Una transición fuera de la tabla responde **409 sin modificar datos**.
- Toda devolución exige comentario: devolver sin observación responde **422**.
- Un usuario que no es destinatario no puede iniciar ni entregar (403).
- `submit` / `resubmit` en un tipo de tarea con `requiere_archivo = 1` sin ningún
  archivo vinculado al intento actual responden **422** y no modifican datos.
- Tabla `entrega` (decisión del PM, 13-nov-2026; aplica a G3 y G4). **Intento
  actual** = la última fila de `entrega` de la asignación que no tiene una
  transición `submitted` posterior en `tarea_transicion`. G4 crea esa fila (y
  enlaza `archivo.entrega_id`) al vincular el archivo. En `submit` / `resubmit`,
  G3 usa el intento actual y solo si no existe lo crea (`numero_intento = MAX + 1`,
  con el texto del borrador); nunca se crean dos intentos para un mismo envío.
- Fechas límite y prioridad se copian o resuelven consistentemente en la
  asignación.
- Cada transición corre dentro de una transacción de base de datos.
- El historial de transiciones es inmutable: se agrega, jamás se edita. La
  cancelación conserva la historia.

## 5. Definición de HECHO (checklist de cada PR)

- [ ] Corre desde cero con `pip install -r requirements.txt` (raíz) en una
      máquina que no es la de ustedes.
- [ ] Respeta el CONTRATO_COMUN.md (prefijo, formato de error, códigos).
- [ ] Pruebas de TODAS las transiciones válidas e inválidas, y pasan
      (inválida → 409 sin cambios; devolución sin comentario → 422).
- [ ] Cada transición aparece en el historial con actor y fecha.
- [ ] Sus endpoints aparecen en el OpenAPI y coinciden con este contrato.
- [ ] Ningún archivo fuera de la carpeta del grupo fue tocado.
- [ ] Sin credenciales ni datos personales reales en el código.
- [ ] El README del grupo dice cómo correr y probar el módulo, y cómo lo
      consume el G4.

## 6. Historial de cambios

| Fecha | Qué cambió | Quién lo pidió | Aprobado por |
|---|---|---|---|
| 2026-09-26 | Versión inicial | — | PM |
| 2026-09-28 | Jerarquía de fuentes; prefijo `/api/v1`; **nuevo** `POST /assignments/{id}/close` (la acción `close` no tenía endpoint); columna "Endpoint dueño" y reparto G3 servicio / G4 endpoints; nota tarea vs. asignación; eventos emitidos; reglas del .docx que faltaban (409, 422, independencia, idempotente o 409); checklist con pruebas y OpenAPI | PM | PM |
| 2026-11-14 | §4: `submit`/`resubmit` responden 422 si el tipo exige archivo y el intento actual no tiene ninguno; regla del intento actual de `entrega` compartida con G4 | PM (decisión del 13-nov) y hallazgo de QA | Pendiente |
