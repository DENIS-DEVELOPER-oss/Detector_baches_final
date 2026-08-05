/* =========================================================================
   Modulo de deteccion de baches - logica del cliente.

   Organizacion (misma idea que en el backend: una clase por responsabilidad)

     GestorModos      -> muestra un modo a la vez y apaga la camara al salir
     GestorUbicacion  -> mapa compartido; copia coordenadas al modo activo
     Camara           -> envoltura de getUserMedia reutilizable
     CapturaFoto      -> modo 3
     GrabadorVideo    -> modo 4
     DeteccionVivo    -> modo 5

   El mapa lo entrega `crearMapa()` (static/js/mapas.js), que decide solo entre
   Google Maps y django-leaflet; aqui no se sabe cual de los dos es. La busqueda
   de direcciones usa `Geocodificador`, que consulta a geopy en el servidor.
   ========================================================================= */

/* global crearMapa, Geocodificador, CONFIG_MAPAS,
          parsearCoordenadas, enlaceGoogleMaps, enlaceGoogleMapsPunto */

const COLOR_NIVEL = {
  BAJA: '#4fc98a',
  MEDIA: '#f5b544',
  ALTA: '#f2704f',
  CRITICA: '#c0392b'
};

const ETIQUETA_CLASE = { pothole: 'Bache', crack: 'Grieta' };


/* ------------------------------------------------------------------ Camara */
class Camara {
  constructor(elementoVideo, elementoEstado) {
    this.video = elementoVideo;
    this.estado = elementoEstado;
    this.flujo = null;
  }

  get activa() {
    return this.flujo !== null;
  }

  async iniciar(deviceId) {
    if (this.activa) return true;
    try {
      this.flujo = await navigator.mediaDevices.getUserMedia({
        video: deviceId ? { deviceId: { exact: deviceId } } : { facingMode: 'environment' },
        audio: false
      });
    } catch (e) {
      this.informar('No se pudo acceder a la camara: ' + e.message);
      return false;
    }
    this.video.srcObject = this.flujo;
    await this.video.play();
    this.informar('Camara activa');
    return true;
  }

  detener() {
    if (this.flujo) this.flujo.getTracks().forEach(t => t.stop());
    this.flujo = null;
    this.video.srcObject = null;
    this.informar('Camara detenida');
  }

  informar(texto) {
    if (this.estado) this.estado.textContent = texto;
  }

  /** Devuelve el cuadro actual como data URL JPEG. */
  cuadro(calidad = 0.85) {
    const lienzo = document.createElement('canvas');
    lienzo.width = this.video.videoWidth;
    lienzo.height = this.video.videoHeight;
    lienzo.getContext('2d').drawImage(this.video, 0, 0);
    return lienzo.toDataURL('image/jpeg', calidad);
  }
}


/* ------------------------------------------------------------- Modo activo */
class GestorModos {
  constructor(alCambiar) {
    this.botones = Array.from(document.querySelectorAll('#selectorModos .modo'));
    this.paneles = Array.from(document.querySelectorAll('.panel-modo'));
    this.alCambiar = alCambiar;
    this.actual = null;

    this.botones.forEach(boton => {
      boton.addEventListener('click', () => this.activar(boton.dataset.modo));
    });
  }

  activar(modo) {
    if (this.actual === modo) return;
    const anterior = this.actual;
    this.actual = modo;

    this.botones.forEach(b => b.classList.toggle('activo', b.dataset.modo === modo));
    this.paneles.forEach(p => {
      p.classList.toggle('visible', p.dataset.panel.split(' ').includes(modo));
    });

    if (this.alCambiar) this.alCambiar(modo, anterior);
  }

  get panelActivo() {
    return this.paneles.find(p => p.classList.contains('visible')) || null;
  }
}


