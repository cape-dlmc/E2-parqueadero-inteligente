/* =========================================================================
   Parqueadero Montería · Comportamiento de la interfaz
   Todo el contenido dinámico pasa por escapeHtml() antes de mostrarse.
   ========================================================================= */

const estado = {
  zonas: [],
  sedes: [],
  zonaSeleccionada: null,
  ultimaIdentificacion: localStorage.getItem("usuario_identificacion") || "",
  formularioListo: false,
  misReservas: [],
  todasReservasActivas: [],
  filtroMapa: "todos",
  subtabActual: "usuario",
  reservaPorAmpliar: null,
  recordatorioAvisado: {},
  reservaDemo: null,
};

const VISTAS = {
  "inicio": { titulo: "Inicio", sub: "Resumen de la sede Montería y de sus zonas" },
  "mapa": { titulo: "Mapa de zonas", sub: "Revisa cada zona, reservas activas y restricciones antes de reservar" },
  "reservar": { titulo: "Reservar", sub: "Elige zona, vehículo y horario. La reserva se guarda y genera tu comprobante." },
  "mis-reservas": { titulo: "Mis reservas", sub: "Consulta tus reservas, amplía tu tiempo o revisa las zonas ocupadas en vivo" },
  "calidad": { titulo: "Datos y pruebas", sub: "Cómo se cargaron los datos y resultado de las pruebas" },
};

// ---------------------------------------------------------------- utilidades
function escapeHtml(valor) {
  return String(valor ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function numero(n) {
  return (n === null || n === undefined || Number.isNaN(Number(n))) ? "—" : Number(n).toLocaleString("es-CO");
}

function horaCorta(texto) {
  // "2036-06-10 08:00:00" -> "10 jun 2036 · 08:00"
  if (!texto) return "—";
  const [fecha, hora] = texto.split(" ");
  const [anio, mes, dia] = fecha.split("-");
  const meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${Number(dia)} ${meses[Number(mes) - 1]} ${anio} · ${hora.slice(0, 5)}`;
}

function etiquetaZona(z) {
  const num = (z.nombre.match(/(\d+)$/) || ["", ""])[1];
  return `${z.sector.charAt(0)}${num}`;
}

async function api(ruta, opciones = {}) {
  const resp = await fetch(ruta, {
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    ...opciones,
  });
  let datos = null;
  try { datos = await resp.json(); } catch (_) { /* respuesta sin cuerpo JSON */ }
  if (!resp.ok) {
    const e = datos && datos.error ? datos.error : { codigo: `HTTP_${resp.status}`, mensaje: "El servidor respondió con un error." };
    const err = new Error(e.mensaje);
    err.codigo = e.codigo;
    err.campo = e.campo;
    err.status = resp.status;
    throw err;
  }
  return datos;
}

function alertaError(titulo, err) {
  const codigo = err.codigo ? `<div class="alerta-codigo">${escapeHtml(err.codigo)}</div>` : "";
  return `<div class="alerta-error"><div class="alerta-titulo">${escapeHtml(titulo)}</div>${escapeHtml(err.message)}${codigo}</div>`;
}

function mostrarGlobal(texto, tipo = "error") {
  const caja = document.getElementById("mensaje-global");
  caja.textContent = texto;
  caja.className = `alert ${tipo}`;
  clearTimeout(mostrarGlobal._t);
  mostrarGlobal._t = setTimeout(() => caja.classList.add("hidden"), 5000);
}

// ---------------------------------------------------------------- sonido y notificaciones
function sonarAviso() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    if (ctx.state === "suspended") ctx.resume();
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gain = ctx.createGain();

    osc1.type = "sine";
    osc1.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(880.00, ctx.currentTime + 0.12); // A5

    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.55);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(ctx.destination);

    osc1.start();
    osc1.stop(ctx.currentTime + 0.14);
    osc2.start(ctx.currentTime + 0.12);
    osc2.stop(ctx.currentTime + 0.55);
  } catch (_) {}
}

function pedirPermisoNotificaciones() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

function lanzarNotificacion(titulo, cuerpo) {
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      new Notification(titulo, { body: cuerpo });
    } catch (_) {}
  }
}

function mostrarToast(titulo, mensaje, tipo = "ok") {
  const cont = document.getElementById("toast-container");
  if (!cont) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${tipo}`;
  const icono = tipo === "ok" ? "✓" : (tipo === "warn" ? "⚠️" : "✕");
  toast.innerHTML = `
    <span class="toast-icono">${icono}</span>
    <div class="toast-content">
      <div class="toast-titulo">${escapeHtml(titulo)}</div>
      <div class="toast-sub">${escapeHtml(mensaje)}</div>
    </div>`;
  cont.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(30px)";
    setTimeout(() => toast.remove(), 250);
  }, 4500);
}

// ---------------------------------------------------------------- generador de QR SVG
function generarSvgQR(texto) {
  // Genera un código QR gráfico SVG estructurado y estéticamente idéntico a un QR estándar
  let hash = 0;
  for (let i = 0; i < texto.length; i++) {
    hash = ((hash << 5) - hash) + texto.charCodeAt(i);
    hash |= 0;
  }
  const size = 21;
  const matriz = Array.from({ length: size }, () => Array(size).fill(0));

  function marcarPatron(r, c) {
    for (let i = 0; i < 7; i++) {
      for (let j = 0; j < 7; j++) {
        if (i === 0 || i === 6 || j === 0 || j === 6 || (i >= 2 && i <= 4 && j >= 2 && j <= 4)) {
          matriz[r + i][c + j] = 1;
        }
      }
    }
  }
  marcarPatron(0, 0);
  marcarPatron(0, size - 7);
  marcarPatron(size - 7, 0);

  // Líneas de sincronía
  for (let i = 8; i < size - 8; i++) {
    if (i % 2 === 0) {
      matriz[6][i] = 1;
      matriz[i][6] = 1;
    }
  }

  // Módulos dinámicos derivados del hash del texto
  let seed = Math.abs(hash);
  for (let i = 0; i < size; i++) {
    for (let j = 0; j < size; j++) {
      if ((i < 8 && j < 8) || (i < 8 && j >= size - 8) || (i >= size - 8 && j < 8) || i === 6 || j === 6) {
        continue;
      }
      seed = (seed * 9301 + 49297) % 233280;
      if (seed % 3 === 0) matriz[i][j] = 1;
    }
  }

  let rects = "";
  for (let i = 0; i < size; i++) {
    for (let j = 0; j < size; j++) {
      if (matriz[i][j]) {
        rects += `<rect x="${j}" y="${i}" width="1" height="1" fill="#0f172a" />`;
      }
    }
  }
  return `<svg viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges">${rects}</svg>`;
}

