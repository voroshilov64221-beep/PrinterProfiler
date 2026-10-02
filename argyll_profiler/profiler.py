# -*- coding: utf-8 -*-
"""Высокоуровневые сценарии профилирования с прогрессом."""
import os
import shutil
import time
from dataclasses import dataclass
import threading
from typing import Callable, Optional

from .argyll import Argyll, ArgyllError
from .config import Config, sanitize_name, clamp_patches
from .metadata import save_metadata, update_metadata
from .logger import ProfilerLogger


class ProfilerError(RuntimeError):
    pass


class ProfilerCancelled(ProfilerError):
    """Пользователь нажал Стоп — это не ошибка, а нормальный исход."""
    pass


@dataclass
class ProfileRequest:
    printer: str
    paper: str
    finish: str
    paper_size: str
    patches: int
    overwrite: bool = False
    resume: bool = False


ProgressCallback = Callable[[int, int, str], None]
PauseCallback = Callable[[str], None]


class Profiler:
    STEPS_FULL = 5

    def __init__(self, config: Config, logger: ProfilerLogger,
                 progress_cb: Optional[ProgressCallback] = None,
                 pause_cb: Optional[PauseCallback] = None,
                 cancel_event: Optional[threading.Event] = None,
                 proc_cb=None):
        self.cfg = config
        self.log = logger
        self.progress_cb = progress_cb
        self.pause_cb = pause_cb
        self.cancel_event = cancel_event or threading.Event()
        self.argyll = Argyll(config.argvll_path, logger,
                             cancel_event=self.cancel_event,
                             proc_cb=proc_cb)

    def _check_cancel(self):
        if self.cancel_event.is_set():
            raise ProfilerCancelled("Операция отменена пользователем")

    # ---------- прогресс / пауза ----------
    def _step(self, step, total, msg):
        self.log.info(f"[{step}/{total}] {msg}")
        if self.progress_cb:
            self.progress_cb(step, total, msg)

    def _pause(self, message):
        if self.pause_cb:
            self.pause_cb(message)
        else:
            input(f"   {message}\n   Нажмите Enter...")

    # ---------- папка профиля ----------
    def prepare_dir(self, profile_name, overwrite):
        profile_dir = os.path.join(self.cfg.base_dir, profile_name)
        if os.path.exists(profile_dir):
            if not overwrite:
                raise ProfilerError(f"Папка уже существует: {profile_dir}")
            shutil.rmtree(profile_dir)
        os.makedirs(profile_dir, exist_ok=True)
        return profile_dir

    # ---------- полный цикл ----------
    def run_full(self, req: ProfileRequest) -> str:
        paper = sanitize_name(req.paper, "UnknownPaper")
        finish = sanitize_name(req.finish, "Matte")
        printer = sanitize_name(req.printer, "Printer")
        profile_name = f"{printer}_{paper}_{finish}"
        patches = clamp_patches(req.patches)

        profile_dir = self.prepare_dir(profile_name, req.overwrite)

        save_metadata(profile_dir, {
            "printer": req.printer, "paper": req.paper,
            "finish": req.finish, "paper_size": req.paper_size,
            "patches": patches, "argyll_version": self.argyll.version(),
            "profile_name": profile_name, "status": "started",
        })

        total = self.STEPS_FULL

        self._step(1, total, "Генерация мишени (targen)...")
        self.argyll.targen(profile_name, patches, cwd=profile_dir)

        self._step(2, total, "Создание TIFF (printtarg)...")
        self.argyll.printtarg(profile_name, req.paper_size, cwd=profile_dir)

        tiff = os.path.join(profile_dir, f"{profile_name}.tif")
        self._step(3, total, f"Печать мишени: {tiff}")
        self._pause(f"Напечатайте {os.path.basename(tiff)} и нажмите Продолжить")

        self._step(4, total, "Калибровка и измерение (chartread)...")
        try:
            self._calibrate_and_measure(profile_name, profile_dir,
                                        resume=req.resume)
        except ProfilerCancelled:
            try:
                from .metadata import mark_cancelled
                mark_cancelled(profile_dir)
            except Exception:
                pass
            raise

        self._step(5, total, "Построение ICC-профиля (colprof)...")
        self.argyll.colprof(profile_name, cwd=profile_dir)

        icc = self._find_icc(profile_dir, profile_name)
        update_metadata(profile_dir, {"icc_path": icc, "status": "ready"})
        self.log.success(f"🎉 Профиль готов: {icc}")
        return icc

    # ---------- только измерение ----------
    def run_measurement(self, profile_dir: str, resume: bool = False) -> str:
        profile_name = os.path.basename(profile_dir.rstrip("/\\"))
        ti1 = self._find_first(profile_dir, ".ti1")
        if not ti1 and not resume:
            raise ProfilerError(f"В {profile_dir} нет .ti1 мишени")

        total = 2
        self._step(1, total, "Калибровка и измерение (chartread)...")
        try:
            self._calibrate_and_measure(profile_name, profile_dir,
                                        resume=resume)
        except ProfilerCancelled:
            try:
                from .metadata import mark_cancelled
                mark_cancelled(profile_dir)
            except Exception:
                pass
            raise

        self._step(2, total, "Построение ICC-профиля (colprof)...")
        self.argyll.colprof(profile_name, cwd=profile_dir)

        icc = self._find_icc(profile_dir, profile_name)
        update_metadata(profile_dir, {"icc_path": icc, "status": "ready"})
        return icc

    # ---------- измерение ----------
    def _calibrate_and_measure(self, profile_name, profile_dir,
                               resume: bool = False):
        if not resume:
            self._check_cancel()
            self._pause(
                "Установите прибор в положение калибровки и нажмите Продолжить"
            )
            self._check_cancel()
            sp = self.argyll.launch_spotread(cwd=profile_dir)
            self.log.info("   Открыто окно spotread для калибровки.")
            self._pause(
                "После калибровки закройте spotread и нажмите Продолжить"
            )
            self._check_cancel()
            deadline = time.time() + self.cfg.timeout_seconds
            while sp.poll() is None:
                if self.cancel_event.is_set():
                    try:
                        sp.terminate()
                        sp.wait(timeout=5)
                    except Exception:
                        try: sp.kill()
                        except Exception: pass
                    raise ProfilerCancelled("Отменено на этапе калибровки")
                if time.time() > deadline:
                    try: sp.terminate()
                    except Exception: pass
                    raise ProfilerError("Таймаут spotread: закройте окно калибровки")
                time.sleep(0.5)
        else:
            self.log.info("⏩ Продолжение прерванного измерения (chartread -r)")

        self._check_cancel()
        proc = self.argyll.launch_chartread(
            profile_name, cwd=profile_dir, resume=resume,
        )
        self.log.info(
            "   Открыто окно chartread. Измерьте строки, затем введите 'd'."
        )
        ti3 = os.path.join(profile_dir, f"{profile_name}.ti3")
        deadline = time.time() + self.cfg.timeout_seconds
        while time.time() < deadline:
            if self.cancel_event.is_set():
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try: proc.kill()
                    except Exception: pass
                raise ProfilerCancelled("Отменено на этапе измерения")
            if proc.poll() is not None:
                break
            if os.path.exists(ti3):
                time.sleep(2)
                break
            time.sleep(1)
        else:
            raise ProfilerError("Таймаут измерения")

        if not os.path.exists(ti3):
            if self.cancel_event.is_set():
                raise ProfilerCancelled("Измерение прервано пользователем")
            raise ProfilerError(
                f"Файл измерений не создан: {ti3}\n"
                f"Проверьте, что chartread завершился успешно "
                f"и прибор откалиброван через spotread."
            )

    # ---------- проверка точности ----------
    def check_accuracy(self, profile_dir: str) -> dict:
        profile_name = os.path.basename(profile_dir.rstrip("/\\"))
        return self.argyll.profcheck(profile_name, cwd=profile_dir)

    # ---------- сравнение двух профилей ----------
    def compare(self, icc1: str, icc2: str) -> dict:
        return self.argyll.compare_profiles(icc1, icc2)

    # ---------- утилиты ----------
    @staticmethod
    def _find_icc(profile_dir, profile_name):
        for ext in (".icc", ".icm"):
            p = os.path.join(profile_dir, f"{profile_name}{ext}")
            if os.path.exists(p):
                return p
        for f in os.listdir(profile_dir):
            if f.lower().endswith((".icc", ".icm")):
                return os.path.join(profile_dir, f)
        raise ProfilerError("ICC-профиль не найден после colprof")

    @staticmethod
    def _find_first(profile_dir, ext):
        for f in os.listdir(profile_dir):
            if f.lower().endswith(ext):
                return os.path.join(profile_dir, f)
        return None