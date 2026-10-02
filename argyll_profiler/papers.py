# -*- coding: utf-8 -*-
"""Шаблоны бумаг: предустановки для быстрого выбора."""
import json
import os
from dataclasses import dataclass, asdict
from typing import List, Optional

DEFAULT_LIBRARY_NAME = "papers_templates.json"


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class PaperTemplate:
    name: str
    vendor: str = ""
    finish: str = "Glossy"
    size: str = "A4"
    patches: int = 800
    media_type: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PaperTemplate":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# ---------- предустановки по умолчанию ----------
DEFAULT_TEMPLATES = [
    PaperTemplate("Canon_Pro_Platinum_A4", "Canon", "Glossy", "A4", 800,
                  "Photo Paper Pro Platinum",
                  "Родная бумага Canon PRO-10S"),
    PaperTemplate("Canon_Pro_Luster_A4", "Canon", "Luster", "A4", 800,
                  "Photo Paper Pro Luster", ""),
    PaperTemplate("Canon_Matte_A4", "Canon", "Matte", "A4", 600,
                  "Matte Photo Paper", "Меньше патчей для матовой"),
    PaperTemplate("Lomond_Glossy_A4", "Lomond", "Glossy", "A4", 800,
                  "Photo Paper Glossy", ""),
    PaperTemplate("Epson_Premium_Glossy_A4", "Epson", "Glossy", "A4", 800,
                  "Premium Glossy Photo Paper", ""),
    PaperTemplate("Hahnemuhle_PhotoRag_A4", "Hahnemühle", "Matte", "A4", 1200,
                  "Photo Rag", "Требует 1200 для точности"),
    PaperTemplate("A3_Universal_Glossy", "Universal", "Glossy", "A3", 1200,
                  "Photo Paper", "A3 — всегда 1200 патчей"),
]


class PapersLibrary:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(
            _project_root(), DEFAULT_LIBRARY_NAME)
        self.templates: List[PaperTemplate] = []
        self.load()

    # ---------- загрузка / сохранение ----------
    def load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.templates = [PaperTemplate.from_dict(d) for d in data]
                if self.templates:
                    return
            except Exception:
                pass
        # fallback — предустановки
        self.templates = list(DEFAULT_TEMPLATES)
        self.save()

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([t.to_dict() for t in self.templates],
                          f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # ---------- работа с шаблонами ----------
    def add(self, tpl: PaperTemplate) -> None:
        self.templates.append(tpl)
        self.save()

    def remove(self, name: str) -> bool:
        before = len(self.templates)
        self.templates = [t for t in self.templates if t.name != name]
        if len(self.templates) != before:
            self.save()
            return True
        return False

    def get(self, name: str) -> Optional[PaperTemplate]:
        for t in self.templates:
            if t.name == name:
                return t
        return None

    def names(self) -> List[str]:
        return [t.name for t in self.templates]