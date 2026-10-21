# 📋 API REST y Workflow Docente — Proyecto Integrador

> Curso de Programación Web · Ingeniería en Sistemas · Universidad Da Vinci
> PM del proyecto: Jonathan Veras

> Este documento manda sobre todo lo demás del repositorio. Si algo aquí
> contradice lo dicho en el chat, gana este documento. Los cambios a estas
> reglas los hace el PM, con fecha y motivo, en el historial al final.

## 0. Fuentes de verdad (quién gana si dos documentos se contradicen)

| Nivel | Documento | Qué define | Quién lo cambia |
|---|---|---|---|
| 1 | `README.md` (este) | Proceso, reglas del repo, decisiones técnicas | PM |
| 2 | `CONTRATO_COMUN.md` | Convenciones de API que comparten los 6 grupos | PM |
| 3 | `grupos/*/CONTRATO.md` | Endpoints, reglas y checklist de PR de cada módulo | PM, a pedido del grupo |
| 4 | `grupos/*/*.docx` | Requerimiento detallado (versión 1, 2026-09-23) | Congelado |

- Gana el documento con el número de nivel más bajo. Si el .docx y el CONTRATO.md de un grupo
  se contradicen, gana el CONTRATO.md.
- Lo que el .docx exige y el CONTRATO.md no menciona **sigue siendo
  obligatorio**: el contrato resume, no recorta.
- El .docx no se edita. Todo cambio posterior queda en el historial del
  CONTRATO.md correspondiente.
- El OpenAPI **no** es fuente de verdad: se deriva de los contratos y debe
  coincidir con ellos.
- Los .docx oficiales son los que están dentro de `grupos/`. Cualquier otra
  copia (correo, chat, carpeta personal) puede estar desactualizada.

## 1. Qué construimos

Un sistema de workflow docente: coordinadores crean y asignan tareas, los
docentes las reciben en su inbox, entregan evidencias, los revisores aprueban
o devuelven, y los programas de curso se gestionan con versiones y PDF
institucional. **Una sola aplicación, un solo backend en Python** — cada grupo
construye un módulo y todos se integran por contratos de endpoints.

## 2. Los 6 grupos y sus módulos

| Grupo | Módulo | Carpeta | Paquete Python |
|---|---|---|---|
| 1 | Base de datos (modelo, migraciones, semillas, vistas) | `grupos/grupo-1-base-de-datos/` | `g1_bd` |
| 2 | API base y seguridad (auth, roles, archivos, OpenAPI) | `grupos/grupo-2-api-seguridad/` | `g2_api` |
| 3 | Workflow y tareas (tipos, publicación, transiciones) | `grupos/grupo-3-workflow-tareas/` | `g3_workflow` |
| 4 | Inbox y entregas (experiencia del docente y revisor) | `grupos/grupo-4-inbox-entregas/` | `g4_inbox` |
| 5 | Programas de curso, versiones y PDF | `grupos/grupo-5-programas-pdf/` | `g5_programas` |
| 6 | Administración, notificaciones, pruebas y despliegue | `grupos/grupo-6-administracion/` | `g6_admin` |

Cada carpeta de grupo contiene su **CONTRATO.md** (resumen operativo,
contrato de endpoints y checklist de PR) y su **documento de requerimientos
completo** (.docx). El contrato es lo que se evalúa en cada PR, junto con el
`CONTRATO_COMUN.md`.

## 3. Mapa de dependencias (quién necesita a quién)

```
G1 Base de datos  ──→  G2 API y seguridad  ──→  G3 Workflow ──→ G4 Inbox
        │                      │                                  │
        └──────────────────────┴──→  G5 Programas y PDF  ←────────┘
G6 Administración/Calidad consume los servicios de TODOS
```

(G4 ↔ G5: una entrega puede referenciar `program_version_id`.)

