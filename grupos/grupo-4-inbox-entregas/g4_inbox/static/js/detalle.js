// =====================================================
// PANTALLA DE DETALLE / ENTREGA / REVISIÓN
// Conectada al backend real — igual que inbox.js, pero para una sola
// asignación, cuyo id viene en la URL: detalle.html?id=123
// =====================================================

const API_BASE = "/api/v1";

const idAsignacion = new URLSearchParams(location.search).get("id");

const NOMBRE_ESTADO = {
  assigned: "Asignada", in_progress: "En progreso", submitted: "Entregada",
  under_review: "En revisión", returned: "Devuelta", approved: "Aprobada",
  closed: "Cerrada", cancelled: "Cancelada",
};

function claseBadge(estado) {
  return "badge-" + String(estado || "").replace(/_/g, "-");
}

async function apiFetch(ruta, opciones = {}) {
  const respuesta = await fetch(`${API_BASE}${ruta}`, {
    ...opciones,
    headers: { "Content-Type": "application/json", ...Sesion.encabezados(), ...(opciones.headers || {}) },
  });
  const tipo = respuesta.headers.get("content-type") || "";
  const datos = tipo.includes("application/json") ? await respuesta.json() : await respuesta.text();
  if (!respuesta.ok) throw new Error(Sesion.mensajeDeError(datos, respuesta.status));
  return datos;
}

// Sube el archivo al servicio de archivos de G2 (POST /api/v1/files) y
// devuelve el id que G2 le dio en la tabla archivo. Va con FormData y SIN
// Content-Type: el navegador lo pone solo, con el separador del formulario.
async function subirArchivo(archivo) {
  const fd = new FormData();
  fd.append("file", archivo);
  const respuesta = await fetch(`${API_BASE}/files`, {
    method: "POST",
    headers: Sesion.encabezados(),
    body: fd,
  });
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(Sesion.mensajeDeError(datos, respuesta.status));
  return datos.file_id;
}

// GET /api/v1/files/{id} de G2 pide el token en el encabezado, y un enlace
// normal no lo manda: se descarga con fetch y luego se le pasa al navegador.
async function descargarArchivo(archivo) {
  ocultarAvisos();
  try {
    const respuesta = await fetch(`${API_BASE}/files/${encodeURIComponent(archivo.file_id)}`, {
      headers: Sesion.encabezados(),
    });
    if (!respuesta.ok) {
      const datos = await respuesta.json().catch(() => ({}));
      throw new Error(Sesion.mensajeDeError(datos, respuesta.status));
    }
    const url = URL.createObjectURL(await respuesta.blob());
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = archivo.name;
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    mostrarError(`No se pudo descargar ${archivo.name}: ${error.message}`);
  }
}

function textoTamano(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Lista de archivos, del intento más reciente al más antiguo. El reenvío no
// borra la evidencia anterior: se sigue viendo con su número de intento.
function mostrarArchivos(archivos) {
  const caja = document.getElementById("detArchivos");
  const lista = document.getElementById("listaArchivos");
  lista.innerHTML = "";
  caja.style.display = archivos.length ? "block" : "none";
  [...archivos].reverse().forEach((archivo) => {
    const fila = document.createElement("li");
    fila.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:.75rem;padding:.5rem 0;border-bottom:1px solid #E5E7EB;";
    const datos = document.createElement("span");
    const partes = [
      archivo.attempt ? `Intento ${archivo.attempt}` : null,
      (archivo.mime || "").split("/").pop().toUpperCase() || null,
      textoTamano(archivo.size) || null,
      // La fecha de subida no se muestra: G2 la guarda en UTC y el resto en la
      // hora del servidor; con el docker saldría con 6 horas de diferencia.
    ].filter(Boolean);
    const nombre = document.createElement("strong");
    nombre.textContent = archivo.name;
    datos.appendChild(nombre);
    if (partes.length) datos.appendChild(document.createTextNode(` · ${partes.join(" · ")}`));
    fila.appendChild(datos);
    agregarBoton(fila, "Descargar", "btn-udv-dark btn-udv-sm", () => descargarArchivo(archivo));
    lista.appendChild(fila);
  });
}

function mostrarError(mensaje, id = "avisoError") {
  const el = document.getElementById(id);
  el.textContent = mensaje;
  el.style.display = "flex";
}

function ocultarAvisos() {
  ["avisoError", "avisoEntregaError", "avisoEntregaOk"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });
}

// "2026-11-15T16:41" -> "15/11/2026 16:41". Se arma a mano para mostrar la
// hora tal como viene de la base, sin que el navegador la cambie de zona.
function formatearFecha(iso) {
  const [dia, hora] = iso.split("T");
  const [a, m, d] = dia.split("-");
  return `${d}/${m}/${a}${hora ? " " + hora.slice(0, 5) : ""}`;
}