/* ---------------------------------------------------------- Mapa compartido */
class GestorUbicacion {
  /**
   * @param {object} opciones
   * @param {object} opciones.mapa  Instancia ya creada por `crearMapa()`.
   */
  constructor({ zonas, mapa, gestorModos }) {
    this.zonas = zonas;
    this.gestorModos = gestorModos;
    this.mapa = mapa;
    this.geocodificador = new Geocodificador();

    // El mapa avisa cuando el usuario elige un punto (clic o arrastre)
    this.mapa.habilitarSeleccion((lat, lng) => {
      this.escribirEnFormulario(lat, lng);
      this.completarReferencia(lat, lng);
      this.refrescarEnlaceGoogle(lat, lng);
    });

    document.getElementById('btnGps').addEventListener('click', () => this.usarGps());

    // Al elegir una zona, el mapa salta a su centro
    document.querySelectorAll('select[name$="zona"]').forEach(select => {
      select.addEventListener('change', () => {
        const zona = this.zonas.find(z => String(z.id) === select.value);
        if (zona) this.fijar(parseFloat(zona.latitud), parseFloat(zona.longitud), 15);
      });
    });

    this._prepararBuscador();
    this._prepararPuenteGoogle();
  }

  /* --------------------------------------------- Puente con Google Maps */
  _prepararPuenteGoogle() {
    this.abrirGoogle = document.getElementById('abrirGoogle');
    this.pegarGoogle = document.getElementById('pegarGoogle');
    this.ayudaGoogle = document.getElementById('ayudaGoogle');
    if (!this.pegarGoogle) return;

    this.ayudaOriginal = this.ayudaGoogle.textContent;
    this.refrescarEnlaceGoogle();

    const usar = () => this._usarPegado();
    document.getElementById('usarGoogle').addEventListener('click', usar);
    this.pegarGoogle.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); usar(); }
    });
    this.pegarGoogle.addEventListener('paste', () => setTimeout(usar, 0));
    this.pegarGoogle.addEventListener('input', () => {
      if (!this.pegarGoogle.value.trim()) this._avisarGoogle(this.ayudaOriginal);
    });
  }

  refrescarEnlaceGoogle(lat, lng) {
    if (!this.abrirGoogle) return;
    this.abrirGoogle.href = (lat === undefined)
      ? enlaceGoogleMaps(CONFIG_MAPAS.centro[0], CONFIG_MAPAS.centro[1], CONFIG_MAPAS.zoom)
      : enlaceGoogleMapsPunto(lat.toFixed(7), lng.toFixed(7));
  }

  _avisarGoogle(texto, clase) {
    this.ayudaGoogle.textContent = texto;
    this.ayudaGoogle.className = 'form-text small mb-0 ' + (clase || '');
  }

  _usarPegado() {
    const punto = parsearCoordenadas(this.pegarGoogle.value);
    if (!punto) {
      this._avisarGoogle(
        'No se reconocieron coordenadas. Ejemplo valido: -15.4997, -70.1330', 'erroneo');
      return;
    }
    this.fijar(punto.lat, punto.lng, 18);
    this._avisarGoogle(
      `Punto colocado en ${punto.lat}, ${punto.lng}. Se usara en el modo abierto.`, 'correcto');
  }

  /* ------------------------------------------------ Buscador de direcciones */
  _prepararBuscador() {
    this.entrada = document.getElementById('buscarDireccion');
    this.lista = document.getElementById('resultadosDireccion');
    this.cargando = document.getElementById('cargandoDireccion');
    if (!this.entrada) return;

    this.entrada.addEventListener('input', () => {
      const texto = this.entrada.value;
      if (texto.trim().length < 3) {
        this._ocultarResultados();
        return;
      }
      this.cargando.classList.remove('d-none');
      this.geocodificador.buscar(texto)
        .then(lugares => this._mostrarResultados(lugares))
        .catch(() => this._mostrarError('No se pudo buscar la direccion.'))
        .finally(() => this.cargando.classList.add('d-none'));
    });

    // Enter no debe enviar el formulario del modo activo
    this.entrada.addEventListener('keydown', e => {
      if (e.key === 'Enter') e.preventDefault();
      if (e.key === 'Escape') this._ocultarResultados();
    });

    document.addEventListener('click', e => {
      if (!this.lista.contains(e.target) && e.target !== this.entrada) {
        this._ocultarResultados();
      }
    });
  }

  _mostrarResultados(lugares) {
    this.lista.innerHTML = '';
    if (!lugares.length) {
      this._mostrarError('Sin resultados para esa direccion.');
      return;
    }
    lugares.forEach(lugar => {
      const item = document.createElement('li');
      item.innerHTML = `${lugar.direccion}
        <span class="coordenadas">${lugar.latitud}, ${lugar.longitud}</span>`;
      item.addEventListener('click', () => {
        this.fijar(lugar.latitud, lugar.longitud, 17);
        this.escribirReferencia(lugar.direccion);
        this.entrada.value = lugar.direccion;
        this._ocultarResultados();
      });
      this.lista.appendChild(item);
    });
    this.lista.classList.remove('d-none');
  }

  _mostrarError(mensaje) {
    this.lista.innerHTML = `<li class="vacio">${mensaje}</li>`;
    this.lista.classList.remove('d-none');
  }

  _ocultarResultados() {
    this.lista.classList.add('d-none');
    this.lista.innerHTML = '';
  }

  /** Rellena la referencia con la direccion del punto, si esta vacia. */
  completarReferencia(lat, lng) {
    const campo = this.campoReferencia();
    if (!campo || campo.value.trim()) return;
    this.geocodificador.direccionDe(lat, lng).then(direccion => {
      if (direccion && !campo.value.trim()) campo.value = direccion;
    });
  }

  escribirReferencia(direccion) {
    const campo = this.campoReferencia();
    if (campo) campo.value = direccion;
  }

  campoReferencia() {
    const panel = this.gestorModos.panelActivo;
    return panel ? panel.querySelector('input[name$="direccion_referencia"]') : null;
  }

  /** Inputs de coordenadas del modo que esta abierto. */
  camposActivos() {
    const panel = this.gestorModos.panelActivo;
    if (!panel) return [];
    return [
      panel.querySelector('input[name$="latitud"]'),
      panel.querySelector('input[name$="longitud"]')
    ];
  }

  escribirEnFormulario(lat, lng) {
    const [campoLat, campoLng] = this.camposActivos();
    if (campoLat) campoLat.value = lat.toFixed(7);
    if (campoLng) campoLng.value = lng.toFixed(7);
  }

  fijar(lat, lng, zoom) {
    // `fijarSeleccion` mueve el marcador y dispara el callback de seleccion,
    // que es quien escribe en el formulario.
    this.mapa.fijarSeleccion(lat, lng, zoom);
  }

  /** Al cambiar de modo, copia las coordenadas ya elegidas al nuevo formulario. */
  sincronizar() {
    const p = this.mapa.posicionSeleccion();
    if (p) this.escribirEnFormulario(p.lat, p.lng);
  }

  usarGps() {
    if (!navigator.geolocation) {
      alert('Su navegador no permite geolocalizacion.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => this.fijar(pos.coords.latitude, pos.coords.longitude, 17),
      () => alert('No se pudo obtener la ubicacion. Otorgue el permiso al navegador.')
    );
  }
}


