"""Arranca la demo local del G6:  python -m g6_admin"""

import uvicorn


def main() -> None:
    print("\n  Pantalla de catálogos:  http://127.0.0.1:8000/g6/catalogos.html")
    print("  Estado del servicio:    http://127.0.0.1:8000/api/v1/health")
    print("  Documentación (OpenAPI): http://127.0.0.1:8000/docs")
    print("  Para detener el servidor: Ctrl+C\n")
    uvicorn.run("g6_admin.app_demo:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