function adaptarTarea(api) {
  return {
    id: api.id,
    titulo: api.title || api.task_type || `Tarea ${api.id}`,
    tipo: api.task_type || "",
    estado: api.status,
    instrucciones: api.instructions || "",
    // Observación de la última devolución (viene del historial de G3, no de
    // los comentarios: un comentario del docente no es una observación).
    devolucion: api.last_return && api.last_return.comment ? api.last_return : null,
    aprobacion: api.last_approval && api.last_approval.comment ? api.last_approval : null,
    borrador: api.draft_comment || "",
    // Quién está viendo: el docente dueño ve los botones de entregar y el
    // revisor los de revisar. Los demás (coordinación, auditoría) solo leen.
    esDestinatario: Boolean(api.viewer && api.viewer.is_assignee),
    esRevisor: Boolean(api.viewer && api.viewer.is_reviewer),
    archivo: (api.files || []).length ? api.files[api.files.length - 1].name : null,
    archivos: api.files || [],
    // Por defecto true: si el backend no manda este campo (no debería
    // pasar), es más seguro seguir pidiendo evidencia que dejar de pedirla.
    requiereArchivo: api.requiere_archivo !== false,
  };
}

let tareaActual = null;

function agregarBoton(contenedor, texto, clase, accion) {
  const btn = document.createElement("button");
  btn.className = `btn-udv ${clase}`;
  btn.textContent = texto;
  btn.onclick = accion;
  contenedor.appendChild(btn);
}

function mostrarFormularioEntrega(tarea) {
  document.getElementById("formEntrega").style.display = "block";
  document.getElementById("entregaComentario").value = tarea.borrador || "";
  document.getElementById("entregaArchivo").value = "";

  // Este tipo de tarea no pide evidencia — se oculta el campo de archivo
  // en vez de mostrarlo y luego dejar entregar sin usarlo.
  const campoArchivo = document.getElementById("entregaArchivo");
  const etiquetaArchivo = document.querySelector('label[for="entregaArchivo"]');
  campoArchivo.style.display = tarea.requiereArchivo ? "block" : "none";
  if (etiquetaArchivo) etiquetaArchivo.style.display = tarea.requiereArchivo ? "block" : "none";
  document.getElementById("entregaArchivoNota").style.display = tarea.requiereArchivo ? "block" : "none";

  document.getElementById("archivoInfo").textContent = !tarea.requiereArchivo
    ? "Esta tarea no requiere evidencia adjunta."
    : tarea.archivo
      ? `📎 Archivo registrado: ${tarea.archivo}`
      : "Selecciona la evidencia que vas a registrar.";
  const botones = document.getElementById("entregaBotones");
  botones.innerHTML = "";
  // el estilo "outline" de udv.css es blanco, para fondos oscuros: aquí no se vería
  agregarBoton(botones, "Guardar borrador", "btn-udv-dark", () => guardarBorrador(tarea));
  agregarBoton(botones, tarea.estado === "returned" ? "Reenviar" : "Entregar", "btn-udv-primary", () => confirmarEntrega(tarea));
}

// GET /api/v1/assignments/{id} — carga y pinta la pantalla completa
async function cargarDetalle() {
  ocultarAvisos();
  try {
    const api = await apiFetch(`/assignments/${idAsignacion}`);
    tareaActual = adaptarTarea(api);

    document.getElementById("cargando").style.display = "none";
    document.getElementById("detalle").style.display = "block";
    document.getElementById("detTipo").textContent = tareaActual.tipo;
    document.getElementById("detTitulo").textContent = tareaActual.titulo;
    document.getElementById("detInstrucciones").textContent = tareaActual.instrucciones;

    const badge = document.getElementById("detEstadoBadge");
    badge.textContent = NOMBRE_ESTADO[tareaActual.estado] || tareaActual.estado;
    badge.className = `udv-badge ${claseBadge(tareaActual.estado)}`;

    document.getElementById("obsGroup").style.display = "none";
    document.getElementById("obs").value = "";
    document.getElementById("formEntrega").style.display = "none";

    mostrarArchivos(tareaActual.archivos);

    const contComentario = document.getElementById("detComentario");
    contComentario.innerHTML = "";
    if (tareaActual.estado === "returned" && tareaActual.devolucion) {
      const d = tareaActual.devolucion;
      const aviso = document.createElement("div");
      aviso.className = "udv-alert udv-alert-danger";
      const fecha = d.at ? ` (${formatearFecha(d.at)})` : "";
      aviso.textContent = `Observación del revisor${fecha}: ${d.comment}`;
      contComentario.appendChild(aviso);
    }
    if (tareaActual.estado === "approved" && tareaActual.aprobacion) {
      const d = tareaActual.aprobacion;
      const aviso = document.createElement("div");
      aviso.className = "udv-alert udv-alert-success";
      const fecha = d.at ? ` (${formatearFecha(d.at)})` : "";
      aviso.textContent = `Comentario del revisor al aprobar${fecha}: ${d.comment}`;
      contComentario.appendChild(aviso);
    }

    // Los botones dependen del estado Y de quién mira: al docente nunca se
    // le muestra "Tomar para revisar", ni al revisor "Entregar".
    const botones = document.getElementById("detBotones");
    botones.innerHTML = "";
    const docente = tareaActual.esDestinatario;
    const revisor = tareaActual.esRevisor;
    if (docente && tareaActual.estado === "assigned") {
      agregarBoton(botones, "Iniciar tarea", "btn-udv-primary", () => transicion(tareaActual, "start"));
    } else if (docente && (tareaActual.estado === "in_progress" || tareaActual.estado === "returned")) {
      mostrarFormularioEntrega(tareaActual);
    } else if (revisor && tareaActual.estado === "submitted") {
      agregarBoton(botones, "Tomar para revisar", "btn-udv-primary", () => transicion(tareaActual, "review"));
    } else if (docente && tareaActual.estado === "submitted") {
      botones.textContent = "Tu entrega está en espera de revisión.";
    } else if (revisor && tareaActual.estado === "under_review") {
      agregarBoton(botones, "Aprobar", "btn-udv-primary", () => aprobar(tareaActual));
      agregarBoton(botones, "Devolver", "btn-udv-gold", () => devolver(tareaActual));
      document.getElementById("obsGroup").style.display = "block";
    } else {
      botones.textContent = "Sin acciones disponibles en este estado.";
    }
  } catch (error) {
    document.getElementById("cargando").style.display = "none";
    mostrarError(`No se pudo cargar la asignación: ${error.message}`);
  }
}

