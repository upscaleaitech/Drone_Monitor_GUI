from __future__ import annotations
from typing import Optional, Tuple
from PySide6 import QtWidgets, QtCore, QtGui
from serial_location_reader import SerialLocationReader

# Try to use the embedded browser for the map (Leaflet)
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEB_OK = True
except Exception:
    WEB_OK = False

# ---------------- Theme ----------------
BG        = "#0f141a"
CARD      = "#161d24"
CARD_DARK = "#121820"
BORDER    = "#283442"
TEXT      = "#d7e0ea"
MUTED     = "#8fa5b5"
GREEN     = "#2e7d32"   # ARMED banner color
RED       = "#c73333"   # DISARMED banner color
ACCENT    = "#7CFC99"
WARN      = "#ffd166"
ERR       = "#ff6b6b"

APP_QSS = f"""
QMainWindow {{ background:{BG}; color:{TEXT}; font-family:Segoe UI,Inter,system-ui,Arial; font-size:13px; }}
QGroupBox {{ background:{CARD}; border:1px solid {BORDER}; border-radius:14px; margin-top:12px; padding:10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left:14px; top:2px; color:{MUTED}; padding:0 6px; background:{CARD_DARK}; border-radius:8px; }}
QLabel#title {{ color:{MUTED}; }}
QLabel[value="true"] {{ color:{ACCENT}; font-weight:600; }}
QSplitter::handle {{ background:{BG}; width:6px; }}
"""

MODE_NAMES = {0: "MANUAL", 1: "STABILIZE", 2: "ALT HOLD", 3: "LOITER", 4: "AUTO"}