Regla práctica: si tu módulo necesita algo de otro grupo que aún no existe,
**no lo inventes** — trabaja contra el contrato de ese grupo (su tabla de
endpoints) usando datos de ejemplo, y avísale al PM para coordinar fechas.

## 4. Cómo está organizado el repo

- **`main`** — rama protegida. Nadie hace push directo (el servidor lo
  rechaza). Todo entra por Pull Request.
- **Una rama por grupo** (`grupo-1` … `grupo-6`) — ahí trabaja cada equipo.
  Si un grupo quiere ramas por funcionalidad, las crea como sub-ramas
  (`grupo-3/publicacion`) y las integra a `grupo-3`, nunca a `main`.
- **Una rama de QA por grupo** (`qa/grupo-1` … `qa/grupo-6`) — ahí trabaja el
  equipo de QA, que es aparte de los seis grupos. Cada una sale de la rama del
  grupo que prueba y guarda sus escenarios, evidencias y pruebas dentro de la
  carpeta de ese grupo, en una subcarpeta `qa/`
  (`grupos/grupo-6-administracion/qa/`), nunca en la raíz. Solo QA escribe en
  las ramas `qa/*`; los hallazgos se reportan al coordinador del grupo y al PM.
- **Ramas del PM** (`pm/...`) — cambios a la raíz, auditorías e integración.
  Las del PM también entran a `main` solo por Pull Request.
- **Una carpeta por grupo** — cada grupo toca SOLO su carpeta. Tocar la
  carpeta de otro grupo invalida el PR completo.
- **La raíz es del PM.** `README.md`, `CONTRATO_COMUN.md`, `requirements.txt`,
  `requirements-base.txt`, `.gitignore`, `.env.example`, `main.py` (punto de
  entrada), `Dockerfile`, `docker-compose.yml`, `.dockerignore` y
  `railway.json` los mantiene el PM. Si tu grupo necesita un cambio en la
  raíz, lo pide al PM. Ningún grupo crea carpetas ni archivos en la raíz.

### Estructura del código dentro de cada carpeta

Los nombres de carpeta llevan guiones y **no se pueden importar en Python**.
Por eso el código de cada grupo vive en un paquete con nombre válido:

```
grupos/grupo-2-api-seguridad/
├── CONTRATO.md
├── 02_Requerimientos_API_y_Seguridad.docx
├── README.md            ← cómo correr y probar el módulo
├── requirements.txt     ← dependencias propias del grupo
├── g2_api/              ← el código (paquete Python)
└── tests/
```

El punto de entrada de la raíz (`main.py`) registra las carpetas de grupo
para que cualquier módulo pueda hacer `from g2_api import ...`. Nadie importa
por ruta de archivo ni copia código de otro grupo.

**Una sola app.** Ningún grupo crea su propia `FastAPI()` para producción:
cada módulo expone uno o más `APIRouter` con la ruta completa
(`APIRouter(prefix="/api/v1/tasks")`) y el PM los registra en la lista
`ROUTERS` de `main.py`. Un router que aún no está en la rama se omite sin
tumbar la app y aparece como pendiente en `GET /health`. Los archivos
estáticos y estilos compartidos los sirve `main.py`, no los grupos.

### Dependencias

- Cada grupo declara sus librerías en **su** `requirements.txt`.
- El `requirements.txt` de la raíz solo incluye los seis archivos de grupo
  y `requirements-base.txt` (PM), que trae lo mínimo para que `main.py`
  arranque. Toda la aplicación se instala con `pip install -r requirements.txt`
  desde la raíz.
- Si dos grupos piden versiones distintas de la misma librería, decide el PM.
  Las versiones ya decididas están en §5 ("Versiones oficiales").
- Un `requirements.txt` dentro de un subpaquete (por ejemplo
  `g4_inbox/requirements.txt`) solo puede apuntar al del grupo
  (`-r ../requirements.txt`), nunca declarar versiones propias.

## 5. Decisiones técnicas