// ---------------------------------------------------------------- navegación
function irA(vista) {
  if (!VISTAS[vista]) return;
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.view === vista));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === `v-${vista}`));
  document.getElementById("titulo-vista").textContent = VISTAS[vista].titulo;
  document.getElementById("subtitulo-vista").textContent = VISTAS[vista].sub;
  document.getElementById("mensaje-global").classList.add("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });

  if (vista === "inicio") cargarInicio();
  if (vista === "mapa") { cargarZonas().then(dibujarMapa); }
  if (vista === "reservar") prepararFormulario();
  if (vista === "mis-reservas") inicializarMisReservas();
  if (vista === "calidad") cargarPipeline();
  if (location.hash !== `#${vista}`) history.replaceState(null, "", `#${vista}`);
}

// ---------------------------------------------------------------- datos base
async function cargarZonas(forzar = false) {
  if (estado.zonas.length && !forzar) return estado.zonas;
  estado.zonas = await api("/zonas");
  return estado.zonas;
}

function zonaPorCodigo(codigo) {
  return estado.zonas.find(z => z.codigo_zona === codigo) || null;
}

function miReservaEnZona(codigo) {
  const activas = estado.misReservas.filter(r => r.estado === "activa");
  if (estado.reservaDemo && estado.reservaDemo.codigo_zona === codigo) return estado.reservaDemo;
  return activas.find(r => r.codigo_zona === codigo) || null;
}

// ---------------------------------------------------------------- inicio
async function cargarInicio() {
  try {
    const [zonas, pipe] = await Promise.all([cargarZonas(true), api("/api/pipeline").catch(() => null)]);
    const reservables = zonas.filter(z => z.reservable).length;
    const capacidad = zonas.reduce((a, z) => a + z.capacidad, 0);
    document.getElementById("kpi-zonas").textContent = numero(zonas.length);
    document.getElementById("kpi-reservables").textContent = numero(reservables);
    document.getElementById("kpi-no-reservables").textContent =
      zonas.length - reservables ? `${zonas.length - reservables} sin reservas` : "Todas admiten reservas";
    document.getElementById("kpi-capacidad").textContent = numero(capacidad);
    document.getElementById("kpi-lecturas").textContent = pipe ? numero(pipe.lecturas_en_bd) : "—";

    const porSector = {};
    zonas.forEach(z => {
      const s = porSector[z.sector] ||= { zonas: 0, reservables: 0, capacidad: 0 };
      s.zonas += 1; s.reservables += z.reservable ? 1 : 0; s.capacidad += z.capacidad;
    });
    document.getElementById("tabla-sectores").innerHTML = Object.entries(porSector).map(([sector, s]) => `
      <tr>
        <td><b>${escapeHtml(sector)}</b></td>
        <td class="num">${numero(s.zonas)}</td>
        <td class="num">${numero(s.reservables)}</td>
        <td class="num">${numero(s.capacidad)}</td>
      </tr>`).join("");
  } catch (err) {
    mostrarGlobal("No se pudieron cargar los datos de la sede. ¿Está corriendo el servidor?");
  }
}

// ---------------------------------------------------------------- restricciones
function htmlRestricciones(z, tipoElegido = null) {
  const tipos = z.tipos_permitidos.map(t => t === "carro" ? "Carros" : "Motos").join(" y ");
  const chips = [];
  chips.push(z.reservable
    ? `<span class="chip chip-ok">✓ Admite reservas</span>`
    : `<span class="chip chip-bad">✕ No admite reservas</span>`);

  if (z.reservas_activas > 0) {
    chips.push(`<span class="chip chip-warn">⚠️ ${numero(z.reservas_activas)} cupo(s) reservados</span>`);
  } else if (z.reservable) {
    chips.push(`<span class="chip chip-info">Cupos libres para reservar</span>`);
  }

  const miR = miReservaEnZona(z.codigo_zona);
  if (miR) {
    chips.push(`<span class="chip chip-ok" style="border-color:var(--acc);color:var(--acc);">★ Tu reserva activa nº ${miR.id}</span>`);
  }

  if (tipoElegido) {
    chips.push(z.tipos_permitidos.includes(tipoElegido)
      ? `<span class="chip chip-info">Tu ${tipoElegido} sí entra</span>`
      : `<span class="chip chip-warn">Tu ${tipoElegido} no entra aquí</span>`);
  }
  const nota = z.nota ? `<div class="nota-zona">${escapeHtml(z.nota)}</div>` : "";
  return `
    <h3>${escapeHtml(z.nombre)}</h3>
    <div class="sector">${escapeHtml(z.sector)} · ${numero(z.capacidad)} cupos totales · código ${escapeHtml(z.codigo_zona)}</div>
    <div class="chips">${chips.join("")}</div>
    <ul class="reglas">
      <li><span>Cupos libres en vivo</span><span style="color:var(--ok);font-size:15px;">${numero(z.cupos_disponibles ?? z.capacidad)} / ${numero(z.capacidad)}</span></li>
      <li><span>Reservas activas en esta zona</span><span style="color:${z.reservas_activas ? 'var(--warn)' : 'var(--mut)'}">${numero(z.reservas_activas || 0)}</span></li>
      <li><span>Vehículos permitidos</span><span>${escapeHtml(tipos)}</span></li>
      <li><span>Horario de reserva</span><span>${escapeHtml(z.horario)}</span></li>
      <li><span>Duración máxima</span><span>${numero(z.max_horas_reserva)} h</span></li>
      <li><span>Reservas activas por persona</span><span>${numero(z.max_reservas_activas_usuario)}</span></li>
    </ul>
    ${nota}`;
}

