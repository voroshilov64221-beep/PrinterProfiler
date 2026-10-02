# -*- coding: utf-8 -*-
"""Обёртки над инструментами ArgyllCMS.

Важно: все вызовы идут с cwd=profile_dir. Файлы .ti1/.ti2/.ti3/.icc
создаются ArgyllCMS в текущей директории процесса. Мы её задаём явно,
чтобы избежать проблем с кириллицей в пути.
"""
import os
import re
import subprocess
import threading
import time
from typing import Callable, List, Optional, Tuple


class ArgyllError(RuntimeError):
    pass


class ArgyllCancelled(ArgyllError):
    """Пользователь нажал Стоп во время работы Argyll-инструмента."""
    pass


ProcCallback = Callable[[subprocess.Popen], None]


# Флаг Windows для открытия нового окна консоли
CREATE_NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0

# Флаг Windows для скрытия окна консоли
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _subprocess_env() -> dict:
    """Окружение с UTF-8, чтобы ArgyllCMS не спотыкался о кириллицу."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if os.name == "nt":
        env["LANG"] = "en_US.UTF-8"
        env["LC_ALL"] = "en_US.UTF-8"
    return env


class Argyll:
    def __init__(self, bin_dir: str, logger,
                 cancel_event: Optional[threading.Event] = None,
                 proc_cb: Optional[ProcCallback] = None):
        self.bin_dir = bin_dir
        self.log = logger
        self.cancel_event = cancel_event or threading.Event()
        self.proc_cb = proc_cb

    def _register(self, proc: subprocess.Popen) -> None:
        if self.proc_cb is not None:
            try:
                self.proc_cb(proc)
            except Exception:
                pass

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise ArgyllCancelled("Отменено пользователем")

    def _terminate(self, proc: subprocess.Popen) -> None:
        """Hybrid: terminate → 5 сек → kill."""
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
                return
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ---------- пути ----------
    def tool(self, name: str) -> str:
        if os.name == "nt" and not name.lower().endswith(".exe"):
            exe_name = f"{name}.exe"
        else:
            exe_name = name
        path = os.path.join(self.bin_dir, exe_name)
        if not os.path.exists(path):
            alt = os.path.join(self.bin_dir, name)
            if os.path.exists(alt):
                return alt
            raise ArgyllError(f"Инструмент не найден: {path}")
        return path

    def version(self) -> str:
        try:
            r = subprocess.run(
                [self.tool("colprof"), "-?"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
                env=_subprocess_env(),
            )
            m = re.search(r"[Vv]ersion\s+([\d.]+)", r.stdout + r.stderr)
            return m.group(1) if m else "unknown"
        except Exception:
            return "unknown"

    # ---------- запуск ----------
    def _run(self, args: List[str], cwd: Optional[str] = None,
             timeout: int = 600, console: bool = False) -> Tuple[int, str]:
        self.log.debug(f"RUN: {' '.join(args)} (cwd={cwd})")
        self._check_cancel()
        flags = CREATE_NEW_CONSOLE if console else CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                args, cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env=_subprocess_env(),
                creationflags=flags,
            )
        except FileNotFoundError as e:
            raise ArgyllError(f"Не найден инструмент: {args[0]}") from e
        except Exception as e:
            raise ArgyllError(f"Не удалось запустить {args[0]}: {e}") from e
        self._register(proc)
        deadline = time.time() + timeout
        while proc.poll() is None:
            if self.cancel_event.is_set():
                self._terminate(proc)
                raise ArgyllCancelled(f"Отменено во время {os.path.basename(args[0])}")
            if time.time() > deadline:
                self._terminate(proc)
                raise ArgyllError(f"Таймаут {timeout} сек: {args[0]}")
            time.sleep(0.2)
        try:
            out, _ = proc.communicate(timeout=5)
        except Exception:
            out = ""
        return proc.returncode, (out or "")

    # ---------- проверка прибора ----------
    def check_instrument(self) -> bool:
        """Проверка реального подключения прибора.

        Использует `spotread -v` в фоне и анализирует вывод за 6 секунд.

        Почему НЕ используем:
          - `-L` — в ArgyllCMS 3.x не существует (старый флаг).
          - `-O` — с открытым прибором требует калибровки или нажатия
            кнопки, может зависнуть.
          - `-e -x` — `-x` в spotread означает «показать Yxy вместо Lab»,
            а не «выйти» — прибор уходит в интерактивную калибровку
            и висит.

        Поэтому: запускаем `spotread -v`, даём 6 секунд на попытку
        открыть прибор, затем принудительно завершаем и смотрим вывод.
        """
        args = [self.tool("spotread"), "-v"]
        self.log.debug(f"PROBE: {' '.join(args)} (6s timeout)")

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_subprocess_env(),
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:
            self.log.error(f"❌ Не удалось запустить spotread: {e}")
            return False

        # Даём прибору 6 секунд на открытие
        probe_seconds = 6
        try:
            out, _ = proc.communicate(timeout=probe_seconds)
        except subprocess.TimeoutExpired:
            # Процесс ещё жив — значит, прибор ОТКРЫТ и ждёт действий
            proc.kill()
            try:
                out, _ = proc.communicate(timeout=3)
            except Exception:
                out = ""

        out = out or ""
        low = out.lower()
        rc = proc.returncode

        # 1) Явные признаки отсутствия прибора
        negatives = (
            "unable to find",
            "no instrument",
            "unable to open",
            "failed to open",
            "no device",
            "instrument not found",
            "couldn't find",
            "could not open",
            "no port",
            "no usb device",
            "no matching usb",
            "instrument does not match",
            "instrument doesn't match",
        )
        for neg in negatives:
            if neg in low:
                self.log.error("❌ ColorMunki не обнаружен.")
                self.log.error("")
                self.log.error("   🔧 БЫСТРОЕ РЕШЕНИЕ (в 90% случаев):")
                self.log.error("      Установите драйвер libusb-win32 через Zadig:")
                self.log.error("      1. Скачайте Zadig: https://zadig.akeo.ie/")
                self.log.error("      2. Запустите Zadig ОТ ИМЕНИ АДМИНИСТРАТОРА")
                self.log.error("      3. Меню Options → List All Devices")
                self.log.error("      4. В списке выберите 'colormunki' (Interface 0)")
                self.log.error("      5. В правом поле выберите 'libusb-win32 (v1.4.0.0)'")
                self.log.error("      6. Нажмите 'Install Driver' или 'Replace Driver'")
                self.log.error("      7. Дождитесь окончания установки (10-30 сек)")
                self.log.error("      8. Перезапустите проверку прибора")
                self.log.error("")
                self.log.error("   📋 ДРУГИЕ ПРИЧИНЫ:")
                self.log.error("     • Прибор не подключён к USB-порту")
                self.log.error("     • Прибор занят другим ПО (закройте i1Studio, Calibrite)")
                self.log.error("     • Недостаточно прав (запустите от администратора)")
                self.log.error("")
                self.log.error("   🔄 ВОЗВРАТ РОДНОГО ДРАЙВЕРА (для i1Studio):")
                self.log.error("     В Zadig выберите 'HID (Microsoft)' и нажмите Replace Driver")
                self.log.error("")
                self.log.error("   ─── Технический вывод spotread ───")
                for line in out.strip().splitlines()[:12]:
                    self.log.error(f"     {line}")
                return False

        # 2) Прибор ОТКРЫТ и ждёт калибровки — тоже успех
        waiting_markers = (
            "place instrument",
            "white calibration",
            "calibration reference",
            "waiting for",
            "make a measurement",
        )
        for w in waiting_markers:
            if w in low:
                self.log.success("✅ Прибор обнаружен и готов к работе")
                self.log.info("   (прибор открыт и ждёт калибровки)")
                return True

        # 3) Положительные маркеры типа прибора
        positives = (
            "instrument type",
            "instrument:",
            "colormunki",
            "i1display",
            "i1pro",
            "i1studio",
            "found instrument",
            "opened instrument",
        )
        for p in positives:
            if p in low:
                self.log.success("✅ Прибор обнаружен и готов к работе")
                m = re.search(r"instrument type[:\s]+([^\n\r]+)",
                              out, re.IGNORECASE)
                if m:
                    self.log.info(f"   Тип прибора: {m.group(1).strip()}")
                return True

        # 4) Не смогли однозначно определить
        self.log.error("❌ Не удалось подтвердить подключение прибора.")
        self.log.error("")
        self.log.error("   🔧 РЕШЕНИЕ: переустановите драйвер через Zadig:")
        self.log.error("      1. Zadig: https://zadig.akeo.ie/ (запустить от админа)")
        self.log.error("      2. Options → List All Devices")
        self.log.error("      3. Выберите 'colormunki' (Interface 0)")
        self.log.error("      4. Установите 'libusb-win32 (v1.4.0.0)'")
        self.log.error("      5. Перезапустите проверку")
        self.log.error("")
        self.log.error(f"   Код возврата spotread: {rc}")
        self.log.error("   ─── вывод spotread ───")
        if out.strip():
            for line in out.strip().splitlines()[:12]:
                self.log.error(f"     {line}")
        else:
            self.log.error("     (пусто — процесс был принудительно завершён)")
        return False

    # ---------- targen ----------
    def targen(self, profile_name: str, patches: int, cwd: str) -> None:
        args = [
            self.tool("targen"), "-v", "-d", "2", "-e", "4",
            "-B", "4", "-s", "50", "-f", str(patches), profile_name,
        ]
        rc, out = self._run(args, cwd=cwd, timeout=180)
        if rc != 0:
            raise ArgyllError(f"targen failed: {out}")
        self.log.info("✅ Мишень сгенерирована")

    # ---------- printtarg ----------
    def printtarg(self, profile_name: str, paper_size: str, cwd: str) -> None:
        args = [
            self.tool("printtarg"), "-v", "-i", "CM",
            "-p", paper_size.lower(), "-t", "300",
            "-w", "g", "-k", "g", "-o", "k", profile_name,
        ]
        rc, out = self._run(args, cwd=cwd, timeout=180)
        if rc != 0:
            raise ArgyllError(f"printtarg failed: {out}")
        self.log.info("✅ TIFF-файл создан")

    # ---------- spotread (калибровка) ----------
    def launch_spotread(self, cwd: Optional[str] = None) -> subprocess.Popen:
        self._check_cancel()
        proc = subprocess.Popen(
            [self.tool("spotread"), "-v"],
            cwd=cwd,
            creationflags=CREATE_NEW_CONSOLE,
            env=_subprocess_env(),
        )
        self._register(proc)
        return proc

    # ---------- chartread ----------
    def launch_chartread(self, profile_name: str, cwd: str,
                         resume: bool = False) -> subprocess.Popen:
        args = [self.tool("chartread"), "-v", "-H", "-N"]
        if resume:
            args.append("-r")
        args.append(profile_name)
        self._check_cancel()
        proc = subprocess.Popen(
            args, cwd=cwd,
            creationflags=CREATE_NEW_CONSOLE,
            env=_subprocess_env(),
        )
        self._register(proc)
        return proc

    def can_resume(self, profile_dir: str, profile_name: str) -> bool:
        """True, если есть .ti3, но нет .icc/.icm — измерение не завершено."""
        ti3 = os.path.join(profile_dir, f"{profile_name}.ti3")
        icc = os.path.join(profile_dir, f"{profile_name}.icc")
        icm = os.path.join(profile_dir, f"{profile_name}.icm")
        return os.path.exists(ti3) and not (
            os.path.exists(icc) or os.path.exists(icm)
        )

    # ---------- colprof ----------
    def colprof(self, profile_name: str, cwd: str) -> str:
        args = [
            self.tool("colprof"), "-v", "-cmt", "-dpp",
            "-D", profile_name, profile_name,
        ]
        rc, out = self._run(args, cwd=cwd, timeout=600)
        if rc != 0:
            raise ArgyllError(f"colprof failed: {out}")
        self.log.success("✅ Профиль построен")
        return out

    # ---------- profcheck ----------
    def profcheck(self, profile_name: str, cwd: str) -> dict:
        ti3 = os.path.join(cwd, f"{profile_name}.ti3")
        icc = os.path.join(cwd, f"{profile_name}.icc")
        if not os.path.exists(ti3):
            raise ArgyllError(f"Не найден {ti3}")
        if not os.path.exists(icc):
            icc2 = os.path.join(cwd, f"{profile_name}.icm")
            if os.path.exists(icc2):
                icc = icc2
            else:
                raise ArgyllError(f"Не найден ICC-профиль {profile_name}.icc/.icm")

        args = [
            self.tool("profcheck"), "-v", "-k", "-w",
            f"{profile_name}.ti3", os.path.basename(icc),
        ]
        rc, out = self._run(args, cwd=cwd, timeout=180)
        return parse_profcheck(out, rc == 0)

    # ---------- сравнение двух ICC ----------
    def compare_profiles(self, icc1: str, icc2: str) -> dict:
        """Сравнение двух ICC через profcheck -C."""
        if not os.path.exists(icc1):
            raise ArgyllError(f"Не найден {icc1}")
        if not os.path.exists(icc2):
            raise ArgyllError(f"Не найден {icc2}")

        cwd = os.path.dirname(icc1) or "."
        args = [
            self.tool("profcheck"), "-v", "-C",
            os.path.basename(icc1), os.path.basename(icc2),
        ]
        rc, out = self._run(args, cwd=cwd, timeout=180)
        result = parse_profcheck(out, rc == 0)
        result["icc1"] = icc1
        result["icc2"] = icc2
        return result


def parse_profcheck(output: str, ok: bool) -> dict:
    """Разбор вывода profcheck."""
    result = {
        "ok": ok, "peak": None, "avg": None, "rms": None,
        "quality": "Неизвестно", "raw": output,
    }
    m = re.search(
        r"peak err\s*[=:]\s*([\d.]+).*?avg err\s*[=:]\s*([\d.]+)"
        r".*?rms\s*[=:]\s*([\d.]+)",
        output, re.IGNORECASE | re.DOTALL,
    )
    if m:
        result["peak"] = float(m.group(1))
        result["avg"] = float(m.group(2))
        result["rms"] = float(m.group(3))
    else:
        for key, pat in (
            ("peak", r"peak err\s*[=:]\s*([\d.]+)"),
            ("avg",  r"avg err\s*[=:]\s*([\d.]+)"),
            ("rms",  r"rms\s*[=:]\s*([\d.]+)"),
        ):
            mm = re.search(pat, output, re.IGNORECASE)
            if mm:
                result[key] = float(mm.group(1))

    if result["avg"] is not None:
        a = result["avg"]
        if a < 1.0:
            result["quality"] = "🌟 Отлично! Профессиональный уровень"
        elif a < 2.0:
            result["quality"] = "✅ Хорошо! Качественный профиль"
        elif a < 3.0:
            result["quality"] = "⚠️ Приемлемо, но можно улучшить"
        else:
            result["quality"] = "❌ Требуется улучшение. Попробуйте 1200 патчей"
    return result