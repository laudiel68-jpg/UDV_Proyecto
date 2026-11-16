# Configuracion del Grupo 2: lee las variables del archivo .env (Persona 5).
import os
import warnings
from dotenv import load_dotenv

load_dotenv()

def _lista(valor: str):
    return [v.strip() for v in valor.split(",") if v.strip()]

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
SECRET_KEY = os.getenv("SECRET_KEY", "")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES= int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
CORS_ORIGINS = _lista(os.getenv("CORS_ORIGINS", "http://localhost:5500"))
LOGIN_MAX_INTENTOS = int(os.getenv("LOGIN_MAX_INTENTOS", "5"))
LOGIN_BLOQUEO_MINUTOS = int(os.getenv("LOGIN_BLOQUEO_MINUTOS", "15"))
CONTRASENA_MIN = int(os.getenv("CONTRASENA_MIN", "8")) # largo minimo de la contraseña (Persona 1).
CONTRASENA_MAX = int(os.getenv("CONTRASENA_MAX", "64")) # largo maximo de la contraseña (Persona 1).
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "almacen_archivos") # Carpeta donde files.py guarda los archivos (Persona 4).

# Una clave vacía o la de ejemplo permite falsificar tokens, así que el arranque se detiene.
if not SECRET_KEY or SECRET_KEY == "TU_CLAVE_SECRETA":
    raise RuntimeError("Falta SECRET_KEY: copia .env.example a .env y define un valor propio.")

# Con menos de 32 caracteres la firma del token es débil: solo avisa para no romper un despliegue que ya funciona.
if len(SECRET_KEY) < 32:
    warnings.warn("SECRET_KEY tiene menos de 32 caracteres: usa una clave más larga y aleatoria.", RuntimeWarning)

# Sin DATABASE_URL se usa SQLite local, que solo sirve para pruebas y no para un servidor.
if not os.getenv("DATABASE_URL"):
    warnings.warn("Falta DATABASE_URL: se usa SQLite local (solo para pruebas).", RuntimeWarning)