// ---------------------------------------------------------------- mapa interactivo
function dibujarMapa() {
  const svg = document.getElementById("mapa");
  const zonas = estado.zonas;
  if (!zonas.length) {
    cargarZonas().then(dibujarMapa).catch(() => mostrarGlobal("No se pudo cargar el mapa."));
    return;
  }

  // Filtrado
  const zonasFiltradas = zonas.filter(z => {
    if (estado.filtroMapa === "con-reservas") return (z.reservas_activas > 0);
    if (estado.filtroMapa === "mis-reservas") return Boolean(miReservaEnZona(z.codigo_zona));
    return true;
  });

  const sectores = [...new Map(zonas.map(z => [z.sector, z.y])).entries()];
  const sectoresSvg = sectores.map(([s, y]) =>
    `<text class="sector-txt" x="8" y="${y - 2}">${escapeHtml(s.toUpperCase())}</text>`).join("");

  const rects = zonas.map(z => {
    const visible = zonasFiltradas.includes(z);
    const opacidad = visible ? "1" : "0.2";
    const miR = miReservaEnZona(z.codigo_zona);

    let clase = z.reservable ? "ok" : "no";
    if (z.reservas_activas > 0) clase += " con-reservas";
    if (miR) clase += " mi-reserva";
    const sel = estado.zonaSeleccionada === z.codigo_zona ? " sel" : "";

    const badgeReserva = (z.reservas_activas > 0)
      ? `<text class="zona-res-badge" x="${z.x + 9.5}" y="${z.y + 3.2}">R:${z.reservas_activas}</text>`
      : "";

    const starMia = miR
      ? `<text class="zona-star" x="${z.x + 2.5}" y="${z.y + 3.2}">★</text>`
      : "";

    return `
      <g data-codigo="${escapeHtml(z.codigo_zona)}" style="opacity:${opacidad};" tabindex="0" role="button" aria-label="${escapeHtml(z.nombre)}">
        <rect class="zona-rect ${clase}${sel}" x="${z.x}" y="${z.y}" width="12" height="12" rx="1.6"></rect>
        <text class="zona-txt" x="${z.x + 6}" y="${z.y + 6.2}">${escapeHtml(etiquetaZona(z))}</text>
        <text class="zona-sub" x="${z.x + 6}" y="${z.y + 9.6}">${numero(z.cupos_disponibles ?? z.capacidad)}</text>
        ${badgeReserva}
        ${starMia}
      </g>`;
  }).join("");

  svg.innerHTML = `${sectoresSvg}${rects}`;
  svg.querySelectorAll("g[data-codigo]").forEach(g => {
    const abrir = () => seleccionarZona(g.dataset.codigo);
    g.addEventListener("click", abrir);
    g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); } });
  });

  if (estado.zonaSeleccionada) pintarDetalle(zonaPorCodigo(estado.zonaSeleccionada));
}

function seleccionarZona(codigo) {
  estado.zonaSeleccionada = codigo;
  dibujarMapa();
}

function pintarDetalle(z) {
  const caja = document.getElementById("detalle-zona");
  if (!z) {
    caja.innerHTML = `<p class="muted">Selecciona una zona en el esquema para ver sus restricciones y disponibilidad.</p>`;
    return;
  }
  const miR = miReservaEnZona(z.codigo_zona);
  const bloqueMia = miR ? `
    <div class="alerta-ok" style="margin-top:14px;border-color:var(--acc);">
      <div class="alerta-titulo">★ Tienes una reserva activa aquí</div>
      Reserva nº ${miR.id} · Fin: ${escapeHtml(miR.fin.slice(11, 16))}
      <div class="actions" style="margin-top:8px;">
        <button class="btn btn-sm btn-primary" id="btn-detalle-ver-ticket">Ver ticket / QR</button>
        <button class="btn btn-sm" id="btn-detalle-ampliar">⏱ Ampliar tiempo</button>
      </div>
    </div>` : "";

  caja.innerHTML = `
    ${htmlRestricciones(z)}
    ${bloqueMia}
    <div class="actions">
      <button class="btn btn-primary" id="btn-reservar-aqui" ${z.reservable ? "" : "disabled"}>
        ${z.reservable ? "Reservar en esta zona" : "Zona no reservable"}
      </button>
    </div>`;

  const btn = document.getElementById("btn-reservar-aqui");
  if (btn && z.reservable) btn.addEventListener("click", () => {
    estado.zonaSeleccionada = z.codigo_zona;
    irA("reservar");
    document.querySelector('#form-reserva [name="codigo_zona"]').value = z.codigo_zona;
    actualizarRestricciones();
  });

  if (miR) {
    document.getElementById("btn-detalle-ver-ticket")?.addEventListener("click", () => mostrarTicket(miR));
    document.getElementById("btn-detalle-ampliar")?.addEventListener("click", () => abrirModalAmpliar(miR.id));
  }
}

// ---------------------------------------------------------------- formulario de reserva
async function prepararFormulario() {
  if (estado.formularioListo) { actualizarRestricciones(); return; }
  try {
    const zonas = await cargarZonas();
    const select = document.getElementById("select-zona");
    const grupos = {};
    zonas.forEach(z => { (grupos[z.sector] ||= []).push(z); });
    select.innerHTML = Object.entries(grupos).map(([sector, lista]) => `
      <optgroup label="${escapeHtml(sector)}">
        ${lista.map(z => `<option value="${escapeHtml(z.codigo_zona)}" ${z.reservable ? "" : "disabled"}>
          ${escapeHtml(z.nombre)} · ${escapeHtml(z.tipos_permitidos.join(" y "))}${z.reservable ? (z.reservas_activas ? ` (${z.reservas_activas} res.)` : "") : " (no reservable)"}
        </option>`).join("")}
      </optgroup>`).join("");

    if (estado.ultimaIdentificacion) {
      document.querySelector('#form-reserva [name="identificacion"]').value = estado.ultimaIdentificacion;
    }

    const hoy = new Date(Date.now() - 5 * 3600 * 1000);   // hora de Montería (UTC-5)
    const fecha = new Date(hoy.getTime() + 86400000);     // mañana
    document.querySelector('#form-reserva [name="fecha"]').min = fecha.toISOString().slice(0, 10);
    document.querySelector('#form-reserva [name="fecha"]').value = fecha.toISOString().slice(0, 10);
    document.querySelector('#form-reserva [name="inicio"]').value = "08:00";
    document.querySelector('#form-reserva [name="fin"]').value = "10:00";
    estado.formularioListo = true;
    if (estado.zonaSeleccionada) select.value = estado.zonaSeleccionada;
    actualizarRestricciones();
  } catch (err) {
    mostrarGlobal("No se pudo cargar el formulario. ¿Está corriendo el servidor?");
  }
}

