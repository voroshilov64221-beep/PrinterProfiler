# -*- coding: utf-8 -*-
"""Автопоиск принтеров через win32print (опционально).

Если pywin32 не установлен — функции возвращают пустые значения,
GUI продолжает работать с ручным вводом имени принтера.
"""
from typing import List

try:
    import win32print
    HAS_WIN32PRINT = True
except Exception:
    HAS_WIN32PRINT = False


def list_printers() -> List[str]:
    """Возвращает отсортированный список имён локальных и сетевых принтеров."""
    if not HAS_WIN32PRINT:
        return []
    try:
        printers = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
            None, 2,
        )
        return sorted({p["pPrinterName"] for p in printers})
    except Exception:
        return []


def get_default_printer() -> str:
    """Имя принтера по умолчанию (или пустая строка)."""
    if not HAS_WIN32PRINT:
        return ""
    try:
        return win32print.GetDefaultPrinter() or ""
    except Exception:
        return ""


def find_canon_pro10s() -> str:
    """Ищет в системе что-то похожее на Canon PRO-10S."""
    for name in list_printers():
        low = name.lower()
        if "pro-10" in low or "pro10" in low:
            return name
    return ""


def has_support() -> bool:
    """True, если win32print доступен."""
    return HAS_WIN32PRINT