/* ------------------------------------------------------- 1 y 2: subir archivo */
class SubidaArchivo {
  constructor() {
    this.input = document.querySelector('#formArchivo input[type=file]');
    this.zona = document.getElementById('zonaSoltar');
    this.previa = document.getElementById('previaArchivo');
    this.etiqueta = document.querySelector('[data-etiqueta-archivo]');

    this.input.addEventListener('change', () => this.mostrar());

    ['dragenter', 'dragover'].forEach(evento =>
      this.zona.addEventListener(evento, e => {
        e.preventDefault();
        this.zona.classList.add('encima');
      }));

    ['dragleave', 'drop'].forEach(evento =>
      this.zona.addEventListener(evento, e => {
        e.preventDefault();
        this.zona.classList.remove('encima');
      }));

    this.zona.addEventListener('drop', e => {
      if (e.dataTransfer.files.length) {
        this.input.files = e.dataTransfer.files;
        this.mostrar();
      }
    });
  }

  /** Preselecciona el filtro del selector segun el modo elegido. */
  ajustarModo(modo) {
    if (modo === 'video') {
      this.input.setAttribute('accept', 'video/mp4,video/webm,video/x-msvideo,video/quicktime');
      if (this.etiqueta) this.etiqueta.textContent = 'Video';
    } else if (modo === 'imagen') {
      this.input.setAttribute('accept', 'image/*');
      if (this.etiqueta) this.etiqueta.textContent = 'Imagen';
    }
  }