# ---------------- Leaflet page ----------------
LEAFLET_HTML = f"""
<!doctype html><html><head>
<meta charset='utf-8'><meta name='viewport' content='initial-scale=1,width=device-width'>
<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<style>
  html,body {{height:100%; margin:0; background:{BG}; display:flex; flex-direction:column;}}
  #map {{ flex:1 1 auto; width:100%; background:#0a0f14; }}
  #map .leaflet-tile {{ image-rendering:auto; }}

  #coordbar {{
      height:36px; background:#000; color:{ACCENT}; border-top:1px solid #222;
      display:flex; align-items:center; gap:10px; padding:0 14px; font:15px Consolas,monospace;
  }}
  #coord {{ color:{ACCENT}; }}
  #conn {{
      margin-left:auto; padding:4px 10px; border-radius:12px; border:1px solid {BORDER};
      background:{CARD_DARK}cc; color:{TEXT}; font:13px Consolas,monospace;
  }}
  #conn.ok {{ color:{ACCENT}; }} #conn.wait {{ color:{WARN}; }} #conn.err {{ color:{ERR}; }}

  /* Drone icon */
  .drone-icon{{ width:56px; height:56px; position:relative;
    transform-origin:50% 50%; transform: translateZ(0);
    will-change: transform;
    pointer-events:none; z-index:10000;
    filter: drop-shadow(0 1px 3px rgba(0,0,0,.75));
  }}
  .drone-icon svg{{ width:56px; height:56px; display:block; }}

  .pulse{{ position:absolute; left:50%; top:50%;
    width:64px; height:64px; margin:-32px 0 0 -32px; border-radius:50%;
    background:rgba(0,214,255,.18); box-shadow:0 0 0 0 rgba(0,214,255,.45);
    animation:pulse 1.6s ease-out infinite;
  }}
  @keyframes pulse{{
    0%   {{ transform:scale(.55); box-shadow:0 0 0 0 rgba(0,214,255,.45); }}
    70%  {{ transform:scale(1);   box-shadow:0 0 0 18px rgba(0,214,255,0); }}
    100% {{ transform:scale(.55); box-shadow:0 0 0 0 rgba(0,214,255,0); }}
  }}

  .altTip {{ background:#0000; border:none; box-shadow:none; color:#fff; font-weight:700;
             text-shadow:0 1px 3px #000; font-family:Segoe UI,Arial; }}
  .leaflet-control-attribution {{ font-size:11px; opacity:.85; }}

  /* Move Leaflet controls to bottom-right with margin */
  .leaflet-bottom.leaflet-right {{ margin:0 10px 48px 0; }}
</style></head><body>
<div id='map'></div>
<div id='coordbar'>
  <span id='coord'>--</span>
  <span id='conn' class='wait'>Connecting…</span>
</div>
<script>
  var map = L.map('map', {{
    worldCopyJump:true,
    zoomControl:true,
    zoomAnimation:false,
    markerZoomAnimation:false,
    fadeAnimation:false,
    zoomSnap:1,
    scrollWheelZoom:true
  }});
  map.setView([0,0], 2);

  var osmStandard = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19, detectRetina: false, updateWhenIdle: true, keepBuffer: 6,
    attribution: '&copy; OpenStreetMap contributors'
  }});

  var cartoLight = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    maxZoom: 20, detectRetina: false, keepBuffer: 6,
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
  }});

  var cartoDark = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    maxZoom: 20, detectRetina: false, keepBuffer: 6,
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
  }});

  var osmHOT = L.tileLayer('https://{{s}}.tile.openstreetmap.fr/hot/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 20, detectRetina: false, keepBuffer: 6,
    attribution: '&copy; OpenStreetMap France, &copy; OpenStreetMap contributors'
  }});

  var base = cartoLight.addTo(map);

  L.control.layers(
    {{
      'Carto Light (labels clear)': cartoLight,
      'Carto Dark': cartoDark,
      'OSM Standard': osmStandard,
      'OSM Humanitarian': osmHOT
    }},
    {{}},
    {{ position: 'bottomright', collapsed: true }}
  ).addTo(map);

  var path = L.polyline([], {{color:'red', weight:3, opacity:0.9}}).addTo(map);
  var marker=null, altTip=null, iconEl=null, lastPt=null;
  var coordEl = document.getElementById('coord');
  var connEl  = document.getElementById('conn');

  function setConn(text,state){{
    if(!connEl) return;
    connEl.textContent=text||'';
    connEl.classList.remove('ok','wait','err');
    connEl.classList.add(state==1?'ok':state==0?'wait':'err');
  }}

  function droneSVG(){{
    return `
    <div class="drone-icon">
      <div class="pulse"></div>
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <defs>
          <g id="arm">
            <circle cx="0" cy="0" r="6" fill="#ffffff" stroke="#111" stroke-width="1.6"/>
            <rect x="-14" y="-2" width="28" height="4" rx="2" fill="#ffffff" stroke="#111" stroke-width="1.2"/>
          </g>
        </defs>
        <path d="M32 5 L38 18 L32 16 L26 18 Z" fill="#00d6ff" stroke="#003344" stroke-width="1.4"/>
        <g transform="translate(32,32) rotate(0)"><use href="#arm"/></g>
        <g transform="translate(32,32) rotate(90)"><use href="#arm"/></g>
        <circle cx="32" cy="32" r="7.5" fill="#ffffff" stroke="#111" stroke-width="1.8"/>
      </svg>
    </div>`;
  }}

  function ensureMarker(lat, lon){{
    if(!marker){{
      const icon = L.divIcon({{
        className:'', html:droneSVG(),
        iconSize:[56,56], iconAnchor:[28,28]
      }});
      marker = L.marker([lat,lon], {{icon, zIndexOffset:10000}}).addTo(map);
      altTip = L.tooltip({{permanent:true, direction:'bottom', className:'altTip', offset:[0,28]}})
                .setLatLng([lat,lon]).setContent('').addTo(map);
      if(path.bringToBack) path.bringToBack();
      if(marker.bringToFront) marker.bringToFront();
      const root = marker.getElement ? marker.getElement() : (marker._icon||null);
      iconEl = root ? root.querySelector('.drone-icon') : null;
    }}
  }}

  function setDrone(lat, lon, yawDeg, alt, jump, trail){{
    ensureMarker(lat, lon);
    marker.setLatLng([lat,lon]);
    if (iconEl) {{
      iconEl.style.transform = 'rotate(' + (yawDeg||0) + 'deg) translateZ(0)';
    }}
    if (altTip) {{
      altTip.setLatLng([lat,lon]).setContent(alt != null ? (Math.round(alt) + ' m') : '');
    }}
    if (trail) {{
      var pt = L.latLng(lat,lon);
      if (!lastPt || pt.distanceTo(lastPt) > 0.5) {{
        path.addLatLng(pt);
        lastPt = pt;
      }}
    }}
    if (jump) {{
      var z = map.getZoom();
      map.setView([lat,lon], (z && z > 2) ? z : 13);
    }}
    if (coordEl) coordEl.textContent = lat.toFixed(5) + ', ' + lon.toFixed(5);
    if (marker.bringToFront) marker.bringToFront();
    if (marker.setZIndexOffset) marker.setZIndexOffset(10000);
  }}

  function invalidateMap() {{ try {{ map.invalidateSize(true); }} catch(e) {{}} }}
  window.addEventListener('resize', invalidateMap);

  window.setConn  = setConn;
  window.setDrone = setDrone;
  window.invalidateMap = invalidateMap;

  setConn('Initializing…', 0);
</script></body></html>
"""
# ---------------- Map widget with throttled JS + maximize button ----------------
class MapView(QtWidgets.QWidget):
    """
    Throttles UI->JS updates (~15 FPS) and provides a maximize/restore button.
    """
    toggleMaximize = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stack = QtWidgets.QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)

        # offline placeholder
        self.offline = QtWidgets.QWidget(self)
        v = QtWidgets.QVBoxLayout(self.offline); v.setContentsMargins(0, 0, 0, 0)
        v.addStretch(1)
        msg = QtWidgets.QLabel("Web map is OFF (offline mode)", alignment=QtCore.Qt.AlignCenter)
        msg.setStyleSheet(f"color:{MUTED}; background:{BG};")
        v.addWidget(msg)
        v.addStretch(1)
        self.stack.addWidget(self.offline)

        # web view
        self.web: QWebEngineView | None = None
        self._ready = False

        # throttled state
        self._pending_conn: Optional[Tuple[str, int]] = None
        self._pending_drone: Optional[Tuple[float, float, Optional[float], Optional[float], bool, bool]] = None

        # flush timer (~15 FPS)
        self._flush = QtCore.QTimer(self)
        self._flush.setInterval(66)
        self._flush.timeout.connect(self._flush_tick)

        if WEB_OK:
            self.web = QWebEngineView(self)
            self.web.loadFinished.connect(self._on_load)
            self.web.setHtml(LEAFLET_HTML)
            self.stack.addWidget(self.web)
            self.stack.setCurrentWidget(self.web)
        else:
            self.stack.setCurrentWidget(self.offline)

        # overlay maximize button (⤢ / ⤡)
        self.maxBtn = QtWidgets.QToolButton(self)
        self.maxBtn.setText("⤢")
        self.maxBtn.setToolTip("Maximize map")
        self.maxBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.maxBtn.setAutoRaise(True)
        self.maxBtn.setStyleSheet(
            "QToolButton{background:rgba(0,0,0,.55); color:white; border:1px solid #333; "
            "border-radius:6px; padding:4px 8px; font:16px 'Segoe UI Symbol','Segoe UI';}"
            "QToolButton:hover{background:rgba(0,0,0,.75);}"
        )
        self.maxBtn.clicked.connect(self.toggleMaximize)

    # --- lifecycle ---
    def _on_load(self, ok: bool):
        self._ready = bool(ok)
        if self._ready and self.web:
            self.web.setZoomFactor(1.0)           # avoid extra WebEngine scaling
            self._run_js("invalidateMap();")       # ensure correct initial tiling
            if not self._flush.isActive():
                self._flush.start()

    def _run_js(self, code: str):
        if self.web and self._ready and self.stack.currentWidget() is self.web:
            self.web.page().runJavaScript(code)

    def _flush_tick(self):
        if self._pending_conn is not None:
            text, state = self._pending_conn
            t = (text or "").replace("\\", "\\\\").replace("'", "\\'")
            self._run_js(f"setConn('{t}', {int(state)});")
            self._pending_conn = None

        if self._pending_drone is not None:
            lat, lon, yaw, alt, jump, trail = self._pending_drone
            y = 0.0 if yaw is None else float(yaw)
            a = "null" if alt is None else f"{float(alt):.1f}"
            self._run_js(f"setDrone({lat:.7f},{lon:.7f},{y:.1f},{a},{str(bool(jump)).lower()},{str(bool(trail)).lower()});")
            self._pending_drone = None

    # --- External control ---
    def use_web(self, enabled: bool):
        self.stack.setCurrentWidget(self.web if (enabled and self.web) else self.offline)
        if enabled and self.web and self._ready and not self._flush.isActive():
            self._flush.start()
        if not enabled and self._flush.isActive():
            self._flush.stop()
        self._run_js("invalidateMap();")

    def is_web_active(self) -> bool:
        return self.stack.currentWidget() is self.web

    # --- Telemetry hooks (throttled) ---
    @QtCore.Slot(float, float, object, object, bool, bool)
    def set_drone(self, lat: float, lon: float, yaw_deg: float | None, alt: float | None, jump: bool, trail: bool = True):
        self._pending_drone = (float(lat), float(lon), yaw_deg, alt, bool(jump), bool(trail))

    @QtCore.Slot(str, int)
    def set_conn(self, text: str, state: int):
        self._pending_conn = (text, int(state))

    def set_city(self, text: str):
        pass

    def resizeEvent(self, e: QtGui.QResizeEvent) -> None:
        super().resizeEvent(e)
        # keep button top-right with 10px margin
        self.maxBtn.adjustSize()
        m = 10
        self.maxBtn.move(self.width() - self.maxBtn.width() - m, m)
        # force Leaflet to recalc tiles exactly on any resize
        QtCore.QTimer.singleShot(0, lambda: self._run_js("invalidateMap();"))

