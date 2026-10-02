# -*- coding: utf-8 -*-
"""Конфигурация и валидация."""
import json
import os
import shutil
from dataclasses import dataclass, asdict
from typing import List, Optional

CONFIG_FILENAME = "printer_profiler_config.json"
INVALID_CHARS = r'<>:"/\|?*'


def project_root() -> str:
    """Корень проекта (там, где лежит пакет argyll_profiler)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sanitize_name(name: str, fallback: str = "Unknown") -> str:
    if not name:
        return fallback
    for ch in INVALID_CHARS:
        name = name.replace(ch, "_")
    name = name.strip().strip(".").replace(" ", "_")
    while "__" in name:
        name = name.replace("__", "_")
    return name or fallback


def clamp_patches(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 800
    return max(50, min(10000, n))


@dataclass
class Config:
    argvll_path: str = ""
    base_dir: str = ""
    printer_name: str = "Canon_PixmaPro10S"
    default_patches: int = 800
    quality_patches: int = 1200
    timeout_seconds: int = 900
    dry_run: bool = False
    log_level: str = "INFO"
    papers_library: str = ""
    backup_dir: str = ""
    auto_backup: bool = False

    @classmethod
    def from_file(cls, config_path: str) -> "Config":
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                known = {k: v for k, v in data.items()
                         if k in cls.__dataclass_fields__}
                return cls(**known)
            except Exception:
                pass
        return cls()

    def save(self, config_path: str) -> None:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=4, ensure_ascii=False)

    def validate(self) -> List[str]:
        problems = []
        if not self.argvll_path or not os.path.isdir(self.argvll_path):
            problems.append("Путь к ArgyllCMS не задан или не существует")
        elif not os.path.exists(os.path.join(self.argvll_path, "targen.exe")):
            problems.append("В папке ArgyllCMS не найден targen.exe")

        if not self.base_dir:
            problems.append("Базовая папка профилей не задана")
        else:
            try:
                os.makedirs(self.base_dir, exist_ok=True)
            except Exception as e:
                problems.append(f"Не удалось создать базовую папку: {e}")

        if not self.backup_dir:
            self.backup_dir = os.path.join(project_root(), "backups")
        try:
            os.makedirs(self.backup_dir, exist_ok=True)
        except Exception as e:
            problems.append(f"Не удалось создать папку бэкапов: {e}")

        if not self.papers_library:
            self.papers_library = os.path.join(project_root(),
                                               "papers_templates.json")

        self.default_patches = clamp_patches(self.default_patches)
        self.quality_patches = clamp_patches(self.quality_patches)
        self.timeout_seconds = max(60, int(self.timeout_seconds))
        return problems


def find_argyll_path() -> Optional[str]:
    exe = shutil.which("targen.exe") or shutil.which("targen")
    if exe:
        return os.path.dirname(exe)
    candidates = [
        r"C:\Program Files\ArgyllCMS\bin",
        r"C:\ArgyllCMS\bin",
        r"D:\ArgyllCMS\bin",
        r"E:\ArgyllCMS\bin",
        os.path.join(os.path.expanduser("~"), "ArgyllCMS", "bin"),
    ]
    for p in candidates:
        if os.path.exists(os.path.join(p, "targen.exe")):
            return p
    return None


def default_config_path() -> str:
    return os.path.join(project_root(), CONFIG_FILENAME)


def load_config(config_path: Optional[str] = None,
                interactive: bool = True) -> Config:
    path = config_path or default_config_path()
    cfg = Config.from_file(path)

    if not cfg.argvll_path:
        found = find_argyll_path()
        if found:
            cfg.argvll_path = found
        elif interactive:
            print("\n⚠️ ArgyllCMS не найден автоматически.")
            while True:
                p = input("Введите путь к папке bin ArgyllCMS: ").strip().strip('"')
                if p and os.path.exists(os.path.join(p, "targen.exe")):
                    cfg.argvll_path = p
                    break
                print("❌ Не найдено targen.exe в этой папке.")
        else:
            raise RuntimeError("ArgyllCMS не найден")

    if not cfg.base_dir:
        default_base = os.path.join(project_root(), "profiles")
        if interactive:
            user = input(f"\n📁 Папка для профилей [{default_base}]: ").strip().strip('"')
            cfg.base_dir = user or default_base
        else:
            cfg.base_dir = default_base

    os.makedirs(cfg.base_dir, exist_ok=True)

    problems = cfg.validate()
    if problems:
        raise RuntimeError("Конфиг невалиден: " + "; ".join(problems))

    try:
        cfg.save(path)
    except Exception:
        pass
    return cfg