function valoresFormulario() {
  const f = document.getElementById("form-reserva");
  return Object.fromEntries(new FormData(f).entries());
}

function actualizarRestricciones() {
  const v = valoresFormulario();
  const z = zonaPorCodigo(v.codigo_zona);
  const panel = document.getElementById("contenido-restricciones");
  const boton = document.getElementById("btn-reservar");
  if (!z) {
    panel.innerHTML = `<p class="muted">Elige una zona para ver sus condiciones.</p>`;
    boton.disabled = false;
    return;
  }
  panel.innerHTML = htmlRestricciones(z, v.tipo_vehiculo);
  boton.disabled = !z.reservable || !z.tipos_permitidos.includes(v.tipo_vehiculo);
}

function fechaCompleta(fecha, hora) {
  return `${fecha} ${hora}:00`;
}

async function consultarCupos() {
  const v = valoresFormulario();
  const salida = document.getElementById("resultado-disponibilidad");
  salida.classList.remove("hidden");
  if (!v.codigo_zona || !v.fecha || !v.inicio || !v.fin) {
    salida.innerHTML = `<div class="alerta-info">Completa zona, fecha y horas para consultar los cupos.</div>`;
    return;
  }
  try {
    const q = new URLSearchParams({
      inicio: fechaCompleta(v.fecha, v.inicio),
      fin: fechaCompleta(v.fecha, v.fin),
    });
    const d = await api(`/zonas/${encodeURIComponent(v.codigo_zona)}/disponibilidad?${q}`);
    const tipo = d.cupos_para_reservar > 0 ? "alerta-ok" : "alerta-error";
    salida.innerHTML = `
      <div class="${tipo}">
        <div class="alerta-titulo">${numero(d.cupos_para_reservar)} cupos disponibles de ${numero(d.capacidad)}</div>
        ${numero(d.reservas_que_se_cruzan)} reserva(s) activa(s) se cruzan con ese horario.
        ${d.reservable ? "" : "<br>Esta zona no admite reservas."}
      </div>`;
  } catch (err) {
    salida.innerHTML = alertaError("No se pudo consultar", err);
  }
}

async function enviarReserva(evento) {
  evento.preventDefault();
  if (evento.submitter && evento.submitter.id !== "btn-reservar") return;
  const v = valoresFormulario();
  const salida = document.getElementById("resultado-reserva");
  const boton = document.getElementById("btn-reservar");
  salida.classList.add("hidden");

  if (v.fin <= v.inicio) {
    salida.classList.remove("hidden");
    salida.innerHTML = `<div class="alerta-error"><div class="alerta-titulo">Revisa el horario</div>La hora de fin debe ser posterior a la de inicio.</div>`;
    return;
  }

  const cuerpo = {
    identificacion: v.identificacion.trim(),
    nombre: v.nombre.trim(),
    tipo_vehiculo: v.tipo_vehiculo,
    placa: (v.placa || "").trim(),
    codigo_zona: v.codigo_zona,
    inicio: fechaCompleta(v.fecha, v.inicio),
    fin: fechaCompleta(v.fecha, v.fin),
  };

  boton.disabled = true;
  boton.textContent = "Guardando…";
  try {
    const r = await api("/reservas", { method: "POST", body: JSON.stringify(cuerpo) });
    estado.ultimaIdentificacion = r.identificacion;
    localStorage.setItem("usuario_identificacion", r.identificacion);

    // Actualizar datos de zonas para reflejar en el mapa inmediatamente
    await cargarZonas(true);

    sonarAviso();
    mostrarToast("¡Reserva confirmada!", `Reserva nº ${r.id} en ${r.zona_nombre}`, "ok");
    lanzarNotificacion("Reserva Confirmada · Parqueadero", `Reserva nº ${r.id} guardada para las ${r.inicio.slice(11, 16)} a ${r.fin.slice(11, 16)}`);

    salida.classList.remove("hidden");
    salida.innerHTML = `
      <div class="alerta-ok">
        <div class="alerta-titulo">✓ Reserva guardada exitosamente · nº ${r.id}</div>
        ${escapeHtml(r.zona_nombre)} · ${escapeHtml(horaCorta(r.inicio))} a ${escapeHtml(r.fin.slice(11, 16))}
        <div class="alerta-codigo">Vehículo: ${escapeHtml(r.tipo_vehiculo)} · Estado: ${escapeHtml(r.estado)}</div>
        <div class="actions">
          <button type="button" class="btn btn-sm btn-primary" id="btn-ver-comprobante-nuevo">🎫 Ver comprobante / QR</button>
          <button type="button" class="btn btn-sm" id="btn-ver-mis-reservas-nuevo">Ir a Mis reservas</button>
        </div>
      </div>`;

    document.getElementById("btn-ver-comprobante-nuevo")?.addEventListener("click", () => mostrarTicket(r));
    document.getElementById("btn-ver-mis-reservas-nuevo")?.addEventListener("click", () => {
      irA("mis-reservas");
      buscarReservas();
    });

    // Mostrar el ticket modal automáticamente para wow del usuario
    mostrarTicket(r);

    document.getElementById("form-reserva").reset();
    estado.formularioListo = false;
    prepararFormulario();
  } catch (err) {
    salida.classList.remove("hidden");
    salida.innerHTML = alertaError("No se pudo reservar", err);
  } finally {
    boton.disabled = false;
    boton.textContent = "Confirmar reserva";
  }
}

