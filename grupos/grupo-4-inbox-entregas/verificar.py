"""Revisión antes de subir cambios de G4. Correr desde esta carpeta:

    py verificar.py

Hace cinco pasos y se detiene en el primero que falla:

1. Que routes.py, inbox.py y database.py sean de la misma versión.
2. Que no queden restos viejos (X-Role, datos.js, file_id inventado,
   marcas de conflicto de Git) ni cambios fuera de nuestra carpeta.
3. Todas las pruebas de G4 con pytest, sin --ignore.
4. Las pruebas contra MySQL: test_mysql.py (solo lee) y
   test_mysql_escritura.py (escribe).
5. Las pruebas de integración del PM (tests/integracion) que tocan a G4.

Variables que necesita (en CMD: set NOMBRE=valor):
    G4_TEST_MYSQL_URL   base para test_mysql.py (puede ser la compartida, solo lee)
    UDV_TEST_MYSQL_URL  base DESECHABLE (docker-compose de la raíz) para los pasos 4 y 5

Sin esas variables el script falla. Para revisar sin base a propósito:
    py verificar.py --sin-mysql
(en ese caso el resultado NO sirve para abrir el PR).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
G2 = RAIZ / "grupos" / "grupo-2-api-seguridad"

# Pruebas del PM en tests/integracion que revisan a G4. Las demás son de otros
# grupos: se corren al final solo para informar, no detienen el script.
PRUEBAS_PM_DE_G4 = [
    "test_tarea_publicada_por_g3_aparece_en_inbox_g4_solo_del_destinatario",
    "test_estado_en_g4_sigue_las_transiciones_de_g3",
    "test_docente_no_ve_detalle_de_asignacion_ajena",
    "test_docente_no_comenta_ni_vincula_archivos_en_asignacion_ajena",
    "test_comentario_de_g4_se_guarda_en_la_base",
    "test_borrador_de_g4_se_guarda_en_la_base",
    "test_vincular_archivo_inexistente_se_rechaza",
    "test_auditor_no_comenta",
    "test_revisor_no_designado_no_lee_entrega_en_g4",
]

# Texto que no debe aparecer. (archivos donde se busca, texto, por qué)
RESTOS = [
    (["g4_inbox/static", "g4_inbox/routes.py"], "X-Role", "las pantallas ya no mandan X-Role"),
    (["g4_inbox/static"], 'src="js/datos.js"', "datos.js (datos simulados) se eliminó"),
    (["g4_inbox/static"], "demo-", "el file_id se pide a G2, no se inventa"),
]
MARCAS_CONFLICTO = re.compile(r"^(<<<<<<< |>>>>>>> |=======$)", re.M)


def titulo(texto):
    print(f"\n=== {texto}")


def fallar(mensaje):
    print(f"\nFALLÓ: {mensaje}")
    print("No subas todavía. Corrige y vuelve a correr py verificar.py")
    sys.exit(1)


def entorno():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(G2), str(AQUI), env.get("PYTHONPATH", "")])
    env.setdefault("SECRET_KEY", "clave-solo-para-verificar-g4-con-32-caracteres")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def correr(argumentos, cwd=AQUI, env=None):
    mostrar = argumentos[:2] + ["(prueba de imports)"] if "-c" in argumentos else argumentos
    print("  $", " ".join(mostrar))
    r = subprocess.run(argumentos, cwd=cwd, env=env or entorno(), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def resumen_pytest(salida):
    lineas = [x for x in salida.strip().splitlines() if x.strip()]
    return lineas[-1] if lineas else "(sin salida)"


def paso_1_version():
    titulo("1. routes.py, inbox.py y database.py de la misma versión")
    if not G2.is_dir():
        fallar(f"no encuentro G2 en {G2}. Este script se corre dentro del repo completo.")
    prueba = ("from g4_inbox.inbox import ORDEN_PRIORIDAD_POR_DEFECTO; "
              "from g4_inbox.database import fetch_orden_prioridades, guardar_borrador, "
              "crear_comentario, vincular_archivo, ErrorConflicto, ArchivoNoEncontrado; "
              "import g4_inbox.routes as r, inspect; "
              "fuente = inspect.getsource(r); "
              "assert 'database.vincular_archivo' in fuente and 'database.guardar_borrador' in fuente "
              "and 'database.crear_comentario' in fuente, 'routes.py es de una versión anterior'; "
              "print('ok')")
    codigo, salida = correr([sys.executable, "-c", prueba])
    if codigo != 0 or "ok" not in salida:
        print(salida)
        fallar("los tres archivos no son de la misma entrega. Copia juntos routes.py, inbox.py y database.py.")
    print("  ok")


def paso_2_restos():
    titulo("2. Restos viejos y archivos fuera de la carpeta")
    problemas = []
    for rutas, texto, motivo in RESTOS:
        for ruta in rutas:
            base = AQUI / ruta
            archivos = [base] if base.is_file() else base.rglob("*.*")
            for archivo in archivos:
                if archivo.suffix in (".py", ".js", ".html") and texto in archivo.read_text(encoding="utf-8"):
                    problemas.append(f"{archivo.relative_to(AQUI)} contiene '{texto}' ({motivo})")
    for archivo in AQUI.rglob("*"):
        if archivo.is_file() and archivo.suffix in (".py", ".js", ".html", ".css", ".md", ".txt"):
            if MARCAS_CONFLICTO.search(archivo.read_text(encoding="utf-8", errors="replace")):
                problemas.append(f"{archivo.relative_to(AQUI)} tiene marcas de conflicto de Git")
    if (AQUI / "g4_inbox" / "static" / "js" / "datos.js").exists():
        problemas.append("g4_inbox/static/js/datos.js todavía existe")

    codigo, salida = correr(["git", "status", "--porcelain", "--", str(RAIZ)], cwd=RAIZ)
    if codigo == 0:
        carpeta = "grupos/grupo-4-inbox-entregas/"
        for linea in salida.splitlines():
            ruta = linea[3:].strip().strip('"')
            if ruta and not ruta.startswith(carpeta):
                problemas.append(f"cambio fuera de nuestra carpeta: {ruta}")
            if ruta.endswith(".env"):
                problemas.append(f"{ruta} aparece en Git: la clave nunca se sube")
    else:
        print("  (no se pudo leer git status; revisa a mano que solo cambió nuestra carpeta)")

    if problemas:
        for p in problemas:
            print("  -", p)
        fallar("hay restos o cambios que no deben subir")
    print("  ok")


def paso_3_pytest():
    titulo("3. Todas las pruebas de G4")
    codigo, salida = correr([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    print("  ", resumen_pytest(salida))
    if codigo != 0:
        print(salida[-3000:])
        fallar("hay pruebas que fallan")


def _parece_railway(url):
    return bool(re.search(r"railway|rlwy\.net", url or "", re.I))


def paso_4_mysql(sin_mysql):
    titulo("4. Pruebas contra MySQL")
    lectura, escritura = os.environ.get("G4_TEST_MYSQL_URL"), os.environ.get("UDV_TEST_MYSQL_URL")
    if sin_mysql:
        print("  OMITIDO a propósito con --sin-mysql. Este resultado NO sirve para abrir el PR.")
        return False
    if not lectura or not escritura:
        fallar("faltan G4_TEST_MYSQL_URL y/o UDV_TEST_MYSQL_URL. "
               "Levanta la base con docker compose (raíz del repo) y defínelas.")
    codigo, salida = correr([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs",
                             "tests/test_mysql.py", "tests/test_mysql_escritura.py"])
    print("  ", resumen_pytest(salida))
    if codigo != 0 or "skipped" in resumen_pytest(salida):
        print(salida[-3000:])
        fallar("las pruebas con MySQL fallaron o se omitieron")
    return True


def paso_5_integracion():
    titulo("5. Pruebas de integración del PM que tocan a G4")
    env = entorno()
    env["UDV_RAIZ"] = str(RAIZ)
    env["DATABASE_URL"] = os.environ["UDV_TEST_MYSQL_URL"]
    seleccion = " or ".join(PRUEBAS_PM_DE_G4)
    codigo, salida = correr([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             "tests/integracion", "-k", seleccion], cwd=RAIZ, env=env)
    print("  ", resumen_pytest(salida))
    if codigo != 0 or "skipped" in resumen_pytest(salida):
        print(salida[-3000:])
        fallar("alguna prueba de integración de G4 falla")

    titulo("   (solo para informar) integración completa, todos los grupos")
    _, salida = correr([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "tests/integracion"], cwd=RAIZ, env=env)
    for linea in salida.splitlines():
        if linea.startswith("FAILED"):
            print("  ", linea)
    print("  ", resumen_pytest(salida))


def main():
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    sin_mysql = "--sin-mysql" in sys.argv
    if _parece_railway(os.environ.get("UDV_TEST_MYSQL_URL")):
        fallar("UDV_TEST_MYSQL_URL apunta a Railway. Las pruebas que escriben solo van en una base desechable.")
    paso_1_version()
    paso_2_restos()
    paso_3_pytest()
    if paso_4_mysql(sin_mysql):
        paso_5_integracion()
        print("\nTodo pasó. Ahora pide a otra persona del equipo que revise el cambio antes del push.")
    else:
        print("\nPasos 1 a 3 bien, pero sin MySQL. No abras el PR con este resultado.")
        sys.exit(2)


if __name__ == "__main__":
    main()