| Tema | Estado | Quién decide | Plazo |
|---|---|---|---|
| Lenguaje del backend | ✅ **Python** | PM | Definido |
| Framework web (FastAPI / Flask / Django) | ✅ **FastAPI** | PM, con propuesta del G2 | Definido 2026-10-10 |
| ORM y herramienta de migraciones | ⏳ Pendiente (por ahora: scripts SQL del G1; SQLAlchemy sin `create_all`) | G1 + G2 proponen, PM aprueba | Semana 1 |
| Motor de base de datos | ✅ **MySQL 8** (Railway en línea; Docker en local). Reemplaza a SQLite | G1 + G2 proponen, PM aprueba | Definido 2026-10-13 |
| Driver de conexión | ✅ **PyMySQL** + `cryptography` (MySQL 8 la exige para el login) | PM | Definido 2026-10-13 |
| Despliegue | ✅ **Docker** (`Dockerfile` de la raíz) en **Railway** | PM | Definido 2026-10-13 |
| Valores de prioridad de tarea | ⏳ Pendiente: `low/medium/high` o agregar `urgent` | PM | 2026-10-14 |
| Dueño de las acciones sobre asignaciones (start, submit, review, return, approve) | ⏳ Pendiente: G3 o G4 (no los dos) | PM, con G3 + G4 | Semana 1 |
| Identificadores (enteros o UUID) | ✅ **Enteros** (autoincrementales) | G1 + G2 | Definido 2026-10-10 |
| Versiones de librerías compartidas | ✅ Ver tabla abajo | PM | Definido 2026-10-10 |
| Zona horaria institucional | ⏳ Pendiente | PM | Semana 1 |
| Tecnología del frontend (pantallas de G3, G4, G5 y G6) | ⏳ Pendiente | PM | Semana 1 |
| Transporte de eventos para notificaciones | ⏳ Pendiente | G3 + G6 proponen (con G1 si requiere tabla), PM aprueba | Semana 1 |

Cuando una decisión se toma, se marca ✅ aquí y se anota en el historial.
Hasta entonces, nadie escribe código que dependa de ella.

### Versiones oficiales de librerías compartidas

Todo grupo que use una de estas librerías la declara en su
`requirements.txt` con **exactamente** esta versión. Otra versión rompe la
instalación desde la raíz y el PR se rechaza. Para cambiar una versión, se
pide al PM.

| Librería | Versión |
|---|---|
| `fastapi` | `0.142.1` |
| `uvicorn[standard]` | `0.54.0` |
| `pydantic` | `2.14.0` |
| `httpx` (TestClient) | `0.28.1` |
| `pytest` | `9.1.1` |
| `SQLAlchemy` | `2.1.1` |
| `PyMySQL` | `1.1.1` |
| `cryptography` | `44.0.2` |

Nada de rangos (`>=`, `<`, `~=`) en ningún `requirements.txt`: solo `==`.

### Base de datos, entorno local y despliegue

- **Una sola base:** `db_udv` en MySQL 8, con el esquema del G1. Ningún
  grupo crea, borra ni altera tablas desde su código (nada de
  `Base.metadata.create_all`); un cambio de esquema se le pide al G1.
- **Conexión:** siempre por la variable `DATABASE_URL`
  (`mysql+pymysql://usuario:clave@host:3306/db_udv`), nunca escrita en el
  código.
- **Local:** `cp .env.example .env` (y cambiar las claves) y luego
  `docker compose up --build`. Levanta MySQL con los scripts del G1 y la API
  en `http://localhost:8000/api/v1/docs`. `docker compose down -v` borra la
  base local para recrearla. Cada grupo prueba contra su base local.
- **En línea (Railway):** la base compartida es solo para integración y
  demostración, no para pruebas que borran datos. La carga y recarga el PM.
  Los grupos reciben por privado un usuario sin permisos de root.
- **Salud:** `GET /health` (app y routers) y `GET /health/db` (conexión).

## 6. El flujo de trabajo diario