async function guardarBorrador(tarea) {
  try {
    const comment = document.getElementById("entregaComentario").value.trim();
    await apiFetch(`/assignments/${tarea.id}/submission-draft`, {
      method: "PUT",
      body: JSON.stringify({ comment }),
    });
    tarea.borrador = comment;
    const ok = document.getElementById("avisoEntregaOk");
    ok.textContent = "Borrador guardado en el backend. Puedes seguir editándolo antes de entregar.";
    ok.style.display = "flex";
    document.getElementById("avisoEntregaError").style.display = "none";
  } catch (error) {
    mostrarError(error.message, "avisoEntregaError");
  }
}

// Orden de la entrega: 1) guarda el borrador, para no perder lo escrito si
// algo falla; 2) sube el archivo a G2; 3) lo vincula a la asignación con el
// id que devolvió G2; 4) pide a G3 el submit o resubmit.
async function confirmarEntrega(tarea) {
  const comentario = document.getElementById("entregaComentario").value.trim();
  const archivoInput = document.getElementById("entregaArchivo");
  const archivoNuevo = archivoInput.files[0];
  document.getElementById("avisoEntregaError").style.display = "none";
  document.getElementById("avisoEntregaOk").style.display = "none";

  if (tarea.requiereArchivo && !tarea.archivo && !archivoNuevo) {
    mostrarError("Debes seleccionar la evidencia antes de entregar.", "avisoEntregaError");
    return;
  }
  try {
    await apiFetch(`/assignments/${tarea.id}/submission-draft`, {
      method: "PUT",
      body: JSON.stringify({ comment: comentario }),
    });
    if (archivoNuevo) {
      const idArchivo = await subirArchivo(archivoNuevo);
      await apiFetch(`/assignments/${tarea.id}/files`, {
        method: "POST",
        body: JSON.stringify({ file_id: String(idArchivo), name: archivoNuevo.name }),
      });
    }
    const accion = tarea.estado === "returned" ? "resubmit" : "submit";
    await apiFetch(`/assignments/${tarea.id}/${accion}`, {
      method: "POST",
    });
    await cargarDetalle();
    const ok = document.getElementById("avisoEntregaOk");
    ok.textContent = accion === "resubmit" ? "Reenvío registrado correctamente." : "Entrega registrada correctamente.";
    ok.style.display = "flex";
  } catch (error) {
    mostrarError(error.message, "avisoEntregaError");
  }
}

async function transicion(tarea, accion) {
  try {
    await apiFetch(`/assignments/${tarea.id}/${accion}`, {
      method: "POST",
    });
    await cargarDetalle();
  } catch (error) {
    mostrarError(error.message);
  }
}

// La observación es opcional al aprobar, pero si el revisor la escribió se
// envía: queda en el historial de G3 y el docente la ve en el detalle.
async function aprobar(tarea) {
  const comment = document.getElementById("obs").value.trim();
  try {
    await apiFetch(`/assignments/${tarea.id}/approve`, {
      method: "POST",
      body: JSON.stringify({ comment: comment || null }),
    });
    await cargarDetalle();
  } catch (error) {
    mostrarError(error.message);
  }
}

async function devolver(tarea) {
  const comment = document.getElementById("obs").value.trim();
  if (!comment) {
    mostrarError("La observación es obligatoria para devolver.");
    return;
  }
  try {
    await apiFetch(`/assignments/${tarea.id}/return`, {
      method: "POST",
      body: JSON.stringify({ comment }),
    });
    await cargarDetalle();
  } catch (error) {
    mostrarError(error.message);
  }
}

if (!idAsignacion) {
  document.getElementById("cargando").style.display = "none";
  mostrarError("No se indicó qué asignación mostrar. Vuelve al inbox y elige una tarjeta.");
} else {
  cargarDetalle();
}
