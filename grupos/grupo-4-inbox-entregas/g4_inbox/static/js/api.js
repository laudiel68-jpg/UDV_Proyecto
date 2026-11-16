// =====================================================
// CAPA DE DATOS DEL INBOX
// Ya conectado al servidor real — reemplaza los datos de prueba que
// vivían aquí antes. La pantalla (inbox.js) no cambió nada.
// =====================================================

const Api = (function () {
  const BASE = "/api/v1";

  function diasRestantes(fechaTexto) {
    if (typeof fechaTexto !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(fechaTexto)) return null;
    const fecha = new Date(fechaTexto + "T00:00:00");
    if (Number.isNaN(fecha.getTime())) return null;
    const hoy = new Date();
    hoy.setHours(0, 0, 0, 0);
    return Math.round((fecha - hoy) / 86400000);
  }

  async function manejarRespuesta(respuesta) {
    if (!respuesta.ok) {
      const cuerpo = await respuesta.json().catch(() => ({}));
      throw new Error(Sesion.mensajeDeError(cuerpo, respuesta.status));
    }
    return respuesta.json();
  }

  function obtenerInbox({ q = "", status = "", page = 1, per_page = 20 } = {}) {
    const parametros = new URLSearchParams({ q, page, per_page });
    if (status) parametros.set("status", status);
    return fetch(`${BASE}/inbox?${parametros}`, { headers: Sesion.encabezados() }).then(manejarRespuesta);
  }

  function obtenerResumen() {
    return fetch(`${BASE}/inbox/summary`, { headers: Sesion.encabezados() }).then(manejarRespuesta);
  }

  return { obtenerInbox, obtenerResumen, diasRestantes };
})();
