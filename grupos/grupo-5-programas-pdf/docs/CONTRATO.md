# CONTRATO.md — Grupo 5 · Programas de curso, versiones y PDF

> **Nivel 3 de la jerarquía de fuentes de verdad** (README). Por encima:
> README y CONTRATO_COMUN.md. Este contrato es lo que se revisa en cada PR.
> Cambios: se piden al PM por escrito y quedan en el historial.

## 1. El equipo

| Rol | Nombre | Usuario GitHub |
|---|---|---|
| Coordinador (abre los PRs) | Balta Eduardo Tello Recinos (202201740) |baltatello56|
| Dev | Aldron Edgardo Marin Ramos (202406376) |aldron01|
| Dev | Hector Eduardo Cahuil Mateo (202401449)|hectorcahuil|
| Dev | Domingo Darinel Lopez Ramirez (202505663) |darinel940-hash|
| Dev | Kimberly Alejandra Pérez Hernández (202404070) |kp4531410-lab|

## 2. Alcance del módulo

Programas de curso como información estructurada: formulario por
secciones con guardado parcial, filas dinámicas y ordenables (contenidos,
bibliografía, evaluación), borradores y clonación de versiones, comparación de
cambios, flujo de revisión/aprobación/autorización, regla de UNA versión
vigente, PDF institucional reproducible desde los datos autorizados, e
histórico con descarga de PDFs anteriores.

Paquete Python: `g5_programas` (README §2).

## 3. Contrato de endpoints y tabla de transiciones 🔒

Todas las rutas llevan el prefijo `/api/v1` (CONTRATO_COMUN.md §1).

| Método | Ruta | Uso |
|---|---|---|
| GET/POST | /course-programs | Listar (por curso, período, sede, estado, versión) o crear programa |
| GET | /course-programs/{id} | Detalle y versiones |
| POST | /course-programs/{id}/versions | Crear o clonar borrador |
| GET/PUT | /program-versions/{id} | Leer o guardar versión |
| PUT | /program-versions/{id}/sections/{section} | Guardar una sección |
| POST | /program-versions/{id}/submit | Enviar a revisión |
| POST | /program-versions/{id}/review | Tomar la revisión |
| POST | /program-versions/{id}/return | Devolver con observación |
| POST | /program-versions/{id}/approve | Aprobar contenido |
| POST | /program-versions/{id}/authorize | Autorizar y declarar vigente |
| GET | /program-versions/{id}/pdf | Generar o descargar PDF |
| GET | /program-versions/{id}/changes | Comparar con versión anterior |

Transiciones válidas de una versión de programa:

| Estado actual | Acción | Estado nuevo | Actor |
|---|---|---|---|
| draft | submit | submitted | Elaborador (docente responsable) |
| submitted | review | under_review | Revisor o Coordinación |
| under_review | return | returned | Revisor o Coordinación |
| returned | submit | submitted | Elaborador (docente responsable) |
| under_review | approve | approved | Revisor o Coordinación |
| approved | authorize | authorized | `authority` |
| authorized | (otra versión se autoriza) | superseded | Sistema |

Una transición fuera de esta tabla responde 409 sin modificar datos.

**Evento requerido por el contrato de integración** (nombre definido por G6):
`program.authorized`. La emisión efectiva del evento debe verificarse en la
integración con el mecanismo compartido de eventos.

## 4. Reglas duras del módulo

- El programa lógico y sus versiones son entidades distintas.
- Editar solo está permitido en `draft` o `returned`; enviar congela la
  edición hasta una devolución.
- La autorización usa exclusivamente códigos oficiales de rol de G1. El docente
  responsable elabora, edita y envía únicamente su propia versión; Coordinación
  también puede elaborar y enviar. Coordinación y `reviewer` pueden revisar,
  devolver y aprobar; `authority` autoriza. El backend valida estos códigos de
  rol directamente, sin depender de permisos derivados de G1.
- Solo UNA versión autorizada y vigente por curso/sede/período.
- Una versión autorizada es INMUTABLE: los cambios van en un borrador nuevo
  (clonación), jamás editando la vigente.
- Autorizar una versión nueva marca la anterior como `superseded`; no la
  elimina y sigue consultable.
- El número de versión lo asigna el servidor dentro de una transacción.
- El docente responsable debe tener una asignación activa en `docente_curso`
  para el mismo curso, período y sede. Crear un programa desde coordinación
  sin indicar docente no asigna automáticamente a coordinación como docente.
  Solo los gestores pueden cambiar al docente responsable de una versión.
- Abrir versiones nuevas corresponde a `admin`, `coordinator` y `reviewer`.
  El docente puede crear el primer programa y borrador, siempre asignándose
  como responsable y con una asignación activa en G1.
- Guardar una sección no sobrescribe las demás; las filas mantienen su orden.
- La suma de ponderaciones de evaluación se valida (100%) cuando ese sea el
  esquema.
- El PDF se genera desde los datos autorizados — nunca de un borrador —, y
  registra versión, fecha y aprobación de origen. Regenerarlo produce el
  mismo contenido funcional.
- Una devolución conserva sus observaciones.
- La versión se vincula a la asignación (G3) que originó su actualización, y
  una entrega del G4 puede referenciar `program_version_id`.

## 5. Definición de HECHO (checklist de cada PR)

- [ ] Corre desde cero con `pip install -r requirements.txt` (raíz) en una
      máquina que no es la de ustedes.
- [ ] Respeta el CONTRATO_COMUN.md (prefijo, formato de error, códigos).
- [ ] Pruebas de inmutabilidad, versión vigente única y transiciones
      inválidas, y pasan.
- [ ] El programa completo se reconstruye desde la base.
- [ ] El PDF de la versión de ejemplo se genera y descarga correcto.
- [ ] Sus endpoints aparecen en el OpenAPI y coinciden con este contrato.
- [ ] Ningún archivo fuera de la carpeta del grupo fue tocado.
- [ ] Sin credenciales ni datos personales reales en el código.
- [ ] El README del grupo dice cómo correr y probar el módulo.

## 6. Historial de cambios

| Fecha | Qué cambió | Quién lo pidió | Aprobado por |
|---|---|---|---|
| 2026-09-26 | Versión inicial | — | PM |
| 2026-09-28 | Jerarquía de fuentes; prefijo `/api/v1`; tabla de endpoints completada con las rutas del .docx; **nuevo** `POST /program-versions/{id}/review` (el estado `under_review` no tenía acción); tabla de transiciones de programa; evento requerido; reglas de versionado del .docx que faltaban; checklist con pruebas y OpenAPI | PM | PM |
| 2026-11-13 | Docente elabora y envía; coordinación y revisor aprueban; dirección autoriza | Decisión del PM con el ingeniero | PM |
