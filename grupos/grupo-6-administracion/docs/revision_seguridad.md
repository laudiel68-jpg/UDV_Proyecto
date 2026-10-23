# Revisión de seguridad de los datos de demostración (G6-20)

Fecha: 23-oct-2026. Qué se revisó, cómo y qué quedó. Las revisiones que se
pueden automatizar están en `tests/test_seguridad.py` y corren con cada
`pytest`, así que si alguien sube un secreto la prueba falla.

| Qué | Cómo | Resultado |
|---|---|---|
| Código, pruebas y documentos del G6 | Búsqueda de URLs con contraseña, llaves privadas, tokens de GitHub, claves de AWS y `SECRET_KEY` con valor | Sin hallazgos. Las pruebas usan valores falsos marcados como tales |
| Archivos `.env` | Que no haya ninguno en la carpeta | No hay |
| Semilla del G1 (`02_seed.sql`) | Que las contraseñas sean solo hashes bcrypt y los correos de `@demo.udv.edu.gt` | 8 usuarios, todos con hash bcrypt y correo de demo |
| Datos de prueba del G2 (`usuarios_prueba.json`) | Que no traiga contraseñas | No trae |
| Auditoría (`GET /api/v1/audit`) | Que no muestre hashes ni tokens aunque estén guardados | Las claves con `contrasena`, `password`, `hash`, `token`, `secret` o `clave` salen como `***`. Los triggers del G1 solo guardan si la contraseña cambió (`true`/`false`) |
| Registros de errores | Que solo digan el tipo de error | Notificaciones, salud y ambiente registran el tipo (`ConnectionError`), nunca el mensaje ni la URL |
| `python -m g6_admin.ambiente` | Que no imprima secretos | Muestra `usuario:***@host` |

## Lo que queda como decisión del PM

- **Contraseña común de la semilla.** Los 8 usuarios demo comparten la
  contraseña que publica el README del G1. Sirve para la presentación, pero en
  la demostración pública cualquiera podría entrar como administración. Se
  recomienda cambiarla en Railway después de cargar la semilla, o cargar ahí
  una semilla con otra contraseña que no esté en el repositorio.
- **HTTPS** en la dirección pública: lo da Railway; falta confirmarlo con la
  URL final.