# ---------------- Main window ----------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GUI")
        self.resize(1280, 720)
        self.setStyleSheet(APP_QSS)

        # Top strip (logo placeholder on right)
        topstrip = QtWidgets.QWidget()
        topstrip.setFixedHeight(52)
        topstrip.setStyleSheet(f"background:{BG};")
        ts = QtWidgets.QHBoxLayout(topstrip); ts.setContentsMargins(12,8,12,8); ts.setSpacing(8)
        ts.addStretch(1)
        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setFixedHeight(36)
        self.logo_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight)
        ts.addWidget(self.logo_label, 0)

        # Left column (banner + cards)
        left = QtWidgets.QWidget(objectName="leftPanel")
        lv = QtWidgets.QVBoxLayout(left); lv.setContentsMargins(10,10,10,10); lv.setSpacing(10)

        # ARMED/DISARMED banner (left column only)
        self.bannerFill = QtWidgets.QFrame(objectName="statusBanner")
        self.bannerFill.setFixedHeight(44)
        self.bannerFill.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        bf = QtWidgets.QHBoxLayout(self.bannerFill); bf.setContentsMargins(16,6,16,6); bf.setSpacing(6)
        self.bannerLabel = QtWidgets.QLabel("DISARMED")
        self.bannerLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.bannerLabel.setStyleSheet("color:white; font-size:20px; font-weight:700;")
        bf.addWidget(self.bannerLabel, 1)
        lv.addWidget(self.bannerFill)

        # Cards
        self.card_pos  = self._card("Position",[("Latitude (°)","lat"),("Longitude (°)","lon"),("Altitude (m)","alt")])
        self.card_stat = self._card("Status",[("Mode","mode"),("Arm Status","arm"),("Battery Voltage (V)","bat"),
                                              ("Remaining Flight Time (min)","remain"),("GPS Sats","sats"),("GPS Fix","fix")])
        self.card_att  = self._card("Attitude",[("Pitch (°)","pitch"),("Roll (°)","roll"),("Yaw (°)","yaw")])
        self.card_spd  = self._card("Speed",[("X (m/s)","vx"),("Y (m/s)","vy"),("Z (m/s)","vz")])
        for c in (self.card_pos,self.card_stat,self.card_att,self.card_spd): lv.addWidget(c)
        lv.addStretch(1)

        # Map
        self.map = MapView()
        self.map.toggleMaximize.connect(self._toggle_map_max)

        # Splitter
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(left); split.addWidget(self.map)
        split.setSizes([420, 860]); split.setStretchFactor(0,0); split.setStretchFactor(1,1)

        # Central layout
        central = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(central); cv.setContentsMargins(0,0,0,0); cv.setSpacing(0)
        cv.addWidget(topstrip)
        cv.addWidget(split, 1)
        self.setCentralWidget(central)

        # Keep refs for maximize logic
        self._left_panel = left
        self._split = split
        self._prev_sizes: list[int] | None = None
        self._map_maximized = False

        # Serial/telemetry state
        self.serialThread: SerialLocationReader | None = None
        self._got_first_fix = False
        self._last_alt: float | None = None
        self._last_yaw_val: float | None = None
        self._port = "N/A"; self._baud = 0
        self._conn_state: int | None = None
        self.follow_mode = True

        # Initial banner
        self._update_banner(False)

    # ---- helpers ----
    def _set_banner_color(self, color: str):
        self.bannerFill.setStyleSheet(f"QFrame#statusBanner {{ background:{color}; border-radius:12px; }}")

    def _update_banner(self, armed: bool):
        self._set_banner_color(GREEN if armed else RED)
        self.bannerLabel.setText("ARMED" if armed else "DISARMED")

    def _card(self, title: str, rows: list[tuple[str,str]]) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox(title)
        grid = QtWidgets.QGridLayout(g); grid.setHorizontalSpacing(16); grid.setVerticalSpacing(10)
        self._labels = getattr(self, "_labels", {})
        def vlabel():
            w = QtWidgets.QLabel("--"); w.setProperty("value","true")
            f = w.font(); f.setBold(True); w.setFont(f); w.setStyleSheet(f"color:{ACCENT};")
            w.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter); return w
        for r,(name,key) in enumerate(rows):
            t = QtWidgets.QLabel(name); t.setObjectName("title")
            t.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            v = vlabel(); grid.addWidget(t, r, 0); grid.addWidget(v, r, 1); self._labels[key] = v
        g.setLayout(grid)
        return g

    # ---- serial / telemetry wiring ----
    def start_serial_location(self, *, port: str, baud: int = 115200,
                              lines: bool=True, chunk: int=512,
                              logfile: str|None=None, binfile: str|None=None,
                              hexdump: str|None=None, hexwidth: int=16):
        self._port, self._baud = port, baud
        self._set_conn(0)  # Connecting…
        if self.serialThread:
            self.serialThread.stop(); self.serialThread.wait()
        self.serialThread = SerialLocationReader(port, baud, lines, chunk,
                                                logfile, binfile, hexdump, hexwidth, self)
        self.serialThread.locationReceived.connect(self._on_location)
        self.serialThread.telemetryReceived.connect(self._on_telemetry)
        self.serialThread.lineReceived.connect(self._on_serial_line)
        self.serialThread.start()

    def _set_conn(self, state: int):
        if self._conn_state != state:
            self._conn_state = state
            self.map.set_conn(f"{self._port} @ {self._baud} • " +
                              ("Connected" if state==1 else "Connecting…" if state==0 else "ERROR"),
                              state)

    @QtCore.Slot(float, float)
    def _on_location(self, lat: float, lon: float):
        self._set_conn(1)
        self._labels["lat"].setText(f"{lat:.6f}")
        self._labels["lon"].setText(f"{lon:.6f}")
        jump = (not self._got_first_fix) or self.follow_mode
        self.map.set_drone(lat, lon, yaw_deg=self._last_yaw_val, alt=self._last_alt, jump=jump, trail=True)
        self._got_first_fix = True

    @QtCore.Slot(object)
    def _on_telemetry(self, pkt: dict):
        if "latitude" in pkt:  self._labels["lat"].setText(f"{pkt['latitude']:.6f}")
        if "longitude" in pkt: self._labels["lon"].setText(f"{pkt['longitude']:.6f}")
        if "altitude" in pkt:  self._last_alt = float(pkt["altitude"]); self._labels["alt"].setText(f"{self._last_alt:.1f}")
        if "mode" in pkt:      self._labels["mode"].setText(MODE_NAMES.get(int(pkt["mode"]), str(pkt["mode"])))
        if "armed" in pkt:
            armed = bool(pkt["armed"])
            self._update_banner(armed)
            self._labels["arm"].setText("ARMED" if armed else "DISARMED")
        if "battery_voltage" in pkt:
            v=float(pkt["battery_voltage"]); self._labels["bat"].setText(f"{v:.1f}")
        if "remaining_minutes" in pkt: self._labels["remain"].setText(f"{float(pkt['remaining_minutes']):.1f}")
        if "gps_sats" in pkt:   self._labels["sats"].setText(str(int(pkt["gps_sats"])))
        if "gps_fix" in pkt:    self._labels["fix"].setText({0:"No Fix",2:"2D",3:"3D"}.get(int(pkt["gps_fix"]), str(pkt["gps_fix"])))
        for k in ("pitch","roll","yaw"):
            if k in pkt:
                val=float(pkt[k]); self._labels[k].setText(f"{val:.1f}")
                if k=="yaw": self._last_yaw_val = val
        for k in ("vx","vy","vz"):
            if k in pkt: self._labels[k].setText(f"{float(pkt[k]):.2f}")
        if ("latitude" in pkt) and ("longitude" in pkt):
            self.map.set_drone(float(pkt["latitude"]), float(pkt["longitude"]),
                               yaw_deg=self._last_yaw_val, alt=self._last_alt,
                               jump=self.follow_mode, trail=True)

    @QtCore.Slot(str)
    def _on_serial_line(self, text: str):
        if text.startswith("[Serial error]"):
            self._set_conn(-1)
        else:
            self._set_conn(1)

    def closeEvent(self, e: QtGui.QCloseEvent):
        if self.serialThread:
            self.serialThread.stop(); self.serialThread.wait(1000)
        self._set_conn(-1)
        super().closeEvent(e)

    def set_webmap_mode(self, mode: str):
        if mode == "on":
            self.map.use_web(True)
        elif mode == "off":
            self.map.use_web(False)

    # --- maximize/restore the map pane ---
    def _toggle_map_max(self):
        if not self._map_maximized:
            self._prev_sizes = self._split.sizes()
            self._left_panel.hide()
            self._split.setSizes([0, 1_000_000])
            self.map.maxBtn.setText("⤡")
            self.map.maxBtn.setToolTip("Restore layout")
            self._map_maximized = True
        else:
            self._left_panel.show()
            if self._prev_sizes and any(self._prev_sizes):
                self._split.setSizes(self._prev_sizes)
            else:
                self._split.setSizes([420, 860])
            self.map.maxBtn.setText("⤢")
            self.map.maxBtn.setToolTip("Maximize map")
            self._map_maximized = False
        QtCore.QTimer.singleShot(0, lambda: self.map._run_js("invalidateMap();"))