// ---------------------------------------------------------------- modal ticket
function mostrarTicket(r) {
  const modal = document.getElementById("modal-comprobante");
  document.getElementById("ticket-id").textContent = `#${r.id}`;
  document.getElementById("ticket-inicio").textContent = horaCorta(r.inicio);
  document.getElementById("ticket-fin").textContent = (r.fin.split(" ")[1] || "").slice(0, 5);
  document.getElementById("ticket-zona").textContent = r.zona_nombre || r.codigo_zona;

  const z = zonaPorCodigo(r.codigo_zona);
  document.getElementById("ticket-sector").textContent = z ? z.sector : "Campus Montería";
  document.getElementById("ticket-titular").textContent = r.nombre || "Usuario";
  document.getElementById("ticket-id-persona").textContent = r.identificacion;
  document.getElementById("ticket-vehiculo").textContent = `${(r.tipo_vehiculo || "Vehículo").toUpperCase()} ${r.placa ? `(${r.placa})` : ""}`;
  document.getElementById("ticket-creada").textContent = horaCorta(r.creada_en);

  const qrPayload = `PARK-MONTERIA-RES:${r.id}|ZONA:${r.codigo_zona}|USR:${r.identificacion}|INI:${r.inicio}|FIN:${r.fin}`;
  document.getElementById("ticket-qr").innerHTML = generarSvgQR(qrPayload);

  modal.classList.remove("hidden");
}

function cerrarModalTicket() {
  document.getElementById("modal-comprobante").classList.add("hidden");
}

// ---------------------------------------------------------------- ampliación de reserva
function abrirModalAmpliar(reservaId) {
  estado.reservaPorAmpliar = reservaId;
  const modal = document.getElementById("modal-ampliar");
  document.getElementById("mensaje-modal-ampliar").classList.add("hidden");
  modal.classList.remove("hidden");
}

function cerrarModalAmpliar() {
  document.getElementById("modal-ampliar").classList.add("hidden");
  estado.reservaPorAmpliar = null;
}

async function ejecutarAmpliacion(minutos) {
  const id = estado.reservaPorAmpliar;
  const aviso = document.getElementById("mensaje-modal-ampliar");
  if (!id) return;

  // Manejo de la reserva de demostración
  if (id === 99999 && estado.reservaDemo) {
    const finDate = new Date(Date.now() + (minutos + 5) * 60000);
    const ahoraIso = new Date(finDate.getTime() - 5 * 3600 * 1000).toISOString();
    estado.reservaDemo.fin = ahoraIso.slice(0, 10) + " " + ahoraIso.slice(11, 19);
    sonarAviso();
    mostrarToast("Tiempo ampliado", `Se sumaron +${minutos} minutos a la reserva de prueba`, "ok");
    cerrarModalAmpliar();
    document.getElementById("banner-recordatorio").classList.add("hidden");
    actualizarTimerLoop();
    return;
  }

  aviso.classList.remove("hidden");
  aviso.innerHTML = `<div class="alerta-info">Ampliando tiempo con el servidor…</div>`;

  try {
    const res = await api(`/reservas/${id}/ampliar`, {
      method: "POST",
      body: JSON.stringify({ minutos }),
    });
    sonarAviso();
    mostrarToast("¡Tiempo ampliado!", `Tu reserva nº ${id} ahora termina a las ${res.fin.slice(11, 16)}`, "ok");
    lanzarNotificacion("Tiempo de Reserva Ampliado", `Tu cupo en ${res.zona_nombre} se extendió hasta las ${res.fin.slice(11, 16)}.`);
    cerrarModalAmpliar();
    document.getElementById("banner-recordatorio").classList.add("hidden");
    await cargarZonas(true);
    await buscarReservas();
    actualizarTimerLoop();
  } catch (err) {
    aviso.innerHTML = alertaError("No se pudo ampliar", err);
  }
}

async function cancelarReserva(id, contenedorAviso) {
  if (id === 99999 && estado.reservaDemo) {
    estado.reservaDemo = null;
    document.getElementById("banner-recordatorio").classList.add("hidden");
    mostrarToast("Cancelada", "Reserva de prueba cancelada", "ok");
    buscarReservas();
    dibujarMapa();
    return;
  }
  try {
    await api(`/reservas/${id}/cancelar`, { method: "POST" });
    if (contenedorAviso) {
      contenedorAviso.innerHTML = `<div class="alerta-info">La reserva nº ${id} fue cancelada y el cupo quedó libre en el mapa.</div>`;
    }
    mostrarToast("Reserva cancelada", `El cupo nº ${id} ha sido liberado exitosamente`, "ok");
    await cargarZonas(true);
    dibujarMapa();
    if (document.getElementById("v-mis-reservas").classList.contains("active")) buscarReservas();
  } catch (err) {
    if (contenedorAviso) contenedorAviso.innerHTML = alertaError("No se pudo cancelar", err);
    else mostrarGlobal(err.message);
  }
}

// ---------------------------------------------------------------- mis reservas y zonas en vivo
function chipEstado(r) {
  if (r.estado === "cancelada") return `<span class="chip chip-no">Cancelada</span>`;
  const ahora = new Date(Date.now() - 5 * 3600 * 1000).toISOString().slice(0, 19).replace("T", " ");
  return r.fin < ahora
    ? `<span class="chip chip-no">Terminada</span>`
    : `<span class="chip chip-ok">Activa</span>`;
}

function calcularMinutosRestantes(finTexto) {
  if (!finTexto) return 0;
  // finTexto: "2026-10-27 10:30:00" en hora de Montería (UTC-5)
  const ahoraMontería = new Date(Date.now() - 5 * 3600 * 1000);
  const [f, h] = finTexto.split(" ");
  const [y, m, d] = f.split("-");
  const [hh, mm, ss] = h.split(":");
  const finDate = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d), Number(hh), Number(mm), Number(ss || 0)));
  const difMs = finDate.getTime() - ahoraMontería.getTime();
  return Math.floor(difMs / 60000);
}

