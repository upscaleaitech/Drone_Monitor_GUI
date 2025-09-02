from __future__ import annotations
from PySide6 import QtCore
import serial, serial.tools.list_ports  # noqa: F401
import json, time, re, os
from datetime import datetime

# --- small performance helpers ---
_HEX = [f"{i:02X}" for i in range(256)]
_ASCII_MAP = bytes([c if 32 <= c < 127 else ord(".") for c in range(256)])


def _ascii_gutter(b: bytes) -> str:
    # translate() is in C, then ASCII decode
    return b.translate(_ASCII_MAP).decode("ascii", "strict")


class SerialLocationReader(QtCore.QThread):
    # Signals
    locationReceived = QtCore.Signal(float, float)
    telemetryReceived = QtCore.Signal(object)
    lineReceived = QtCore.Signal(str)

    def __init__(
        self,
        port: str,
        baud: int = 115200,
        lines: bool = True,
        chunk: int = 512,
        logfile: str | None = None,
        binfile: str | None = None,
        hexdump: str | None = None,
        hexwidth: int = 16,
        parent=None,
    ):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.lines = bool(lines)
        self.chunk = max(1, int(chunk))

        self.logfile = logfile
        self.binfile = binfile
        self.hexdump_path = hexdump
        self.hexwidth = max(8, int(hexwidth))

        self._stop = False
        self._ser: serial.Serial | None = None

        # opened once
        self._log_fp = None
        self._bin_fp = None
        self._hex_fp = None
        self._hex_addr = 0

        # flush throttling (less I/O CPU)
        self._flush_interval_ms = 250
        self._next_flush_t = time.perf_counter() + (self._flush_interval_ms / 1000.0)

        # patterns (precompiled)
        self._re_loc = re.compile(
            r"Location:\s*([+-]?\d+(?:\.\d+)?)[,\s]+([+-]?\d+(?:\.\d+)?)",
            re.I,
        )
        # literal U+1F4CD (📍), not surrogate pair
        self._re_emoji_loc = re.compile(
            r"\N{ROUND PUSHPIN}\s*Location:\s*([+-]?\d+(?:\.\d+)?)[,\s]+([+-]?\d+(?:\.\d+)?)",
            re.I,
        )
        self._re_latlon_pair = re.compile(
            r"Lat(?:itude)?:\s*([+-]?\d+(?:\.\d+)?)\D+Lon(?:gitude)?:\s*([+-]?\d+(?:\.\d+)?)",
            re.I,
        )

        # JSON framing
        self._json_buf = []
        self._json_depth = 0
        self._json_in_string = False
        self._json_escape = False

    # ------------- control -------------
    def stop(self):
        self._stop = True

    # ------------- serial --------------
    def _open_serial(self):
        # small timeout; readline uses it as line timeout
        self._ser = serial.Serial(self.port, self.baud, timeout=0.2)
        # give FTDI a tick
        time.sleep(0.05)

    # ------------- files ---------------
    def _safe_open(self, path: str, mode: str, **kw):
        try:
            if path:
                os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
                return open(path, mode, **kw)
        except Exception as e:
            self.lineReceived.emit(f"[Serial error] failed to open {path}: {e}")
        return None

    def _open_files(self):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.logfile:
            self._log_fp = self._safe_open(self.logfile, "a", encoding="utf-8", newline="")
            if self._log_fp:
                self._log_fp.write(f"=== LOG START {ts} ===\n")
                self._log_fp.flush()
                self.lineReceived.emit(f"[info] Logging to {os.path.abspath(self.logfile)}")

        if self.binfile:
            self._bin_fp = self._safe_open(self.binfile, "ab")
            if self._bin_fp:
                self.lineReceived.emit(f"[info] Binary capture -> {os.path.abspath(self.binfile)}")

        if self.hexdump_path:
            self._hex_fp = self._safe_open(self.hexdump_path, "a", encoding="utf-8", newline="")
            if self._hex_fp:
                self._hex_addr = 0
                self.lineReceived.emit(f"[info] Hex dump -> {os.path.abspath(self.hexdump_path)}")

    def _flush_if_due(self):
        now = time.perf_counter()
        if now >= self._next_flush_t:
            for fp in (self._log_fp, self._bin_fp, self._hex_fp):
                try:
                    fp and fp.flush()
                except Exception:
                    pass
            # next tick
            self._next_flush_t = now + (self._flush_interval_ms / 1000.0)

    def _close_files(self):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if self._log_fp:
                self._log_fp.write(f"=== LOG END {ts} ===\n")
        except Exception:
            pass
        for fp in (self._log_fp, self._bin_fp, self._hex_fp):
            try:
                fp and fp.flush()
                fp and fp.close()
            except Exception:
                pass
        self._log_fp = self._bin_fp = self._hex_fp = None

    # ------------- logging -------------
    def _log_text(self, s: str):
        if not self._log_fp:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        try:
            self._log_fp.write(f"{ts} {s}\n")
        except Exception as e:
            self.lineReceived.emit(f"[Serial error] logfile write failed: {e}")

    def _log_bin_and_hex(self, data: bytes):
        if not data:
            return
        # raw bin (buffered; flush throttled)
        if self._bin_fp:
            try:
                self._bin_fp.write(data)
            except Exception as e:
                self.lineReceived.emit(f"[Serial error] binfile write failed: {e}")

        # hexdump (continuous address; fast ASCII/HEX)
        if self._hex_fp:
            w = self.hexwidth
            mv = memoryview(data)
            n = len(mv)
            i = 0
            # prebuild lines into a local list, then write once
            out_lines = []
            while i < n:
                chunk = mv[i : i + w]
                hexs = " ".join(_HEX[b] for b in chunk)
                asc = _ascii_gutter(chunk.tobytes())
                out_lines.append(f"{self._hex_addr:08X}: {hexs:<{w*3}} |{asc}|")
                self._hex_addr += len(chunk)
                i += w
            try:
                self._hex_fp.write("\n".join(out_lines) + "\n")
            except Exception as e:
                self.lineReceived.emit(f"[Serial error] hexdump write failed: {e}")

    # ------------- parsing -------------
    def _emit_latlon(self, lat: float, lon: float):
        self.locationReceived.emit(lat, lon)
        self.telemetryReceived.emit({"latitude": lat, "longitude": lon})

    def _parse_line_for_location(self, line: str) -> bool:
        m = self._re_loc.search(line) or self._re_emoji_loc.search(line)
        if m:
            try:
                self._emit_latlon(float(m.group(1)), float(m.group(2)))
                return True
            except Exception:
                return False
        m2 = self._re_latlon_pair.search(line)
        if m2:
            try:
                self._emit_latlon(float(m2.group(1)), float(m2.group(2)))
                return True
            except Exception:
                return False
        return False

    # robust multiline JSON framing with brace depth (ignores braces inside strings)
    def _feed_json_line(self, line: str):
        if not line:
            return

        # Fast path: whole object on one line
        s = line.lstrip()
        if s.startswith("{") and s.rstrip().endswith("}"):
            try:
                obj = json.loads(line)
            except Exception:
                return
            self._emit_json(obj)
            return

        # Streaming path
        for ch in line:
            if self._json_in_string:
                if self._json_escape:
                    self._json_escape = False
                elif ch == "\\":
                    self._json_escape = True
                elif ch == '"':
                    self._json_in_string = False
            else:
                if ch == '"':
                    self._json_in_string = True
                elif ch == "{":
                    self._json_depth += 1
                elif ch == "}":
                    self._json_depth -= 1
            self._json_buf.append(ch)

        if self._json_depth == 0 and self._json_buf:
            payload = "".join(self._json_buf).strip()
            self._json_buf.clear()
            self._json_in_string = False
            self._json_escape = False
            if payload.startswith("{") and payload.endswith("}"):
                try:
                    obj = json.loads(payload)
                except Exception:
                    return
                self._emit_json(obj)

    def _emit_json(self, obj: dict):
        pkt = {}
        for k in (
            "latitude",
            "longitude",
            "altitude",
            "mode",
            "armed",
            "battery_voltage",
            "remaining_minutes",
            "gps_sats",
            "gps_fix",
            "pitch",
            "roll",
            "yaw",
            "vx",
            "vy",
            "vz",
            "city_country",
        ):
            if k in obj:
                pkt[k] = obj[k]
        if "lat" in obj:
            pkt["latitude"] = obj["lat"]
        if "lon" in obj:
            pkt["longitude"] = obj["lon"]

        if pkt:
            self.telemetryReceived.emit(pkt)
            if "latitude" in pkt and "longitude" in pkt:
                try:
                    self.locationReceived.emit(float(pkt["latitude"]), float(pkt["longitude"]))
                except Exception:
                    pass

    # ------------- main loop -------------
    def run(self):
        try:
            self._open_files()
            self._open_serial()
        except Exception as e:
            self.lineReceived.emit(f"[Serial error] open failed: {e}")
            self._close_files()
            return

        self.lineReceived.emit(f"[info] Serial started on {self.port} @ {self.baud}")

        try:
            if self.lines:
                # newline-terminated input
                while not self._stop:
                    try:
                        raw = self._ser.readline()
                    except Exception as e:
                        self.lineReceived.emit(f"[Serial error] {e}")
                        break
                    if not raw:
                        self._flush_if_due()
                        continue

                    self._log_bin_and_hex(raw)

                    # fast decode
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line:
                        self._log_text(line)
                        self.lineReceived.emit(line)
                        # cheap location first, then JSON
                        if not self._parse_line_for_location(line):
                            self._feed_json_line(line)

                    self._flush_if_due()
            else:
                # raw chunk mode
                while not self._stop:
                    try:
                        data = self._ser.read(self.chunk)
                    except Exception as e:
                        self.lineReceived.emit(f"[Serial error] {e}")
                        break
                    if not data:
                        self._flush_if_due()
                        continue

                    self._log_bin_and_hex(data)

                    # opportunistic text parsing
                    txt = data.decode("utf-8", errors="ignore")
                    if txt:
                        # normalize CRLF -> LF once
                        for ln in filter(None, txt.replace("\r", "").split("\n")):
                            self._log_text(ln)
                            self.lineReceived.emit(ln)
                            if not self._parse_line_for_location(ln):
                                self._feed_json_line(ln)

                    self._flush_if_due()

        finally:
            try:
                self._ser and self._ser.close()
            except Exception:
                pass
            # final flush/close
            self._next_flush_t = 0.0
            self._flush_if_due()
            self._close_files()
