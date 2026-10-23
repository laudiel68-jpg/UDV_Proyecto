# Instalación desde cero (G6-19)

Pasos para instalar y correr el sistema en una computadora nueva, desde la
clonación hasta ver la API funcionando. Se probaron tal cual en una copia
limpia del repositorio (ver "Cómo se verificó" al final).

## Lo que necesitas

| Programa | Para qué | Dónde se baja |
|---|---|---|
| Python 3.12 o más nuevo | Correr la API | python.org (marca "Add Python to PATH") |
| Git | Clonar el repositorio | git-scm.com |
| MySQL 8, o MariaDB 10.4 o más nuevo (el de XAMPP sirve) | La base `db_udv` del G1 | dev.mysql.com o apachefriends.org |

## 1. Clonar e instalar

En una terminal (PowerShell en Windows):

```bash
git clone https://github.com/jonnyverasdl-cloud/UDV_Proyecto.git
cd UDV_Proyecto
python -m venv .venv
```

Activa el entorno virtual:

```bash
# Windows (PowerShell). La primera línea solo afecta a esta ventana.
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\activate

# Mac o Linux
source .venv/bin/activate
```

Instala todo desde la raíz:

```bash
pip install -r requirements.txt
```

## 2. Crear la base de datos

Con MySQL encendido (en XAMPP: botón **Start** de MySQL), desde la raíz:

```bash
cd grupos/grupo-1-base-de-datos
python -m g1_bd crear --host 127.0.0.1 --port 3306 --user root --password <clave>
cd ../..
```

Debe terminar con `db_udv creada: 49 tablas, 7 vistas, ...`. Si `root` no
tiene contraseña (XAMPP), omite `--password`. También se puede importar
`Docs/sql/01_schema.sql` y luego `02_seed.sql` en phpMyAdmin (README del G1).

## 3. Configurar el ambiente

Copia el ejemplo y edítalo:

```bash
copy .env.example .env      # Windows
cp .env.example .env        # Mac o Linux
```

Agrega al final de `.env` estas líneas, con tus datos:

```ini
APP_ENV=desarrollo
DATABASE_URL=mysql+pymysql://root:<clave>@127.0.0.1:3306/db_udv
SECRET_KEY=<texto aleatorio de 32 caracteres o más>
```

Para generar `SECRET_KEY`:
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Revisa la configuración (no muestra contraseñas):

```bash
cd grupos/grupo-6-administracion
python -m g6_admin.ambiente
cd ../..
```

Debe decir `✓ Configuración completa.`

## 4. Correr la API

Desde la raíz:

```bash
uvicorn main:app --reload
```

Abre:

- `http://127.0.0.1:8000/health`: la lista `routers` debe incluir `g6_admin.api`.
- `http://127.0.0.1:8000/api/v1/docs`: todas las rutas.

> **Mientras el PM no active el G6 en `main.py`**, `g6_admin.api` no aparece
> en `/health`. Para probar en tu computadora quita el `#` de la línea
> `("g6_admin.api", "router")` en `main.py` y **no subas ese cambio**: la raíz
> es del PM.

## 5. Probar con los usuarios de la semilla

Los usuarios de prueba del G1 tienen la contraseña que publica su README.
En `/api/v1/docs`:

1. `POST /api/v1/auth/login` con `admin@demo.udv.edu.gt`. Copia el
   `access_token`.
2. Pulsa **Authorize** (arriba a la derecha) y pega el token.
3. `GET /api/v1/campuses` muestra `S-CEN` y `S-REG`.
4. `GET /api/v1/notifications` convierte en avisos los eventos que dejó la
   semilla y muestra los del usuario.
5. `GET /api/v1/audit?entity=usuario` muestra el historial de usuarios.

Con `docente1@demo.udv.edu.gt`, `POST /api/v1/campuses` responde 403.

## 6. Correr las pruebas

```bash
cd grupos/grupo-6-administracion
python -m pytest
```

Las pruebas no usan MySQL: crean las tablas del G1 en un SQLite temporal.
Para probar también contra MySQL, con una base **de pruebas** (escriben
registros nuevos):

```bash
# Windows
set G6_MYSQL_URL=mysql+pymysql://root:<clave>@127.0.0.1:3306/db_udv
# Mac o Linux
export G6_MYSQL_URL=mysql+pymysql://root:<clave>@127.0.0.1:3306/db_udv

python -m pytest tests/integracion
```

## Problemas comunes

| Mensaje | Qué hacer |
|---|---|
| `running scripts is disabled on this system` | Falta la línea `Set-ExecutionPolicy` del paso 1 |
| `Cannot install fastapi==... and fastapi==...` | Un `requirements.txt` pide otra versión: avisa al PM |
| `RuntimeError: Falta SECRET_KEY` | Falta `SECRET_KEY` en `.env`, o corriste `uvicorn` fuera de la raíz |
| `Can't connect to MySQL server` | MySQL apagado, o el puerto de `DATABASE_URL` no es el correcto |
| `Unknown database 'db_udv'` | Falta el paso 2 |
| `/health` no lista `g6_admin.api` | Ver la nota del paso 4 |

## Cómo se verificó

El 23-oct-2026 se siguió esta guía en una copia nueva del repositorio
original (`main` en `349c35f`), con la rama `grupo-2` y esta versión del G6,
un entorno virtual nuevo y MySQL 8.0 vacío. El resultado está en
`docs/evidencia_instalacion.md`.
