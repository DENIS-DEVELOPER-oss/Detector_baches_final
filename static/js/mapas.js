/* =========================================================================
   Capa de mapas del sistema.

   Todas las paginas hablan con una sola interfaz (`MapaBase`) y no saben que
   proveedor hay debajo:

     MapaBase (abstracta)
       MapaGoogle    -> Google Maps JavaScript API (si hay clave configurada)
       MapaLeaflet   -> Leaflet + OpenStreetMap (respaldo sin clave)

     crearMapa(...)  -> Factory: devuelve una promesa con la implementacion
                        adecuada, ya inicializada.

   Asi, si manana se cambia de proveedor, solo se toca este archivo.
   ========================================================================= */

/* global google, L, markerClusterer */

(function (global) {
  'use strict';

  const CONFIG = global.CONFIG_MAPAS || {};
  const HAY_GOOGLE = Boolean(CONFIG.claveGoogle);

  // Estilo sobrio para que el mapa no compita con los marcadores
  const ESTILO_GOOGLE = [
    { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
    { featureType: 'transit', elementType: 'labels', stylers: [{ visibility: 'off' }] }
  ];

  /* ------------------------------------------------------------ Abstracta */
  class MapaBase {
    constructor({ contenedor, centro, zoom }) {
      this.contenedor = typeof contenedor === 'string'
        ? document.getElementById(contenedor)
        : contenedor;
      this.centro = centro;
      this.zoom = zoom;
      this.marcadores = [];
      this.marcadorSeleccion = null;
      this.alSeleccionar = null;

      if (!this.contenedor) {
        throw new Error('No existe el contenedor del mapa.');
      }
    }

    /* Las subclases deben implementar estos metodos. */
    _crear() { throw new Error('Sin implementar'); }
    agregarMarcador() { throw new Error('Sin implementar'); }
    limpiarMarcadores() { throw new Error('Sin implementar'); }
    ajustarVista() { throw new Error('Sin implementar'); }
    centrarEn() { throw new Error('Sin implementar'); }
    habilitarSeleccion() { throw new Error('Sin implementar'); }
    fijarSeleccion() { throw new Error('Sin implementar'); }
    refrescar() {}

    /** Carga un FeatureCollection tal como lo entrega la API del sistema. */
    cargarGeoJSON(coleccion) {
      this.limpiarMarcadores();
      (coleccion.features || []).forEach(f => {
        const [lng, lat] = f.geometry.coordinates;
        this.agregarMarcador({
          lat, lng,
          color: f.properties.hex || '#2ec8dd',
          titulo: f.properties.titulo,
          html: MapaBase.globo(f.properties)
        });
      });
      return (coleccion.features || []).length;
    }

    /** Contenido del globo de informacion, igual en ambos proveedores. */
    static globo(p) {
      return `
        <div style="min-width:200px;font-family:'Segoe UI',system-ui,sans-serif">
          <div style="font-weight:600">${p.titulo || ''}</div>
          <div style="color:#98a0ac;font-size:.78rem">${p.codigo || ''} &middot; ${p.zona || ''}</div>
          <hr style="margin:.5rem 0">
          <div style="font-size:.8rem;line-height:1.6">
            <div><strong>${p.baches || 0}</strong> baches &middot; <strong>${p.grietas || 0}</strong> grietas</div>
            <div>Severidad maxima: ${p.severidad || '-'}</div>
            ${p.origen ? `<div>Origen: ${p.origen}</div>` : ''}
            <div style="color:#98a0ac">${p.fecha || ''}</div>
          </div>
          ${p.url ? `<a style="display:block;margin-top:.5rem;padding:.35rem;text-align:center;
             background:#2ec8dd;color:#fff;border-radius:4px;text-decoration:none"
             href="${p.url}">Ver detalle</a>` : ''}
        </div>`;
    }
  }

  /* --------------------------------------------------------- Google Maps */
  class MapaGoogle extends MapaBase {
    _crear() {
      this.mapa = new google.maps.Map(this.contenedor, {
        center: { lat: this.centro[0], lng: this.centro[1] },
        zoom: this.zoom,
        mapTypeId: google.maps.MapTypeId.ROADMAP,
        styles: ESTILO_GOOGLE,
        mapTypeControl: true,
        streetViewControl: false,
        fullscreenControl: true
      });
      this.globo = new google.maps.InfoWindow();
      this.agrupador = null;
      return this;
    }

    agregarMarcador({ lat, lng, color, titulo, html }) {
      const marcador = new google.maps.Marker({
        position: { lat, lng },
        title: titulo || '',
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 8,
          fillColor: color,
          fillOpacity: 0.95,
          strokeColor: '#ffffff',
          strokeWeight: 2
        }
      });

      if (html) {
        marcador.addListener('click', () => {
          this.globo.setContent(html);
          this.globo.open(this.mapa, marcador);
        });
      }

      this.marcadores.push(marcador);
      return marcador;
    }

    /** Agrupa los marcadores; se llama una vez cargados todos. */
    agrupar() {
      if (this.agrupador) this.agrupador.clearMarkers();

      if (global.markerClusterer && global.markerClusterer.MarkerClusterer) {
        this.agrupador = new markerClusterer.MarkerClusterer({
          map: this.mapa,
          markers: this.marcadores
        });
      } else {
        this.marcadores.forEach(m => m.setMap(this.mapa));
      }
    }

    limpiarMarcadores() {
      if (this.agrupador) this.agrupador.clearMarkers();
      this.marcadores.forEach(m => m.setMap(null));
      this.marcadores = [];
    }

    ajustarVista() {
      if (!this.marcadores.length) return;
      const limites = new google.maps.LatLngBounds();
      this.marcadores.forEach(m => limites.extend(m.getPosition()));
      this.mapa.fitBounds(limites, 60);
    }

    centrarEn(lat, lng, zoom) {
      this.mapa.setCenter({ lat, lng });
      if (zoom) this.mapa.setZoom(zoom);
    }

    habilitarSeleccion(callback) {
      this.alSeleccionar = callback;
      this.mapa.addListener('click', e => {
        this.fijarSeleccion(e.latLng.lat(), e.latLng.lng());
      });
    }

    fijarSeleccion(lat, lng, zoom) {
      if (this.marcadorSeleccion) {
        this.marcadorSeleccion.setPosition({ lat, lng });
      } else {
        this.marcadorSeleccion = new google.maps.Marker({
          position: { lat, lng },
          map: this.mapa,
          draggable: true
        });
        this.marcadorSeleccion.addListener('dragend', e => {
          this.fijarSeleccion(e.latLng.lat(), e.latLng.lng());
        });
      }
      this.centrarEn(lat, lng, zoom);
      if (this.alSeleccionar) this.alSeleccionar(lat, lng);
    }

    posicionSeleccion() {
      if (!this.marcadorSeleccion) return null;
      const p = this.marcadorSeleccion.getPosition();
      return { lat: p.lat(), lng: p.lng() };
    }

    refrescar() {
      google.maps.event.trigger(this.mapa, 'resize');
      this.mapa.setCenter(this.mapa.getCenter());
    }
  }

  /* ------------------------------------------------------------- Leaflet */
  class MapaLeaflet extends MapaBase {
    /** Toma tiles y limites de zoom de LEAFLET_CONFIG (settings.py). */
    _crear() {
      const cfg = CONFIG.leaflet || {};

      this.mapa = L.map(this.contenedor, {
        minZoom: cfg.MIN_ZOOM || undefined,
        maxZoom: cfg.MAX_ZOOM || undefined
      }).setView(this.centro, this.zoom);

      const capas = (cfg.TILES && cfg.TILES.length)
        ? cfg.TILES
        : [['OpenStreetMap', 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            { attribution: '&copy; OpenStreetMap' }]];

      capas.forEach(([nombre, url, opciones]) => {
        L.tileLayer(url, opciones || {}).addTo(this.mapa);
      });

      if (cfg.ATTRIBUTION_PREFIX) {
        this.mapa.attributionControl.setPrefix(cfg.ATTRIBUTION_PREFIX);
      }
      if (cfg.SCALE === 'metric') {
        L.control.scale({ imperial: false }).addTo(this.mapa);
      }

      this.grupo = (typeof L.markerClusterGroup === 'function')
        ? L.markerClusterGroup({ maxClusterRadius: 45 })
        : L.layerGroup();
      this.mapa.addLayer(this.grupo);
      return this;
    }

    agregarMarcador({ lat, lng, color, titulo, html }) {
      const marcador = L.circleMarker([lat, lng], {
        radius: 8, color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.92
      });
      if (html) marcador.bindPopup(html);
      if (titulo) marcador.bindTooltip(titulo);
      this.grupo.addLayer(marcador);
      this.marcadores.push(marcador);
      return marcador;
    }

    agrupar() { /* Leaflet ya agrupa al agregar al grupo */ }

    limpiarMarcadores() {
      this.grupo.clearLayers();
      this.marcadores = [];
    }

    ajustarVista() {
      if (!this.marcadores.length) return;
      this.mapa.fitBounds(this.grupo.getBounds().pad(0.2));
    }

    centrarEn(lat, lng, zoom) {
      this.mapa.setView([lat, lng], zoom || this.mapa.getZoom());
    }

    habilitarSeleccion(callback) {
      this.alSeleccionar = callback;
      this.mapa.on('click', e => this.fijarSeleccion(e.latlng.lat, e.latlng.lng));
    }

    fijarSeleccion(lat, lng, zoom) {
      if (this.marcadorSeleccion) {
        this.marcadorSeleccion.setLatLng([lat, lng]);
      } else {
        this.marcadorSeleccion = L.marker([lat, lng], { draggable: true }).addTo(this.mapa);
        this.marcadorSeleccion.on('dragend', e => {
          const p = e.target.getLatLng();
          this.fijarSeleccion(p.lat, p.lng);
        });
      }
      this.centrarEn(lat, lng, zoom);
      if (this.alSeleccionar) this.alSeleccionar(lat, lng);
    }

    posicionSeleccion() {
      if (!this.marcadorSeleccion) return null;
      const p = this.marcadorSeleccion.getLatLng();
      return { lat: p.lat, lng: p.lng };
    }

    refrescar() {
      this.mapa.invalidateSize();
    }
  }

  /* --------------------------------------------------------------- Factory */

  /** Se resuelve cuando el proveedor elegido termino de cargar. */
  const proveedorListo = HAY_GOOGLE
    ? (global.googleMapsListo || Promise.resolve())
    : Promise.resolve();

  /**
   * Crea un mapa ya inicializado.
   *
   * `centro` y `zoom` son opcionales: por defecto se toman de CONFIG_MAPAS, que
   * los recibe como JSON desde el servidor. Interpolar numeros directamente en
   * las plantillas los rompe con locales de coma decimal (es-PE).
   *
   * @returns {Promise<MapaBase>}
   */
  function crearMapa(opciones) {
    const ajustes = Object.assign(
      { centro: CONFIG.centro || [-15.65, -70.1], zoom: CONFIG.zoom || 9 },
      opciones || {}
    );

    if (!Array.isArray(ajustes.centro) || ajustes.centro.length !== 2
        || ajustes.centro.some(n => typeof n !== 'number' || Number.isNaN(n))) {
      return Promise.reject(
        new Error('Centro del mapa invalido: ' + JSON.stringify(ajustes.centro))
      );
    }

    return proveedorListo.then(() => {
      const Clase = (HAY_GOOGLE && global.google && global.google.maps)
        ? MapaGoogle
        : MapaLeaflet;
      const mapa = new Clase(ajustes)._crear();

      // Un mapa creado dentro de un contenedor que aun se esta acomodando
      // necesita un empujon para calcular bien su tamano.
      setTimeout(() => mapa.refrescar(), 250);
      return mapa;
    });
  }

  /* -------------------------------------------------- Georreferenciacion */

  /**
   * Cliente de los endpoints de geopy/Nominatim.
   * El trabajo real ocurre en el servidor (apps/analisis/geocodificacion.py);
   * aqui solo se consulta y se controla que no se dispare en cada tecla.
   */
  class Geocodificador {
    constructor({ urlBuscar, urlInversa, retardo = 500 } = {}) {
      this.urlBuscar = urlBuscar || CONFIG.urlBuscarDireccion;
      this.urlInversa = urlInversa || CONFIG.urlDireccionInversa;
      this.retardo = retardo;
      this._temporizador = null;
    }

    /** Busca una direccion. Espera a que el usuario deje de escribir. */
    buscar(texto) {
      clearTimeout(this._temporizador);
      return new Promise((resolver, rechazar) => {
        if (!texto || texto.trim().length < 3) {
          resolver([]);
          return;
        }
        this._temporizador = setTimeout(() => {
          fetch(`${this.urlBuscar}?q=${encodeURIComponent(texto)}`)
            .then(r => r.json())
            .then(d => (d.ok ? resolver(d.resultados) : rechazar(new Error(d.error))))
            .catch(rechazar);
        }, this.retardo);
      });
    }

    /** Coordenadas -> direccion legible. */
    direccionDe(lat, lng) {
      return fetch(`${this.urlInversa}?lat=${lat}&lng=${lng}`)
        .then(r => r.json())
        .then(d => (d.ok ? d.direccion : ''))
        .catch(() => '');
    }
  }

  /* ------------------------------------------------ Puente con Google Maps */

  /**
   * Interpreta coordenadas copiadas de Google Maps.
   *
   * Acepta lo que Google entrega al hacer clic derecho ("-15.4997, -70.1330")
   * y tambien el enlace de la barra de direcciones, en sus formas habituales:
   *   .../maps/@-15.4997,-70.1330,17z
   *   .../maps/place/Algo/@-15.4997,-70.1330,17z/...
   *   .../maps?q=-15.4997,-70.1330
   *
   * @returns {{lat:number, lng:number}|null}
   */
  function parsearCoordenadas(texto) {
    if (!texto) return null;
    const limpio = String(texto).trim();

    const patrones = [
      /@(-?\d{1,3}(?:\.\d+)?),\s*(-?\d{1,3}(?:\.\d+)?)/,        // .../@lat,lng,17z
      // Los nombres largos van primero: "q" tambien casaria dentro de "query".
      /[?&](?:query|daddr|center|saddr|ll|q)=(-?\d{1,3}(?:\.\d+)?),\s*(-?\d{1,3}(?:\.\d+)?)/i,
      /^(-?\d{1,3}(?:\.\d+)?)[,;\s]+(-?\d{1,3}(?:\.\d+)?)$/     // "lat, lng" a secas
    ];

    for (const patron of patrones) {
      const m = limpio.match(patron);
      if (!m) continue;
      const lat = parseFloat(m[1]);
      const lng = parseFloat(m[2]);
      if (Number.isFinite(lat) && Number.isFinite(lng)
          && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
        return { lat, lng };
      }
    }
    return null;
  }

  /** Enlace que abre ese punto en Google Maps (no necesita clave). */
  function enlaceGoogleMaps(lat, lng, zoom) {
    return `https://www.google.com/maps/@${lat},${lng},${zoom || 18}z`;
  }

  /** Enlace con marcador y ficha del lugar. */
  function enlaceGoogleMapsPunto(lat, lng) {
    return `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
  }

  global.MapaBase = MapaBase;
  global.Geocodificador = Geocodificador;
  global.crearMapa = crearMapa;
  global.mapaUsaGoogle = () => HAY_GOOGLE;
  global.parsearCoordenadas = parsearCoordenadas;
  global.enlaceGoogleMaps = enlaceGoogleMaps;
  global.enlaceGoogleMapsPunto = enlaceGoogleMapsPunto;

})(window);
