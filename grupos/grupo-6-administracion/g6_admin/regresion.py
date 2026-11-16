"""Casos críticos para correr antes de cada entrega (escenario G6-40).

Prueba la API ya levantada, como lo haría una persona, sin cambiar ningún
dato: solo consulta y comprueba que lo prohibido siga prohibido. Por eso se
puede correr contra la base compartida o contra la demostración.

    python -m g6_admin.regresion --url http://127.0.0.1:8000

Inicia sesión con un usuario de administración y uno docente (por defecto los
de la semilla del G1). La contraseña se toma de G6_REGRESION_CLAVE o se
pregunta; nunca se escribe en pantalla. Termina con código 1 si algún caso
falla.
"""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# (método, ruta, token o None, cuerpo o None) → (código HTTP, JSON o None)
Llamada = Callable[[str, str, str | None, dict[str, Any] | None], tuple[int, Any]]

CATALOGOS = ("academic-units", "campuses", "courses", "periods", "modalities", "areas")


@dataclass
class Caso:
    escenario: str
    descripcion: str
    paso: bool
    detalle: str = ""


class _Registro:
    def __init__(self) -> None:
        self.casos: list[Caso] = []

    def __call__(self, escenario: str, descripcion: str, paso: bool, detalle: str = "") -> bool:
        self.casos.append(Caso(escenario, descripcion, bool(paso), "" if paso else detalle))
        return bool(paso)


def ejecutar(llamar: Llamada, *, admin: tuple[str, str],
             docente: tuple[str, str]) -> list[Caso]:
    caso = _Registro()

    codigo, salud = llamar("GET", "/api/v1/health", None, None)
    caso("G6-34", "La API y la base responden en /api/v1/health",
         codigo == 200 and (salud or {}).get("checks", {}).get("database") == "ok",
         f"HTTP {codigo}, {salud}")

    codigo, _ = llamar("GET", "/api/v1/campuses", None, None)
    caso("G6-01", "Sin sesión no se ven los catálogos (401)", codigo == 401, f"HTTP {codigo}")

    token_admin = _entrar(llamar, caso, "administración", *admin)
    token_docente = _entrar(llamar, caso, "docente", *docente)
    if not (token_admin and token_docente):
        return caso.casos  # Sin sesión no tiene sentido seguir.

    # ── Catálogos (G6-01 a G6-03 y G6-21 a G6-25) ──
    for recurso in CATALOGOS:
        codigo, datos = llamar("GET", f"/api/v1/{recurso}?per_page=100", token_docente, None)
        caso("G6-21..25", f"El docente consulta {recurso}",
             codigo == 200 and isinstance((datos or {}).get("data"), list), f"HTTP {codigo}")
    codigo, _ = llamar("POST", "/api/v1/campuses", token_docente,
                       {"code": "REGRESION", "name": "No debe guardarse"})
    caso("G6-02", "El docente no puede agregar a un catálogo (403)", codigo == 403,
         f"HTTP {codigo}")

    # ── Notificaciones (G6-04 a G6-13) ──
    codigo, datos = llamar("GET", "/api/v1/notifications", token_docente, None)
    caso("G6-04..13", "El docente ve sus notificaciones",
         codigo == 200 and "total" in (datos or {}), f"HTTP {codigo}")

    # ── Panel (G6-26 a G6-29) ──
    codigo, panel = llamar("GET", "/api/v1/dashboard?limit=100", token_admin, None)
    if caso("G6-26..29", "Administración ve el panel", codigo == 200, f"HTTP {codigo}"):
        caso("G6-26", "Las tareas por estado suman el total", _cuadra(panel["tasks"]),
             str(panel["tasks"]))
        caso("G6-26", "Las asignaciones por estado suman el total",
             _cuadra(panel["assignments"]), str(panel["assignments"]))
        caso("G6-27", "Cada vencida ya pasó su fecha límite",
             all(_fecha(a["due_date"]) <= _fecha(panel["generated_at"])
                 for a in panel["overdue"]["items"]),
             str(panel["overdue"]["items"][:3]))
        caso("G6-28", "Cada próxima a vencer está dentro del plazo de aviso",
             all(_fecha(panel["generated_at"]) <= _fecha(a["due_date"])
                 for a in panel["due_soon"]["items"]),
             str(panel["due_soon"]["items"][:3]))
        cumplimiento = panel["compliance"]
        esperado = (round(100 * cumplimiento["completed"] / cumplimiento["expected"], 1)
                    if cumplimiento["expected"] else None)
        caso("G6-29", "El cumplimiento es entregadas entre esperadas",
             cumplimiento["percentage"] == esperado, str(cumplimiento))
    codigo, _ = llamar("GET", "/api/v1/dashboard", token_docente, None)
    caso("G6-26..29", "El docente no ve el panel (403)", codigo == 403, f"HTTP {codigo}")

    # ── Auditoría (G6-30 a G6-33) ──
    _, yo = llamar("GET", "/api/v1/me", token_admin, None)
    id_admin = (yo or {}).get("id")
    filtros = {
        "G6-30": (f"user_id={id_admin}", lambda r: r["actor_id"] == id_admin),
        "G6-31": (f"from={_hoy()}&to={_hoy()}", lambda r: r["created_at"].startswith(_hoy())),
        "G6-32": ("entity=usuario", lambda r: r["entity"] == "usuario"),
        "G6-33": ("action=LOGIN_OK", lambda r: r["action"] == "LOGIN_OK"),
    }
    for escenario, (consulta, cumple) in filtros.items():
        codigo, datos = llamar("GET", f"/api/v1/audit?{consulta}&per_page=100", token_admin, None)
        registros = (datos or {}).get("data") or []
        # El inicio de sesión de esta misma corrida deja registros de hoy.
        caso(escenario, f"La auditoría filtra con {consulta.split('&')[0]}",
             codigo == 200 and bool(registros) and all(cumple(r) for r in registros),
             f"HTTP {codigo}, {len(registros)} registros")
    codigo, _ = llamar("GET", "/api/v1/audit", token_docente, None)
    caso("G6-30..33", "El docente no consulta la auditoría (403)", codigo == 403,
         f"HTTP {codigo}")
    return caso.casos