  mostrar() {
    this.previa.innerHTML = '';
    const archivo = this.input.files[0];
    if (!archivo) return;

    const url = URL.createObjectURL(archivo);
    const nodo = archivo.type.startsWith('video')
      ? Object.assign(document.createElement('video'), { src: url, controls: true })
      : Object.assign(document.createElement('img'), { src: url });
    nodo.className = 'previa-archivo';
    this.previa.appendChild(nodo);

    const pie = document.createElement('div');
    pie.className = 'small text-muted mt-2';
    pie.textContent = `${archivo.name} - ${(archivo.size / 1048576).toFixed(1)} MB`;
    this.previa.appendChild(pie);
  }
}


/* ----------------------------------------------------------- 3: tomar foto */
class CapturaFoto {
  constructor(selectorCamara) {
    this.selectorCamara = selectorCamara;
    this.camara = new Camara(
      document.getElementById('videoFoto'),
      document.querySelector('[data-estado="foto"]')
    );
    this.previa = document.getElementById('previaFoto');
    this.campo = document.getElementById('campoCaptura');
    this.btnTomar = document.getElementById('btnTomarFoto');
    this.btnRepetir = document.getElementById('btnRepetirFoto');
    this.btnGuardar = document.getElementById('btnGuardarFoto');

    document.querySelector('[data-camara-iniciar="foto"]').addEventListener('click', () => this.iniciar());
    document.querySelector('[data-camara-detener="foto"]').addEventListener('click', () => this.detener());
    this.btnTomar.addEventListener('click', () => this.tomar());
    this.btnRepetir.addEventListener('click', () => this.repetir());
  }

  async iniciar() {
    if (!await this.camara.iniciar(this.selectorCamara.value)) return;
    this.btnTomar.disabled = false;
    document.querySelector('[data-camara-detener="foto"]').disabled = false;
    document.querySelector('[data-camara-iniciar="foto"]').disabled = true;
  }

  detener() {
    this.camara.detener();
    this.btnTomar.disabled = true;
    document.querySelector('[data-camara-detener="foto"]').disabled = true;
    document.querySelector('[data-camara-iniciar="foto"]').disabled = false;
  }

  tomar() {
    const dataUrl = this.camara.cuadro(0.9);
    this.campo.value = dataUrl;
    this.previa.src = dataUrl;
    this.previa.classList.remove('d-none');
    this.btnRepetir.classList.remove('d-none');
    this.btnTomar.classList.add('d-none');
    this.btnGuardar.disabled = false;
    this.camara.informar('Fotografia lista para analizar');
  }

  repetir() {
    this.campo.value = '';
    this.previa.classList.add('d-none');
    this.btnRepetir.classList.add('d-none');
    this.btnTomar.classList.remove('d-none');
    this.btnGuardar.disabled = true;
    this.camara.informar('Camara activa');
  }
}


/* -------------------------------------------------------- 4: grabar video */
class GrabadorVideo {
  constructor(selectorCamara) {
    this.selectorCamara = selectorCamara;
    this.camara = new Camara(
      document.getElementById('videoGrabar'),
      document.querySelector('[data-estado="grabar"]')
    );
    this.previa = document.getElementById('previaGrabacion');
    this.btnGrabar = document.getElementById('btnGrabar');
    this.btnDescartar = document.getElementById('btnDescartarGrabacion');
    this.btnGuardar = document.getElementById('btnGuardarGrabacion');
    this.indicador = document.getElementById('indicadorRec');
    this.cronometro = document.getElementById('cronometro');
    this.formulario = document.getElementById('formGrabar');

    this.grabador = null;
    this.trozos = [];
    this.blob = null;
    this.temporizador = null;
    this.segundos = 0;

    document.querySelector('[data-camara-iniciar="grabar"]').addEventListener('click', () => this.iniciar());
    document.querySelector('[data-camara-detener="grabar"]').addEventListener('click', () => this.detener());
    this.btnGrabar.addEventListener('click', () => this.alternar());
    this.btnDescartar.addEventListener('click', () => this.descartar());
    this.formulario.addEventListener('submit', e => this.adjuntar(e));
  }