async function inicializarMisReservas() {
  const input = document.getElementById("input-buscar-id");
  if (!input.value && estado.ultimaIdentificacion) {
    input.value = estado.ultimaIdentificacion;
  }
  if (input.value) {
    buscarReservas();
  } else {
    // Si no tiene identificación, mostrar de una vez las zonas reservadas en vivo
    cambiarSubtab("todas-zonas");
  }
}

function cambiarSubtab(tab) {
  estado.subtabActual = tab;
  document.querySelectorAll(".subtab-btn").forEach(b => b.classList.toggle("active", b.dataset.subtab === tab));
  document.getElementById("subtab-contenido-usuario").classList.toggle("hidden", tab !== "usuario");
  document.getElementById("subtab-contenido-todas").classList.toggle("hidden", tab !== "todas-zonas");
  if (tab === "todas-zonas") cargarZonasReservadasCampus();
}

async function buscarReservas() {
  const form = document.getElementById("form-buscar");
  const id = form.identificacion.value.trim();
  const lista = document.getElementById("lista-reservas");
  if (!id) {
    lista.innerHTML = `<div class="vacio">Escribe una identificación para buscar o revisa la pestaña 'Zonas reservadas en vivo'.</div>`;
    return;
  }
  estado.ultimaIdentificacion = id;
  localStorage.setItem("usuario_identificacion", id);
  lista.innerHTML = `<div class="vacio">Buscando tus reservas…</div>`;

  try {
    let reservas = await api(`/reservas?identificacion=${encodeURIComponent(id)}`);
    if (estado.reservaDemo && id === estado.reservaDemo.identificacion) {
      reservas = [estado.reservaDemo, ...reservas];
    }
    estado.misReservas = reservas;

    if (!reservas.length) {
      lista.innerHTML = `
        <div class="vacio">
          <p>No hay reservas para la identificación <b>${escapeHtml(id)}</b>.</p>
          <button class="btn btn-sm btn-primary" style="margin-top:10px;" data-go="reservar">Hacer una reserva ahora</button>
        </div>`;
      lista.querySelector("[data-go]")?.addEventListener("click", () => irA("reservar"));
      return;
    }

    lista.innerHTML = reservas.map(r => {
      const activa = r.estado === "activa" && chipEstado(r).includes("Activa");
      const mins = activa ? calcularMinutosRestantes(r.fin) : null;
      const esUrgente = activa && mins !== null && mins <= 10 && mins >= 0;

      let timerHtml = "";
      if (activa && mins !== null) {
        if (mins <= 10) {
          timerHtml = `<div class="timer-box" style="color:#f59e0b;">⏳ Quedan ${mins} min en tu puesto (¡Atención!)</div>`;
        } else {
          const h = Math.floor(mins / 60);
          const m = mins % 60;
          timerHtml = `<div class="timer-box">⏳ Tiempo restante: ${h > 0 ? `${h}h ` : ""}${m}m</div>`;
        }
      }

      return `
        <article class="reserva ${r.estado === "cancelada" ? "cancelada" : ""} ${esUrgente ? "urgente" : ""}">
          <div class="reserva-top">
            <div>
              <h3>${escapeHtml(r.zona_nombre)}</h3>
              <div class="meta">Reserva nº ${r.id} · ${escapeHtml(r.tipo_vehiculo || "vehículo")}</div>
            </div>
            ${chipEstado(r)}
          </div>
          <div class="fecha">${escapeHtml(horaCorta(r.inicio))} → ${escapeHtml(r.fin.slice(11, 16))}</div>
          ${timerHtml}
          <div class="meta">Registrada: ${escapeHtml(horaCorta(r.creada_en))}</div>
          <div class="reserva-acciones">
            <button class="btn btn-sm btn-primary" data-ticket="${r.id}">🎫 Ver ticket / QR</button>
            ${activa ? `<button class="btn btn-sm" data-ampliar="${r.id}">⏱ Ampliar tiempo</button>` : ""}
            ${activa ? `<button class="btn btn-sm btn-danger" data-cancelar="${r.id}">Cancelar</button>` : ""}
          </div>
        </article>`;
    }).join("");

    lista.querySelectorAll("[data-ticket]").forEach(b => {
      b.addEventListener("click", () => {
        const res = estado.misReservas.find(x => x.id === Number(b.dataset.ticket));
        if (res) mostrarTicket(res);
      });
    });

    lista.querySelectorAll("[data-ampliar]").forEach(b => {
      b.addEventListener("click", () => abrirModalAmpliar(Number(b.dataset.ampliar)));
    });

    lista.querySelectorAll("[data-cancelar]").forEach(b => {
      b.addEventListener("click", () => cancelarReserva(Number(b.dataset.cancelar), null));
    });

    actualizarTimerLoop();
  } catch (err) {
    lista.innerHTML = alertaError("No se pudieron cargar las reservas", err);
  }
}

async function cargarZonasReservadasCampus() {
  const lista = document.getElementById("lista-todas-reservas");
  lista.innerHTML = `<div class="vacio">Consultando reservas activas en toda la sede…</div>`;
  try {
    const activas = await api("/reservas/activas");
    estado.todasReservasActivas = activas;

    if (!activas.length) {
      lista.innerHTML = `
        <div class="vacio">
          <p>En este momento <b>no hay zonas reservadas</b> en el campus. ¡Todos los cupos están libres!</p>
          <button class="btn btn-sm btn-primary" style="margin-top:10px;" data-go="reservar">Ser el primero en reservar</button>
        </div>`;
      lista.querySelector("[data-go]")?.addEventListener("click", () => irA("reservar"));
      return;
    }

    lista.innerHTML = activas.map(r => `
      <article class="reserva">
        <div class="reserva-top">
          <div>
            <h3>${escapeHtml(r.zona_nombre)}</h3>
            <div class="meta">${escapeHtml(r.sector)} · Reserva nº ${r.id}</div>
          </div>
          <span class="chip chip-warn">Cupo Reservado</span>
        </div>
        <div class="fecha">⏰ ${escapeHtml(horaCorta(r.inicio))} a ${escapeHtml(r.fin.slice(11, 16))}</div>
        <div class="meta">Titular: <b>${escapeHtml(r.nombre || "Usuario")}</b> (${escapeHtml(r.tipo_vehiculo || "vehículo")})</div>
        <div class="meta">Hora de registro: ${escapeHtml(horaCorta(r.creada_en))}</div>
        <div class="reserva-acciones">
          <button class="btn btn-sm" data-ver-zona="${escapeHtml(r.codigo_zona)}">Ver en el mapa</button>
        </div>
      </article>`).join("");

    lista.querySelectorAll("[data-ver-zona]").forEach(b => {
      b.addEventListener("click", () => {
        estado.zonaSeleccionada = b.dataset.verZona;
        irA("mapa");
      });
    });
  } catch (err) {
    lista.innerHTML = alertaError("No se pudieron cargar las reservas del campus", err);
  }
}

