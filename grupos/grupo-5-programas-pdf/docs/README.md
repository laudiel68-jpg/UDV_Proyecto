# Programas de curso UDV

Módulo FastAPI para gestionar programas de curso y sus versiones, controlar el
flujo de revisión y autorización, y generar el PDF institucional. G5 se integra
con la aplicación compartida y la base de datos de G1; este repositorio no
incluye un servidor FastAPI independiente ni un `main.py`.

## Estructura

```text
grupo-5-programas-pdf/
├── .env.example
├── .gitignore
├── requirements.txt
├── g5_programas/
│   ├── __init__.py
│   ├── auth.py             # Autenticación G2 y permisos por rol
│   ├── database.py         # Sesiones SQLAlchemy y errores de MySQL
│   ├── domain.py           # Estados y reglas de transición
│   ├── errors.py           # Errores de API
│   ├── pdf.py              # Adaptador del generador de PDF
│   ├── pdf_service.py      # Construcción del documento con ReportLab
│   ├── repository.py       # Consultas y operaciones sobre el esquema G1
│   ├── schemas.py          # Esquemas Pydantic para Swagger y validación
│   └── router.py           # Rutas bajo /api/v1
├── frontend/
│   ├── Programa.html
│   ├── script.js
│   ├── assets/
│   │   └── udv-logo.jpg
│   └── estilos/
│       ├── style.css
│       └── udv.css
├── tests/
│   ├── conftest.py
│   ├── test_api_contract.py
│   ├── test_database.py
│   └── test_program_flow.py
└── docs/
    ├── README.md
    ├── instrucciones.md
    └── CONTRATO.md
```

## Requisitos e integración

- Python 3.10 o posterior.
- Las dependencias se fijan en `requirements.txt`: FastAPI 0.142.1,
  Pydantic 2.14.0, Uvicorn 0.54.0, SQLAlchemy 2.1.1, PyMySQL 1.1.1,
  cryptography 44.0.2, ReportLab 4.5.1 y pytest 9.1.1.
- Una base MySQL compatible con el esquema compartido de G1, incluyendo sus
  catálogos, tablas, vistas y procedimientos usados por el repositorio. La
  autorización utiliza `sp_autorizar_version`.
- Una aplicación host FastAPI que registre `g5_programas.router`, configure
  `app.state.database_session_factory` (o permita que G5 cree la sesión desde
  `DATABASE_URL`) y tenga disponible el paquete G2 con
  `g2_api.routers.auth.obtener_usuario_actual`.

Instale las dependencias del módulo desde la raíz del proyecto:

```bash
python -m pip install -r requirements.txt
```

`DATABASE_URL` debe ser una URL de SQLAlchemy para MySQL. El host y puerto
dependen de dónde se ejecute la aplicación:

```bash
# Aplicación ejecutada directamente en el equipo; Docker Compose publica MySQL
# en el puerto 3307 por defecto (MYSQL_PORT_LOCAL).
export DATABASE_URL='mysql+pymysql://<usuario>:<contraseña>@localhost:3307/db_udv'
```

Si la API y MySQL corren en Docker Compose, el host es `db` y el puerto interno
es `3306`:

```text
mysql+pymysql://<usuario>:<contraseña>@db:3306/db_udv
```

En Railway, configure `DATABASE_URL` en las variables del servicio con la URL
privada de la base MySQL. No escriba credenciales reales en el código ni en
este archivo. G5 aislado lee la variable del entorno y no carga `.env`
automáticamente; en la aplicación compartida, G2 carga `.env` y Docker
Compose también aplica su configuración de entorno.

`.env.example` es solo una plantilla y no debe contener valores reales.
Mantenga las credenciales locales en `.env` (ignorado por Git) o inyéctelas
al proceso desde el entorno de ejecución. G5 no firma ni valida JWT por su
cuenta: esa responsabilidad y `SECRET_KEY` pertenecen a G2. No incluya esa
clave en el frontend ni en archivos compartidos.

Registre el router desde la aplicación compartida:

```python
from fastapi import FastAPI
from g5_programas import router

app = FastAPI()
app.include_router(router)
```

G5 usa `obtener_usuario_actual` de G2 como dependencia de autenticación. Si
G2 no está disponible, los endpoints protegidos responden con error 503. Si no
configura una fábrica de sesiones propia, G5 usa `DATABASE_URL`.

El punto de entrada compartido debe registrar también el manejador de errores
de G5 para conservar el formato común de las excepciones `ApiError`. La
integración debe hacer ambas llamadas:

```python
app.include_router(router)

from g5_programas.errors import registrar_errores

registrar_errores(app)
```

## Frontend y pruebas

El frontend está en `frontend/` y se publica en `/app/g5/Programa.html`. El
inicio de sesión pertenece a G2 y se realiza desde el portal común de `/app/`
mediante `POST /api/v1/auth/login`; G5 no implementa un login propio.
Reutiliza el token `sessionStorage["udv_token"]` y lo envía en el encabezado
`Authorization: Bearer` a la API del mismo origen. La pantalla carga el
listado de programas y permite abrir uno con el botón **Abrir**, por lo que
`program_id` en la URL es opcional.

La lista muestra todos los programas a coordinación y revisión, y solo las
versiones asignadas al docente autenticado. El docente responsable elabora,
edita y envía su propia versión; coordinación también puede elaborar y enviar.
Coordinación y revisión pueden revisar, devolver y aprobar; `authority`
autoriza. `admin`, coordinación y revisión pueden abrir versiones nuevas.
El backend valida los códigos oficiales de G1 en cada operación.
La pantalla usa los estilos comunes de `/udv-styles/udv.css`.

Los cuerpos de escritura están descritos con modelos Pydantic para que
Swagger muestre los campos de creación, versión, encabezado y transiciones.
Al crear un programa o actualizar `responsables`, puede enviarse
`docente_responsable_id`; G5 verifica que ese usuario tenga una asignación
activa en `docente_curso` para el mismo curso, período y sede. Si no se indica
un responsable al crear, coordinación no queda asignada automáticamente como
docente. Un usuario con rol `teacher` solo se asigna a sí mismo si tiene esa
asignación activa en G1.
La edición de una versión se limita a su autor asignado o a `coordinator`.
Las actividades de evaluación aceptan el formato del formulario o una lista
de objetos con `nombre`, `ponderacion` y `semana`; las listas incompletas
responden 422 sin borrar las filas existentes. El número de versión se asigna
por programa y respeta la unicidad de G1 aunque cambie el período.

Al crear una versión desde un trabajo de G3, el enlace puede incluir
`&tarea_destinatario_origen_id=<id-de-asignacion>`. Si no se proporciona en
una versión nueva, se conserva la asignación de origen de la versión clonada.

Ejecute las pruebas disponibles desde la raíz:

```bash
python -m pytest -q
```

Las pruebas cubren transiciones y permisos, y hacen solicitudes HTTP a rutas
protegidas con encabezados Bearer y roles oficiales en el formato de usuario
de G2. El proveedor de identidad se sustituye por fixtures, así que no validan
un JWT real ni conectan a MySQL. Deben complementarse con pruebas de
integración en la aplicación host y una base MySQL local de prueba.

## Documentación

- [Instrucciones para QA](instrucciones.md): contexto, cambios que revisar,
  pruebas y pendientes de integración.