  static tipoSoportado() {
    // VP8 es el que OpenCV lee con mas fiabilidad desde el navegador.
    const preferidos = ['video/webm;codecs=vp8', 'video/webm', 'video/mp4'];
    return preferidos.find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || '';
  }

  async iniciar() {
    if (!window.MediaRecorder) {
      this.camara.informar('Su navegador no permite grabar video.');
      return;
    }
    if (!await this.camara.iniciar(this.selectorCamara.value)) return;
    this.btnGrabar.disabled = false;
    document.querySelector('[data-camara-detener="grabar"]').disabled = false;
    document.querySelector('[data-camara-iniciar="grabar"]').disabled = true;
  }

  detener() {
    if (this.grabador && this.grabador.state !== 'inactive') this.grabador.stop();
    this.camara.detener();
    this.btnGrabar.disabled = true;
    document.querySelector('[data-camara-detener="grabar"]').disabled = true;
    document.querySelector('[data-camara-iniciar="grabar"]').disabled = false;
  }

  alternar() {
    if (this.grabador && this.grabador.state === 'recording') this.pararGrabacion();
    else this.empezarGrabacion();
  }

  empezarGrabacion() {
    const tipo = GrabadorVideo.tipoSoportado();
    this.trozos = [];
    this.grabador = new MediaRecorder(this.camara.flujo, tipo ? { mimeType: tipo } : undefined);
    this.grabador.ondataavailable = e => { if (e.data.size) this.trozos.push(e.data); };
    this.grabador.onstop = () => this.finalizar();
    this.grabador.start();

    this.btnGrabar.innerHTML = '<i class="bi bi-stop-fill"></i> Detener grabacion';
    this.btnGrabar.classList.replace('btn-danger', 'btn-dark');
    this.indicador.classList.remove('d-none');
    this.segundos = 0;
    this.cronometro.textContent = '00:00';
    this.temporizador = setInterval(() => {
      this.segundos += 1;
      const m = String(Math.floor(this.segundos / 60)).padStart(2, '0');
      const s = String(this.segundos % 60).padStart(2, '0');
      this.cronometro.textContent = `${m}:${s}`;
    }, 1000);
  }

  pararGrabacion() {
    this.grabador.stop();
    clearInterval(this.temporizador);
    this.indicador.classList.add('d-none');
    this.btnGrabar.innerHTML = '<i class="bi bi-record-circle"></i> Grabar';
    this.btnGrabar.classList.replace('btn-dark', 'btn-danger');
  }

  finalizar() {
    this.blob = new Blob(this.trozos, { type: this.grabador.mimeType || 'video/webm' });
    this.previa.src = URL.createObjectURL(this.blob);
    this.previa.classList.remove('d-none');
    this.btnDescartar.classList.remove('d-none');
    this.btnGuardar.disabled = false;
    this.camara.informar(
      `Grabacion lista (${this.segundos}s, ${(this.blob.size / 1048576).toFixed(1)} MB)`
    );
  }

  descartar() {
    this.blob = null;
    this.previa.classList.add('d-none');
    this.previa.removeAttribute('src');
    this.btnDescartar.classList.add('d-none');
    this.btnGuardar.disabled = true;
    this.camara.informar('Grabacion descartada');
  }

  /** Inyecta el blob en el formulario como si fuera un archivo elegido. */
  adjuntar(evento) {
    if (!this.blob) {
      evento.preventDefault();
      alert('Grabe un video antes de analizarlo.');
      return;
    }
    let campo = this.formulario.querySelector('input[name="grabacion"]');
    if (!campo) {
      campo = document.createElement('input');
      campo.type = 'file';
      campo.name = 'grabacion';
      campo.hidden = true;
      this.formulario.appendChild(campo);
    }
    const extension = this.blob.type.includes('mp4') ? 'mp4' : 'webm';
    const archivo = new File([this.blob], `grabacion.${extension}`, { type: this.blob.type });
    const transferencia = new DataTransfer();
    transferencia.items.add(archivo);
    campo.files = transferencia.files;
  }
}


