# Evidencia: instalación desde cero (G6-19) y ambiente (G6-35)

Fecha: 23-oct-2026. Se siguió `docs/instalacion.md` paso por paso, sin
ajustes manuales fuera de la guía.

| Paso | Qué se hizo | Resultado |
|---|---|---|
| 1 | `git clone` del original (`main` en `349c35f`) + carpeta del G2 de la rama `grupo-2` + esta versión del G6; entorno virtual nuevo; `pip install -r requirements.txt` | Instaló sin conflictos (Python 3.13) |
| 2 | MySQL 8.0 vacío; `python -m g1_bd crear` | `db_udv creada: 49 tablas, 7 vistas, 60 triggers, 4 procedimientos y funciones` |
| 3 | `.env` desde `.env.example` + `APP_ENV`, `DATABASE_URL`, `SECRET_KEY`; `python -m g6_admin.ambiente` | `✓ Configuración completa.` y la URL se muestra como `root:***@...` |
| 4 | Línea del G6 activada en `main.py` (solo local); `uvicorn main:app` | `/health`: `routers` incluye `g6_admin.api`, `pendientes` vacío |
| 5 | Login real del G2 con `admin@demo.udv.edu.gt` | `GET /campuses` 200 con `S-CEN` y `S-REG`; `GET /audit?entity=usuario` 200 con 10 registros |
| 5 | Login con `docente1@demo.udv.edu.gt` | `POST /campuses` 403; `GET /notifications` muestra el aviso `program.authorized` que salió del trigger del G1 |
| 6 | `python -m pytest` en la carpeta del G6 | 190 pasan, 13 omitidas (las de MySQL, sin `G6_MYSQL_URL`) |
| 6 | `python -m pytest tests/integracion` con `G6_MYSQL_URL` | 13 pasan |

## Lo que encontramos en la raíz (para el PM)

- `main.py` monta `auth.router` del G2 pero no `auth.me_router`, así que
  `GET /api/v1/me` responde 404. La pantalla de catálogos lo usa para saber
  el rol; sin él, igual funciona porque el servidor decide (403).
- `main.py` aún no monta `g6_admin/pantallas/` en `/g6` ni
  `grupos/udv-styles/` en `/udv-styles`.
- `docker-compose.yml` carga `Docs/sql/db_udv_completo.sql`, pero el G1 ahora
  entrega `01_schema.sql` y `02_seed.sql`. Con `docker compose up` la base
  quedaría vacía.