// ---------------------------------------------------------------- bucle de recordatorio (10 min)
function actualizarTimerLoop() {
  const ticker = document.getElementById("ticker-reserva");
  const banner = document.getElementById("banner-recordatorio");
  const bannerDesc = document.getElementById("banner-desc");

  const activas = estado.misReservas.filter(r => r.estado === "activa" && chipEstado(r).includes("Activa"));
  if (estado.reservaDemo) activas.push(estado.reservaDemo);

  if (!activas.length) {
    ticker.classList.add("hidden");
    banner.classList.add("hidden");
    return;
  }

  // Encontrar la reserva que termina más pronto
  let masCercana = null;
  let menorMins = Infinity;

  activas.forEach(r => {
    const m = calcularMinutosRestantes(r.fin);
    if (m >= 0 && m < menorMins) {
      menorMins = m;
      masCercana = r;
    }
  });

  if (!masCercana) {
    ticker.classList.add("hidden");
    banner.classList.add("hidden");
    return;
  }

  // Ticker en cabecera
  ticker.classList.remove("hidden");
  document.getElementById("ticker-texto").textContent =
    `${masCercana.zona_nombre.split("·")[0].trim()}: faltan ${menorMins}m`;

  // Comprobar si faltan 10 minutos o menos para el recordatorio
  if (menorMins <= 10 && menorMins >= 0) {
    banner.classList.remove("hidden");
    banner.classList.add("pulsar");
    bannerDesc.textContent =
      `Tu reserva nº ${masCercana.id} en ${masCercana.zona_nombre} termina a las ${masCercana.fin.slice(11, 16)} (quedan ${menorMins} min). ¿Deseas ampliar tu tiempo en el puesto?`;

    // Vincular botones rápidos del banner
    document.getElementById("btn-banner-ampliar-30").onclick = () => {
      estado.reservaPorAmpliar = masCercana.id;
      ejecutarAmpliacion(30);
    };
    document.getElementById("btn-banner-ampliar-60").onclick = () => {
      estado.reservaPorAmpliar = masCercana.id;
      ejecutarAmpliacion(60);
    };

    // Lanzar sonido y alerta solo una vez por reserva
    if (!estado.recordatorioAvisado[masCercana.id]) {
      estado.recordatorioAvisado[masCercana.id] = true;
      sonarAviso();
      mostrarToast("¡Atención! Faltan 10 minutos", `Tu reserva en ${masCercana.zona_nombre} está por finalizar. Puedes ampliarla ahora.`, "warn");
      lanzarNotificacion("⚠️ Recordatorio: 10 minutos para finalizar", `Tu reserva en ${masCercana.zona_nombre} termina a las ${masCercana.fin.slice(11, 16)}.`);
    }
  } else {
    banner.classList.remove("hidden");
    banner.classList.remove("pulsar");
    banner.style.display = "none";
  }
}

// ---------------------------------------------------------------- simulación demo 10 min
function activarDemo10Min() {
  pedirPermisoNotificaciones();
  const ahoraMontería = new Date(Date.now() - 5 * 3600 * 1000);
  const finMontería = new Date(ahoraMontería.getTime() + 9 * 60000 + 30000); // 9 min y 30 seg

  const isoInicio = ahoraMontería.toISOString().replace("T", " ").slice(0, 19);
  const isoFin = finMontería.toISOString().replace("T", " ").slice(0, 19);
  const isoCreada = new Date(ahoraMontería.getTime() - 25 * 60000).toISOString().replace("T", " ").slice(0, 19);

  estado.reservaDemo = {
    id: 99999,
    codigo_zona: "BHMBCCMKT01",
    zona_nombre: "Norte · Bloque 1 (DEMO)",
    identificacion: document.getElementById("input-buscar-id").value.trim() || "1064188073",
    nombre: "Usuario Demo",
    tipo_vehiculo: "carro",
    placa: "DEM999",
    inicio: isoInicio,
    fin: isoFin,
    estado: "activa",
    creada_en: isoCreada,
  };

  delete estado.recordatorioAvisado[99999];
  sonarAviso();
  mostrarToast("⚡ Simulación de 10 min activada", "Reserva de prueba creada con 9 minutos restantes para probar la alerta sonora y la ampliación.", "warn");
  buscarReservas();
  actualizarTimerLoop();
  dibujarMapa();
}

// ---------------------------------------------------------------- calidad y pruebas
function bloqueReconciliacion(titulo, r) {
  if (!r) return "";
  const cuadra = r.reconciliacion_filas_ok && r.consistencia_bd_ok;
  return `
    <div class="recon">
      <div class="recon-titulo">${escapeHtml(titulo)} · <span class="chip ${cuadra ? "chip-ok" : "chip-bad"}">${cuadra ? "Cuadra" : "No cuadra"}</span></div>
      <div class="stat-row">
        <div class="stat"><span>Filas leídas</span><strong>${numero(r.filas_leidas)}</strong></div>
        <div class="stat ok"><span>Nuevas</span><strong>${numero(r.aceptadas_nuevas)}</strong></div>
        <div class="stat"><span>Ya existían</span><strong>${numero(r.ya_existian_identicas)}</strong></div>
        <div class="stat"><span>Duplicados</span><strong>${numero(r.duplicados_exactos_descartados)}</strong></div>
        <div class="stat bad"><span>Rechazadas</span><strong>${numero(r.rechazadas)}</strong></div>
      </div>
    </div>`;
}

