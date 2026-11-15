# Grupo 2 · API y Seguridad (`g2_api`)

Backend en Python (FastAPI) con autenticación, usuarios, roles y archivos.
Las rutas van bajo `/api/v1`, según `CONTRATO.md` y `CONTRATO_COMUN.md`.

## 1. Instalar

Parado en `grupos/grupo-2-api-seguridad/`:

```
python -m venv .venv
.venv\Scripts\activate        # Windows (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env        # Linux/Mac: cp .env.example .env
```

Después abre `.env` y define `SECRET_KEY` (valor largo y aleatorio) y `DATABASE_URL`.

## 2. Correr

```
python -m uvicorn g2_api.main:app --reload
```

- Interfaz de la documentación: `http://127.0.0.1:8000/api/v1/docs`
- Documento OpenAPI: `http://127.0.0.1:8000/api/v1/openapi.json`
- `g2_api/openapi_docs.py` completa la documentación con los errores comunes (401, 403, 404, 409 y 422) y ejemplos reales; `tests/test_openapi.py` lo verifica.
- La app que se despliega en Railway es la del `main.py` de la raíz, no la de `g2_api/main.py`. Por eso la raíz debe llamar `completar_openapi(app)` después de montar los routers; si no, Swagger muestra el esquema genérico de FastAPI:

```python
from g2_api.openapi_docs import completar_openapi
completar_openapi(app)
```

## 3. Probar

```
python -m pytest
```

Las pruebas usan una base SQLite temporal. Nunca tocan la base compartida.

## 4. Variables de entorno

El archivo `.env` **nunca se sube** al repositorio. Se copia desde `.env.example`.

| Variable | Para qué sirve |
|-|-|
| `DATABASE_URL` | Conexión a la base (`mysql+pymysql://...`). Sin ella usa SQLite local. |
| `SECRET_KEY` | Firma de los JWT. Obligatoria; valor largo y aleatorio. |
| `ALGORITHM` | Algoritmo del token (`HS256`). |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Vigencia del token (120 minutos = 7200 segundos). |
| `CORS_ORIGINS` | Orígenes del frontend permitidos, separados por coma. |
| `LOGIN_MAX_INTENTOS` | Intentos fallidos antes del bloqueo (5 intentos). |
| `LOGIN_BLOQUEO_MINUTOS` | Minutos de bloqueo (15 minutos). |
| `CONTRASENA_MIN` / `CONTRASENA_MAX` | Largo de la contraseña (de 8 a 64 caracteres). |
| `UPLOAD_DIR` | Carpeta donde se guardan los archivos subidos. |

## 5. Base de datos

| Opción | Cuándo usarla |
|-|-|
| SQLite (`sqlite:///./dev.db`) | Pruebas locales sin instalar nada. |
| MySQL de Docker | Desde la raíz del repo: `docker compose up -d db` (puerto local 3307). |
| MySQL o MariaDB local (XAMPP) | Con el script del Grupo 1 importado. |
| Base compartida del PM | Integración. Lo que se borra lo ven los demás grupos. |

El esquema lo crea el Grupo 1 (`01_schema.sql` y `02_seed.sql`). Esta API **no crea tablas** en la base compartida.

La versión 1.2.0 de la base (G1) agrega el catálogo `prioridad_tarea` y una llave foránea en `tarea.prioridad`. No afecta a este módulo (`models.py` no usa `tarea`). Si tu base **local** es 1.1.0, aplica `migracion_1.2.0.sql` (en `grupos/grupo-1-base-de-datos/Docs/sql/`) con `mysql -u root db_udv < migracion_1.2.0.sql`; para comprobar la versión: `SELECT * FROM schema_migracion;`. En la base compartida **no se corre**: la actualiza el PM o el Grupo 1.
Las fechas se guardan en UTC y cada conexión nueva queda en UTC.

Para comprobar la conexión:

```
python -c "from g2_api.database import probar_conexion; print(probar_conexion())"
```

### Auditoría: quién hizo el cambio

Los triggers del Grupo 1 guardan el actor desde las variables `@actor_id` y `@ip_origen` de la conexión.
Antes de crear, cambiar o desactivar algo, el router llama:

```
from g2_api.database import fijar_actor
fijar_actor(db, usuario_actual_id, ip)
```