def _entrar(llamar: Llamada, caso: _Registro, quien: str, correo: str, clave: str) -> str | None:
    codigo, datos = llamar("POST", "/api/v1/auth/login", None,
                           {"correo": correo, "password": clave})
    token = (datos or {}).get("access_token") if codigo == 200 else None
    caso("G2", f"Inicia sesión {quien} ({correo})", bool(token), f"HTTP {codigo}")
    return token


def _fecha(texto: str) -> datetime:
    # El panel manda la hora de la base con su zona ("Z" o "-06:00").
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def _cuadra(conteo: dict[str, Any]) -> bool:
    return sum(conteo["by_state"].values()) == conteo["total"]


def _hoy() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def llamada_http(url_base: str, tiempo_maximo: float = 15) -> Llamada:
    """Hace las llamadas con urllib: no necesita librerías extra."""
    def llamar(metodo: str, ruta: str, token: str | None,
               cuerpo: dict[str, Any] | None) -> tuple[int, Any]:
        encabezados = {"Accept": "application/json"}
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode()
            encabezados["Content-Type"] = "application/json"
        if token:
            encabezados["Authorization"] = f"Bearer {token}"
        peticion = urllib.request.Request(url_base.rstrip("/") + ruta, data=datos,
                                          headers=encabezados, method=metodo)
        try:
            with urllib.request.urlopen(peticion, timeout=tiempo_maximo) as respuesta:
                return respuesta.status, _json(respuesta.read())
        except urllib.error.HTTPError as error:
            return error.code, _json(error.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return 0, None  # Sin conexión: cada caso lo reporta como fallido.
    return llamar


def _json(contenido: bytes) -> Any:
    try:
        return json.loads(contenido)
    except ValueError:
        return None


def main(argumentos: list[str] | None = None) -> int:
    lector = argparse.ArgumentParser(prog="python -m g6_admin.regresion",
                                     description=__doc__.splitlines()[0])
    lector.add_argument("--url", default="http://127.0.0.1:8000",
                        help="Dirección de la API (por defecto la local)")
    lector.add_argument("--admin", default="admin@demo.udv.edu.gt")
    lector.add_argument("--docente", default="docente1@demo.udv.edu.gt")
    opciones = lector.parse_args(argumentos)
    clave = os.getenv("G6_REGRESION_CLAVE") or getpass.getpass(
        "Contraseña de los usuarios de prueba: ")

    casos = ejecutar(llamada_http(opciones.url), admin=(opciones.admin, clave),
                     docente=(opciones.docente, clave))
    for c in casos:
        linea = f"  {'✓' if c.paso else '✗'} {c.escenario:<10} {c.descripcion}"
        print(linea + (f"  →  {c.detalle}" if c.detalle else ""))
    fallidos = sum(not c.paso for c in casos)
    print(f"\n{len(casos) - fallidos} de {len(casos)} casos pasaron en {opciones.url}.")
    return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
