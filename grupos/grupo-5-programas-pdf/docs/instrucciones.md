# Instrucciones para QA — G5 Programas y PDF

## Propósito

Esta guía explica el módulo G5, resume los cambios de esta rama y propone
comprobaciones para revisar su comportamiento. G5 administra programas de
curso, versiones, revisión y autorización; es un router para la aplicación
compartida, no un servidor independiente.

Antes de aprobar la integración, comparar el resultado con
[`CONTRATO.md` de G5](https://github.com/jonnyverasdl-cloud/UDV_Proyecto/blob/main/grupos/grupo-5-programas-pdf/CONTRATO.md)
y el [`CONTRATO_COMUN.md`](https://github.com/jonnyverasdl-cloud/UDV_Proyecto/blob/main/CONTRATO_COMUN.md).

## Qué cambió en esta rama

- **Autenticación:** `g5_programas/auth.py` obtiene el usuario mediante
  `g2_api.routers.auth.obtener_usuario_actual` y convierte su ID, nombre y
  roles al `Actor` interno que usan las rutas.
- **G2 no disponible:** si el paquete `g2_api` no se puede importar, el módulo
  define un proveedor alternativo que responde 503. Verificar que este sea el
  comportamiento esperado al ejecutar G5 fuera de la aplicación compartida.
- **Dependencias:** `requirements.txt` fija las versiones oficiales de
  FastAPI, Pydantic, Uvicorn, SQLAlchemy, PyMySQL, cryptography, ReportLab y
  pytest. No usar rangos de versiones.
- **Documentación:** arquitectura, flujo y criterios de revisión se mantienen
  en el README y esta guía.

El selector se llena con los roles de la cuenta autenticada en G2. Solo cambia
la vista de trabajo; el backend vuelve a validar los permisos en cada ruta.
G5 usa únicamente los códigos oficiales de G1: `admin`, `coordinator`,
`teacher`, `reviewer`, `authority` y `auditor`. El docente responsable elabora,
edita y envía su propia versión; coordinación también puede elaborar y enviar.
Coordinación y revisión pueden revisar, devolver y aprobar; `authority`
autoriza. `admin`, coordinación y revisión pueden abrir versiones nuevas. El
backend valida los roles oficiales y restringe al docente a sus versiones.

## Flujo que debe validar QA

Las transiciones normales son:

```text
draft -> submitted -> under_review -> approved -> authorized
             ^             |
             |             v
             +---------- returned
```

| Acción | Estado inicial | Resultado | Rol esperado |
|---|---|---|---|
| Enviar (`submit`) | `draft` o `returned` | `submitted` | Docente responsable |
| Tomar revisión (`review`) | `submitted` | `under_review` | Coordinación o revisión |
| Devolver (`return`) | `under_review` | `returned` | Coordinación o revisión |
| Aprobar (`approve`) | `under_review` | `approved` | Coordinación o revisión |
| Autorizar (`authorize`) | `approved` | `authorized` | `authority` |

Comprobar también que solo `draft` y `returned` se puedan editar, que una
devolución requiera observación y que no existan dos versiones autorizadas
para el mismo programa y período. La versión autorizada debe permanecer
inmutable; una nueva versión se crea como borrador clonado.

## Lista de comprobación

### Instalación y arranque

- [ ] Instalar las dependencias declaradas en `requirements.txt` y confirmar
      que la instalación termine correctamente.
- [ ] Confirmar que la aplicación host incluya el router G5 y llame a
      `registrar_errores(app)`; revisar las rutas en `/api/v1/openapi.json`.
- [ ] Verificar que `DATABASE_URL` apunte a una base de prueba compatible con
      el esquema de G1; G5 no debe crear ni alterar tablas.
- [ ] Confirmar que no haya credenciales reales en archivos versionados:
      `.env.example` contiene solo marcadores y `.env` permanece ignorado.
      La clave `SECRET_KEY` la administra G2; no se agrega a G5 ni al frontend.
- [ ] Iniciar sesión en `/app/`, abrir G5 desde el portal y confirmar que
      reutiliza `sessionStorage["udv_token"]` y envía `Authorization: Bearer`.
- [ ] Abrir G5 sin `program_id`; confirmar que permite seleccionar un programa
      desde el listado de la API. Verificar también el caso con
      `?program_id=<id>`.
- [ ] Confirmar que se carga `/udv-styles/udv.css` y que no se muestra un
      segundo formulario de login dentro de G5.
- [ ] Probar una petición autenticada con el token de G2. Confirmar que
      el usuario y sus roles llegan desde `obtener_usuario_actual`, no desde
      el selector del navegador.
- [ ] Comprobar la matriz de roles: el docente asignado elabora, edita y envía
      su propia versión; coordinación y revisión aprueban; `authority` autoriza.
- [ ] Verificar que `admin`, `coordinator` y `reviewer` puedan gestionar
      borradores y abrir versiones; el docente asignado puede crear, editar y
      enviar su versión, pero otro docente y `auditor` reciben 403.
- [ ] En Swagger, confirmar que los cuerpos de creación, nueva versión,
      encabezado y transiciones muestren sus campos en lugar de un objeto
      genérico.
- [ ] En `PUT /program-versions/{id}/sections/evaluacion`, probar una lista
      como `[{"nombre":"Parcial 1","ponderacion":30,"semana":5}]`; una
      actividad sin `nombre` o `ponderacion` debe recibir 422 sin borrar las
      filas de evaluación existentes.
- [ ] Crear un programa del mismo curso/sede/modalidad en otro período y
      confirmar que recibe el siguiente número de versión sin conflicto de
      unicidad de G1.
- [ ] Asignar `docente_responsable_id` en la creación o sección
      `responsables`; confirmar que el usuario esté activo en
      `docente_curso` para ese curso, período y sede. Si coordinación crea el
      programa sin indicar docente, confirmar que no queda asignada como
      docente responsable.

### Permisos, validación y errores

- [ ] Sin autenticación: 401. Usuario autenticado sin el rol requerido: 403.
- [ ] ID inexistente: 404. Transición fuera de orden o conflicto de versión:
      409.
- [ ] Entrada inválida y devolución sin observación: 422 con detalles por
      campo y el formato común `{"error":{"code","message","details"}}`.
- [ ] Probar cada transición permitida y denegada con roles correctos e
      incorrectos.
- [ ] Confirmar que la UI no sea la única barrera de autorización: probar las
      rutas directamente contra la API.

### Persistencia, auditoría y PDF

- [ ] Probar los filtros del listado por curso, período, sede, estado y versión.
- [ ] Crear una versión desde una asignación G3 y confirmar que
      `tarea_destinatario_origen_id` se conserva en la versión creada.
- [ ] Guardar una sección y comprobar que las demás secciones se conserven.
- [ ] Confirmar que las filas dinámicas mantienen su orden tras guardar y
      volver a cargar.
- [ ] Enviar incompleto o con ponderaciones distintas de 100: la API debe
      rechazarlo sin cambiar el estado.
- [ ] Confirmar que las transiciones guarden actor, estado anterior, estado
      nuevo, fecha y comentario cuando corresponda.
- [ ] Generar PDF solo para una versión `authorized` o `superseded`; comprobar
      respuesta `application/pdf`, contenido y registro de huella.
- [ ] Verificar que autorizar una versión nueva deje la anterior como
      `superseded` y mantenga el historial consultable.

### Pruebas automatizadas

Desde la raíz del proyecto:

```bash
python -m pytest -q
```

La suite incluye pruebas HTTP de las rutas protegidas con encabezados Bearer y
roles oficiales en el formato de usuario que entrega G2. El proveedor de
identidad se sustituye por fixtures: estas pruebas verifican la autorización
de G5, pero no validan un token JWT real ni sustituyen el login de G2. Tampoco
prueban una conexión MySQL real ni la descarga del PDF; se requiere además
validar la integración con la aplicación host y una base MySQL local de prueba.