/* ----------------------------------------------------- 5: deteccion en vivo */
class DeteccionVivo {
  constructor({ selectorCamara, urlAnalizar, csrf }) {
    this.selectorCamara = selectorCamara;
    this.urlAnalizar = urlAnalizar;
    this.csrf = csrf;

    this.video = document.getElementById('videoVivo');
    this.lienzo = document.getElementById('lienzoVivo');
    this.ctx = this.lienzo.getContext('2d');
    this.camara = new Camara(this.video, document.querySelector('[data-estado="vivo"]'));

    this.temporizador = null;
    this.analizando = false;

    document.querySelector('[data-camara-iniciar="vivo"]').addEventListener('click', () => this.iniciar());
    document.querySelector('[data-camara-detener="vivo"]').addEventListener('click', () => this.detener());

    document.getElementById('rangoFps').addEventListener('input', e => {
      document.getElementById('valorFps').textContent = e.target.value;
      if (this.camara.activa) this.programar();
    });

    document.getElementById('chkEspejo').addEventListener('change', e => {
      const t = e.target.checked ? 'scaleX(-1)' : 'none';
      this.video.style.transform = t;
      this.lienzo.style.transform = t;
    });

    document.getElementById('formVivo').addEventListener('submit', e => {
      if (!this.camara.activa) {
        e.preventDefault();
        alert('Inicie la camara antes de guardar una deteccion.');
        return;
      }
      document.getElementById('campoCapturaVivo').value = this.camara.cuadro(0.9);
    });
  }

  async iniciar() {
    if (!await this.camara.iniciar(this.selectorCamara.value)) return;
    this.lienzo.width = this.video.videoWidth;
    this.lienzo.height = this.video.videoHeight;

    document.querySelector('[data-camara-detener="vivo"]').disabled = false;
    document.querySelector('[data-camara-iniciar="vivo"]').disabled = true;
    document.getElementById('btnGuardarVivo').disabled = false;
    this.programar();
  }

  detener() {
    clearInterval(this.temporizador);
    this.camara.detener();
    this.ctx.clearRect(0, 0, this.lienzo.width, this.lienzo.height);
    this.reiniciarContadores();

    document.querySelector('[data-camara-detener="vivo"]').disabled = true;
    document.querySelector('[data-camara-iniciar="vivo"]').disabled = false;
    document.getElementById('btnGuardarVivo').disabled = true;
  }

  programar() {
    clearInterval(this.temporizador);
    const fps = parseInt(document.getElementById('rangoFps').value, 10);
    this.temporizador = setInterval(() => this.analizar(), 1000 / fps);
  }

  async analizar() {
    if (!this.camara.activa || this.analizando || this.video.readyState < 2) return;
    this.analizando = true;
    const inicio = performance.now();

    try {
      const cuerpo = new FormData();
      cuerpo.append('frame', this.camara.cuadro(0.7));

      const respuesta = await fetch(this.urlAnalizar, {
        method: 'POST',
        headers: { 'X-CSRFToken': this.csrf },
        body: cuerpo
      });
      const datos = await respuesta.json();

      if (!datos.ok) {
        this.camara.informar('Error: ' + datos.error);
        return;
      }

      this.dibujar(datos.cajas);
      this.actualizarContadores(datos.severidad);
      const total = Math.round(performance.now() - inicio);
      this.camara.informar(
        `${datos.total} dano(s) | inferencia ${datos.tiempo}s | ida y vuelta ${total} ms`
      );
    } catch (e) {
      this.camara.informar('Sin conexion con el servidor');
    } finally {
      this.analizando = false;
    }
  }

