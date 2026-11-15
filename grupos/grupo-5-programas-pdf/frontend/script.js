
document.addEventListener("DOMContentLoaded", async () => {
  const API = new URL("/api/v1", window.location.origin).toString().replace(/\/$/, "");
  const searchParams = new URLSearchParams(window.location.search);
  const requestedProgramId = Number(searchParams.get("program_id"));
  const hasRequestedProgramId = searchParams.has("program_id");
  let programId = Number.isSafeInteger(requestedProgramId) && requestedProgramId > 0
    ? requestedProgramId
    : null;
  const assignmentOriginParam = searchParams.get("tarea_destinatario_origen_id");
  const parsedAssignmentOriginId = Number(assignmentOriginParam);
  const assignmentOriginId = Number.isSafeInteger(parsedAssignmentOriginId) && parsedAssignmentOriginId > 0
    ? parsedAssignmentOriginId
    : null;
  const invalidAssignmentOrigin = assignmentOriginParam !== null && assignmentOriginId === null;
  const TOKEN_KEY = "udv_token";
  let accessToken = sessionStorage.getItem(TOKEN_KEY);
  let authenticatedUser = null;

  const $ = (selector) => document.querySelector(selector);

  const loginPanel = $("#login-panel");
  const loginStatus = $("#login-status");
  const appContainer = $(".container");
  const role = $("#role");
  const programList = $("#program-list");
  const programStatus = $("#program-status");
  const versionNumberLabel = $("#version-number");
  const saveStatus = $("#save-status");

  const instructor = $("#instructor");
  const deanName = $("#dean-name");
  const coordinatorName = $("#coordinator-name");
  const instructorId = $("#instructor-id");

  const saveButton = $("#save-section");
  const createVersionButton = $("#create-version");
  const submitForReviewButton = $("#submit-review");
  const reviewButton = $("#review-program");
  const returnButton = $("#return-program");
  const approveButton = $("#approve-program");
  const authorizeButton = $("#authorize-version");
  const pdfPreviewButton = $("#pdf-preview");
  const printPdfButton = $("#print-pdf");
  const closePreviewButton = $("#close-preview");
  const pdfDocument = $("#pdf-document");
  const cancelButton = $("#cancel-changes");

  const sectionLinks = document.querySelectorAll(".section-nav a");
  const sections = document.querySelectorAll(".section");
  const programFields = document.querySelectorAll(
    ".section input, .section textarea, .section select",
  );

  // Aquí guardamos el programa y la versión que se está mostrando.
  let program = null;
  let programLoaded = false;
  let currentVersion = null;
  let programVersions = [];
  let versionId = null;
  let state = "draft";
  let currentVersionNumber = 1;
  let isSaving = false;

  const PROGRAM_MANAGERS = ["admin", "coordinator", "reviewer"];
  const PROGRAM_AUTHORS = ["teacher", "coordinator"];
  const PROGRAM_REVIEWERS = ["coordinator", "reviewer"];

  const roleNames = {
    admin: "Administrador de programas",
    coordinator: "Coordinación académica",
    teacher: "Docente responsable",
    reviewer: "Revisor",
    authority: "Dirección",
    auditor: "Auditor (consulta)",
  };

  const roleOptions = [
    { value: "admin", label: "Administrador de programas" },
    { value: "coordinator", label: "Coordinación académica" },
    { value: "teacher", label: "Docente responsable" },
    { value: "reviewer", label: "Revisor" },
    { value: "authority", label: "Dirección" },
    { value: "auditor", label: "Auditor (consulta)" },
  ];

  const statusNames = {
    draft: "BORRADOR",
    submitted: "ENVIADA",
    under_review: "EN REVISIÓN",
    returned: "DEVUELTO",
    approved: "APROBADO",
    authorized: "AUTORIZADO",
    superseded: "REEMPLAZADO",
  };

  // Elegimos qué versión mostrar según el rol y el paso en que va.
  /**
   * Busca la versión más nueva del historial.
   * Si aún no hay ninguna, devuelve null.
   */
  function getLatestVersion() {
    return programVersions.reduce(
      (latestVersion, item) =>
        !latestVersion || item.numero_version > latestVersion.numero_version ? item : latestVersion,
      null,
    );
  }

  function isAssignedTeacher(version = currentVersion) {
    const rawActorId = authenticatedUser?.id ?? authenticatedUser?.user_id;
    const actorId = Number(rawActorId);
    const responsibleId = Number(
      getSectionContent(version, "responsables").docente_responsable_id,
    );
    return Number.isSafeInteger(actorId) && actorId > 0 && actorId === responsibleId;
  }

  function canEditCurrentVersion() {
    return PROGRAM_MANAGERS.includes(role.value) ||
      (role.value === "teacher" && isAssignedTeacher());
  }

  /** Guarda la versión en la lista local o actualiza sus datos si ya estaba. */
  function updateProgramVersion(data) {
    const index = programVersions.findIndex((item) => item.id === data.id);
    if (index === -1) {
      programVersions.push(data);
    } else {
      programVersions[index] = { ...programVersions[index], ...data };
    }
  }

  /**
   * Muestra a cada rol la versión que le toca: la que debe revisar o autorizar,
   * o la más reciente que todavía se puede editar.
   */
  function selectVersionForRole(selectedRole) {
    const latestVersion = getLatestVersion();

    if (selectedRole === "authority" && latestVersion?.estado === "approved") {
      return latestVersion;
    }

    if (
      PROGRAM_MANAGERS.includes(selectedRole) &&
      ["submitted", "under_review", "approved"].includes(latestVersion?.estado)
    ) {
      return latestVersion;
    }

    const editableVersions = programVersions
      .filter((item) => ["draft", "returned"].includes(item.estado))
      .sort((a, b) => b.numero_version - a.numero_version);

    if (selectedRole === "teacher") {
      return (
        editableVersions.find(isAssignedTeacher) ||
        programVersions
          .filter(isAssignedTeacher)
          .sort((a, b) => b.numero_version - a.numero_version)[0] ||
        null
      );
    }

    return (
      editableVersions[0] ||
      programVersions.find(
        (item) =>
          item.numero_version === program?.version_actual &&
          item.estado === "authorized",
      ) ||
      latestVersion
    );
  }

  /** Le cuenta al usuario qué falta hacer con la versión que está viendo. */
  function getVersionStatusMessage() {
    const latestVersion = getLatestVersion();
    if (!latestVersion) return `Rol seleccionado: ${roleNames[role.value]}`;

    if (role.value === "authority" && latestVersion.estado === "approved") {
      return `La versión ${latestVersion.numero_version} está aprobada y pendiente de autorización.`;
    }

    if (
      PROGRAM_MANAGERS.includes(role.value) &&
      latestVersion.estado !== "authorized"
    ) {
      const nextStep = {
        draft: PROGRAM_AUTHORS.includes(role.value)
          ? "el docente responsable o coordinación debe enviarla a revisión"
          : "coordinación o revisión debe enviarla a revisión",
        submitted: "un revisor debe tomar la revisión",
        under_review: "un revisor debe aprobarla o devolverla",
        returned: "un usuario con permiso de gestión debe corregirla",
        approved: "Dirección debe autorizarla",
      }[latestVersion.estado] || "debe completarse su revisión y autorización";

      return `La versión ${latestVersion.numero_version} aún no está vigente: ${nextStep}.`;
    }

    if (role.value === "teacher" && !isAssignedTeacher()) {
      return "Solo puedes editar la versión en la que figuras como docente responsable.";
    }

    return `Rol seleccionado: ${roleNames[role.value]}`;
  }

  function configureRoles(user) {
    const userRoles = new Set(
      (user.roles || []).map((item) =>
        String(typeof item === "string" ? item : item.codigo || "").trim().toLowerCase(),
      ),
    );
    const allowedRoles = roleOptions.filter((option) => userRoles.has(option.value));
    if (!allowedRoles.length) {
      throw new Error("Tu cuenta no tiene un rol habilitado para G5.");
    }

    role.replaceChildren(
      ...allowedRoles.map((option) => {
        const element = document.createElement("option");
        element.value = option.value;
        element.textContent = option.label;
        return element;
      }),
    );
    role.value = allowedRoles[0].value;
    role.disabled = allowedRoles.length === 1;
    const coordinatorLabel = document.querySelector('label[for="coordinator-name"]');
    coordinatorLabel.textContent = role.value === "reviewer" ? "Revisor" : "Coordinación académica";
  }

  async function loadProgramOptions() {
    const programs = [];
    let page = 1;
    let total = 0;
    do {
      const result = await request(`/course-programs?page=${page}&per_page=100`);
      programs.push(...(result.data || []));
      total = result.total || 0;
      page += 1;
    } while (programs.length < total);

    const uniquePrograms = new Map();
    programs.forEach((item) => {
      if (!uniquePrograms.has(item.id)) uniquePrograms.set(item.id, item);
    });

    programList.replaceChildren();
    if (!uniquePrograms.size) {
      const empty = document.createElement("li");
      empty.textContent = "No hay programas disponibles para tu usuario.";
      programList.append(empty);
      return uniquePrograms;
    }

    uniquePrograms.forEach((item) => {
      const row = document.createElement("li");
      const details = document.createElement("div");
      const course = document.createElement("strong");
      course.textContent = [item.codigo, item.asignatura]
        .filter(Boolean)
        .join(" · ") || `Programa ${item.id}`;
      const period = document.createElement("p");
      period.textContent = `Período: ${item.periodo_vigente || item.periodo || "Sin período"}`;
      const currentVersion = document.createElement("p");
      currentVersion.textContent = item.version_actual
        ? `Versión vigente: ${item.version_actual}`
        : "Sin versión vigente";
      details.append(course, period, currentVersion);

      const openButton = document.createElement("button");
      openButton.type = "button";
      openButton.className = "btn-udv btn-udv-primary";
      openButton.textContent = "Abrir";
      openButton.addEventListener("click", () => {
        void withLoading(async () => {
          await openProgram(item.id);
          showMessage("Programa cargado desde el servidor.");
        });
      });

      row.append(details, openButton);
      programList.append(row);
    });
    return uniquePrograms;
  }

  async function openProgramForUser(user) {
    authenticatedUser = user;
    configureRoles(authenticatedUser);
    loginPanel.hidden = true;
    appContainer.hidden = false;
    programLoaded = false;
    programFields.forEach((control) => { control.disabled = true; });
    updateResponsibleEditing();
    updateInterface();
    try {
      const programs = await loadProgramOptions();
      if (!programs.size) {
        showMessage("No hay programas disponibles para mostrar.");
        return;
      }

      const selectedId = programId && programs.has(programId) ? programId : null;
      if (selectedId) {
        await openProgram(selectedId);
        showMessage("Programa cargado desde el servidor.");
      } else {
        programId = null;
        showMessage(
          hasRequestedProgramId
            ? "El programa solicitado no está disponible. Selecciona otro."
            : "Selecciona un programa de la lista y pulsa Abrir.",
        );
      }
    } catch (error) {
      console.error(error);
      showMessage("No se pudo cargar el programa: " + error.message);
    }
  }

  async function openProgram(id) {
    programId = id;
    program = null;
    programVersions = [];
    programLoaded = false;
    programFields.forEach((control) => { control.disabled = true; });
    const url = new URL(window.location.href);
    url.searchParams.set("program_id", String(id));
    window.history.replaceState(null, "", url);
    await loadProgram(id);
  }

  /** Muestra un aviso junto al encabezado del programa. */
  function showMessage(message) {
    saveStatus.textContent = message;
  }

  function parseResponse(response) {
    return response.text().then((text) => {
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch {
        return { mensaje: text };
      }
    });
  }

  // Envía solicitudes a la API y muestra sus errores de forma entendible.
  async function request(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...options.headers,
    };
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
    }

    const response = await fetch(`${API}${path}`, {
      ...options,
      credentials: "same-origin",
      headers,
    });

    const result = await parseResponse(response);

    if (!response.ok) {
      throw new Error(
        result.error?.message ||
          result.error ||
          result.mensaje ||
          `Error del servidor: ${response.status}`,
      );
    }

    return result;
  }

  /** Envía datos JSON, por ejemplo, al guardar o cambiar el estado. */
  function sendJson(path, method, data) {
    return request(path, {
      method: method,
      body: JSON.stringify(data),
    });
  }

  // Leer y cargar lo que la persona escribe en el formulario.
  /** Lee un campo por su ID; si no existe, deja el valor vacío. */
  function getValue(id) {
    return document.getElementById(id)?.value ?? "";
  }

  /**
   * Pone un dato en el campo correspondiente. En las listas desplegables,
   * busca tanto por el valor como por el texto que se muestra.
   */
  function setValue(id, dataItem) {
    const element = document.getElementById(id);

    if (!element || dataItem === undefined || dataItem === null) return;

    if (element.tagName === "SELECT") {
      const option = [...element.options].find(
        (item) => item.value === String(dataItem) ||
          item.textContent.trim() === String(dataItem),
      );

      if (option) element.value = option.value;
      return;
    }

    element.value = dataItem;
  }

  /** Busca los datos de una sección; si aún no tiene, usa un objeto vacío. */
  function getSectionContent(versionData, name) {
    return versionData?.secciones?.[name]?.contenido || {};
  }

  /** Junta la información general y le pone los nombres que espera la API. */
  function captureGeneral() {
    return {
      codigo: getValue("course-code"),
      asignatura: getValue("course"),
      programa: getValue("program-name"),
      departamento: getValue("department"),
      facultad: getValue("faculty"),
      area_formacion: getValue("training-area"),
      pensum: getValue("curriculum"),
      ciclo: getValue("term"),
      anio: getValue("year"),
      nivel: getValue("level"),
      modalidad: getValue("modality"),
      creditos: getValue("credits"),
      horas: getValue("hours"),
      sede: getValue("campus"),
    };
  }

  /** Lee las filas de prerrequisitos y las deja listas para guardar. */
  function capturePrerequisites() {
    const rows = [...document.querySelectorAll("#prerequisites tbody tr")];

    return {
      asignaturas: rows.map((row) => {
        const controls = row.querySelectorAll("input");

        return {
          asignatura: controls[0]?.value || "",
          codigo: controls[1]?.value || "",
          orden: controls[2]?.value || "",
        };
      }),
    };
  }

  // Convierte los campos visibles del formulario al formato que espera la API.
  function captureSections() {
    return {
      responsables: {
        docente: instructor.value,
        docente_responsable_id: instructorId.value ? Number(instructorId.value) : null,
        decanatura: deanName.value,
        coordinador: coordinatorName.value,
      },

      general: captureGeneral(),

      prerrequisitos: capturePrerequisites(),

      descripcion: {
        texto: getValue("description-text"),
      },

      competencias: {
        general: getValue("general-competency"),
        especificas: getValue("specific-competencies"),
      },

      perfil: {
        codigo: getValue("profile-code"),
        contribucion: getValue("profile-contribution"),
      },

      metodologia: {
        texto: getValue("methodology-text"),
      },

      contenidos: {
        texto: getValue("contents-text"),
      },

      bibliografia: {
        texto: getValue("bibliography-text"),
      },

      evaluacion: {
        parcial: getValue("midterm-assessment"),
        final: getValue("final-assessment"),
        proyecto: getValue("project-assessment"),
      },
    };
  }

  // Rellena el formulario con la versión y usa el programa como respaldo inicial.
  function loadSections(versionData) {
    const general = getSectionContent(versionData, "general");
    const responsibleSection = getSectionContent(versionData, "responsables");
    const prerequisites = getSectionContent(versionData, "prerrequisitos");
    const description = getSectionContent(versionData, "descripcion");
    const competencies = getSectionContent(versionData, "competencias");
    const profile = getSectionContent(versionData, "perfil");
    const methodology = getSectionContent(versionData, "metodologia");
    const contentSection = getSectionContent(versionData, "contenidos");
    const bibliography = getSectionContent(versionData, "bibliografia");
    const evaluation = getSectionContent(versionData, "evaluacion");

    // Los datos del programa sirven como valores iniciales.
    setValue("course-code", program?.codigo || "PW-001");
    setValue("course", program?.asignatura || "Programación Web");
    setValue(
      "program-name",
      program?.programa_academico || "Ingeniería en Sistemas",
    );
    setValue("department", program?.departamento || "Tecnología");
    setValue("faculty", program?.facultad || "Ingeniería");
    setValue("training-area", program?.area_formacion || "");
    setValue("curriculum", program?.pensum || "");
    setValue("term", program?.ciclo_academico || "Segundo ciclo");
    setValue("year", program?.anio || 2026);
    setValue("level", program?.nivel_academico || "Licenciatura");
    setValue("modality", program?.modalidad || "Presencial");
    setValue("credits", program?.creditos ?? 4);
    setValue("hours", program?.horas_semanales ?? 64);
    setValue("campus", program?.sede || "Campus Central");

    // Los valores guardados en la sección tienen prioridad.
    Object.entries(general).forEach(([field, dataItem]) => {
      const fieldMappings = {
        programa: "programa",
        ciclo: "ciclo",
        anio: "anio",
        nivel: "nivel",
        horas: "horas",
      };

      setValue(fieldMappings[field] || field, dataItem);
    });

    setValue(
      "instructor",
      responsibleSection.docente || program?.profesor || "",
    );
    setValue("instructor-id", responsibleSection.docente_responsable_id ?? "");
    setValue("dean-name", responsibleSection.decanatura ?? "");
    setValue("coordinator-name", responsibleSection.coordinador ?? "");

    setValue("description-text", description.texto ?? "");
    setValue("general-competency", competencies.general ?? "");
    setValue("specific-competencies", competencies.especificas ?? "");
    setValue("profile-code", profile.codigo ?? "");
    setValue("profile-contribution", profile.contribucion ?? "");
    setValue("methodology-text", methodology.texto ?? "");
    setValue("contents-text", contentSection.texto ?? "");
    setValue("bibliography-text", bibliography.texto ?? "");
    setValue("midterm-assessment", evaluation.parcial ?? "");
    setValue("final-assessment", evaluation.final ?? "");
    setValue("project-assessment", evaluation.proyecto ?? "");

    if (Array.isArray(prerequisites.asignaturas)) {
      loadPrerequisiteRows(prerequisites.asignaturas);
    }
  }

  /** Reconstruye la tabla de prerrequisitos con los registros recibidos del servidor. */
  function loadPrerequisiteRows(rows) {
    const bodyElement = $("#prerequisites tbody");
    bodyElement.replaceChildren();

    rows.forEach((dataItem) => {
      const row = document.createElement("tr");

      [
        ["text", dataItem.asignatura],
        ["text", dataItem.codigo],
        ["number", dataItem.orden],
      ].forEach(([type, content]) => {
        const cell = document.createElement("td");
        const input = document.createElement("input");

        input.type = type;
        input.value = content ?? "";
        cell.append(input);
        row.append(cell);
      });

      bodyElement.append(row);
    });
  }

  // Cargar una versión, guardar cambios y actualizar el estado en pantalla.
  // Selecciona primero una versión editable; si no existe, muestra la vigente más reciente.
  async function loadProgram(id) {
    const result = await request(`/course-programs/${id}`);

    program = result.programa || result;
    programVersions = result.versiones || [];

    if (!program) {
      throw new Error("No se encontró el programa solicitado.");
    }

    const selectedVersion = selectVersionForRole(role.value);

    if (selectedVersion) {
      await loadVersion(selectedVersion.id);
    } else {
      throw new Error("El programa todavía no tiene versiones.");
    }
  }

  // Sincroniza la versión seleccionada y refresca tanto el formulario como sus permisos.
  async function loadVersion(id) {
    const data = await request(`/program-versions/${id}`);

    updateProgramVersion(data);
    currentVersion = data;
    versionId = data.id ?? id;
    currentVersionNumber = data.numero_version ?? 1;
    state = data.estado || "draft";
    programLoaded = true;

    loadSections(data);
    updateStatus();
  }

  // Persiste cada sección por separado para no reemplazar datos de otras secciones.
  async function saveOnServer() {
    if (!versionId) {
      throw new Error("No hay una versión seleccionada para guardar.");
    }

    const capturedSections = captureSections();

    for (const [name, content] of Object.entries(capturedSections)) {
      await sendJson(
        `/program-versions/${versionId}/sections/${name}`,
        "PUT",
        {
          contenido: content,
        },
      );
    }

    await loadVersion(versionId);
    showMessage("Borrador guardado en el servidor.");
  }

  // Envía una transición del flujo y recarga el estado confirmado por el servidor.
  async function executeAction(action, message, data = {}) {
    if (!versionId) {
      throw new Error("No hay una versión seleccionada.");
    }

    const result = await sendJson(`/program-versions/${versionId}/${action}`, "POST", {
      ...data,
    });

    if (result.programa) program = result.programa;
    if (result.version) updateProgramVersion(result.version);

    await loadVersion(versionId);
    showMessage(message);
  }

  // Cambiar de sección y responder a los botones del flujo.
  // Navegación entre secciones.
  sectionLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();

      const id = link.getAttribute("href").substring(1);

      sectionLinks.forEach((item) => item.classList.remove("active"));
      sections.forEach((item) => item.classList.remove("active"));

      link.classList.add("active");
      document.getElementById(id)?.classList.add("active");
    });
  });

  role.addEventListener("change", async () => {
    const coordinatorLabel = document.querySelector('label[for="coordinator-name"]');
    coordinatorLabel.textContent = role.value === "reviewer" ? "Revisor" : "Coordinación académica";
    const selectedVersion = selectVersionForRole(role.value);
    if (selectedVersion && selectedVersion.id !== versionId) {
      await withLoading(async () => {
        await loadVersion(selectedVersion.id);
        showMessage(getVersionStatusMessage());
      });
      return;
    }

    updateStatus();
    showMessage(getVersionStatusMessage());
  });

  // Guardar todas las secciones de la versión.
  saveButton.addEventListener("click", async () => {
    if (!canEditCurrentVersion()) {
      alert("Solo los gestores o el docente responsable pueden editar esta versión.");
      return;
    }

    if (!["draft", "returned"].includes(state)) {
      alert("El programa no se puede modificar en este estado.");
      return;
    }

    await withLoading(async () => {
      await saveOnServer();
    });
  });

  // Antes de enviar, guarda los campos actuales para que la revisión use lo más reciente.
  submitForReviewButton.addEventListener("click", async () => {
    if (
      !PROGRAM_AUTHORS.includes(role.value) ||
      (role.value === "teacher" && !isAssignedTeacher())
    ) {
      alert("Solo el docente responsable de la versión o coordinación pueden enviarla a revisión.");
      return;
    }

    if (!instructor.value.trim()) {
      alert("Escribe el nombre del docente antes de enviar a revisión.");
      return;
    }

    if (!["draft", "returned"].includes(state)) {
      alert("Solo puedes enviar un borrador o un programa devuelto.");
      return;
    }

    await withLoading(async () => {
      await saveOnServer();

      await executeAction("submit", "Programa enviado a revisión.");
    });
  });

  reviewButton.addEventListener("click", async () => {
    if (!PROGRAM_REVIEWERS.includes(role.value) || state !== "submitted") {
      alert("Solo revisión o coordinación pueden tomar una versión enviada.");
      return;
    }
    await withLoading(() => executeAction("review", "Revisión iniciada."));
  });

  returnButton.addEventListener("click", async () => {
    if (!PROGRAM_REVIEWERS.includes(role.value)) {
      alert("Solo revisión o coordinación pueden devolver el programa.");
      return;
    }

    if (state !== "under_review") {
      alert("El programa debe estar en revisión.");
      return;
    }

    const observation = prompt("Indica por qué se devuelve el programa.");
    if (observation === null) return;
    if (!observation.trim()) {
      alert("Debes indicar una observación para devolver el programa.");
      return;
    }

    await withLoading(() =>
      executeAction("return", "Programa devuelto al docente.", {
        observacion: observation.trim(),
      }),
    );
  });

  approveButton.addEventListener("click", async () => {
    if (!PROGRAM_REVIEWERS.includes(role.value)) {
      alert("Solo revisión o coordinación pueden aprobar el programa.");
      return;
    }

    if (state !== "under_review") {
      alert("El programa debe estar en revisión.");
      return;
    }

    await withLoading(() =>
      executeAction("approve", "Programa aprobado."),
    );
  });

  authorizeButton.addEventListener("click", async () => {
    if (role.value !== "authority") {
      alert("Solo un usuario con el rol G1 authority puede autorizar una versión.");
      return;
    }

    if (state !== "approved") {
      alert("El programa debe estar aprobado antes de autorizarlo.");
      return;
    }

    if (!deanName.value.trim()) {
      alert("Escribe el nombre de la Decanatura.");
      return;
    }

    await withLoading(() =>
      executeAction("authorize", "Versión autorizada."),
    );
  });

  createVersionButton.addEventListener("click", async () => {
    if (!PROGRAM_MANAGERS.includes(role.value)) {
      alert("Se requiere el permiso G1 programs.manage para crear una versión.");
      return;
    }
    if (invalidAssignmentOrigin) {
      showMessage("El identificador de asignación de origen en la URL no es válido.");
      return;
    }

    if (state !== "authorized") {
      alert("Debes partir de una versión autorizada.");
      return;
    }

    await withLoading(async () => {
      const newVersion = await sendJson(
        `/course-programs/${programId}/versions`,
        "POST",
        {
          clonar: true,
          periodo_id: currentVersion.periodo_id,
          ...(assignmentOriginParam !== null
            ? { tarea_destinatario_origen_id: assignmentOriginId }
            : {}),
        },
      );

      if (!newVersion.id) {
        throw new Error("El servidor no devolvió el ID de la nueva versión.");
      }

      updateProgramVersion(newVersion);
      await loadVersion(newVersion.id);
      showMessage(`Se creó la versión ${currentVersionNumber} como borrador.`);
    });
  });

  // Cancelar: volver a cargar la versión desde el servidor.
  cancelButton.addEventListener("click", async () => {
    if (!confirm("¿Deseas descartar los cambios que no has guardado?")) return;

    await withLoading(async () => {
      await loadVersion(versionId);
      showMessage("Se cargaron nuevamente los últimos datos guardados.");
    });
  });

  // Mientras se guarda, evitamos que se inicien otras acciones al mismo tiempo.
  async function withLoading(callback) {
    if (isSaving) return;

    isSaving = true;
    updateInterface();
    showMessage("Procesando...");

    try {
      await callback();
    } catch (error) {
      console.error(error);
      showMessage("Error: " + error.message);
      alert("No se pudo completar la acción.\n\n" + error.message);
    } finally {
      isSaving = false;
      updateStatus();
    }
  }

  /** Actualiza el estado, el número de versión y los controles disponibles. */
  function updateStatus() {
    programStatus.className = "udv-badge";
    programStatus.textContent = statusNames[state] || state.toUpperCase();

    const classes = {
      draft: "badge-draft",
      submitted: "badge-under-review",
      under_review: "badge-under-review",
      returned: "badge-returned",
      approved: "badge-approved",
      authorized: "badge-authorized",
      superseded: "badge-superseded",
    };

    programStatus.classList.add(classes[state] || "badge-draft");
    versionNumberLabel.textContent = "Versión " + currentVersionNumber;

    updateInterface();
    updateResponsibleEditing();
  }

  // Cada persona puede editar solo cuando le toca hacerlo.
  function updateResponsibleEditing() {
    const canEdit =
      programLoaded &&
      canEditCurrentVersion() &&
      ["draft", "returned"].includes(state);

    programFields.forEach((control) => {
      if (control instanceof HTMLSelectElement) {
        control.disabled = !canEdit;
      } else if (
        control instanceof HTMLInputElement ||
        control instanceof HTMLTextAreaElement
      ) {
        control.readOnly = !canEdit;
      }
    });

    instructor.readOnly = true;
    instructorId.disabled = !canEdit || !PROGRAM_MANAGERS.includes(role.value);

    deanName.readOnly = !(role.value === "authority" && state === "approved");

    coordinatorName.readOnly = !(
      ["coordinator", "reviewer"].includes(role.value) &&
      ["under_review", "authorized"].includes(state)
    );
  }

  // Mostramos los botones que corresponden al rol y al estado actuales.
  function updateInterface() {
    const buttons = [
      saveButton,
      createVersionButton,
      submitForReviewButton,
      reviewButton,
      returnButton,
      approveButton,
      authorizeButton,
      pdfPreviewButton,
      cancelButton,
      printPdfButton,
      closePreviewButton,
    ];

    buttons.forEach((button) => {
      button.hidden = true;
      button.disabled = isSaving;
    });

    if (!programLoaded) return;

    if (document.body.classList.contains("pdf-preview-mode")) {
      printPdfButton.hidden = false;
      closePreviewButton.hidden = false;
      return;
    }

    pdfPreviewButton.hidden = !["authorized", "superseded"].includes(state);

    if (canEditCurrentVersion() && ["draft", "returned"].includes(state)) {
      saveButton.hidden = false;
      cancelButton.hidden = false;
    }

    if (
      PROGRAM_AUTHORS.includes(role.value) &&
      (role.value !== "teacher" || isAssignedTeacher()) &&
      ["draft", "returned"].includes(state)
    ) {
      submitForReviewButton.hidden = false;
    }

    if (role.value === "authority" && state === "approved") {
      authorizeButton.hidden = false;
    }

    if (PROGRAM_REVIEWERS.includes(role.value)) {
      if (state === "submitted") {
        reviewButton.hidden = false;
      }

      if (state === "under_review") {
        returnButton.hidden = false;
        approveButton.hidden = false;
      }
    }

    if (PROGRAM_MANAGERS.includes(role.value) && state === "authorized") {
      const latestVersion = getLatestVersion();
      const canCreateVersion =
        latestVersion?.id === currentVersion?.id &&
        latestVersion.estado === "authorized" &&
        program?.version_actual === currentVersion?.numero_version;

      if (canCreateVersion) {
        createVersionButton.hidden = false;
      }
    }

    [pdfPreviewButton, printPdfButton, closePreviewButton].forEach((button) => {
      button.disabled = isSaving;
    });
  }

  // Armar una versión del programa lista para imprimir o guardar como PDF.
  /** Crea una pieza del documento y le pone el texto y estilo que necesite. */
  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  /** Lee lo que se eligió en una lista o se escribió en otro campo. */
  function getControlText(control) {
    if (control instanceof HTMLSelectElement) {
      return control.selectedOptions[0]?.textContent.trim() || "";
    }
    return control.value.trim();
  }

  /** Pasa un campo del formulario al documento que se va a imprimir. */
  function addPdfField(destination, field) {
    const control = field.querySelector("input, textarea, select");
    if (!control) return;

    const tagName = field.querySelector("label")?.textContent
      .replace(/\s+/g, " ")
      .trim();
    const dataItem = getControlText(control);
    const container = createElement("div", "pdf-field");
    if (field.classList.contains("full")) {
      container.classList.add("pdf-field-full");
    }

    container.append(
      createElement("span", "pdf-label", tagName || "Dato"),
      createElement(
        "span",
        dataItem ? "pdf-value" : "pdf-value pdf-value-empty",
        dataItem || "No especificado",
      ),
    );
    destination.append(container);
  }

  /** Copia una tabla y cambia sus campos editables por texto para imprimir. */
  function addPdfTable(destination, originalTable) {
    const container = createElement("div", "pdf-table-container");
    const table = originalTable.cloneNode(true);
    table.className = "pdf-table";
    table.removeAttribute("id");
    table.querySelectorAll("[id]").forEach((element) =>
      element.removeAttribute("id"),
    );

    table.querySelectorAll("input, textarea, select").forEach((control) => {
      control.replaceWith(
        createElement("span", "pdf-value", getControlText(control) || "—"),
      );
    });

    container.append(table);
    destination.append(container);
  }

  /** Arma el documento de impresión con la información que aparece en pantalla. */
  function buildPdfDocument() {
    pdfDocument.replaceChildren();

    const headerElement = createElement("header", "pdf-header");
    const logo = createElement("img", "pdf-logo");
    logo.src = "assets/udv-logo.jpg";
    logo.alt = "Escudo de la Universidad Da Vinci de Guatemala";

    const institution = createElement("div", "pdf-institution");
    institution.append(
      createElement("p", "pdf-overline", "Universidad"),
      createElement("h2", "", "Da Vinci de Guatemala"),
      createElement("p", "pdf-faculty", getValue("faculty") || "Facultad académica"),
    );

    const metadata = createElement("div", "pdf-metadata");
    [
      ["Versión", String(currentVersionNumber)],
      ["Emisión", new Date().toLocaleDateString("es-GT")],
      ["Estado", programStatus.textContent.trim()],
    ].forEach(([tagName, dataItem]) => {
      const metadataItem = createElement("div", "pdf-metadata-item");
      metadataItem.append(
        createElement("span", "pdf-metadata-label", tagName),
        createElement("strong", "pdf-metadata-value", dataItem),
      );
      metadata.append(metadataItem);
    });

    headerElement.append(logo, institution, metadata);

    const title = createElement("div", "pdf-title");
    title.append(
      createElement("p", "pdf-title-label", "Documento académico"),
      createElement("h1", "", "Programa de curso"),
      createElement("p", "pdf-course", getValue("course")),
    );
    pdfDocument.append(headerElement, title);

    sections.forEach((section, index) => {
      const sectionTitle = section.querySelector("h3")?.textContent.trim();
      if (!sectionTitle) return;

      const pdfSection = createElement("section", "pdf-section");
      pdfSection.dataset.section = section.id;

      const sectionHeader = createElement("div", "pdf-section-header");
      sectionHeader.append(
        createElement("span", "pdf-section-number", String(index + 1).padStart(2, "0")),
        createElement("h2", "", sectionTitle),
      );
      pdfSection.append(sectionHeader);

      Array.from(section.children).forEach((element) => {
        if (element.matches("h3")) return;
        if (element.matches("p")) {
          pdfSection.append(
            createElement("p", "pdf-description", element.textContent.trim()),
          );
          return;
        }
        if (element.matches(".form")) {
          const fields = createElement("div", "pdf-fields");
          element.querySelectorAll(".field").forEach((field) =>
            addPdfField(fields, field),
          );
          if (fields.childElementCount) pdfSection.append(fields);
          return;
        }
        if (element.matches(".field")) {
          const fields = createElement("div", "pdf-fields");
          addPdfField(fields, element);
          if (fields.childElementCount) pdfSection.append(fields);
          return;
        }
        if (element.matches(".table-container")) {
          const table = element.querySelector("table");
          if (table) addPdfTable(pdfSection, table);
        }
      });

      pdfDocument.append(pdfSection);
    });

    const authorization = createElement("section", "pdf-section");
    authorization.classList.add("pdf-authorization");
    const authorizationHeader = createElement("div", "pdf-section-header");
    authorizationHeader.append(
      createElement(
        "span",
        "pdf-section-number",
        String(sections.length + 1).padStart(2, "0"),
      ),
      createElement("h2", "", "Firmas de autorización"),
    );
    authorization.append(authorizationHeader);

    const date = createElement(
      "p",
      "pdf-authorization-date",
      `Facultad de ${getValue("faculty") || "—"} · ${new Date().toLocaleDateString("es-GT")}`,
    );
    authorization.append(date);

    const signatures = createElement("div", "pdf-signatures");
    [
      ["Elaborado por", instructor.value.trim()],
      ["Decanatura", deanName.value.trim()],
      ["Coordinación académica", coordinatorName.value.trim()],
    ].forEach(([roleTitle, name]) => {
      const signature = createElement("div", "pdf-signature");
      signature.append(
        createElement("div", "pdf-signature-line"),
        createElement("span", "pdf-signature-name", name || " "),
        createElement("span", "pdf-signature-role", roleTitle),
      );
      signatures.append(signature);
    });

    authorization.append(signatures);
    pdfDocument.append(authorization);
  }

  // Descargar el PDF autorizado o abrir la vista para imprimir.
  pdfPreviewButton.addEventListener("click", async () => {
    if (!["authorized", "superseded"].includes(state)) {
      showMessage("El PDF solo está disponible para versiones autorizadas.");
      return;
    }

    await withLoading(async () => {
      const response = await fetch(`${API}/program-versions/${versionId}/pdf`, {
        credentials: "same-origin",
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      });
      if (!response.ok) {
        let error = {};
        try {
          error = await response.json();
        } catch {
          error = {};
        }
        throw new Error(
          error.error?.message || `No se pudo generar el PDF: ${response.status}`,
        );
      }

      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `programa-${program.id}-version-${currentVersionNumber}.pdf`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      showMessage("PDF autorizado descargado.");
    });
  });

  // Abre el diálogo de impresión con el formato que aparece en la vista previa.
  printPdfButton.addEventListener("click", () => window.print());

  closePreviewButton.addEventListener("click", () => {
    document.body.classList.remove("pdf-preview-mode");
    pdfDocument.hidden = true;
    updateInterface();
    showMessage("Vista previa cerrada.");
  });

  async function restoreSession() {
    if (!accessToken) {
      loginStatus.textContent = "Primero inicia sesión desde el portal UDV.";
      return;
    }

    try {
      const user = await request("/me");
      await openProgramForUser(user);
    } catch (error) {
      console.error(error);
      accessToken = null;
      sessionStorage.removeItem(TOKEN_KEY);
      loginStatus.textContent = `No se pudo validar la sesión compartida: ${error.message}`;
    }
  }

  await restoreSession();
});
