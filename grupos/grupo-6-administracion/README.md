# Grupo 6: Administración, notificaciones, pruebas y despliegue

Módulo `g6_admin`. Este README explica cómo correr y probar lo que existe hasta
ahora (CONTRATO.md del G6 §5).

## Qué hay por ahora

| Pieza | Ruta | Escenarios QA |
|---|---|---|
| Estado del servicio | `GET /api/v1/health` | G6-34, G6-36 (en lo que toca a esta ruta) |
| Catálogos | `GET` y `POST` en `/api/v1/academic-units`, `/campuses`, `/courses`, `/periods`, `/modalities` y `/areas` | G6-01, G6-02, G6-03, G6-21 a G6-25 |
| Pantalla de catálogos | `/g6/catalogos.html` | G6-01, G6-02 |

Hay 49 pruebas automáticas en `tests/`.

## Cómo correrlo

Se necesita Python 3.10 o más reciente. Desde la **raíz** del repositorio:

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # Mac o Linux
pip install -r requirements.txt
cd grupos/grupo-6-administracion
python -m g6_admin
```

Después abre en el navegador:

- Pantalla de catálogos: http://127.0.0.1:8000
- Estado del servicio: http://127.0.0.1:8000/api/v1/health
- Documentación interactiva (OpenAPI): http://127.0.0.1:8000/docs

Para detener el servidor, presiona `Ctrl+C` en la terminal. Los registros que
agregues se borran al reiniciar, porque todavía se guardan en memoria.

## Cómo correr las pruebas

Desde `grupos/grupo-6-administracion`, con el entorno activado:

```bash
python -m pytest
```

## Probar a mano que el servidor rechaza a quien no es administrador (G6-03)

1. Abre http://127.0.0.1:8000/docs.
2. Despliega `POST /api/v1/campuses` y presiona **Try it out**.
3. En `x-demo-role` escribe `teacher` y en el cuerpo pon
   `{"code": "NORTE", "name": "Sede Norte"}`.
4. Presiona **Execute**. La respuesta es `403` con el formato de error común.
   Con `admin` la respuesta es `201`.

## Cómo está organizado

| Archivo | Qué hace | ¿Depende del framework? |
|---|---|---|
| `g6_admin/catalogos.py` | Reglas de catálogos: validación, permiso, búsqueda, orden y paginación | No |
| `g6_admin/salud.py` | Arma la respuesta de `/health` sin exponer detalles internos | No |
| `g6_admin/seguridad.py` | Usuario y regla "solo administración modifica catálogos" | No |
| `g6_admin/errores.py` | Formato de error del contrato común | No |
| `g6_admin/paginacion.py` | Respuesta con `page`, `per_page`, `total`, `data` | No |
| `g6_admin/datos_ejemplo.py` | Registros ficticios para ver la pantalla con contenido | No |
| `g6_admin/api.py` | Rutas HTTP y función `instalar(app)` para la app principal | Sí |
| `g6_admin/app_demo.py` | App local para desarrollar y mostrar avances | Sí |
| `g6_admin/pantallas/catalogos.html` | Pantalla con los estilos de `grupos/udv-styles/udv.css` | No |

## Piezas temporales

Estas partes existen solo para poder avanzar antes de que otros grupos
publiquen lo suyo. Cada una está marcada como `TEMPORAL` o `PENDIENTE` en el
código.

| Pieza | Por qué es temporal | Se reemplaza por |
|---|---|---|
| FastAPI | El framework sigue pendiente (README §5) | La decisión del PM. Solo cambian `api.py` y `app_demo.py` |
| Encabezado `X-Demo-Role` y usuarios de demostración | La autenticación es del G2 | La sesión o token del G2 (`GET /api/v1/me`). Fuera de la app de demostración el encabezado no da acceso |
| Códigos de rol `admin` y `teacher` | Los nombres oficiales los define el G2 | Los roles del G2 |
| `errores.py` y `paginacion.py` | El formato de error y la paginación son servicio compartido del G2 | Los imports de `g2_api` |
| Máximo de `per_page` en 100 | Lo documenta el G2 en el OpenAPI | El valor del G2 |
| Repositorio en memoria | Las tablas son del G1 | Un repositorio con los mismos métodos que use las tablas del G1 |
| Campos `code`, `name`, `is_active` | Las columnas reales las fija el diccionario de datos del G1 | Los campos del G1 (por ejemplo, fechas del período) |
| Verificación de base de datos en `/health` | Todavía no hay motor ni conexión | Una consulta mínima a la base |

## Variables de entorno

| Variable | Uso | Valor por defecto |
|---|---|---|
| `APP_ENV` | Nombre del ambiente que muestra `/health` (G6-35) | `desarrollo` |
| `APP_VERSION` | Versión que muestra `/health` | La versión de `g6_admin` |

El archivo `.env.example` de la raíz es del PM; hay que pedirle que agregue
estas variables.