  dibujar(cajas) {
    const ancho = this.lienzo.width;
    const alto = this.lienzo.height;
    this.ctx.clearRect(0, 0, ancho, alto);
    this.ctx.lineWidth = Math.max(2, ancho / 320);
    this.ctx.font = `${Math.max(13, ancho / 48)}px system-ui, sans-serif`;
    this.ctx.textBaseline = 'bottom';

    cajas.forEach(c => {
      const color = COLOR_NIVEL[c.severidad] || '#2ec8dd';
      const x = c.x1 * ancho;
      const y = c.y1 * alto;
      const w = (c.x2 - c.x1) * ancho;
      const h = (c.y2 - c.y1) * alto;

      this.ctx.strokeStyle = color;
      this.ctx.strokeRect(x, y, w, h);

      const nombre = ETIQUETA_CLASE[c.clase] || c.clase;
      const texto = `${nombre} - ${c.severidad} ${Math.round(c.confianza * 100)}%`;
      const medida = this.ctx.measureText(texto);
      const altoTexto = parseInt(this.ctx.font, 10) + 7;

      this.ctx.fillStyle = color;
      this.ctx.fillRect(x, Math.max(0, y - altoTexto), medida.width + 10, altoTexto);
      this.ctx.fillStyle = '#fff';
      this.ctx.fillText(texto, x + 5, Math.max(altoTexto, y) - 3);
    });
  }

  actualizarContadores(severidad) {
    document.getElementById('vivoBaja').textContent = severidad.BAJA || 0;
    document.getElementById('vivoMedia').textContent = severidad.MEDIA || 0;
    document.getElementById('vivoAlta').textContent = severidad.ALTA || 0;
    document.getElementById('vivoCritica').textContent = severidad.CRITICA || 0;
  }

  reiniciarContadores() {
    ['vivoBaja', 'vivoMedia', 'vivoAlta', 'vivoCritica']
      .forEach(id => { document.getElementById(id).textContent = '0'; });
  }
}


/* ------------------------------------------------------------- Arranque */
function iniciarModuloDeteccion(config) {
  const selectorCamara = document.getElementById('selectCamara');

  async function listarCamaras() {
    try {
      const dispositivos = await navigator.mediaDevices.enumerateDevices();
      const camaras = dispositivos.filter(d => d.kind === 'videoinput');
      selectorCamara.innerHTML = camaras.length
        ? camaras.map((c, i) => `<option value="${c.deviceId}">${c.label || 'Camara ' + (i + 1)}</option>`).join('')
        : '<option value="">Camara predeterminada</option>';
    } catch (e) {
      selectorCamara.innerHTML = '<option value="">Camara predeterminada</option>';
    }
  }
  listarCamaras();

  const subida = new SubidaArchivo();
  const foto = new CapturaFoto(selectorCamara);
  const grabador = new GrabadorVideo(selectorCamara);
  const vivo = new DeteccionVivo({
    selectorCamara,
    urlAnalizar: config.urlAnalizar,
    csrf: config.csrf
  });

  let ubicacion = null;

  const modos = new GestorModos((modo) => {
    // Apagar cualquier camara que no pertenezca al modo recien abierto
    if (modo !== 'foto') foto.detener();
    if (modo !== 'grabar') grabador.detener();
    if (modo !== 'vivo') vivo.detener();

    subida.ajustarModo(modo);
    if (ubicacion) ubicacion.sincronizar();
  });

  modos.activar(config.modoInicial || 'imagen');

  // El mapa se crea de forma asincrona: la API de Google avisa por callback.
  // Sin centro ni zoom explicitos, crearMapa() usa los de CONFIG_MAPAS.
  crearMapa({ contenedor: 'mapa' })
    .then(mapa => {
      ubicacion = new GestorUbicacion({
        zonas: config.zonas,
        mapa,
        gestorModos: modos
      });
    })
    .catch(e => console.error('No se pudo crear el mapa de ubicacion:', e));

  // Evita el doble envio mientras corre la inferencia
  document.querySelectorAll('form').forEach(formulario => {
    formulario.addEventListener('submit', () => {
      const boton = formulario.querySelector('[data-boton-envio]');
      if (!boton || boton.disabled) return;
      boton.disabled = true;
      boton.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Analizando...';
    });
  });

  window.addEventListener('beforeunload', () => {
    foto.detener();
    grabador.detener();
    vivo.detener();
  });
}
