"""Se ejecuta antes que cualquier prueba.

En la app integrada G4 lee de MySQL por defecto. Las pruebas, en cambio,
corren con los datos de ejemplo en memoria (no necesitan base de datos), así
que aquí se apaga MySQL ANTES de que se importe g4_inbox.routes.

Para probar contra una base real hay dos módulos aparte:
- test_mysql.py: solo lee (G4_TEST_MYSQL_URL), sirve con la base compartida.
- test_mysql_escritura.py: escribe (UDV_TEST_MYSQL_URL), solo base desechable.
"""
import os

os.environ["G4_USAR_MYSQL"] = "0"

# Si se va a probar escribiendo, toda la app (G2, G3, G4) debe usar esa base y
# no la del .env, que puede ser la de Railway. Se fija aquí porque cada módulo
# lee DATABASE_URL al importarse, y load_dotenv no pisa una variable ya puesta.
import re

import pytest

if os.environ.get("UDV_TEST_MYSQL_URL"):
    if re.search(r"railway|rlwy\.net", os.environ["UDV_TEST_MYSQL_URL"], re.I):
        pytest.exit("UDV_TEST_MYSQL_URL apunta a Railway: las pruebas que escriben "
                    "solo se corren en una base desechable.", returncode=3)
    os.environ["DATABASE_URL"] = os.environ["UDV_TEST_MYSQL_URL"]
