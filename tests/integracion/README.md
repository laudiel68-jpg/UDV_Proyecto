# Pruebas de integración del PM

Prueban la **aplicación completa** (`main.py` con los seis módulos) contra una
base MySQL cargada con el esquema y la semilla de G1. Cubren lo que las pruebas
de cada grupo no ven: el flujo entre módulos (G3 → G4 → G2 → G5 → G6), los
permisos cruzados entre roles y el formato común de errores y paginación.

Cada prueba afirma lo que piden `README.md`, `CONTRATO_COMUN.md` y los
`CONTRATO.md`; si falla, es un defecto del módulo, no de la prueba.

## Cómo correrlas

Necesitan una base **desechable**: escriben tareas, usuarios y archivos.
Nunca apuntarlas a Railway.

```bash
# 1. MySQL local con la base de G1 (desde la raíz del repo)
docker compose up -d
mysql -h 127.0.0.1 -P 3307 -u root -p < grupos/grupo-1-base-de-datos/Docs/sql/01_schema.sql
mysql -h 127.0.0.1 -P 3307 -u root -p < grupos/grupo-1-base-de-datos/Docs/sql/02_seed.sql

# 2. Variables (PowerShell: $env:NOMBRE = "valor")
export UDV_TEST_MYSQL_URL="mysql+pymysql://udv_app:<clave>@127.0.0.1:3307/db_udv"
export UDV_RAIZ="$(pwd)"
export SECRET_KEY="una-clave-de-pruebas-de-al-menos-32-caracteres"

# 3. Correr
python -m pytest tests/integracion -v
```

Sin `UDV_TEST_MYSQL_URL` las pruebas se omiten, así que `pytest` desde la raíz
sigue funcionando para los grupos que no tienen MySQL a mano.

## Para los grupos

Antes de abrir un PR, corran estas pruebas además de las suyas. Lo que aquí
falla, falla en Railway.
