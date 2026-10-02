# -*- coding: utf-8 -*-
"""Логгер с callback для GUI и записью в файл."""
import datetime
import logging
import os
from typing import Callable, Optional

LogCallback = Callable[[str, str], None]


class ProfilerLogger:
    def __init__(self, base_dir: str, level: str = "INFO",
                 log_file: Optional[str] = None,
                 gui_callback: Optional[LogCallback] = None,
                 console: bool = True):
        self.gui_callback = gui_callback
        self.console = console

        log_dir = os.path.join(base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        if log_file is None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = os.path.join(log_dir, f"profile_{ts}.log")
        self.log_file = log_file

        self._logger = logging.getLogger(f"ICCProfiler.{id(self)}")
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        self._logger.handlers.clear()
        self._logger.propagate = False

        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"))
        fh.setLevel(logging.DEBUG)
        self._logger.addHandler(fh)

        if console:
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter("%(message)s"))
            ch.setLevel(logging.INFO)
            self._logger.addHandler(ch)

    def info(self, msg, gui=True):
        self._logger.info(msg)
        if gui and self.gui_callback:
            self.gui_callback("INFO", msg)

    def warning(self, msg, gui=True):
        self._logger.warning(msg)
        if gui and self.gui_callback:
            self.gui_callback("WARNING", msg)

    def error(self, msg, gui=True):
        self._logger.error(msg)
        if gui and self.gui_callback:
            self.gui_callback("ERROR", msg)

    def step(self, msg, gui=True):
        self._logger.info(msg)
        if gui and self.gui_callback:
            try:
                self.gui_callback("STEP", msg)
            except Exception:
                pass

    def success(self, msg, gui=True):
        self._logger.info(msg)
        if gui and self.gui_callback:
            self.gui_callback("SUCCESS", msg)

    def debug(self, msg):
        self._logger.debug(msg)

    def exception(self, msg="Ошибка"):
        self._logger.exception(msg)

    def set_gui_callback(self, cb):
        self.gui_callback = cb