#!/usr/bin/env python3
import sys, os, argparse, socket, urllib.request
from PySide6 import QtCore, QtGui, QtWidgets
from gui_mainwindow import MainWindow
import serial.tools.list_ports as list_ports

APP_ID = u"ReliableTech.GUI"  # Windows taskbar grouping

def resource_path(relpath: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), relpath))

def choose_icon(cli_icon: str | None = None) -> QtGui.QIcon:
    # CLI override
    if cli_icon:
        p = resource_path(cli_icon) if not os.path.isabs(cli_icon) else cli_icon
        if os.path.exists(p):
            ic = QtGui.QIcon(p)
            if not ic.isNull():
                return ic
    # Asset fallbacks
    for name in (
        "assets/monitor.ico", "assets/monitor.png", "assets/monitor.svg",
        "assets/company_logo.ico", "assets/company_logo.png", "assets/company_logo.svg",
    ):
        full = resource_path(name)
        if os.path.exists(full):
            ic = QtGui.QIcon(full)
            if not ic.isNull():
                return ic
    return QtGui.QIcon()

def have_internet(timeout: float = 1.0) -> bool:
    try:
        s = socket.create_connection(("1.1.1.1", 53), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False

def tiles_reachable(timeout: float = 1.5) -> bool:
    try:
        urllib.request.urlopen("https://tile.openstreetmap.org/0/0/0.png", timeout=timeout).close()
        return True
    except Exception:
        return False

def resolve_webmap_mode(mode: str) -> bool:
    if mode == "on": return True
    if mode == "off": return False
    # auto
    return have_internet() and tiles_reachable()

def autodetect_port() -> str | None:
    ports = list(list_ports.comports())
    if not ports:
        return None
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if "ftdi" in desc or "usb" in desc or "ftdi" in hwid:
            return p.device
    return ports[0].device

def main() -> int:
    # Windows taskbar grouping & name
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    # ---- Hi-DPI crispness (safe across PySide6 versions) ----
    try:
        # Qt 6 API path (if available)
        if hasattr(QtGui.QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
            QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        else:
            raise AttributeError
    except Exception:
        # Fallback via environment and legacy attributes (set BEFORE QApplication)
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
        os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
        try:
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("GUI")
    app.setApplicationDisplayName("GUI")

    # ---- CLI ----
    ap = argparse.ArgumentParser(description="UART Location Monitor GUI")
    ap.add_argument("--web-map", choices=["on", "off", "auto"], default="auto",
                    help="Web map mode (default: auto)")
    ap.add_argument("--port", help="COM port (e.g., COM7). If omitted, the first detected port is used.")
    ap.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")

    # --lines defaults True; allow --no-lines if supported
    try:
        from argparse import BooleanOptionalAction  # Python 3.9+
        ap.add_argument("--lines", action=BooleanOptionalAction, default=True,
                        help="Read line-by-line (default True). Use --no-lines for raw chunk mode.")
    except Exception:
        grp = ap.add_mutually_exclusive_group()
        grp.add_argument("--lines", dest="lines", action="store_true", default=True,
                         help="Read line-by-line (default)")
        grp.add_argument("--no-lines", dest="lines", action="store_false",
                         help="Disable line mode (use raw chunk mode)")

    ap.add_argument("--chunk", type=int, default=512, help="Chunk size for raw mode")
    ap.add_argument("--logfile", help="Append human-readable logs here")
    ap.add_argument("--binfile", help="Write raw bytes to this file")
    ap.add_argument("--hexdump", help="Write hex dump to this file")
    ap.add_argument("--hexwidth", type=int, default=32, help="Hex bytes per line (default 32)")
    ap.add_argument("--icon", help="Explicit icon file (ico/png/svg)")
    ap.add_argument("--title", default="GUI", help="Window title (default: GUI)")
    args = ap.parse_args()

    icon = choose_icon(args.icon)
    if not icon.isNull():
        app.setWindowIcon(icon)

    win = MainWindow()
    win.setWindowTitle(args.title or "GUI")
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()

    # Web map setting
    use_web = resolve_webmap_mode(args.web_map)
    try:
        win.set_webmap_mode(args.web_map)
    except Exception:
        try:
            win.map.use_web(use_web)
        except Exception:
            pass

    # Port selection
    port = args.port or autodetect_port()
    if not port:
        QtWidgets.QMessageBox.warning(
            win, "No COM Ports",
            "No serial ports detected. Connect your USB-UART device and rerun with --port COMx."
        )
        return app.exec()

    # Start serial
    try:
        win.start_serial_location(
            port=port, baud=args.baud, lines=args.lines, chunk=args.chunk,
            logfile=args.logfile, binfile=args.binfile, hexdump=args.hexdump, hexwidth=args.hexwidth
        )
    except TypeError:
        win.start_serial_location(
            port=port, baud=args.baud, chunk=args.chunk,
            logfile=args.logfile, binfile=args.binfile, hexdump=args.hexdump, hexwidth=args.hexwidth
        )

    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
