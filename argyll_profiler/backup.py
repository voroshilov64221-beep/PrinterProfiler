# -*- coding: utf-8 -*-
"""ZIP-бэкапы профилей."""
import datetime
import os
import zipfile
from typing import List, Tuple


def create_backup(profile_dir: str, backup_dir: str,
                  tag: str = "") -> str:
    """Создаёт ZIP-архив папки профиля.

    Возвращает путь к архиву.
    """
    if not os.path.isdir(profile_dir):
        raise FileNotFoundError(f"Папка не найдена: {profile_dir}")
    os.makedirs(backup_dir, exist_ok=True)

    name = os.path.basename(profile_dir.rstrip("/\\"))
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""
    zip_path = os.path.join(backup_dir, f"{name}{suffix}_{ts}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(profile_dir):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, profile_dir)
                zf.write(full, arcname=os.path.join(name, rel))
    return zip_path


def list_backups(backup_dir: str) -> List[Tuple[str, str, int]]:
    """Список архивов: (путь, дата создания, размер в байтах)."""
    if not os.path.isdir(backup_dir):
        return []
    result: List[Tuple[str, str, int]] = []
    for fn in os.listdir(backup_dir):
        if fn.lower().endswith(".zip"):
            full = os.path.join(backup_dir, fn)
            try:
                mtime = datetime.datetime.fromtimestamp(
                    os.path.getmtime(full)
                ).strftime("%Y-%m-%d %H:%M:%S")
                result.append((full, mtime, os.path.getsize(full)))
            except Exception:
                pass
    result.sort(key=lambda x: x[1], reverse=True)
    return result


def restore_backup(zip_path: str, target_dir: str) -> str:
    """Распаковывает архив в target_dir. Возвращает target_dir."""
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_dir)
    return target_dir