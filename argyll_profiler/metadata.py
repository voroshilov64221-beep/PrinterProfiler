# -*- coding: utf-8 -*-
"""Метаданные профиля — надёжнее, чем парсинг имён."""
import datetime
import json
import os

META_FILE = "metadata.json"


def save_metadata(profile_dir: str, data: dict) -> None:
    data = dict(data)
    data.setdefault("created", datetime.datetime.now().isoformat())
    with open(os.path.join(profile_dir, META_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_metadata(profile_dir: str) -> dict:
    path = os.path.join(profile_dir, META_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def update_metadata(profile_dir: str, **kwargs) -> None:
    data = load_metadata(profile_dir)
    data.update(kwargs)
    save_metadata(profile_dir, data)


def mark_cancelled(profile_dir: str) -> None:
    """Помечает профиль как прерванный пользователем."""
    try:
        update_metadata(profile_dir, {"status": "cancelled"})
    except Exception:
        pass