async function cargarPipeline() {
  const caja = document.getElementById("pipeline-resumen");
  caja.innerHTML = `<p class="muted">Cargando…</p>`;
  try {
    const p = await api("/api/pipeline");
    const rec = p.reconciliaciones || {};
    caja.innerHTML = `
      <div class="stat-row">
        <div class="stat"><span>Zonas</span><strong>${numero(p.zonas_en_catalogo)}</strong></div>
        <div class="stat"><span>Lecturas en la base</span><strong>${numero(p.lecturas_en_bd)}</strong></div>
      </div>
      ${bloqueReconciliacion("Carga inicial · datos originales", rec.datos_originales)}
      ${bloqueReconciliacion("Anomalías de prueba", rec.anomalias_prueba)}`;
  } catch (err) {
    caja.innerHTML = alertaError("No se pudo cargar el pipeline", err);
  }
}

async function ejecutarPruebas() {
  const boton = document.getElementById("btn-pruebas");
  const resumen = document.getElementById("pruebas-resumen");
  const salida = document.getElementById("pruebas-salida");
  boton.disabled = true;
  boton.textContent = "Ejecutando…";
  salida.textContent = "Ejecutando pytest en el servidor…";
  try {
    const d = await api("/api/run-tests", { method: "POST" });
    const ok = d.codigo === 0;
    resumen.innerHTML = `
      <div class="stat-row">
        <div class="stat ok"><span>Pasaron</span><strong>${numero(d.resumen.passed)}</strong></div>
        <div class="stat ${d.resumen.failed ? "bad" : ""}"><span>Fallaron</span><strong>${numero(d.resumen.failed)}</strong></div>
        <div class="stat"><span>Duración</span><strong>${d.resumen.duracion_s ? d.resumen.duracion_s + " s" : "—"}</strong></div>
      </div>
      <span class="chip ${ok ? "chip-ok" : "chip-bad"}">${ok ? "Todas las pruebas pasaron" : "Hay pruebas fallidas"}</span>`;
    salida.textContent = d.output || "pytest no devolvió salida.";
  } catch (err) {
    resumen.innerHTML = alertaError("No se pudieron ejecutar las pruebas", err);
    salida.textContent = err.message;
  } finally {
    boton.disabled = false;
    boton.textContent = "Ejecutar pruebas";
  }
}

// ---------------------------------------------------------------- estado de la API
async function comprobarApi() {
  const caja = document.getElementById("estado-api");
  try {
    await api("/health");
    caja.className = "status on";
    caja.querySelector("span:last-child").textContent = "API en línea";
  } catch (_) {
    caja.className = "status off";
    caja.querySelector("span:last-child").textContent = "API sin conexión";
  }
}

// ---------------------------------------------------------------- arranque
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-item").forEach(b => b.addEventListener("click", () => irA(b.dataset.view)));
  document.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => irA(b.dataset.go)));

  // Formulario reserva
  document.getElementById("select-zona")?.addEventListener("change", e => {
    estado.zonaSeleccionada = e.target.value;
    actualizarRestricciones();
  });
  document.querySelector('#form-reserva [name="tipo_vehiculo"]')?.addEventListener("change", actualizarRestricciones);
  document.getElementById("btn-disponibilidad")?.addEventListener("click", consultarCupos);
  document.getElementById("form-reserva")?.addEventListener("submit", enviarReserva);

  // Mis reservas
  document.getElementById("form-buscar")?.addEventListener("submit", e => { e.preventDefault(); buscarReservas(); });
  document.getElementById("btn-demo-alerta")?.addEventListener("click", activarDemo10Min);
  document.getElementById("btn-recargar-activas")?.addEventListener("click", cargarZonasReservadasCampus);

  // Subtabs en Mis Reservas
  document.querySelectorAll(".subtab-btn").forEach(b => {
    b.addEventListener("click", () => cambiarSubtab(b.dataset.subtab));
  });

  // Filtros en mapa
  document.querySelectorAll(".filtro-btn").forEach(b => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".filtro-btn").forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      estado.filtroMapa = b.dataset.filtro;
      dibujarMapa();
    });
  });

  // Modales
  document.getElementById("btn-cerrar-modal")?.addEventListener("click", cerrarModalTicket);
  document.getElementById("btn-imprimir-ticket")?.addEventListener("click", () => window.print());
  document.getElementById("btn-ir-mis-reservas")?.addEventListener("click", () => {
    cerrarModalTicket();
    irA("mis-reservas");
    buscarReservas();
  });
  document.getElementById("modal-comprobante")?.addEventListener("click", e => {
    if (e.target.id === "modal-comprobante") cerrarModalTicket();
  });

  document.getElementById("btn-cerrar-modal-ampliar")?.addEventListener("click", cerrarModalAmpliar);
  document.getElementById("modal-ampliar")?.addEventListener("click", e => {
    if (e.target.id === "modal-ampliar") cerrarModalAmpliar();
  });
  document.querySelectorAll(".btn-opcion").forEach(b => {
    b.addEventListener("click", () => ejecutarAmpliacion(Number(b.dataset.minutos)));
  });

  // Banner recordatorio
  document.getElementById("btn-banner-cerrar")?.addEventListener("click", () => {
    document.getElementById("banner-recordatorio").classList.add("hidden");
  });

  // Pruebas y pipeline
  document.getElementById("btn-pruebas")?.addEventListener("click", ejecutarPruebas);
  document.getElementById("btn-actualizar-pipeline")?.addEventListener("click", cargarPipeline);

  // Carga inicial
  comprobarApi();
  setInterval(comprobarApi, 20000);
  setInterval(actualizarTimerLoop, 5000);

  pedirPermisoNotificaciones();

  const inicial = (location.hash || "#inicio").slice(1);
  irA(VISTAS[inicial] ? inicial : "inicio");
});

window.addEventListener("hashchange", () => {
  const v = location.hash.slice(1);
  if (VISTAS[v]) irA(v);
});