Hay que llamarla otra vez después de cada `commit`, porque la conexión vuelve al pool y las variables se limpian.
En `auditoria` solo se escriben a mano los eventos de acceso (login, login fallido y logout).

## 6. Seguridad

- Contraseñas solo con hash bcrypt; ninguna respuesta las devuelve.
- Autorización en el servidor con `Authorization: Bearer <token>`.
- Errores en el formato común, sin trazas, SQL ni rutas internas.
- Los archivos de `/files` los descarga su dueño, un admin o un rol que no sea docente con el permiso `files.download` (revisor, coordinación, autoridad o auditoría); cualquier otro usuario recibe 403.
- Sin credenciales en el código: todo va en `.env`.

## 7. Estructura

| Carpeta o archivo | Qué contiene |
|-|-|
| `g2_api/` | Código: routers, middleware y utils. |
| `frontend-login/` | Pantalla de login. |
| `tests/` | Pruebas automáticas (pytest). |
| `CONTRATO.md` | Contrato del PM (no se toca). |
| `GUIA_GRUPO2.md` | Quién hace qué cada semana. |
| `PENDIENTES_QA.md` | Pendientes del QA y quién los corrige. |

Esqueleto del proyecto (Cada línea dice qué es el archivo o la carpeta, para qué sirve y quién lo elaboró):

