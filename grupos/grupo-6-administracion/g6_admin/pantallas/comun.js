// Sesión y llamadas a la API que comparten las pantallas del panel y la auditoría.
// El login es del G2 (POST /api/v1/auth/login). El token se guarda solo en esta
// pestaña (sessionStorage) con la misma clave que usa catalogos.html, así que
// entrar en una pantalla sirve para las demás.
"use strict";

const UDV = (() => {
  const CLAVE_TOKEN = "udv_token";
  const $ = (id) => document.getElementById(id);

  function leerToken() {
    try { return sessionStorage.getItem(CLAVE_TOKEN) || localStorage.getItem(CLAVE_TOKEN); }
    catch { return null; }
  }

  function guardarToken(token) {
    try {
      if (token) sessionStorage.setItem(CLAVE_TOKEN, token);
      else { sessionStorage.removeItem(CLAVE_TOKEN); localStorage.removeItem(CLAVE_TOKEN); }
    } catch { /* Sin almacenamiento: la sesión dura lo que la página. */ }
  }

  class ErrorDeApi extends Error {
    constructor(estadoHttp, error) {
      super(error?.message || "No se pudo completar la solicitud.");
      this.estadoHttp = estadoHttp;
      this.error = error;
    }
  }

  let alPerderSesion = () => {};

  async function llamarApi(ruta, opciones = {}) {
    const encabezados = { Accept: "application/json" };
    if (opciones.body) encabezados["Content-Type"] = "application/json";
    const token = leerToken();
    if (token) encabezados.Authorization = `Bearer ${token}`;
    let respuesta;
    try {
      respuesta = await fetch(`/api/v1${ruta}`, { ...opciones, headers: encabezados });
    } catch {
      throw new ErrorDeApi(0, null);
    }
    const cuerpo = await respuesta.json().catch(() => null);
    if (respuesta.status === 401 && !opciones.sinAvisoDeSesion) alPerderSesion();
    if (!respuesta.ok) throw new ErrorDeApi(respuesta.status, cuerpo?.error);
    return cuerpo;
  }

  function textoDeError(error, sinPermiso) {
    if (error.estadoHttp === 0) return "No hay conexión con la API. Revisa que el servidor siga corriendo.";
    if (error.estadoHttp === 401) return "Tu sesión no está activa. Inicia sesión para continuar.";
    if (error.estadoHttp === 403) return sinPermiso;
    return error.message;
  }

  function mostrarAlerta(contenedor, tipo, texto) {
    contenedor.replaceChildren();
    if (!texto) return;
    const alerta = document.createElement("div");
    alerta.className = `udv-alert udv-alert-${tipo}`;
    alerta.textContent = texto;
    contenedor.append(alerta);
  }

  // Fecha ISO con su zona ("2026-11-02T18:00:00Z" o "...-06:00") → texto en la hora del navegador.
  const formatoFecha = new Intl.DateTimeFormat("es-GT", { dateStyle: "medium", timeStyle: "short" });
  function fecha(iso) {
    return iso ? formatoFecha.format(new Date(iso)) : "—";
  }

  // La auditoría se filtra por días en UTC: se muestra también en UTC para que cuadre.
  const formatoUtc = new Intl.DateTimeFormat("es-GT", {
    dateStyle: "medium", timeStyle: "medium", timeZone: "UTC" });
  function fechaUtc(iso) {
    return iso ? formatoUtc.format(new Date(iso)) : "—";
  }

  function celda(texto, clase) {
    const td = document.createElement("td");
    td.textContent = texto ?? "—";
    if (clase) td.className = clase;
    return td;
  }

  // Conecta el formulario de login, el botón de salir y la carga de /me.
  // alCambiar(yo) se llama con el usuario de /me, o con null si no hay sesión.
  function iniciarSesion(alCambiar) {
    const aviso = $("aviso-sesion");
    const barra = $("barra-sesion");

    function sinSesion() {
      aviso.hidden = false;
      barra.hidden = true;
      alCambiar(null);
    }
    alPerderSesion = sinSesion;

    async function cargar() {
      if (!leerToken()) return sinSesion();
      try {
        const yo = await llamarApi("/me");
        yo.codigosDeRol = (yo?.roles || []).map((r) => (typeof r === "string" ? r : r?.codigo ?? r?.code));
        aviso.hidden = true;
        barra.hidden = false;
        $("usuario-sesion").textContent = `Sesión: ${yo.correo}`;
        alCambiar(yo);
      } catch (error) {
        if (error.estadoHttp !== 401) alCambiar({ correo: "", codigosDeRol: null });
      }
    }

    $("form-login").addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const boton = $("entrar");
      boton.disabled = true;
      mostrarAlerta($("mensaje-login"), null);
      try {
        const respuesta = await llamarApi("/auth/login", {
          method: "POST", sinAvisoDeSesion: true,
          body: JSON.stringify({ correo: $("login-correo").value.trim(), password: $("login-clave").value }),
        });
        guardarToken(respuesta.access_token);
        $("login-clave").value = "";
        await cargar();
      } catch (error) {
        const texto = [401, 422].includes(error.estadoHttp)
          ? "Correo o contraseña incorrectos." : textoDeError(error, error.message);
        mostrarAlerta($("mensaje-login"), "danger", texto);
      } finally {
        boton.disabled = false;
      }
    });

    $("salir").addEventListener("click", async () => {
      try { await llamarApi("/auth/logout", { method: "POST", sinAvisoDeSesion: true }); } catch { /* Ya vencida. */ }
      guardarToken(null);
      sinSesion();
    });

    return cargar();
  }

  return { $, llamarApi, textoDeError, mostrarAlerta, fecha, fechaUtc, celda, iniciarSesion };
})();