1. `git pull origin grupo-X` — SIEMPRE antes de empezar.
2. Commits pequeños y frecuentes con mensajes claros:
   `git commit -m "inbox: filtro por estado y vencimiento"`.
3. `git push origin grupo-X` — tu trabajo queda respaldado y visible.
4. Para integrar, **solo el coordinador del grupo** abre el Pull Request.

**Sobre los puntos:** GitHub registra CADA commit con nombre y fecha — el
historial individual es visible para siempre. Que el coordinador maneje el PR
no significa que se lleve el crédito de nadie.

## 7. Reglas duras (no se negocian)

1. **Nunca push directo a `main`.**
2. **Solo el coordinador de cada grupo abre PRs.**
3. **Cada grupo toca solo su carpeta y su rama.**
4. **Backend en Python, un solo lenguaje.** Somos una aplicación, no seis
   apps pegadas con cinta. La libertad de cada grupo está en CÓMO implementa
   su módulo — mientras sus endpoints reciban y devuelvan exactamente lo que
   dice su CONTRATO.md y respeten el CONTRATO_COMUN.md.
5. **Nada de credenciales en el código.** Un commit con una contraseña
   adentro se rechaza y esa contraseña se considera quemada.
6. **Sin pruebas no hay PR.** Cada PR trae pruebas automáticas de lo que
   agrega, y pasan.

## 8. Seguridad (aviso amistoso ⚠️)

El servidor sanitiza y registra todas las entradas. Los intentos de inyección
SQL, XSS y similares no rompen nada y **quedan registrados con usuario y
hora**. Si te interesa la seguridad ofensiva, excelente — hablemos y te
enseño en un entorno hecho para eso.

## 9. Ayuda

¿Nunca has usado Git o GitHub? Sin pena — escríbeme y lo vemos juntos en 15
minutos. Glosario mínimo: **commit** = foto de tu avance con tu nombre ·
**push** = subir tus commits · **PR** = pedir que tu código entre a `main`
tras revisión · **merge** = la integración aprobada.

---

## Historial de cambios a este documento

| Fecha | Cambio | Motivo |
|---|---|---|
| 2026-09-26 | Versión inicial | Arranque del proyecto |
| 2026-09-28 | Jerarquía de fuentes de verdad (§0); `CONTRATO_COMUN.md`; raíz del PM, paquetes Python y `requirements.txt` por grupo (§4); tabla de decisiones técnicas (§5); sub-ramas por funcionalidad; regla dura 6 (pruebas) | README, CONTRATO.md, .docx y OpenAPI se declaraban fuente de verdad sin orden; la estructura por carpetas no permitía importar código entre grupos |
| 2026-10-10 | §5: FastAPI, SQLite e identificadores enteros pasan a ✅; tabla de versiones oficiales de librerías compartidas. §4: los `requirements.txt` de subpaquetes solo apuntan al del grupo | G2, G3 y G4 ya escribían código sobre estas decisiones; G4 pedía `fastapi==0.115.0` y G2 `0.142.1`, y las dependencias de G3 y G4 no se instalaban desde la raíz |
| 2026-10-13 | §5: motor MySQL 8 en lugar de SQLite; driver PyMySQL; despliegue con Docker en Railway; SQLAlchemy, PyMySQL y cryptography en versiones oficiales; prohibidos los rangos de versión; nueva sección de base de datos, entorno local y despliegue; prioridades y dueño de acciones de asignación quedan pendientes. §4: archivos nuevos de la raíz (`main.py`, Docker, `railway.json`, `requirements-base.txt`), regla de una sola app con `APIRouter` y ramas `qa/*` y `pm/*` documentadas | G1 montó el esquema en MySQL; el deploy en Railway fallaba porque `main` no tenía punto de entrada; G3, G4 y G5 levantaban cada uno su propia app y base; G3 y G4 usan prioridades distintas e implementan las mismas transiciones; QA se separó como equipo aparte y sus ramas no estaban documentadas |