```
grupos/grupo-2-api-seguridad/
├── CONTRATO.md                             # Contrato del PM con las rutas y reglas que debe cumplir el grupo. (Elaborado por Jonathan Veras - PM)
├── 02_Requerimientos_API_y_Seguridad.docx  # Requerimientos del módulo de API y seguridad. (Elaborado por Jonathan Veras - PM)
├── README.md                               # Guía para instalar, correr y probar el proyecto. (Elaborado por Robert Rodríguez)
├── GUIA_GRUPO2.md                          # Guía con las tareas de cada semana y el estado del grupo. (Elaborado por Daniel Cobos)
├── PENDIENTES_QA.md                        # Resumen de los hallazgos del QA y quién corrige cada uno. (Elaborado por Robert Rodríguez)
├── requirements.txt                        # Lista de librerías de Python que se instalan con pip. (Elaborado por Robert Rodríguez)
├── .env.example                            # Plantilla de las variables de entorno, sin claves reales. (Elaborado por Robert Rodríguez)
├── .gitignore                              # Evita subir al repositorio el .env, la base local y los archivos generados. (Elaborado por Robert Rodríguez)
├── pytest.ini                              # Configuración de pytest: carpeta de pruebas y ruta de los imports. (Elaborado por Daniel Cobos)
├── frontend-login/                         # Pantalla de login que consume la API. (Elaborado por Fulvio Jiménez)
│   ├── index.html                          # Estructura de la pantalla con el formulario de correo y contraseña. (Elaborado por Fulvio Jiménez)
│   ├── style.css                           # Estilos y diseño adaptable de la pantalla de login. (Elaborado por Fulvio Jiménez)
│   ├── script.js                           # Envía el login a la API y muestra el error si falla. (Elaborado por Fulvio Jiménez)
│   ├── logo.webp                           # Logo que se muestra en la pantalla de login. (Elaborado por Fulvio Jiménez)
│   └── imagen.webp                         # Imagen decorativa de la pantalla de login. (Elaborado por Fulvio Jiménez)
├── tests/                                  # Pruebas automáticas con pytest y una base SQLite temporal. (Elaborado por el Grupo 2)
│   ├── conftest.py                         # Prepara la base temporal y el cliente que usan todas las pruebas. (Elaborado por Robert Rodríguez)
│   ├── test_auth.py                        # Pruebas de login, logout y /me. (Elaborado por Daniel Cobos)
│   ├── test_users.py                       # Pruebas de usuarios y roles: 401, 403, 404, 409 y 422. (Elaborado por Randy Torres)
│   ├── test_errores.py                     # Pruebas del formato de error y de la paginación. (Elaborado por Edgar Domingo)
│   ├── test_file.py                        # Pruebas de archivos: tipo no permitido, tamaño y descarga. (Elaborado por Fulvio Jiménez)
│   ├── test_hallazgos_pm.py                # Pruebas de los hallazgos del PM: descarga por rol, archivo eliminado, validaciones 422 y Coordinación. (Elaborado por Daniel Cobos)
│   └── test_openapi.py                     # Pruebas de que Swagger coincide con lo que responde la API. (Elaborado por Robert Rodríguez)
└── g2_api/                                 # Paquete con todo el código de la API. (Elaborado por el Grupo 2)
    ├── __init__.py                         # Marca la carpeta como paquete de Python. (Elaborado por Daniel Cobos)
    ├── main.py                             # Crea la app y conecta los routers, el CORS y los errores. (Elaborado por Robert Rodríguez)
    ├── config.py                           # Lee las variables del .env y las deja listas para usar. (Elaborado por Robert Rodríguez)
    ├── database.py                         # Conexión a MySQL, sesiones y la función fijar_actor para la auditoría. (Elaborado por Robert Rodríguez)
    ├── models.py                           # Tablas de seguridad (usuario, rol, sesión, archivo y auditoría) como clases. (Elaborado por Robert Rodríguez)
    ├── openapi_docs.py                     # Completa Swagger con los errores comunes y ejemplos reales. (Elaborado por Robert Rodríguez)
    ├── seguridad.py                        # Crea y valida los tokens JWT y revisa las contraseñas. (Elaborado por Daniel Cobos)
    ├── routers/                            # Rutas de la API agrupadas por tema. (Elaborado por Daniel Cobos, Randy Torres y Fulvio Jiménez)
    │   ├── __init__.py                     # Marca la carpeta como paquete de Python. (Elaborado por Daniel Cobos)
    │   ├── auth.py                         # Login, logout y /me, con el bloqueo por intentos fallidos. (Elaborado por Daniel Cobos)
    │   ├── users.py                        # Crear, listar, consultar, editar y desactivar usuarios. (Elaborado por Randy Torres)
    │   ├── roles.py                        # Listar roles y crear uno nuevo, solo para el admin. (Elaborado por Randy Torres)
    │   └── files.py                        # Subir archivos validados y descargarlos el dueño, un admin o un rol no docente con permiso. (Elaborado por Fulvio Jiménez)
    ├── middleware/                         # Código que se ejecuta antes o después de cada ruta. (Elaborado por Randy Torres y Edgar Domingo)
    │   ├── __init__.py                     # Marca la carpeta como paquete de Python. (Elaborado por Daniel Cobos)
    │   ├── auth_middleware.py              # Exige un rol permitido y responde 403 si no lo tiene. (Elaborado por Randy Torres)
    │   └── error_handler.py                # Da a todos los errores el mismo formato JSON, sin datos internos. (Elaborado por Edgar Domingo)
    └── utils/                              # Funciones de apoyo que usan varios routers. (Elaborado por Edgar Domingo)
        ├── __init__.py                     # Marca la carpeta como paquete de Python. (Elaborado por Daniel Cobos)
        ├── paginacion.py                   # Arma las listas con page, per_page, total y data. (Elaborado por Edgar Domingo)
        └── registro.py                     # Guarda en auditoría el login, el login fallido y el logout. (Elaborado por Edgar Domingo)
```

## 8. Responsable de cada archivo

| Persona | Cuenta de GitHub | Archivos |
|-|-|-|
| Daniel - Persona 1 (Coordinador) | `dancobs` | `routers/auth.py`, `seguridad.py`, `tests/test_auth.py`, `tests/test_hallazgos_pm.py`, `GUIA_GRUPO2.md` |
| Randy - Persona 2 | `rtorresixcoy375` | `routers/users.py`, `routers/roles.py`, `middleware/auth_middleware.py`, `tests/test_users.py` |
| Edgar - Persona 3 | `zeusgeo99-code` | `middleware/error_handler.py`, `utils/paginacion.py`, `utils/registro.py`, `tests/test_errores.py` |
| Fulvio - Persona 4 | `Ful55` | `routers/files.py`, `frontend-login/`, `tests/test_file.py` |
| Robert - Persona 5 | `Davids107` | `main.py`, `config.py`, `database.py`, `models.py`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`, `tests/conftest.py`, `tests/test_openapi.py`, `g2_api/openapi_docs.py` |
| Jonathan Veras - PM | — | `CONTRATO.md`, `CONTRATO_COMUN.md`, los `.docx` de requerimientos y la raíz del repo |

