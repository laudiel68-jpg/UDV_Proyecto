# Imagen de la aplicación (mantenida por el PM). La usan docker-compose y Railway.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Primero solo los requirements, para reutilizar la caché si el código cambia.
COPY requirements.txt requirements-base.txt ./
COPY grupos/grupo-1-base-de-datos/requirements.txt grupos/grupo-1-base-de-datos/
COPY grupos/grupo-2-api-seguridad/requirements.txt grupos/grupo-2-api-seguridad/
COPY grupos/grupo-3-workflow-tareas/requirements.txt grupos/grupo-3-workflow-tareas/
COPY grupos/grupo-4-inbox-entregas/requirements.txt grupos/grupo-4-inbox-entregas/
COPY grupos/grupo-5-programas-pdf/requirements.txt grupos/grupo-5-programas-pdf/
COPY grupos/grupo-6-administracion/requirements.txt grupos/grupo-6-administracion/
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
# Railway define PORT; en local se usa 8000.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
