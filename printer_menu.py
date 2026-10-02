# -*- coding: utf-8 -*-
r"""
GUI профилирования принтера — Premium Dark v3.2.1 (гибрид CTk + tk).

Изменения в v3.2.1:
- Диалог активации: работает вставка ключа из буфера обмена.
  - Ctrl+V, Ctrl+Shift+V, Shift+Insert.
  - Ctrl+C / Ctrl+X для копирования/вырезания.
  - Правая кнопка мыши — контекстное меню.
  - Кнопки «📋 Вставить из буфера» и «🗑 Очистить».
  - Статус «📋 Ключ вставлен из буфера» при успешной вставке.

Сохранены фиксы v3.2.0 и v2.3.1–v3.1.1.
"""

# === DPI-AWARENESS ===
import os as _os
import sys as _sys
import subprocess as _subprocess
import ctypes as _ctypes


def _enable_dpi_awareness():
    if _os.name != "nt":
        return
    try:
        _ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi_awareness()


def _relaunch_via_pythonw():
    if _os.name != "nt":
        return
    if getattr(_sys, "frozen", False):
        return
    if _os.path.basename(_sys.executable).lower() == "pythonw.exe":
        return
    if _os.environ.get("_PRINTER_MENU_RELAUNCHED") == "1":
        return

    _pythonw = _os.path.join(_os.path.dirname(_sys.executable), "pythonw.exe")
    if not _os.path.exists(_pythonw):
        return

    _script = _os.path.abspath(_sys.argv[0]) if _sys.argv and _sys.argv[0] \
        else _os.path.abspath(__file__)

    _env = _os.environ.copy()
    _env["_PRINTER_MENU_RELAUNCHED"] = "1"

    try:
        _subprocess.Popen(
            [_pythonw, _script] + _sys.argv[1:],
            close_fds=True,
            env=_env,
            creationflags=_subprocess.DETACHED_PROCESS
                          | _subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except Exception:
        return

    _sys.exit(0)


_relaunch_via_pythonw()
# === /DPI + RELAUNCH ===

import os
import queue
import json
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import webbrowser
from tkinter import filedialog, messagebox, ttk

try:
    import customtkinter as ctk
except ImportError:
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror(
        "Ошибка зависимостей",
        "Установите customtkinter:\n\n    pip install customtkinter"
    )
    _r.destroy()
    sys.exit(1)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from argyll_profiler.config import (
    Config, load_config, find_argyll_path,
    sanitize_name, clamp_patches,
)
from argyll_profiler.logger import ProfilerLogger
from argyll_profiler.profiler import (
    Profiler, ProfileRequest, ProfilerError, ProfilerCancelled,
)
from argyll_profiler.metadata import load_metadata
from argyll_profiler.papers import PapersLibrary, PaperTemplate
from argyll_profiler.report import build_report
from argyll_profiler.backup import create_backup
from argyll_profiler.printers import list_printers, find_canon_pro10s

# ─── Лицензирование ───
try:
    import licensing as lic
    from licensing import (
        TRIAL_LIMIT, SELLER_EMAIL, APP_NAME as LIC_APP_NAME,
        APP_VERSION as LIC_APP_VERSION,
        get_hwid, verify_key_online, save_license, load_license,
        reset_license, is_activated, bump_launch_count,
        get_trial_left,
    )
    _LICENSE_AVAILABLE = True
except ImportError as _e:
    _LICENSE_AVAILABLE = False
    _LICENSE_ERROR = str(_e)


CONFIG_FILENAME = "printer_profiler_config.json"
THEME_FILENAME = "theme.json"
THEME_LIGHT_FILENAME = "theme_light.json"
DPI_OVERRIDE_FILENAME = "dpi_override.txt"
UI_SETTINGS_FILENAME = "ui_settings.json"
LOGS_DIRNAME = "logs"


# ═══════════════════════════════════════════════════════════════
# UI-НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
def _read_ui_settings() -> dict:
    path = os.path.join(SCRIPT_DIR, UI_SETTINGS_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_ui_settings(data: dict):
    path = os.path.join(SCRIPT_DIR, UI_SETTINGS_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_ui_setting(key: str, default=None):
    return _read_ui_settings().get(key, default)


def _set_ui_setting(key: str, value):
    data = _read_ui_settings()
    data[key] = value
    _write_ui_settings(data)


# ═══════════════════════════════════════════════════════════════
# ТЕМА
# ═══════════════════════════════════════════════════════════════
_DEFAULT_THEME = {
    "general": {
        "dpi_scaling": 1.0,
        "default_geometry": "1500x980",
        "min_geometry": "1280x900",
        "appearance": "dark",
    },
    "palette": {
        "bg_root": "#0d0d16", "bg_main": "#1a1a28", "bg_surface": "#141420",
        "bg_overlay": "#25253a", "bg_hover": "#32324d",
        "bg_active": "#3d3d5c", "bg_log": "#0a0a12",
        "fg": "#e8ebf5", "fg_dim": "#a8adc4", "fg_muted": "#7d8299",
        "fg_faint": "#565b73",
        "accent": "#7aa2f7", "sky": "#7dcfff", "teal": "#73daca",
        "green": "#9ece6a", "yellow": "#e0af68", "orange": "#ff9e64",
        "red": "#f7768e", "pink": "#ff7eb6", "mauve": "#bb9af7",
        "border": "#2f2f45", "border_accent": "#3d3d5c",
    },
    "fonts": {
        "title":      {"family": "Segoe UI", "size": 22, "weight": "bold"},
        "subtitle":   {"family": "Segoe UI", "size": 13, "weight": "normal"},
        "h2":         {"family": "Segoe UI", "size": 15, "weight": "bold"},
        "body":       {"family": "Segoe UI", "size": 13, "weight": "normal"},
        "small":      {"family": "Segoe UI", "size": 12, "weight": "normal"},
        "tiny":       {"family": "Segoe UI", "size": 11, "weight": "normal"},
        "btn":        {"family": "Segoe UI", "size": 13, "weight": "bold"},
        "btn_small":  {"family": "Segoe UI", "size": 12, "weight": "bold"},
        "mono":       {"family": "Consolas", "size": 14, "weight": "normal"},
        "mono_log":   {"family": "Consolas", "size": 14, "weight": "normal"},
        "mono_small": {"family": "Consolas", "size": 12, "weight": "normal"},
        "metric":     {"family": "Segoe UI", "size": 24, "weight": "bold"},
        "clock":      {"family": "Consolas", "size": 12, "weight": "normal"},
        "author":     {"family": "Segoe UI", "size": 15, "weight": "bold"},
    },
}


def _get_screen_size():
    if sys.platform != "win32":
        try:
            r = tk.Tk()
            r.withdraw()
            w, h = r.winfo_screenwidth(), r.winfo_screenheight()
            r.destroy()
            return int(w), int(h)
        except Exception:
            return 1920, 1080
    user32 = _ctypes.windll.user32
    try:
        _ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def _get_system_dpi():
    if sys.platform != "win32":
        return 96
    try:
        return int(_ctypes.windll.user32.GetDpiForSystem())
    except Exception:
        pass
    try:
        hdc = _ctypes.windll.user32.GetDC(0)
        dpi = _ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        _ctypes.windll.user32.ReleaseDC(0, hdc)
        return int(dpi)
    except Exception:
        return 96


def _pick_scaling(height: int, sys_dpi: int) -> float:
    if height >= 4000:
        base = 1.75
    elif height >= 2000:
        base = 1.50
    elif height >= 1500:
        base = 1.25
    elif height >= 1300:
        base = 1.20
    elif height >= 1150:
        base = 1.05
    else:
        base = 1.00
    dpi_factor = max(1.0, min(2.0, sys_dpi / 96.0))
    scaling = round(base * (0.85 + 0.15 * dpi_factor), 2)
    return max(1.0, min(2.0, scaling))


def _read_dpi_override():
    path = os.path.join(SCRIPT_DIR, DPI_OVERRIDE_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = re.sub(r"#.*", "", f.read())
        m = re.search(r"([0-9]+(?:[.,][0-9]+)?)", text)
        if not m:
            return None
        v = float(m.group(1).replace(",", "."))
        if 0.5 <= v <= 3.0:
            return v
    except Exception:
        return None
    return None


def _adjust_geometry(geom: str, sw: int, sh: int) -> str:
    try:
        w, h = geom.lower().split("x")
        w, h = int(w), int(h)
    except Exception:
        return geom
    max_w = max(1024, sw - 60)
    max_h = max(720, sh - 80)
    return f"{min(w, max_w)}x{min(h, max_h)}"


def _resolve_dpi_scaling(theme_general: dict) -> float:
    manual = _read_dpi_override()
    if manual is not None:
        return manual
    raw = theme_general.get("dpi_scaling")
    if raw is not None:
        try:
            v = float(raw)
            if 0.5 <= v <= 3.0 and abs(v - 1.0) > 0.001:
                return v
        except Exception:
            pass
    sw, sh = _get_screen_size()
    dpi = _get_system_dpi()
    return _pick_scaling(sh, dpi)


def _resolve_geometry(theme_general: dict) -> tuple:
    sw, sh = _get_screen_size()
    default_geom = theme_general.get("default_geometry", "1500x980")
    min_geom = theme_general.get("min_geometry", "1280x900")
    default_geom = _adjust_geometry(default_geom, sw, sh)
    try:
        dw, dh = [int(x) for x in default_geom.lower().split("x")]
        mw, mh = [int(x) for x in str(min_geom).lower().split("x")]
        min_geom = f"{min(dw, mw)}x{min(dh, mh)}"
    except Exception:
        pass
    return default_geom, min_geom


def _load_theme():
    theme_name = _get_ui_setting("theme", "dark")
    if theme_name == "light":
        path = os.path.join(SCRIPT_DIR, THEME_LIGHT_FILENAME)
    else:
        path = os.path.join(SCRIPT_DIR, THEME_FILENAME)

    if not os.path.exists(path):
        data = dict(_DEFAULT_THEME)
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = dict(_DEFAULT_THEME)

    for section in ("general", "palette", "fonts"):
        base = _DEFAULT_THEME.get(section, {})
        got = data.get(section, {}) or {}
        merged = dict(base)
        merged.update(got)
        data[section] = merged
    return data


THEME = _load_theme()


class Palette:
    def __init__(self, data: dict):
        self._data = dict(data)

    def __getattr__(self, item):
        if item in self._data:
            return self._data[item]
        return _DEFAULT_THEME["palette"].get(item, "#000000")


class AppFonts:
    def __init__(self, data: dict):
        self._data = dict(data)
        self._cache = {}

    def get(self, key: str):
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        f = self._data.get(key) or _DEFAULT_THEME["fonts"].get(key, {})
        result = (
            f.get("family", "Segoe UI"),
            int(f.get("size", 10)),
            f.get("weight", "normal"),
        )
        self._cache[key] = result
        return result


P = Palette(THEME.get("palette", {}))
F = AppFonts(THEME.get("fonts", {}))

ctk.set_appearance_mode(THEME["general"].get("appearance", "dark"))
ctk.set_default_color_theme("blue")


def is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin():
    if is_admin():
        return
    import ctypes
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        exe = sys.executable
        params = subprocess.list2cmdline(
            [os.path.abspath(sys.argv[0])] + sys.argv[1:])
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, params, None, 1)
        if rc <= 32:
            ctypes.windll.user32.MessageBoxW(
                0, f"Не удалось получить права (код {rc})", "Ошибка", 0x10)
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(
            0, f"Ошибка прав: {e}", "Ошибка", 0x10)
    sys.exit()


class SectionTitle(ctk.CTkFrame):
    def __init__(self, parent, text: str, icon: str = "",
                 color: str = None, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        color = color or P.accent
        ctk.CTkLabel(
            self, text=icon, font=F.get("h2"),
            text_color=color, width=20,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            self, text=text.upper(), font=F.get("h2"),
            text_color=P.fg,
        ).pack(side="left")
        ctk.CTkFrame(self, fg_color=P.border, height=1,
                     corner_radius=0).pack(
            side="left", fill="x", expand=True, padx=(10, 0))


class StatusDot(tk.Canvas):
    def __init__(self, parent, color: str, size: int = 12,
                 bg: str = None, **kw):
        if bg is None:
            try:
                parent_bg = parent.cget("fg_color")
                if isinstance(parent_bg, (list, tuple)):
                    parent_bg = parent_bg[0]
                bg = parent_bg
            except Exception:
                bg = P.bg_surface
        super().__init__(parent, width=size, height=size,
                         bg=bg, highlightthickness=0, **kw)
        self.dot = self.create_oval(2, 2, size - 2, size - 2,
                                    fill=color, outline="")

    def set_color(self, color: str):
        self.itemconfig(self.dot, fill=color)


class ProfilerWorker(threading.Thread):
    def __init__(self, task_fn, log_queue, progress_queue, done_queue,
                 cancel_event=None):
        super().__init__(daemon=True)
        self.task_fn = task_fn
        self.log_q = log_queue
        self.prog_q = progress_queue
        self.done_q = done_queue
        self.cancel = cancel_event or threading.Event()

    def _log(self, level, msg):
        self.log_q.put((level, msg))

    def _progress(self, step, total, msg):
        self.prog_q.put((step, total, msg))

    def run(self):
        try:
            self.task_fn(self._log, self._progress)
            if self.cancel.is_set():
                self.done_q.put(("cancelled", None))
            else:
                self.done_q.put(("ok", None))
        except ProfilerCancelled as e:
            self._log("WARNING", f"⏹ {e}")
            self.done_q.put(("cancelled", None))
        except ProfilerError as e:
            self._log("ERROR", f"❌ {e}")
            self.done_q.put(("error", str(e)))
        except Exception as e:
            self._log("ERROR", f"❌ {e}")
            self.done_q.put(("error", str(e)))


class PrinterMenu:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("🖨️  Argyll Printer Profiler  —  Premium")

        gen = THEME.get("general", {})
        default_geom, min_geom = _resolve_geometry(gen)
        self.root.geometry(default_geom)
        self.root.minsize(*self._parse_geom(min_geom))

        ctk.set_appearance_mode(gen.get("appearance", "dark"))

        try:
            self.cfg: Config = load_config(interactive=False)
        except Exception:
            self.cfg = Config()

        if not getattr(self.cfg, "argvll_path", ""):
            found = find_argyll_path()
            if found:
                self.cfg.argvll_path = found

        if not self.cfg.base_dir:
            self.cfg.base_dir = os.path.join(SCRIPT_DIR, "profiles")
        os.makedirs(self.cfg.base_dir, exist_ok=True)

        try:
            cfg_path = os.path.join(SCRIPT_DIR, CONFIG_FILENAME)
            if not os.path.exists(cfg_path):
                self.cfg.save(cfg_path)
        except Exception:
            pass

        self.logger = ProfilerLogger(
            self.cfg.base_dir, self.cfg.log_level,
            gui_callback=None, console=False)

        self.papers = PapersLibrary(self.cfg.papers_library or None)

        self.log_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        self.done_queue = queue.Queue()

        self.worker = None
        self.is_running = False
        self.cancel_event = threading.Event()
        self._current_proc = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._pulse_on = False
        self._start_time = None
        self._patches_touched = False
        self._closing = False
        self._zadig_shown = False

        self._log_buffer = []
        self._current_profile_dir = None
        self._log_save_after_ops = False

        self._daily_log_dir = os.path.join(SCRIPT_DIR, LOGS_DIRNAME)
        try:
            os.makedirs(self._daily_log_dir, exist_ok=True)
        except Exception:
            self._daily_log_dir = ""

        # ─── Лицензия ───
        self.activated = False
        self.license_owner = None
        self.trial_left = 0
        self._license_dialog_open = False
        self._license_banner = None

        self._init_ttk_style()

        self._build_ui()
        self._init_license()

        self._center()
        self._poll_queues()
        self._tick_clock()
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

        self._check_argyll_tools()
        try:
            if not list_printers():
                self._append_log(
                    "WARNING",
                    "🖨 Список принтеров пуст. Установите pywin32: "
                    "pip install pywin32")
        except Exception:
            pass

    @staticmethod
    def _parse_geom(s: str):
        try:
            w, h = s.lower().split("x")
            return int(w), int(h)
        except Exception:
            return (1280, 900)

    def _init_ttk_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Premium.Treeview",
            background=P.bg_log,
            fieldbackground=P.bg_log,
            foreground=P.fg,
            bordercolor=P.border,
            rowheight=26,
            font=F.get("small"))
        style.configure(
            "Premium.Treeview.Heading",
            background=P.bg_overlay,
            foreground=P.accent,
            font=F.get("small"))
        style.map("Premium.Treeview",
                  background=[("selected", P.bg_hover)],
                  foreground=[("selected", P.mauve)])

    def _check_argyll_tools(self):
        required = ["targen", "chartread", "colprof", "profcheck",
                    "printtarg", "spotread"]
        bin_dir = getattr(self.cfg, "argvll_path", "") or ""
        if not bin_dir:
            self._append_log(
                "ERROR",
                "❌ ArgyllCMS: путь к bin не задан. "
                "Откройте ⚙ Настройки.")
            return
        missing = []
        for tool in required:
            found = False
            for ext in (".exe", ".EXE", ""):
                p = os.path.join(bin_dir, tool + ext)
                if os.path.exists(p):
                    found = True
                    break
            if not found:
                missing.append(tool)
        if missing:
            self._append_log(
                "ERROR",
                "❌ ArgyllCMS: не найдены — " + ", ".join(missing) +
                f"  (в {bin_dir})")
            self._append_log(
                "WARNING",
                "   Проверьте ⚙ Настройки → путь к bin.")
        else:
            self._append_log(
                "SUCCESS",
                f"✅ ArgyllCMS: все {len(required)} утилит на месте "
                f"({bin_dir}).")

    # ═══════════════════════════════════════════════════════════
    # ЛИЦЕНЗИРОВАНИЕ
    # ═══════════════════════════════════════════════════════════
    def _init_license(self):
        if not _LICENSE_AVAILABLE:
            self._append_log(
                "ERROR",
                f"❌ Модуль licensing не загружен: {_LICENSE_ERROR}")
            self.activated = True
            self.trial_left = 999
            return

        self.activated, self.license_owner = False, None
        try:
            self.activated, self.license_owner = is_activated()
            if not self.activated:
                bump_launch_count()
                self.trial_left = get_trial_left()
            else:
                self.trial_left = 0
        except Exception as e:
            self.trial_left = TRIAL_LIMIT
            try:
                self.logger.write(f"license init error: {e}")
            except Exception:
                pass

        if self.activated:
            self._append_log(
                "SUCCESS",
                f"✅ Лицензия активирована: {self.license_owner}")
            self._update_license_banner()
        else:
            if self.trial_left > 0:
                self._append_log(
                    "WARNING",
                    f"🔓 Пробная версия: осталось "
                    f"{self.trial_left} из {TRIAL_LIMIT} запусков")
                self._update_license_banner()
            else:
                self._append_log(
                    "ERROR",
                    "🔒 Пробный период истёк. Требуется активация.")
                self._update_license_banner()
                self._set_buttons_enabled(False)
                self.root.after(400, self._show_activation_dialog)

    def _update_license_banner(self):
        if self._license_banner is None:
            return
        try:
            if self.activated:
                self._license_banner.configure(
                    text=f"✅ Лицензия активирована  •  "
                         f"{self.license_owner or 'Покупатель'}",
                    text_color=P.green)
            elif self.trial_left > 0:
                self._license_banner.configure(
                    text=f"🔓 Пробная версия: осталось "
                         f"{self.trial_left} из {TRIAL_LIMIT} запусков",
                    text_color=P.yellow)
            else:
                self._license_banner.configure(
                    text="🔒 Пробный период истёк — требуется активация",
                    text_color=P.red)
        except Exception:
            pass

    def _set_buttons_enabled(self, enabled: bool):
        for b in getattr(self, "btn_all", []):
            try:
                if b is self.btn_stop:
                    continue
                b.configure(state="normal" if enabled else "disabled")
            except Exception:
                pass

    def _is_locked(self) -> bool:
        if not _LICENSE_AVAILABLE:
            return False
        return (not self.activated) and (self.trial_left <= 0)

    def _guard_operation(self) -> bool:
        if self._is_locked():
            self._show_activation_dialog()
            return False
        return True

    def _show_activation_dialog(self):
        if self._license_dialog_open:
            return
        if not _LICENSE_AVAILABLE:
            messagebox.showerror(
                "Ошибка",
                "Модуль licensing не загружен.\n"
                "Приложение не может проверить лицензию.")
            return

        self._license_dialog_open = True

        dlg = ctk.CTkToplevel(self.root)
        dlg.title("🔒 Активация Printer Profiler")
        dlg.geometry("640x640")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        def _on_close():
            self._license_dialog_open = False
            try:
                dlg.destroy()
            except Exception:
                pass
            if self._is_locked():
                try:
                    self.root.after(100, self.on_exit)
                except Exception:
                    pass

        dlg.protocol("WM_DELETE_WINDOW", _on_close)

        head = ctk.CTkFrame(dlg, fg_color=P.bg_main, height=60,
                             corner_radius=0)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=P.yellow, width=5).pack(side="left", fill="y")
        ctk.CTkLabel(head, text="🔒  Требуется активация",
                     font=F.get("title"),
                     text_color=P.fg).pack(side="left", padx=14)

        body = ctk.CTkFrame(dlg, fg_color=P.bg_root, corner_radius=0)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(
            body,
            text=(f"Пробный период истёк "
                  f"({TRIAL_LIMIT} запусков).\n\n"
                  f"Чтобы продолжить, активируйте ключ.\n"
                  f"Скопируйте HWID и отправьте продавцу, "
                  f"затем введите полученный ключ."),
            font=F.get("body"), text_color=P.fg,
            justify="left", anchor="w").pack(
            fill="x", pady=(0, 14))

        hwid = get_hwid()

        # HWID
        ctk.CTkLabel(body, text="Ваш HWID:",
                     font=F.get("small"),
                     text_color=P.fg_dim,
                     anchor="w").pack(fill="x")
        hwid_row = ctk.CTkFrame(body, fg_color="transparent")
        hwid_row.pack(fill="x", pady=(2, 10))

        hwid_entry = ctk.CTkEntry(
            hwid_row, font=F.get("mono"),
            fg_color=P.bg_overlay, border_color=P.border,
            text_color=P.yellow, justify="center", height=36)
        hwid_entry.insert(0, hwid)
        try:
            hwid_entry.configure(state="readonly")
        except Exception:
            pass
        hwid_entry.pack(side="left", fill="x", expand=True)

        def _copy_hwid():
            try:
                dlg.clipboard_clear()
                dlg.clipboard_append(hwid)
                dlg.update()
                _set_status("✅ HWID скопирован в буфер обмена",
                             P.green)
            except Exception as e:
                _set_status(f"❌ Не удалось скопировать: {e}",
                             P.red)

        ctk.CTkButton(
            hwid_row, text="📋", width=44, height=36,
            command=_copy_hwid,
            font=F.get("body"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.accent).pack(side="left", padx=(6, 0))

        # Кнопки отправки
        btns_row = ctk.CTkFrame(body, fg_color="transparent")
        btns_row.pack(fill="x", pady=(0, 14))

        def _write_seller():
            try:
                subject = (f"Лицензия Printer Profiler — "
                           f"HWID {hwid}")
                body_text = (
                    f"Здравствуйте!\r\n\r\n"
                    f"Прошу выдать лицензионный ключ для "
                    f"Printer Profiler.\r\n\r\n"
                    f"HWID: {hwid}\r\n\r\n"
                    f"Спасибо!")
                mailto = (
                    f"mailto:{SELLER_EMAIL}"
                    f"?subject={urllib.parse.quote(subject)}"
                    f"&body={urllib.parse.quote(body_text)}")
                os.startfile(mailto)
            except Exception as e:
                try:
                    dlg.clipboard_clear()
                    dlg.clipboard_append(
                        f"HWID: {hwid}\nEmail: {SELLER_EMAIL}")
                    _set_status(
                        "📋 Текст письма скопирован в буфер обмена",
                        P.yellow)
                except Exception:
                    _set_status(f"❌ {e}", P.red)

        ctk.CTkButton(
            btns_row, text="📧  Написать продавцу",
            command=_write_seller,
            font=F.get("btn"),
            fg_color=P.accent, hover_color=P.sky,
            text_color=P.bg_root,
            height=40, corner_radius=6).pack(
            side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            btns_row, text="📋  Копировать HWID",
            command=_copy_hwid,
            font=F.get("btn"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.fg,
            height=40, corner_radius=6).pack(
            side="left", fill="x", expand=True)

        # Поле ключа
        ctk.CTkLabel(body, text="Ключ активации:",
                     font=F.get("small"),
                     text_color=P.fg_dim,
                     anchor="w").pack(fill="x")
        key_var = tk.StringVar()
        key_entry = ctk.CTkEntry(
            body, textvariable=key_var,
            font=F.get("mono"),
            fg_color=P.bg_overlay, border_color=P.border,
            text_color=P.fg, justify="center",
            height=40)
        key_entry.pack(fill="x", pady=(2, 6), ipady=2)
        key_entry.focus_set()

        # Кнопки «Вставить / Очистить» под полем ключа
        paste_row = ctk.CTkFrame(body, fg_color="transparent")
        paste_row.pack(fill="x", pady=(0, 10))

        # Статус
        status = ctk.CTkLabel(
            body, text="", font=F.get("small"),
            text_color=P.fg_muted, anchor="w",
            justify="left")
        status.pack(fill="x", pady=(0, 8))

        def _set_status(text, color=None):
            try:
                status.configure(
                    text=text,
                    text_color=color or P.fg_muted)
            except Exception:
                pass

        # ─── Вставка / копирование ключа ───
        def _paste_key(event=None):
            """Вставляет ключ из буфера обмена в поле."""
            try:
                txt = dlg.clipboard_get()
            except Exception:
                try:
                    txt = key_entry.clipboard_get()
                except Exception:
                    _set_status(
                        "❌ Буфер обмена пуст или недоступен", P.red)
                    return "break"
            if not txt:
                _set_status("❌ Буфер обмена пуст", P.red)
                return "break"
            txt = str(txt).strip().replace("\n", "").replace("\r", "")
            if not txt:
                _set_status("❌ Буфер содержит только пустые строки",
                             P.red)
                return "break"
            try:
                key_var.set(txt)
                key_entry.icursor(len(txt))
                key_entry.xview_moveto(1.0)
                _set_status("📋 Ключ вставлен из буфера", P.sky)
            except Exception as e:
                _set_status(f"❌ {e}", P.red)
            return "break"

        def _copy_key(event=None):
            """Копирует содержимое поля в буфер обмена."""
            try:
                txt = key_var.get()
                if not txt:
                    _set_status("❌ Поле пустое", P.red)
                    return "break"
                dlg.clipboard_clear()
                dlg.clipboard_append(txt)
                dlg.update()
                _set_status("📋 Скопировано в буфер", P.green)
            except Exception as e:
                _set_status(f"❌ {e}", P.red)
            return "break"

        def _clear_key(event=None):
            try:
                key_var.set("")
                key_entry.focus_set()
                _set_status("🗑 Поле очищено", P.fg_muted)
            except Exception:
                pass
            return "break"

        # Привязки к полю — все возможные комбинации
        key_entry.bind("<Control-v>", _paste_key)
        key_entry.bind("<Control-V>", _paste_key)
        key_entry.bind("<Control-Shift-v>", _paste_key)
        key_entry.bind("<Control-Shift-V>", _paste_key)
        key_entry.bind("<Shift-Insert>", _paste_key)
        key_entry.bind("<Control-c>", _copy_key)
        key_entry.bind("<Control-C>", _copy_key)
        key_entry.bind("<Control-x>", _copy_key)
        key_entry.bind("<Control-X>", _copy_key)

        # Контекстное меню по правой кнопке
        context_menu = tk.Menu(
            dlg, tearoff=0,
            bg=P.bg_overlay, fg=P.fg,
            activebackground=P.accent,
            activeforeground=P.bg_root,
            font=F.get("small"))
        context_menu.add_command(label="📋  Вставить",
                                  command=_paste_key)
        context_menu.add_command(label="📄  Копировать",
                                  command=_copy_key)
        context_menu.add_separator()
        context_menu.add_command(label="🗑  Очистить",
                                  command=_clear_key)

        def _show_ctx_menu(event):
            try:
                key_entry.focus_set()
                context_menu.tk_popup(event.x_root, event.y_root)
            except Exception:
                pass
            finally:
                try:
                    context_menu.grab_release()
                except Exception:
                    pass

        key_entry.bind("<Button-3>", _show_ctx_menu)

        # Кнопки под полем: «Вставить» и «Очистить»
        ctk.CTkButton(
            paste_row, text="📋  Вставить из буфера",
            command=_paste_key,
            font=F.get("small"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.accent,
            height=32, corner_radius=6).pack(
            side="left", fill="x", expand=True, padx=(0, 4))

        ctk.CTkButton(
            paste_row, text="🗑  Очистить",
            command=_clear_key,
            font=F.get("small"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.fg_dim,
            height=32, corner_radius=6).pack(
            side="left", fill="x", expand=True, padx=(4, 0))

        def _try_activate():
            key = (key_var.get() or "").strip().upper()
            if not key:
                _set_status("❌ Введите ключ", P.red)
                key_entry.focus_set()
                return
            _set_status("⏳ Проверка ключа...", P.sky)
            dlg.update_idletasks()

            r = verify_key_online(key)
            if not r.valid:
                reason = r.reason or ""
                msg_map = {
                    "empty": "❌ Пустой ключ",
                    "not_found": "❌ Ключ не найден",
                    "revoked": "❌ Ключ отозван",
                    "expired": "❌ Срок действия истёк",
                    "hwid_mismatch":
                        "❌ Ключ привязан к другому ПК",
                    "wrong_product":
                        "❌ Это ключ от другого продукта.\n"
                        "Для Printer Profiler нужен ключ вида "
                        "PRINTER-...",
                    "bad_signature":
                        "❌ Неверная подпись сервера",
                    "no_signature":
                        "❌ Сервер не вернул подпись",
                    "bad_response":
                        "❌ Некорректный ответ сервера",
                }
                if reason.startswith("network"):
                    _set_status(
                        "❌ Нет связи с сервером активации.\n"
                        "Проверьте интернет и повторите.",
                        P.red)
                elif reason.startswith("http"):
                    _set_status(f"❌ Ошибка сервера: {reason}",
                                 P.red)
                else:
                    _set_status(
                        msg_map.get(reason,
                                     f"❌ {reason or 'Ошибка'}"),
                        P.red)
                return

            owner = r.owner or "Покупатель"
            try:
                save_license(key)
            except Exception:
                pass

            self.activated = True
            self.license_owner = owner
            self.trial_left = 0
            self._append_log("SUCCESS",
                              f"✅ Лицензия активирована: {owner}")
            if r.lifetime:
                self._append_log("INFO",
                                  "♾️ Бессрочная лицензия")
            elif r.expires_at:
                self._append_log(
                    "INFO",
                    f"📅 Действует до: {r.expires_at[:10]}")
            self._update_license_banner()
            self._set_buttons_enabled(True)

            messagebox.showinfo(
                "Активация успешна",
                f"✅ Лицензия активирована.\n\n"
                f"Владелец: {owner}")
            self._license_dialog_open = False
            dlg.destroy()

        act_row = ctk.CTkFrame(body, fg_color="transparent")
        act_row.pack(fill="x", pady=(6, 0))

        ctk.CTkButton(
            act_row, text="✅  Активировать",
            command=_try_activate,
            font=F.get("btn"),
            fg_color=P.green, hover_color=P.teal,
            text_color=P.bg_root,
            height=44, corner_radius=6).pack(
            side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            act_row, text="❌  Выход",
            command=_on_close,
            font=F.get("btn"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.fg,
            height=44, corner_radius=6).pack(
            side="left", fill="x", expand=True)

        dlg.bind("<Return>", lambda e: _try_activate())

    # ═══════════════════════════════════════════════════════════
    # BUILD UI
    # ═══════════════════════════════════════════════════════════
    def _build_ui(self):
        self.root.configure(fg_color=P.bg_root)
        self._build_header()

        main = ctk.CTkFrame(self.root, fg_color=P.bg_root)
        main.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        left = ctk.CTkScrollableFrame(
            main, fg_color=P.bg_main, width=400,
            corner_radius=8,
            scrollbar_button_color=P.bg_hover,
            scrollbar_button_hover_color=P.accent,
        )
        left.pack(side="left", fill="y", padx=(0, 10))
        self._build_left_panel(left)

        right = ctk.CTkFrame(main, fg_color=P.bg_main, corner_radius=8)
        right.pack(side="right", fill="both", expand=True)
        self._build_right_panel(right)

        self._build_statusbar()

    def _build_header(self):
        header = ctk.CTkFrame(self.root, fg_color=P.bg_main,
                              height=82, corner_radius=8)
        header.pack(fill="x", padx=14, pady=(10, 10))
        header.pack_propagate(False)

        strip = tk.Frame(header, bg=P.mauve, width=5)
        strip.pack(side="left", fill="y", padx=(0, 14))

        icon_box = ctk.CTkFrame(header, fg_color=P.bg_overlay,
                                width=54, height=54, corner_radius=10)
        icon_box.pack(side="left", padx=(0, 14), pady=14)
        icon_box.pack_propagate(False)
        ctk.CTkLabel(icon_box, text="🖨️",
                     font=("Segoe UI", 22)).pack(expand=True)

        title_block = ctk.CTkFrame(header, fg_color="transparent")
        title_block.pack(side="left", fill="y", pady=14)
        ctk.CTkLabel(title_block, text="Argyll Printer Profiler",
                     font=F.get("title"), text_color=P.fg,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            title_block,
            text="Canon Pixma Pro-10S  •  ArgyllCMS  •  ColorMunki Design",
            font=F.get("subtitle"), text_color=P.fg_dim,
            anchor="w").pack(anchor="w", pady=(2, 0))

        right_block = ctk.CTkFrame(header, fg_color="transparent")
        right_block.pack(side="right", fill="y", pady=14, padx=(0, 6))

        ver_box = ctk.CTkFrame(right_block, fg_color=P.bg_overlay,
                               corner_radius=6)
        ver_box.pack(side="top", anchor="e")
        ctk.CTkLabel(ver_box, text="  v3.2.1  •  Premium  ",
                     font=F.get("tiny"), text_color=P.mauve).pack()

        self._license_banner = ctk.CTkLabel(
            right_block, text="",
            font=F.get("small"), text_color=P.yellow, anchor="e")
        self._license_banner.pack(side="top", anchor="e", pady=(4, 0))

        dev_box = ctk.CTkFrame(right_block, fg_color="transparent")
        dev_box.pack(side="top", anchor="e", pady=(4, 0))
        self.header_dot = StatusDot(dev_box, P.fg_muted, size=12,
                                    bg=P.bg_main)
        self.header_dot.pack(side="left", padx=(0, 6))
        self.header_dev_label = ctk.CTkLabel(
            dev_box, text="Прибор: не проверен",
            font=F.get("small"), text_color=P.fg_dim)
        self.header_dev_label.pack(side="left")

    def _build_left_panel(self, parent):
        SectionTitle(parent, "Параметры профиля", "⚙",
                     color=P.fg_muted).pack(fill="x", padx=14, pady=(14, 6))

        params = ctk.CTkFrame(parent, fg_color="transparent")
        params.pack(fill="x", padx=14)

        def field(label, widget_factory):
            row = ctk.CTkFrame(params, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=label, font=F.get("small"),
                         text_color=P.fg_dim, width=110,
                         anchor="w").pack(side="left")
            widget_factory(row)

        self.var_template = tk.StringVar(value="— свой —")
        self.template_cb = None

        def add_template(row):
            self.template_cb = ctk.CTkOptionMenu(
                row, values=["— свой —"] + self.papers.names(),
                variable=self.var_template,
                command=lambda _=None: self._on_template_selected(),
                font=F.get("body"), dropdown_font=F.get("body"),
                fg_color=P.bg_overlay, button_color=P.bg_hover,
                button_hover_color=P.accent,
                text_color=P.fg, dropdown_hover_color=P.bg_hover,
                dropdown_text_color=P.fg)
            self.template_cb.pack(side="left", fill="x", expand=True)

        field("Шаблон:", add_template)

        printer_default = find_canon_pro10s() or self.cfg.printer_name
        self.var_printer = tk.StringVar(value=printer_default)
        self.printer_cb = None

        def add_printer(row):
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True)
            values = list_printers() or [self.cfg.printer_name]
            self.printer_cb = ctk.CTkComboBox(
                box, values=values, variable=self.var_printer,
                font=F.get("body"), dropdown_font=F.get("body"),
                fg_color=P.bg_overlay, border_color=P.border,
                button_color=P.bg_hover, button_hover_color=P.accent,
                text_color=P.fg, dropdown_hover_color=P.bg_hover,
                dropdown_text_color=P.fg)
            self.printer_cb.pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                box, text="↻", width=36,
                command=self._refresh_printers,
                font=F.get("body"),
                fg_color=P.bg_overlay, hover_color=P.bg_hover,
                text_color=P.accent).pack(side="left", padx=(4, 0))

        field("Принтер:", add_printer)

        self.var_paper = tk.StringVar(value="LomondGlossy")

        def add_paper(row):
            ctk.CTkEntry(row, textvariable=self.var_paper,
                         font=F.get("body"),
                         fg_color=P.bg_overlay, border_color=P.border,
                         text_color=P.fg).pack(
                side="left", fill="x", expand=True)

        field("Бумага:", add_paper)

        self.var_finish = tk.StringVar(value="Glossy")

        def add_finish(row):
            ctk.CTkOptionMenu(
                row, values=["Glossy", "Satin", "Matte", "Luster"],
                variable=self.var_finish,
                font=F.get("body"), dropdown_font=F.get("body"),
                fg_color=P.bg_overlay, button_color=P.bg_hover,
                button_hover_color=P.accent,
                text_color=P.fg, dropdown_hover_color=P.bg_hover,
                dropdown_text_color=P.fg).pack(
                side="left", fill="x", expand=True)

        field("Поверхность:", add_finish)

        self.var_size = tk.StringVar(value="A4")

        def add_size(row):
            ctk.CTkOptionMenu(
                row, values=["A4", "A3", "Letter", "A2"],
                variable=self.var_size,
                font=F.get("body"), dropdown_font=F.get("body"),
                fg_color=P.bg_overlay, button_color=P.bg_hover,
                button_hover_color=P.accent,
                text_color=P.fg, dropdown_hover_color=P.bg_hover,
                dropdown_text_color=P.fg).pack(
                side="left", fill="x", expand=True)

        field("Размер:", add_size)

        self.var_patches = tk.IntVar(value=self.cfg.default_patches)

        def add_patches(row):
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True)

            ctk.CTkButton(
                box, text="−", width=32,
                command=lambda: self._spin_patches(-50),
                font=F.get("body"),
                fg_color=P.bg_overlay, hover_color=P.bg_hover,
                text_color=P.fg).pack(side="left")

            self.patches_entry = ctk.CTkEntry(
                box, textvariable=self.var_patches,
                font=F.get("body"),
                fg_color=P.bg_overlay, border_color=P.border,
                text_color=P.fg, justify="center")
            self.patches_entry.pack(side="left", fill="x",
                                    expand=True, padx=4)
            self.patches_entry.bind("<KeyRelease>",
                                    self._mark_patches_touched)

            ctk.CTkButton(
                box, text="+", width=32,
                command=lambda: self._spin_patches(+50),
                font=F.get("body"),
                fg_color=P.bg_overlay, hover_color=P.bg_hover,
                text_color=P.fg).pack(side="left")

        field("Патчей:", add_patches)

        self.patches_hint = ctk.CTkLabel(
            params, text="", font=F.get("tiny"),
            text_color=P.yellow, anchor="w", justify="left")
        self.patches_hint.pack(fill="x", pady=(0, 2))
        self._update_patches_hint()

        flags = ctk.CTkFrame(params, fg_color="transparent")
        flags.pack(fill="x", pady=(8, 0))

        self.var_overwrite = tk.BooleanVar(value=False)
        self.var_resume = tk.BooleanVar(value=False)
        self.var_auto_backup = tk.BooleanVar(value=self.cfg.auto_backup)

        def chk(parent, var, text, color):
            return ctk.CTkCheckBox(
                parent, text=text, variable=var,
                font=F.get("small"),
                fg_color=color, hover_color=color,
                border_color=P.border_accent,
                text_color=P.fg_dim,
                checkmark_color=P.bg_root)

        chk(flags, self.var_overwrite, "Перезапись",
            P.orange).pack(anchor="w", pady=1)
        chk(flags, self.var_resume,
            "Resume (продолжить измерение)",
            P.yellow).pack(anchor="w", pady=1)
        chk(flags, self.var_auto_backup,
            "Автобэкап после создания",
            P.green).pack(anchor="w", pady=1)

        SectionTitle(parent, "Операции", "▶",
                     color=P.green).pack(fill="x", padx=14, pady=(16, 6))

        ops = ctk.CTkFrame(parent, fg_color="transparent")
        ops.pack(fill="x", padx=14)

        self.btn_full = self._add_op_btn(
            ops, "Полный цикл", "🔄", self.on_full_cycle, P.accent)
        self.btn_measure = self._add_op_btn(
            ops, "Только измерение", "📏", self.on_measure_only, P.accent)
        self.btn_resume = self._add_op_btn(
            ops, "Продолжить измерение", "⏩", self.on_resume, P.accent)
        self.btn_1200 = self._add_op_btn(
            ops, "Улучшить (качество)", "⚡", self.on_improve_1200, P.accent)
        self.btn_check = self._add_op_btn(
            ops, "Проверить точность + HTML", "📊",
            self.on_check_accuracy, P.teal)
        self.btn_compare = self._add_op_btn(
            ops, "Сравнить два профиля", "🆚", self.on_compare, P.teal)
        self.btn_inst = self._add_op_btn(
            ops, "Проверить прибор", "🔍",
            self.on_check_instrument, P.yellow)
        self.btn_backup = self._add_op_btn(
            ops, "Резервная копия профиля", "💾", self.on_backup, P.accent)
        self.btn_stop = self._add_op_btn(
            ops, "Остановить", "⏹", self.on_stop, P.red)
        self.btn_stop.configure(state="disabled")

        self.btn_all = [self.btn_full, self.btn_measure, self.btn_resume,
                        self.btn_1200, self.btn_check, self.btn_compare,
                        self.btn_inst, self.btn_backup, self.btn_stop]

        SectionTitle(parent, "Сервис", "●",
                     color=P.fg_faint).pack(fill="x", padx=14, pady=(16, 6))

        svc1 = ctk.CTkFrame(parent, fg_color="transparent")
        svc1.pack(fill="x", padx=14)

        for text, cmd in (
            ("📂  Папка", self.on_open_folder),
            ("🎨  Профили", self.on_open_profiles),
            ("⚙  Настр.", self.on_settings),
            ("📚  Шаблоны", self.on_manage_papers),
        ):
            ctk.CTkButton(
                svc1, text=text, command=cmd,
                font=F.get("tiny"),
                fg_color=P.bg_overlay, hover_color=P.bg_hover,
                text_color=P.fg_dim,
                height=32, corner_radius=6).pack(
                side="left", fill="x", expand=True, padx=1)

        svc2 = ctk.CTkFrame(parent, fg_color="transparent")
        svc2.pack(fill="x", padx=14, pady=(4, 14))

        ctk.CTkButton(
            svc2, text="🔧  Драйвер",
            command=self._show_zadig_help,
            font=F.get("tiny"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.fg_dim,
            height=32, corner_radius=6).pack(
            side="left", fill="x", expand=True, padx=(1, 1))

        ctk.CTkButton(
            svc2, text="♻  Перезапуск",
            command=self.on_restart,
            font=F.get("tiny"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.sky,
            height=32, corner_radius=6).pack(
            side="left", fill="x", expand=True, padx=(1, 1))

        ctk.CTkButton(
            svc2, text="❌  Выход",
            command=self.on_exit,
            font=F.get("tiny"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.red,
            height=32, corner_radius=6).pack(
            side="left", fill="x", expand=True, padx=(1, 1))

    def _add_op_btn(self, parent, text, icon, cmd, color):
        btn = ctk.CTkButton(
            parent, text=f"  {icon}   {text}",
            command=cmd,
            font=F.get("btn"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.fg,
            anchor="w",
            height=42, corner_radius=6)
        btn.pack(fill="x", pady=2)
        return btn

    def _build_right_panel(self, parent):
        SectionTitle(parent, "Прогресс", "◉",
                     color=P.accent).pack(fill="x", padx=14, pady=(14, 6))

        prog_box = ctk.CTkFrame(parent, fg_color="transparent")
        prog_box.pack(fill="x", padx=14)

        info_row = ctk.CTkFrame(prog_box, fg_color="transparent")
        info_row.pack(fill="x")
        self.progress_label = ctk.CTkLabel(
            info_row, text="Ожидание запуска...",
            font=F.get("body"), text_color=P.fg, anchor="w")
        self.progress_label.pack(side="left")

        bar_wrap = ctk.CTkFrame(prog_box, fg_color="transparent")
        bar_wrap.pack(fill="x", pady=(6, 0))

        self.progress = ctk.CTkProgressBar(
            bar_wrap, height=24,
            fg_color=P.bg_surface, progress_color=P.mauve,
            corner_radius=10)
        self.progress.set(0)
        self.progress.pack(fill="x")

        self.progress_pct = ctk.CTkLabel(
            bar_wrap, text="0%", font=F.get("btn_small"),
            text_color=P.fg)

        self.pause_banner = ctk.CTkFrame(prog_box, fg_color=P.yellow,
                                         corner_radius=8)
        self.pause_label = ctk.CTkLabel(
            self.pause_banner, text="",
            font=F.get("btn"), text_color=P.bg_root,
            wraplength=680, justify="left", anchor="w")
        self.pause_label.pack(side="left", fill="x", expand=True,
                              padx=14, pady=10)

        self.btn_continue = ctk.CTkButton(
            self.pause_banner, text="▶  ПРОДОЛЖИТЬ",
            font=F.get("btn"),
            fg_color=P.bg_root, hover_color=P.bg_surface,
            text_color=P.yellow,
            command=self._release_pause,
            height=38, corner_radius=6)
        self.btn_continue.pack(side="right", padx=8, pady=6)

        SectionTitle(parent, "Журнал", "▤",
                     color=P.fg_muted).pack(fill="x", padx=14, pady=(14, 6))

        tab_wrap = ctk.CTkFrame(parent, fg_color="transparent")
        tab_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        tab_bar = ctk.CTkFrame(tab_wrap, fg_color="transparent")
        tab_bar.pack(fill="x")
        self.tab_buttons = {}
        self.tab_frames = {}
        self.tab_current = None

        for key, label in (("log", "📋  Журнал"),
                           ("meta", "📊  Метаданные"),
                           ("raw", "🖥  Сырой вывод")):
            b = ctk.CTkButton(
                tab_bar, text=label,
                font=F.get("small"),
                fg_color=P.bg_overlay, hover_color=P.bg_hover,
                text_color=P.fg_dim,
                height=32, corner_radius=6,
                command=lambda k=key: self._switch_tab(k))
            b.pack(side="left", padx=(0, 2))
            self.tab_buttons[key] = b
            f = ctk.CTkFrame(tab_wrap, fg_color=P.bg_log, corner_radius=6)
            self.tab_frames[key] = f

        log_f = self.tab_frames["log"]
        log_box = tk.Frame(log_f, bg=P.bg_log)
        log_box.pack(fill="both", expand=True, padx=2, pady=2)

        self.log_text = tk.Text(
            log_box, wrap="char", font=F.get("mono_log"),
            bg=P.bg_log, fg=P.fg,
            insertbackground=P.fg, relief="flat", bd=0,
            padx=14, pady=10, state="disabled",
            spacing1=2, spacing3=4)
        log_sb = ctk.CTkScrollbar(
            log_box, command=self.log_text.yview,
            fg_color=P.bg_surface, button_color=P.bg_hover,
            button_hover_color=P.accent, width=12)
        log_sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.config(yscrollcommand=log_sb.set)

        for tag, color in (
            ("INFO",    P.fg),
            ("WARNING", P.yellow),
            ("ERROR",   P.red),
            ("SUCCESS", P.green),
            ("STEP",    P.mauve),
            ("DIM",     P.fg_dim),
        ):
            self.log_text.tag_config(tag, foreground=color)

        meta_f = self.tab_frames["meta"]
        meta_box = tk.Frame(meta_f, bg=P.bg_log)
        meta_box.pack(fill="both", expand=True, padx=2, pady=2)
        self.meta_text = tk.Text(
            meta_box, wrap="word", font=F.get("mono"),
            bg=P.bg_log, fg=P.fg,
            insertbackground=P.fg, relief="flat", bd=0,
            padx=10, pady=8, state="disabled")
        meta_sb = ctk.CTkScrollbar(
            meta_box, command=self.meta_text.yview,
            fg_color=P.bg_surface, button_color=P.bg_hover,
            button_hover_color=P.accent, width=12)
        meta_sb.pack(side="right", fill="y")
        self.meta_text.pack(side="left", fill="both", expand=True)
        self.meta_text.config(yscrollcommand=meta_sb.set)

        raw_f = self.tab_frames["raw"]
        raw_box = tk.Frame(raw_f, bg=P.bg_log)
        raw_box.pack(fill="both", expand=True, padx=2, pady=2)
        self.raw_text = tk.Text(
            raw_box, wrap="word", font=F.get("mono_small"),
            bg=P.bg_log, fg=P.fg_dim,
            insertbackground=P.fg, relief="flat", bd=0,
            padx=10, pady=8, state="disabled")
        raw_sb = ctk.CTkScrollbar(
            raw_box, command=self.raw_text.yview,
            fg_color=P.bg_surface, button_color=P.bg_hover,
            button_hover_color=P.accent, width=12)
        raw_sb.pack(side="right", fill="y")
        self.raw_text.pack(side="left", fill="both", expand=True)
        self.raw_text.config(yscrollcommand=raw_sb.set)

        self._switch_tab("log")

    def _switch_tab(self, key):
        if self.tab_current == key:
            return
        for k, f in self.tab_frames.items():
            if k == key:
                f.pack(fill="both", expand=True, pady=(4, 0))
                self.tab_buttons[k].configure(
                    fg_color=P.bg_overlay, text_color=P.accent)
            else:
                f.pack_forget()
                self.tab_buttons[k].configure(
                    fg_color=P.bg_overlay, text_color=P.fg_dim)
        self.tab_current = key

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self.root, fg_color=P.bg_surface,
                           height=46, corner_radius=0)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.status_dot = StatusDot(bar, P.green, size=12, bg=P.bg_surface)
        self.status_dot.pack(side="left", padx=(14, 6), pady=17)

        self.status = ctk.CTkLabel(
            bar, text="Готов к работе",
            font=F.get("small"), text_color=P.fg_dim, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        self.clock_label = ctk.CTkLabel(
            bar, text="", font=F.get("clock"), text_color=P.fg_muted)
        self.clock_label.pack(side="right", padx=(0, 10))

        author_box = ctk.CTkFrame(bar, fg_color=P.bg_overlay,
                                  corner_radius=6)
        author_box.pack(side="right", padx=(0, 14), pady=7)
        ctk.CTkLabel(
            author_box, text="VOROSHILOV.D.V.  •  2026  •  ESSO",
            font=F.get("author"), text_color=P.mauve,
        ).pack(padx=12, pady=2)

        tk.Frame(bar, bg=P.border, width=1).pack(
            side="right", fill="y", padx=6, pady=8)

    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2 - 20
        if y < 0:
            y = 0
        if x < 0:
            x = 0
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ═══════════════════════════════════════════════════════════
    # ЛОГИКА UI
    # ═══════════════════════════════════════════════════════════
    def _append_log(self, level, msg):
        try:
            self._log_buffer.append((level, msg))
            if len(self._log_buffer) > 5000:
                del self._log_buffer[:1000]
        except Exception:
            pass

        if self._daily_log_dir and level != "DIM":
            try:
                day = time.strftime("%Y-%m-%d")
                path = os.path.join(self._daily_log_dir, f"{day}.log")
                line = (f"[{time.strftime('%H:%M:%S')}] "
                        f"[{level:<7}] {msg}\n")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

        try:
            self.log_text.config(state="normal")
            tag = level if level in (
                "INFO", "WARNING", "ERROR", "SUCCESS", "STEP", "DIM") \
                else "INFO"
            self.log_text.insert("end", msg + "\n", tag)
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        except tk.TclError:
            pass

    def _clear_log(self):
        try:
            self._log_buffer = []
        except Exception:
            pass
        try:
            self.log_text.config(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.config(state="disabled")
        except tk.TclError:
            pass

    def _save_log_to_file(self, target_dir: str) -> str:
        if not target_dir or not os.path.isdir(target_dir):
            return ""
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(target_dir, f"profile_log_{ts}.txt")
            header = [
                "Argyll Printer Profiler — журнал операции",
                f"Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"Папка: {target_dir}",
                "─" * 60,
                "",
            ]
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(header))
                for lvl, msg in self._log_buffer:
                    f.write(f"[{lvl:<7}] {msg}\n")
            return path
        except Exception as e:
            self._append_log("WARNING", f"Не удалось сохранить лог: {e}")
            return ""

    def _set_meta(self, data: dict):
        try:
            self.meta_text.config(state="normal")
            self.meta_text.delete("1.0", "end")
            for k, v in data.items():
                self.meta_text.insert("end", f"{k:<22} =  {v}\n")
            self.meta_text.config(state="disabled")
            self._switch_tab("meta")
        except tk.TclError:
            pass

    def _set_raw(self, text: str):
        try:
            self.raw_text.config(state="normal")
            self.raw_text.delete("1.0", "end")
            self.raw_text.insert("end", text or "(пусто)")
            self.raw_text.config(state="disabled")
        except tk.TclError:
            pass

    def _poll_queues(self):
        if self._closing:
            return
        while True:
            try:
                level, msg = self.log_queue.get_nowait()
                self._append_log(level, msg)
            except queue.Empty:
                break
        while True:
            try:
                step, total, msg = self.progress_queue.get_nowait()
                pct = step / max(total, 1)
                try:
                    self.progress.set(max(0.0, min(1.0, pct)))
                    self.progress_pct.configure(text=f"{int(pct * 100)}%")
                    self.progress_label.configure(text=msg)
                    self.status.configure(text=msg)
                except tk.TclError:
                    pass
            except queue.Empty:
                break
        while True:
            try:
                kind, err = self.done_queue.get_nowait()
                self._on_worker_done(kind, err)
            except queue.Empty:
                break
        try:
            self.root.after(100, self._poll_queues)
        except tk.TclError:
            pass

    def _tick_clock(self):
        if self._closing:
            return
        now = time.strftime("%H:%M:%S")
        try:
            if self.is_running and self._start_time:
                elapsed = int(time.time() - self._start_time)
                mm, ss = divmod(elapsed, 60)
                hh, mm = divmod(mm, 60)
                self.clock_label.configure(
                    text=f"⏱ {hh:02d}:{mm:02d}:{ss:02d}   •   {now}")
            else:
                self.clock_label.configure(text=now)
            self.root.after(1000, self._tick_clock)
        except tk.TclError:
            pass

    # ═══════════════════════════════════════════════════════════
    # ПАТЧИ
    # ═══════════════════════════════════════════════════════════
    def _mark_patches_touched(self, event=None):
        self._patches_touched = True
        self._update_patches_hint()

    def _spin_patches(self, delta: int):
        try:
            cur = int(self.var_patches.get())
        except Exception:
            cur = self.cfg.default_patches
        new = max(50, min(10000, cur + delta))
        self.var_patches.set(new)
        self._patches_touched = True
        self._update_patches_hint()

    def _set_patches(self, value: int, mark_touched: bool = False):
        try:
            self.var_patches.set(int(value))
        except Exception:
            return
        if mark_touched:
            self._patches_touched = True
        self._update_patches_hint()

    def _update_patches_hint(self):
        try:
            cur = int(self.var_patches.get())
            default = self.cfg.default_patches
            if cur != default:
                self.patches_hint.configure(
                    text=f"⚠  отличается от значения по умолчанию ({default})")
            else:
                self.patches_hint.configure(text="")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # WORKER
    # ═══════════════════════════════════════════════════════════
    def _set_running(self, running: bool):
        self.is_running = running
        for b in self.btn_all:
            try:
                if self._is_locked():
                    b.configure(state="disabled")
                    continue
                if b is self.btn_stop:
                    b.configure(state="normal" if running else "disabled")
                else:
                    b.configure(state="disabled" if running else "normal")
            except tk.TclError:
                pass
        if running:
            try:
                self.status_dot.set_color(P.mauve)
            except tk.TclError:
                pass
            self._start_time = time.time()
        else:
            self._start_time = None

    def _start_worker(self, task_fn, title: str, pre_backup: bool = True):
        if not self._guard_operation():
            return
        if self.is_running:
            messagebox.showwarning("Занято", "Операция уже выполняется")
            return
        if pre_backup:
            self._safety_backup()
        self._clear_log()
        self._append_log("STEP", f"═══ {title} ═══")
        try:
            self.progress.set(0)
            self.progress_pct.configure(text="0%")
            self.progress_label.configure(text="Запуск...")
            self.status.configure(text=f"⏳ {title}...")
        except tk.TclError:
            pass
        self._set_running(True)
        self._pause_event.set()
        self._hide_pause_banner()

        self.cancel_event.clear()
        self._current_proc = None
        worker = ProfilerWorker(task_fn, self.log_queue,
                                self.progress_queue, self.done_queue,
                                self.cancel_event)
        self.worker = worker
        worker.start()

    def _on_worker_done(self, kind, err):
        self._set_running(False)
        self._hide_pause_banner()
        if kind == "cancelled":
            try:
                self.status.configure(text="⏹ Остановлено пользователем")
                self.status_dot.set_color(P.orange)
                self.progress_label.configure(text="Остановлено")
            except tk.TclError:
                pass
            self._append_log("WARNING", "⏹ Операция прервана пользователем")
            self._maybe_save_log_after_op()
            return
        if kind == "ok":
            try:
                self.progress.set(1.0)
                self.progress_pct.configure(text="100%")
                self.status.configure(text="✅ Готово")
                self.status_dot.set_color(P.green)
            except tk.TclError:
                pass
            self._append_log("SUCCESS", "✅ Операция успешно завершена")
            self._maybe_save_log_after_op()
            messagebox.showinfo("Готово", "Операция успешно завершена.")
        else:
            try:
                self.status.configure(text="❌ Ошибка")
                self.status_dot.set_color(P.red)
            except tk.TclError:
                pass
            self._append_log("ERROR", f"Ошибка: {err}")
            self._maybe_save_log_after_op()
            err_text = (err or "").lower()
            is_instrument_err = (
                "colormunki" in err_text
                or "прибор" in err_text
                or "instrument" in err_text
            )
            if is_instrument_err:
                self._ask_zadig_help()
            else:
                messagebox.showerror(
                    "Ошибка", err or "Неизвестная ошибка")

    def _maybe_save_log_after_op(self):
        if not self._log_save_after_ops:
            return
        target = self._current_profile_dir
        if not target:
            return
        path = self._save_log_to_file(target)
        if path:
            self._append_log("SUCCESS", f"📝 Лог сохранён: {path}")
        self._log_save_after_ops = False
        self._current_profile_dir = None

    # ═══════════════════════════════════════════════════════════
    # ПАУЗА
    # ═══════════════════════════════════════════════════════════
    def _request_pause(self, message: str):
        if self.cancel_event.is_set() or self._closing:
            return
        self.log_queue.put(("WARNING", f"⏸  {message}"))
        self._pause_event.clear()
        try:
            self.root.after(0, lambda: self._show_pause_banner(message))
        except tk.TclError:
            return
        while not self._pause_event.wait(timeout=0.2):
            if self.cancel_event.is_set() or self._closing:
                break
        try:
            self.root.after(0, self._hide_pause_banner)
        except tk.TclError:
            pass

    def _show_pause_banner(self, message: str):
        if self._closing:
            return
        try:
            self.pause_label.configure(text=f"⏸  {message}")
            if not self.pause_banner.winfo_ismapped():
                self.pause_banner.pack(fill="x", pady=(10, 0))
            self.status.configure(text=f"⏸ {message}")
            self.status_dot.set_color(P.yellow)
            self._pulse_on = True
            self._pulse_banner()
        except tk.TclError:
            pass

    def _pulse_banner(self):
        if not self._pulse_on or self._closing:
            return
        try:
            current = self.pause_banner.cget("fg_color")
            new = P.orange if current == P.yellow else P.yellow
            self.pause_banner.configure(fg_color=new)
            self.root.after(600, self._pulse_banner)
        except tk.TclError:
            return

    def _hide_pause_banner(self):
        self._pulse_on = False
        if self._closing:
            return
        try:
            self.pause_banner.pack_forget()
            self.pause_banner.configure(fg_color=P.yellow)
        except tk.TclError:
            pass
        if self.is_running:
            try:
                self.status_dot.set_color(P.mauve)
            except tk.TclError:
                pass

    def _release_pause(self):
        self._pause_event.set()

    # ═══════════════════════════════════════════════════════════
    # ОБЩИЕ ЗАДАЧИ
    # ═══════════════════════════════════════════════════════════
    def _safety_backup(self):
        import datetime as _dt
        import zipfile
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        bdir = self.cfg.backup_dir or os.path.join(SCRIPT_DIR, "backups")
        os.makedirs(bdir, exist_ok=True)
        zp = os.path.join(bdir, f"_pre_run_{ts}.zip")
        try:
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
                candidates = [
                    os.path.join(SCRIPT_DIR, CONFIG_FILENAME),
                    os.path.join(self.cfg.base_dir, CONFIG_FILENAME),
                ]
                for cfg_path in candidates:
                    if os.path.exists(cfg_path):
                        z.write(cfg_path, CONFIG_FILENAME)
                        break
                papers_path = getattr(self.cfg, "papers_library", None)
                if papers_path and os.path.exists(papers_path):
                    z.write(papers_path, os.path.basename(papers_path))
            self._append_log("SUCCESS", f"💾 Страховочный бэкап: {zp}")
        except Exception as e:
            self._append_log("WARNING", f"Бэкап не создан: {e}")

    def _build_profiler(self, log_fn, progress_fn):
        self.logger.set_gui_callback(lambda lvl, m: log_fn(lvl, m))
        return Profiler(
            self.cfg, self.logger,
            progress_cb=lambda s, t, m: progress_fn(s, t, m),
            pause_cb=self._request_pause,
            cancel_event=self.cancel_event,
            proc_cb=self._register_proc,
        )

    def _register_proc(self, proc):
        self._current_proc = proc

    def on_stop(self):
        if not self.is_running:
            return
        if not messagebox.askyesno(
                "Стоп",
                "Прервать текущую операцию?\n\n"
                "Незавершённые файлы (.ti1, .ti2, .ti3) останутся в папке "
                "профиля — их можно дособрать через "
                "«Продолжить измерение»."):
            return
        self._append_log("WARNING", "⏹ Запрошена остановка...")
        try:
            self.status.configure(text="⏹ Останавливаю...")
        except tk.TclError:
            pass
        self.cancel_event.set()
        self._pause_event.set()
        proc = self._current_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception as e:
                self._append_log("ERROR", f"Не удалось убить процесс: {e}")

    def _read_request_from_ui(self) -> ProfileRequest:
        paper = sanitize_name(
            self.var_paper.get().strip() or "Unknown", "Unknown")
        try:
            patches_val = int(self.var_patches.get())
        except Exception:
            patches_val = self.cfg.default_patches
        return ProfileRequest(
            printer=sanitize_name(self.var_printer.get(), "Printer"),
            paper=paper,
            finish=self.var_finish.get(),
            paper_size=self.var_size.get(),
            patches=clamp_patches(patches_val),
            overwrite=self.var_overwrite.get(),
            resume=self.var_resume.get(),
        )

    # ═══════════════════════════════════════════════════════════
    # ОБРАБОТЧИКИ КНОПОК
    # ═══════════════════════════════════════════════════════════
    def on_full_cycle(self):
        if not self._guard_operation():
            return
        req = self._read_request_from_ui()
        auto_backup = self.var_auto_backup.get()
        self._log_save_after_ops = True

        def task(log_fn, progress_fn):
            profiler = self._build_profiler(log_fn, progress_fn)
            icc = profiler.run_full(req)
            profile_dir = os.path.dirname(icc)
            self._current_profile_dir = profile_dir
            meta = load_metadata(profile_dir)
            self.root.after(0, lambda: self._set_meta(meta))
            if auto_backup:
                try:
                    zp = create_backup(profile_dir, self.cfg.backup_dir)
                    log_fn("SUCCESS", f"💾 Бэкап: {zp}")
                except Exception as e:
                    log_fn("WARNING", f"Не удалось создать бэкап: {e}")

        self._start_worker(
            task, f"Полный цикл: {req.paper} ({req.patches} патчей)")

    def on_measure_only(self):
        if not self._guard_operation():
            return
        folder = filedialog.askdirectory(
            title="Выберите папку с напечатанной мишенью",
            initialdir=self.cfg.base_dir)
        if not folder:
            return
        resume = self.var_resume.get()
        self._current_profile_dir = folder
        self._log_save_after_ops = True

        def task(log_fn, progress_fn):
            profiler = self._build_profiler(log_fn, progress_fn)
            profiler.run_measurement(folder, resume=resume)

        self._start_worker(task, "Только измерение")

    @staticmethod
    def _find_unfinished_profiles(base: str, max_depth: int = 3):
        found = []
        base = os.path.abspath(base)
        for root, dirs, files in os.walk(base):
            rel = os.path.relpath(root, base)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > max_depth:
                dirs[:] = []
                continue
            has_ti3 = any(f.lower().endswith(".ti3") for f in files)
            has_icc = any(f.lower().endswith((".icc", ".icm"))
                          for f in files)
            if has_ti3 and not has_icc:
                found.append(root)
        return found

    def on_resume(self):
        if not self._guard_operation():
            return
        base = self.cfg.base_dir
        candidates = []
        if os.path.isdir(base):
            try:
                candidates = self._find_unfinished_profiles(base)
            except Exception as e:
                self._append_log("WARNING",
                                 f"Поиск незавершённых профилей: {e}")

        if not candidates:
            folder = filedialog.askdirectory(
                title="Выберите папку для продолжения",
                initialdir=self.cfg.base_dir)
            if not folder:
                return
            candidates = [folder]
        else:
            msg = "Найдены незавершённые профили:\n" + \
                  "\n".join("  • " + os.path.relpath(c, base)
                            for c in candidates) + \
                  "\n\nПродолжить первый?"
            if not messagebox.askyesno("Resume", msg):
                folder = filedialog.askdirectory(
                    title="Выберите папку для продолжения",
                    initialdir=self.cfg.base_dir)
                if not folder:
                    return
                candidates = [folder]

        folder = candidates[0]
        self._current_profile_dir = folder
        self._log_save_after_ops = True

        def task(log_fn, progress_fn):
            profiler = self._build_profiler(log_fn, progress_fn)
            profiler.run_measurement(folder, resume=True)

        self._start_worker(task, f"Resume: {os.path.basename(folder)}")

    def on_improve_1200(self):
        if not self._guard_operation():
            return
        req = self._read_request_from_ui()
        base = clamp_patches(req.patches)
        req.patches = max(base, self.cfg.quality_patches)
        req.overwrite = True
        req.paper = req.paper + f"_{req.patches}"

        target_dir = os.path.join(self.cfg.base_dir, req.paper)
        if os.path.isdir(target_dir):
            if not messagebox.askyesno(
                "Перезапись",
                f"Папка «{req.paper}» уже существует.\n"
                f"Перезаписать результаты ({req.patches} патчей)?"):
                return

        self._log_save_after_ops = True

        def task(log_fn, progress_fn):
            profiler = self._build_profiler(log_fn, progress_fn)
            icc = profiler.run_full(req)
            profile_dir = os.path.dirname(icc)
            self._current_profile_dir = profile_dir

        self._start_worker(task, f"{req.patches} патчей: {req.paper}")

    def on_check_accuracy(self):
        if not self._guard_operation():
            return
        folder = filedialog.askdirectory(
            title="Выберите папку профиля",
            initialdir=self.cfg.base_dir)
        if not folder:
            return

        self._current_profile_dir = folder
        self._log_save_after_ops = True

        def task(log_fn, progress_fn):
            profiler = self._build_profiler(log_fn, progress_fn)
            progress_fn(1, 1, "Проверка DeltaE (profcheck)...")
            stats = profiler.check_accuracy(folder)
            log_fn("STEP", "─" * 52)
            log_fn("INFO", f"  Peak ΔE: {stats.get('peak')}")
            log_fn("INFO", f"  Avg  ΔE: {stats.get('avg')}")
            log_fn("INFO", f"  RMS:     {stats.get('rms')}")
            log_fn("SUCCESS", f"  {stats.get('quality', '')}")
            self.root.after(0, lambda: self._set_raw(stats.get("raw", "")))
            meta = load_metadata(folder)
            self.root.after(0, lambda: self._set_meta(meta))
            report = build_report(folder, stats, open_after=False)
            log_fn("SUCCESS", f"📄 Отчёт: {report}")
            self.root.after(0, lambda: self._offer_open(report))

        self._start_worker(task, "Проверка точности")

    def _offer_open(self, path):
        if messagebox.askyesno("Отчёт готов",
                               f"Открыть HTML-отчёт?\n\n{path}"):
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    @staticmethod
    def _find_profile_in_dir(folder: str) -> str:
        try:
            base = os.path.basename(os.path.normpath(folder))
            candidates = [fn for fn in os.listdir(folder)
                          if fn.lower().endswith((".icc", ".icm"))]
            if not candidates:
                return ""
            for fn in candidates:
                if os.path.splitext(fn)[0].lower() == base.lower():
                    return os.path.join(folder, fn)
            for fn in candidates:
                if fn.lower().startswith(base.lower()):
                    return os.path.join(folder, fn)
            candidates.sort()
            return os.path.join(folder, candidates[0])
        except Exception:
            pass
        return ""

    def on_compare(self):
        if not self._guard_operation():
            return
        f1 = filedialog.askdirectory(title="Первый профиль",
                                     initialdir=self.cfg.base_dir)
        if not f1:
            return
        f2 = filedialog.askdirectory(title="Второй профиль",
                                     initialdir=self.cfg.base_dir)
        if not f2:
            return

        icc1 = self._find_profile_in_dir(f1)
        icc2 = self._find_profile_in_dir(f2)
        if not icc1 or not icc2:
            messagebox.showerror(
                "Ошибка",
                "В одной из папок не найден файл .icc/.icm")
            return

        name1 = os.path.basename(icc1)
        name2 = os.path.basename(icc2)

        def task(log_fn, progress_fn):
            profiler = self._build_profiler(log_fn, progress_fn)
            progress_fn(1, 1, "Сравнение (profcheck -C)...")
            stats = profiler.compare(icc1, icc2)
            log_fn("STEP", "─" * 52)
            log_fn("INFO", f"  {name1}  ↔  {name2}")
            log_fn("INFO", f"  Peak ΔE: {stats.get('peak')}")
            log_fn("INFO", f"  Avg  ΔE: {stats.get('avg')}")
            log_fn("INFO", f"  RMS:     {stats.get('rms')}")
            self.root.after(0, lambda: self._set_raw(stats.get("raw", "")))

        self._start_worker(task, "Сравнение профилей", pre_backup=False)

    def on_backup(self):
        if not self._guard_operation():
            return
        folder = filedialog.askdirectory(
            title="Профиль для бэкапа",
            initialdir=self.cfg.base_dir)
        if not folder:
            return

        def task(log_fn, progress_fn):
            progress_fn(1, 1, "Создание ZIP-архива...")
            zp = create_backup(folder, self.cfg.backup_dir)
            log_fn("SUCCESS", f"💾 Бэкап: {zp}")

        self._start_worker(task, f"Бэкап: {os.path.basename(folder)}",
                           pre_backup=False)

    def on_check_instrument(self):
        if not self._guard_operation():
            return

        def task(log_fn, progress_fn):
            profiler = self._build_profiler(log_fn, progress_fn)
            progress_fn(1, 1, "Поиск прибора...")
            ok = profiler.argyll.check_instrument()
            if ok:
                self.root.after(0, lambda: self._update_dev_status(True))
            else:
                raise RuntimeError(
                    "ColorMunki не обнаружен. "
                    "Нажмите 🔧 Драйвер для справки по Zadig.")

        self._start_worker(task, "Проверка прибора", pre_backup=False)

    def _update_dev_status(self, ok: bool):
        if ok:
            self.header_dot.set_color(P.green)
            self.header_dev_label.configure(text="Прибор: подключён",
                                            text_color=P.green)
            self._zadig_shown = False
        else:
            self.header_dot.set_color(P.red)
            self.header_dev_label.configure(text="Прибор: не найден",
                                            text_color=P.red)

    def _ask_zadig_help(self):
        if self._closing:
            return
        if self._zadig_shown:
            return
        self._zadig_shown = True
        try:
            if messagebox.askyesno(
                "🔧 Установка драйвера (Zadig)",
                "Прибор не обнаружен.\n\n"
                "В 90% случаев нужен драйвер libusb-win32 через Zadig.\n\n"
                "Открыть окно с пошаговой инструкцией?"
            ):
                self._show_zadig_help()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # СПРАВКА ПО ZADIG
    # ═══════════════════════════════════════════════════════════
    def _show_zadig_help(self):
        w = ctk.CTkToplevel(self.root)
        w.title("🔧  Драйвер ColorMunki через Zadig")
        w.geometry("780x680")
        w.transient(self.root)
        w.grab_set()

        head = ctk.CTkFrame(w, fg_color=P.bg_main, height=56,
                            corner_radius=0)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=P.yellow, width=5).pack(side="left", fill="y")
        ctk.CTkLabel(head, text="🔧  Установка драйвера через Zadig",
                     font=F.get("title"), text_color=P.fg).pack(
            side="left", padx=14)

        body = ctk.CTkFrame(w, fg_color=P.bg_root, corner_radius=0)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        txt = tk.Text(body, wrap="word", font=F.get("body"),
                      bg=P.bg_log, fg=P.fg,
                      relief="flat", bd=0, padx=14, pady=12)
        txt.pack(fill="both", expand=True)

        txt.tag_config("h", font=F.get("h2"), foreground=P.accent,
                       spacing1=10, spacing3=6)
        txt.tag_config("ok", foreground=P.green)
        txt.tag_config("warn", foreground=P.orange)
        txt.tag_config("dim", foreground=P.fg_muted)

        def h(t): txt.insert("end", t + "\n", "h")
        def t(t): txt.insert("end", t + "\n")
        def ok(t): txt.insert("end", t + "\n", "ok")
        def warn(t): txt.insert("end", t + "\n", "warn")
        def dim(t): txt.insert("end", t + "\n", "dim")

        h("🎯 Что делать (5 минут)")
        t("1. Скачайте Zadig:  https://zadig.akeo.ie/")
        t("2. Запустите Zadig ОТ ИМЕНИ АДМИНИСТРАТОРА.")
        t("3. Меню Options → галочка 'List All Devices'.")
        t("4. Выберите 'colormunki' (Interface 0).")
        t("5. В поле справа от стрелок выберите:")
        ok("     libusb-win32 (v1.4.0.0)")
        t("6. Нажмите 'Install Driver' или 'Replace Driver'.")
        t("7. Дождитесь окончания — 10-30 секунд.")
        t("8. Закройте Zadig и нажмите '🔍 Проверить прибор'.")

        h("✅ Как понять, что всё сработало")
        ok("• В журнале: ✅ Прибор обнаружен и готов к работе")
        ok("• В заголовке окна кружок станет зелёным")
        ok("• В Диспетчере устройств появится 'libusb-win32 devices'")

        h("🔄 Возврат родного драйвера (для i1Studio / Calibrite)")
        warn("Если после профилирования захотите снова использовать i1Studio:")
        t("1. Откройте Zadig.")
        t("2. Options → List All Devices → выберите colormunki (Interface 0).")
        t("3. В поле драйвера выберите 'HID (Microsoft)'.")
        t("4. Нажмите 'Replace Driver'.")
        t("5. Перезагрузите компьютер.")
        dim("Или через Диспетчер устройств: удалить устройство, "
            "отключить и подключить кабель — Windows поставит драйвер "
            "автоматически.")

        h("📋 Другие причины, если Zadig не помог")
        t("• Прибор занят другим ПО — закройте i1Studio, Calibrite, X-Rite.")
        t("• Недостаточно прав — запустите GUI от администратора.")
        t("• Плохой USB-кабель или порт — попробуйте другой порт.")
        t("• Устаревший firmware прибора — обратитесь к производителю.")

        txt.config(state="disabled")

        btns = ctk.CTkFrame(w, fg_color=P.bg_main, height=56,
                            corner_radius=0)
        btns.pack(fill="x", side="bottom")
        btns.pack_propagate(False)

        def open_zadig():
            webbrowser.open("https://zadig.akeo.ie/")

        ctk.CTkButton(
            btns, text="🌐  Открыть сайт Zadig", command=open_zadig,
            font=F.get("btn"),
            fg_color=P.accent, hover_color=P.sky,
            text_color=P.bg_root,
            height=40, corner_radius=6).pack(
            side="left", padx=14, pady=10)
        ctk.CTkButton(
            btns, text="Закрыть", command=w.destroy,
            font=F.get("btn"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.fg,
            height=40, corner_radius=6).pack(
            side="right", padx=14, pady=10)

    # ═══════════════════════════════════════════════════════════
    # ПРОЧЕЕ
    # ═══════════════════════════════════════════════════════════
    def _on_template_selected(self):
        name = self.var_template.get()
        if name == "— свой —":
            return
        t = self.papers.get(name)
        if not t:
            return

        current = self.var_patches.get()
        if (not self._patches_touched) or current == self.cfg.default_patches:
            self._set_patches(t.patches, mark_touched=False)
        else:
            self._update_patches_hint()

        self.var_paper.set(t.name)
        self.var_finish.set(t.finish)
        self.var_size.set(t.size)

        self._append_log(
            "INFO",
            f"📚 Шаблон: {t.name}  ({t.vendor})  •  "
            f"патчей: {self.var_patches.get()}")

    def _refresh_printers(self):
        plist = list_printers()
        if not plist:
            msg = ("Не удалось получить список принтеров.\n"
                   "Установите pywin32: pip install pywin32")
            messagebox.showinfo("Принтеры", msg)
            return
        try:
            self.printer_cb.configure(values=plist)
        except Exception as e:
            self._append_log(
                "WARNING",
                f"Не удалось обновить список принтеров: {e}")
            return
        try:
            if self.var_printer.get() not in plist:
                self.var_printer.set(plist[0])
        except Exception:
            pass
        self._append_log("INFO", f"🖨 Найдено принтеров: {len(plist)}")

    def on_open_folder(self):
        path = self.cfg.base_dir
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def on_open_profiles(self):
        base = self.cfg.base_dir
        os.makedirs(base, exist_ok=True)

        built = []
        try:
            for f in os.listdir(base):
                p = os.path.join(base, f)
                if not os.path.isdir(p):
                    continue
                has_icc = any(
                    fn.lower().endswith((".icc", ".icm"))
                    for fn in os.listdir(p)
                )
                if has_icc:
                    built.append((p, os.path.getmtime(p)))
        except Exception as e:
            self._append_log("ERROR", f"Не удалось просканировать: {e}")
            return

        if not built:
            self._append_log("INFO",
                             "📂 Готовых профилей пока нет — открываю profiles/")
            try:
                os.startfile(base)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
            return

        built.sort(key=lambda x: x[1], reverse=True)
        latest = built[0][0]

        self._append_log(
            "INFO",
            f"🎨 Найдено профилей: {len(built)}. "
            f"Последний: {os.path.basename(latest)}",
        )

        try:
            subprocess.Popen(["explorer", f"/select,{latest}"])
        except Exception as e:
            self._append_log("WARNING", f"Не удалось выделить: {e}")
            try:
                os.startfile(base)
            except Exception as e2:
                messagebox.showerror("Ошибка", str(e2))

    def on_settings(self):
        w = ctk.CTkToplevel(self.root)
        w.title("⚙  Настройки")
        w.geometry("680x820")
        w.transient(self.root)
        w.grab_set()

        head = ctk.CTkFrame(w, fg_color=P.bg_main, height=56,
                            corner_radius=0)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=P.mauve, width=5).pack(side="left", fill="y")
        ctk.CTkLabel(head, text="⚙  Настройки", font=F.get("title"),
                     text_color=P.fg).pack(side="left", padx=14)

        body = ctk.CTkScrollableFrame(w, fg_color=P.bg_root, corner_radius=0)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        def section(title, color):
            ctk.CTkLabel(body, text=title, font=F.get("h2"),
                         text_color=color, anchor="w").pack(
                fill="x", pady=(8, 4))
            ctk.CTkFrame(body, fg_color=P.border, height=1,
                         corner_radius=0).pack(fill="x")
            box = ctk.CTkFrame(body, fg_color="transparent")
            box.pack(fill="x", pady=6)
            return box

        def field(parent, label, value, width=44):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=label, width=180, anchor="w",
                         font=F.get("small"),
                         text_color=P.fg_dim).pack(side="left")
            e = ctk.CTkEntry(row, font=F.get("body"),
                             fg_color=P.bg_overlay, border_color=P.border,
                             text_color=P.fg)
            e.insert(0, str(value))
            e.pack(side="left", fill="x", expand=True)
            return e

        s1 = section("ArgyllCMS", P.sky)
        e_argyll = field(s1, "Путь к bin:", self.cfg.argvll_path)

        s2 = section("Папки", P.sky)
        e_base = field(s2, "Профили:", self.cfg.base_dir)
        e_backup = field(s2, "Бэкапы:", self.cfg.backup_dir)

        s3 = section("Профили", P.mauve)
        e_printer = field(s3, "Имя принтера:", self.cfg.printer_name)

        current_patches = self.var_patches.get()
        e_def = field(s3, "Патчей по умолч.:", current_patches)
        e_q = field(s3, "Патчей качества:", self.cfg.quality_patches)
        e_to = field(s3, "Таймаут (сек):", self.cfg.timeout_seconds)

        ctk.CTkLabel(
            s3,
            text="ℹ  «Патчей по умолч.» синхронизировано со спинбоксом "
                 "главного окна.",
            font=F.get("tiny"), text_color=P.fg_muted,
            anchor="w", justify="left", wraplength=560,
        ).pack(fill="x", pady=(2, 0))

        s4 = section("Интерфейс", P.fg_muted)

        v_theme = tk.StringVar(
            value=_get_ui_setting("theme", "dark"))
        theme_row = ctk.CTkFrame(s4, fg_color="transparent")
        theme_row.pack(fill="x", pady=4)
        ctk.CTkLabel(theme_row, text="Тема:",
                     font=F.get("small"), text_color=P.fg_dim,
                     width=180, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            theme_row, values=["dark", "light"],
            variable=v_theme,
            font=F.get("small"), dropdown_font=F.get("small"),
            fg_color=P.bg_overlay, button_color=P.bg_hover,
            button_hover_color=P.accent,
            text_color=P.fg, dropdown_hover_color=P.bg_hover,
            dropdown_text_color=P.fg).pack(
            side="left", fill="x", expand=True)

        ctk.CTkLabel(
            s4,
            text="ℹ  После смены темы нажмите «♻ Перезапуск» "
                 "в сервисном блоке.",
            font=F.get("tiny"), text_color=P.fg_muted,
            anchor="w", justify="left", wraplength=560,
        ).pack(fill="x", pady=(2, 0))

        s5 = section("Прочее", P.fg_muted)
        v_auto = tk.BooleanVar(value=self.cfg.auto_backup)
        ctk.CTkCheckBox(
            s5, text="Автобэкап после создания профиля",
            variable=v_auto, font=F.get("small"),
            fg_color=P.green, hover_color=P.green,
            border_color=P.border_accent,
            text_color=P.fg,
            checkmark_color=P.bg_root).pack(anchor="w", pady=4)

        # ─── Лицензия ───
        if _LICENSE_AVAILABLE:
            s6 = section("Лицензия", P.yellow)
            lic_row = ctk.CTkFrame(s6, fg_color="transparent")
            lic_row.pack(fill="x", pady=4)

            hwid = get_hwid()
            lic_status = (
                f"✅ Активирована: {self.license_owner}"
                if self.activated
                else (f"🔓 Пробная: осталось "
                      f"{self.trial_left} из {TRIAL_LIMIT}"
                      if self.trial_left > 0
                      else "🔒 Пробный период истёк")
            )
            ctk.CTkLabel(
                lic_row, text=lic_status,
                font=F.get("small"),
                text_color=(P.green if self.activated
                             else (P.yellow if self.trial_left > 0
                                   else P.red)),
                anchor="w").pack(side="left")

            hwid_row = ctk.CTkFrame(s6, fg_color="transparent")
            hwid_row.pack(fill="x", pady=(4, 4))
            ctk.CTkLabel(hwid_row, text="HWID:",
                         font=F.get("small"),
                         text_color=P.fg_dim).pack(side="left",
                                                    padx=(0, 6))
            hwid_e = ctk.CTkEntry(
                hwid_row, font=F.get("mono_small"),
                fg_color=P.bg_overlay, border_color=P.border,
                text_color=P.yellow, height=28)
            hwid_e.insert(0, hwid)
            try:
                hwid_e.configure(state="readonly")
            except Exception:
                pass
            hwid_e.pack(side="left", fill="x", expand=True)

            def _copy_hwid2():
                try:
                    w.clipboard_clear()
                    w.clipboard_append(hwid)
                    messagebox.showinfo("OK", "HWID скопирован")
                except Exception:
                    pass

            ctk.CTkButton(
                hwid_row, text="📋", width=36, height=28,
                command=_copy_hwid2,
                font=F.get("small"),
                fg_color=P.bg_overlay, hover_color=P.bg_hover,
                text_color=P.accent).pack(side="left", padx=(4, 0))

            lic_btns = ctk.CTkFrame(s6, fg_color="transparent")
            lic_btns.pack(fill="x", pady=(4, 0))

            if not self.activated:
                ctk.CTkButton(
                    lic_btns, text="🔑  Активировать",
                    command=lambda: (w.destroy(),
                                      self._show_activation_dialog()),
                    font=F.get("small"),
                    fg_color=P.green, hover_color=P.teal,
                    text_color=P.bg_root,
                    height=30, corner_radius=6).pack(
                    side="left", fill="x", expand=True, padx=(0, 4))
            else:
                def _reset_lic():
                    if not messagebox.askyesno(
                            "Лицензия",
                            "Сбросить активацию? Потребуется ввести "
                            "ключ заново.\n\n"
                            "После сброса приложение закроется."):
                        return
                    try:
                        reset_license()
                    except Exception:
                        pass
                    messagebox.showinfo(
                        "OK", "Лицензия сброшена. Приложение закроется.")
                    try:
                        w.destroy()
                    except Exception:
                        pass
                    try:
                        self.root.after(200, self.on_exit)
                    except Exception:
                        pass

                ctk.CTkButton(
                    lic_btns, text="🗑  Сбросить ключ",
                    command=_reset_lic,
                    font=F.get("small"),
                    fg_color=P.red, hover_color=P.orange,
                    text_color=P.bg_root,
                    height=30, corner_radius=6).pack(
                    side="left", fill="x", expand=True)

        btns = ctk.CTkFrame(w, fg_color=P.bg_main, height=56,
                            corner_radius=0)
        btns.pack(fill="x", side="bottom")
        btns.pack_propagate(False)

        def save():
            self.cfg.argvll_path = e_argyll.get().strip()
            self.cfg.base_dir = e_base.get().strip()
            self.cfg.backup_dir = e_backup.get().strip()
            self.cfg.printer_name = e_printer.get().strip() or "Printer"
            try:
                self.cfg.default_patches = int(e_def.get())
                self.cfg.quality_patches = int(e_q.get())
                self.cfg.timeout_seconds = int(e_to.get())
            except ValueError:
                messagebox.showerror("Ошибка",
                                     "Числовые поля заполнены неверно")
                return
            self.cfg.auto_backup = v_auto.get()

            self._set_patches(self.cfg.default_patches, mark_touched=False)
            self._patches_touched = False

            _set_ui_setting("theme", v_theme.get())

            problems = self.cfg.validate()
            if problems:
                messagebox.showerror("Ошибка", "\n".join(problems))
                return
            try:
                self.cfg.save(os.path.join(SCRIPT_DIR, CONFIG_FILENAME))
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
                return

            self._check_argyll_tools()
            messagebox.showinfo("OK", "Настройки сохранены")
            w.destroy()

        ctk.CTkButton(
            btns, text="💾  Сохранить", command=save,
            font=F.get("btn"),
            fg_color=P.green, hover_color=P.teal,
            text_color=P.bg_root,
            height=40, corner_radius=6).pack(
            side="right", padx=14, pady=10)
        ctk.CTkButton(
            btns, text="Отмена", command=w.destroy,
            font=F.get("btn"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.fg,
            height=40, corner_radius=6).pack(side="right", pady=10)

    def on_manage_papers(self):
        w = ctk.CTkToplevel(self.root)
        w.title("📚  Шаблоны бумаг")
        w.geometry("920x600")
        w.transient(self.root)

        head = ctk.CTkFrame(w, fg_color=P.bg_main, height=56,
                            corner_radius=0)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=P.mauve, width=5).pack(side="left", fill="y")
        ctk.CTkLabel(head, text="📚  Шаблоны бумаг",
                     font=F.get("title"), text_color=P.fg).pack(
            side="left", padx=14)

        body = ctk.CTkFrame(w, fg_color=P.bg_root, corner_radius=0)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        cols = ("name", "vendor", "finish", "size", "patches", "media_type")
        headers = {
            "name": "Имя", "vendor": "Вендор", "finish": "Поверхн.",
            "size": "Размер", "patches": "Патчи", "media_type": "Media Type",
        }
        widths = {"name": 190, "vendor": 90, "finish": 80,
                  "size": 60, "patches": 60, "media_type": 190}

        tree = ttk.Treeview(body, columns=cols, show="headings",
                            height=15, style="Premium.Treeview")
        for c in cols:
            tree.heading(c, text=headers[c])
            tree.column(c, width=widths[c], anchor="w")
        tree.pack(side="left", fill="both", expand=True)

        sb = ctk.CTkScrollbar(
            body, command=tree.yview,
            fg_color=P.bg_surface, button_color=P.bg_hover,
            button_hover_color=P.accent, width=12)
        sb.pack(side="right", fill="y")
        tree.config(yscrollcommand=sb.set)

        def refresh():
            tree.delete(*tree.get_children())
            for t in self.papers.templates:
                tree.insert("", "end", values=(
                    t.name, t.vendor, t.finish, t.size,
                    t.patches, t.media_type))

        refresh()

        btns = ctk.CTkFrame(w, fg_color=P.bg_main, height=56,
                            corner_radius=0)
        btns.pack(fill="x", side="bottom")
        btns.pack_propagate(False)

        def add_tpl():
            self._edit_template(None, refresh)

        def edit_tpl():
            sel = tree.selection()
            if not sel:
                return
            name = tree.item(sel[0])["values"][0]
            t = self.papers.get(name)
            self._edit_template(t, refresh)

        def del_tpl():
            sel = tree.selection()
            if not sel:
                return
            name = tree.item(sel[0])["values"][0]
            if messagebox.askyesno("Удалить", f"Удалить шаблон '{name}'?"):
                self.papers.remove(name)
                refresh()

        def export_tpl():
            path = filedialog.asksaveasfilename(
                title="Экспорт шаблонов",
                defaultextension=".json",
                filetypes=[("JSON", "*.json")],
                initialfile="papers_export.json")
            if not path:
                return
            try:
                data = [
                    {"name": t.name, "vendor": t.vendor,
                     "finish": t.finish, "size": t.size,
                     "patches": t.patches,
                     "media_type": t.media_type, "notes": t.notes}
                    for t in self.papers.templates
                ]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                messagebox.showinfo("OK", f"Экспортировано: {len(data)}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        def import_tpl():
            path = filedialog.askopenfilename(
                title="Импорт шаблонов",
                filetypes=[("JSON", "*.json")])
            if not path:
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                count = 0
                for item in data:
                    tpl = PaperTemplate(
                        name=str(item.get("name", "")).strip(),
                        vendor=str(item.get("vendor", "")),
                        finish=str(item.get("finish", "Glossy")),
                        size=str(item.get("size", "A4")),
                        patches=int(item.get("patches", 800)),
                        media_type=str(item.get("media_type", "")),
                        notes=str(item.get("notes", "")))
                    if tpl.name:
                        self.papers.add(tpl)
                        count += 1
                refresh()
                messagebox.showinfo("OK", f"Импортировано: {count}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        for text, cmd, color in (
            ("➕  Добавить", add_tpl, P.green),
            ("✏  Изменить", edit_tpl, P.accent),
            ("🗑  Удалить", del_tpl, P.red),
            ("📥  Импорт", import_tpl, P.sky),
            ("📤  Экспорт", export_tpl, P.sky),
            ("Закрыть", w.destroy, P.fg_dim),
        ):
            ctk.CTkButton(
                btns, text=text, command=cmd,
                font=F.get("btn"),
                fg_color=P.bg_overlay, hover_color=P.bg_hover,
                text_color=color,
                height=40, corner_radius=6).pack(
                side="left", padx=6, pady=10)

    def _edit_template(self, tpl, on_save):
        w = ctk.CTkToplevel(self.root)
        w.title("Шаблон бумаги")
        w.geometry("580x540")
        w.transient(self.root)
        w.grab_set()

        head = ctk.CTkFrame(w, fg_color=P.bg_main, height=50,
                            corner_radius=0)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=P.green, width=5).pack(side="left", fill="y")
        ctk.CTkLabel(
            head,
            text=("✏  Изменить шаблон" if tpl else "➕  Новый шаблон"),
            font=F.get("title"), text_color=P.fg).pack(side="left", padx=14)

        body = ctk.CTkFrame(w, fg_color=P.bg_root, corner_radius=0)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        def field(label, value):
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=label, width=140, anchor="w",
                         font=F.get("small"),
                         text_color=P.fg_dim).pack(side="left")
            e = ctk.CTkEntry(row, font=F.get("body"),
                             fg_color=P.bg_overlay, border_color=P.border,
                             text_color=P.fg)
            e.insert(0, str(value))
            e.pack(side="left", fill="x", expand=True)
            return e

        e_name = field("Имя:", tpl.name if tpl else "")
        e_vendor = field("Вендор:", tpl.vendor if tpl else "")
        e_finish = field("Поверхность:", tpl.finish if tpl else "Glossy")
        e_size = field("Размер:", tpl.size if tpl else "A4")
        e_patches = field("Патчи:", tpl.patches if tpl else 800)
        e_media = field("Media Type:", tpl.media_type if tpl else "")
        e_notes = field("Заметки:", tpl.notes if tpl else "")

        def save():
            name = e_name.get().strip()
            if not name:
                messagebox.showerror("Ошибка", "Имя обязательно")
                return
            try:
                patches = int(e_patches.get())
            except ValueError:
                messagebox.showerror("Ошибка", "Патчи — целое число")
                return
            new_tpl = PaperTemplate(
                name=name, vendor=e_vendor.get().strip(),
                finish=e_finish.get().strip(),
                size=e_size.get().strip(),
                patches=patches,
                media_type=e_media.get().strip(),
                notes=e_notes.get().strip())
            if tpl:
                self.papers.remove(tpl.name)
            self.papers.add(new_tpl)
            on_save()
            w.destroy()

        btns = ctk.CTkFrame(w, fg_color=P.bg_main, height=56,
                            corner_radius=0)
        btns.pack(fill="x", side="bottom")
        btns.pack_propagate(False)

        ctk.CTkButton(
            btns, text="💾  Сохранить", command=save,
            font=F.get("btn"),
            fg_color=P.green, hover_color=P.teal,
            text_color=P.bg_root,
            height=40, corner_radius=6).pack(
            side="right", padx=14, pady=10)
        ctk.CTkButton(
            btns, text="Отмена", command=w.destroy,
            font=F.get("btn"),
            fg_color=P.bg_overlay, hover_color=P.bg_hover,
            text_color=P.fg,
            height=40, corner_radius=6).pack(side="right", pady=10)

    def on_restart(self):
        if self.is_running:
            if not messagebox.askokcancel(
                    "Перезапуск",
                    "Операция выполняется. Прервать и перезапустить?"):
                return
        else:
            if not messagebox.askokcancel(
                    "Перезапуск",
                    "Перезапустить интерфейс?\n\n"
                    "Полезно после смены dpi_override.txt, theme.json "
                    "или обновления ArgyllCMS."):
                return

        if self.is_running:
            self.cancel_event.set()
            self._pause_event.set()
            proc = self._current_proc
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        self._closing = True

        try:
            if getattr(sys, "frozen", False):
                exe = sys.executable
                args = [exe] + sys.argv[1:]
            else:
                exe = sys.executable
                script = os.path.abspath(sys.argv[0]) if sys.argv and \
                    sys.argv[0] else os.path.abspath(__file__)
                args = [exe, script] + sys.argv[1:]

            env = os.environ.copy()
            env.pop("_PRINTER_MENU_RELAUNCHED", None)

            subprocess.Popen(
                args,
                close_fds=True,
                env=env,
                cwd=SCRIPT_DIR,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except Exception as e:
            self._closing = False
            messagebox.showerror("Ошибка", f"Не удалось перезапустить: {e}")
            return

        try:
            self.root.destroy()
        except Exception:
            pass

    def on_exit(self):
        self._closing = True
        if self.is_running:
            if not messagebox.askokcancel(
                    "Выход",
                    "Операция выполняется. Прервать и выйти?"):
                self._closing = False
                return
            self.cancel_event.set()
            self._pause_event.set()
            proc = self._current_proc
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            self.root.after(50, self._final_exit)
            return
        self._final_exit()

    def _final_exit(self):
        if messagebox.askokcancel(
                "Выход",
                "Выйти?\n\n🔧 Не забудьте восстановить родной драйвер\n"
                "   через Zadig (HID/Microsoft), если планируете\n"
                "   использовать калибратор в i1Studio."):
            try:
                self.root.destroy()
            except Exception:
                pass
        else:
            self._closing = False


# ═══════════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════════
def main():
    run_as_admin()
    root = ctk.CTk()

    dpi_scaling = _resolve_dpi_scaling(THEME.get("general", {}))
    if dpi_scaling > 0:
        try:
            root.tk.call("tk", "scaling", dpi_scaling)
        except Exception:
            pass

    app = PrinterMenu(root)
    root.mainloop()


if __name__ == "__main__":
    main()