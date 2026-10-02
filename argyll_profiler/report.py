# -*- coding: utf-8 -*-
"""Генерация HTML-отчётов по результатам проверки профиля (profcheck)."""
import datetime
import html
import os
from typing import Dict, Optional

from .metadata import load_metadata

REPORT_CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; background:#f5f5f7;
       color:#1c1c1e; margin:0; padding:30px; }
.container { max-width: 900px; margin: 0 auto; background:#fff;
             border-radius:12px; box-shadow:0 4px 20px rgba(0,0,0,.08);
             padding:30px 40px; }
h1 { font-size:22px; margin:0 0 6px; }
h2 { font-size:16px; color:#555; margin:24px 0 10px;
     border-bottom:1px solid #eee; padding-bottom:6px; }
table { border-collapse:collapse; width:100%; margin:10px 0; }
th, td { text-align:left; padding:8px 12px; border-bottom:1px solid #eee; }
th { background:#f0f0f5; font-weight:600; }
.metric { font-size:26px; font-weight:700; }
.badge { display:inline-block; padding:4px 12px; border-radius:20px;
         font-size:13px; font-weight:600; }
.badge.good { background:#d1f0d1; color:#0a5c0a; }
.badge.warn { background:#fff3cd; color:#8a6d00; }
.badge.bad  { background:#f8d7da; color:#8a1c1c; }
.badge.unknown { background:#e5e5ea; color:#555; }
.footer { color:#888; font-size:12px; margin-top:30px; text-align:center; }
pre { background:#f0f0f5; padding:12px; border-radius:6px; overflow:auto;
      font-size:12px; }
"""


def _badge(avg: Optional[float], status: Optional[str] = None) -> str:
    """Цветной бейдж оценки по среднему DeltaE."""
    if status == "cancelled":
        return '<span class="badge warn">⏹ Прервано</span>'
    if avg is None:
        return '<span class="badge unknown">Неизвестно</span>'
    if avg < 1.0:
        return '<span class="badge good">🌟 Отлично</span>'
    if avg < 2.0:
        return '<span class="badge good">✅ Хорошо</span>'
    if avg < 3.0:
        return '<span class="badge warn">⚠ Приемлемо</span>'
    return '<span class="badge bad">❌ Требует улучшения</span>'


def build_report(profile_dir: str, stats: Dict,
                 output_path: Optional[str] = None,
                 open_after: bool = False) -> str:
    """Создаёт HTML-отчёт по результатам profcheck.

    stats — словарь из parse_profcheck с полями:
        peak, avg, rms, quality, raw

    Возвращает путь к созданному HTML.
    """
    profile_name = os.path.basename(profile_dir.rstrip("/\\"))
    meta = load_metadata(profile_dir)

    if output_path is None:
        output_path = os.path.join(profile_dir, "report.html")

    e = html.escape
    peak = stats.get("peak")
    avg = stats.get("avg")
    rms = stats.get("rms")
    quality = stats.get("quality", "")

    # Таблица метаданных
    rows = []
    for k, v in meta.items():
        rows.append(f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>")
    meta_html = "".join(rows) or (
        "<tr><td colspan='2'>Метаданные отсутствуют</td></tr>"
    )

    raw = e(stats.get("raw", ""))[:5000]
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_doc = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Отчёт профиля {e(profile_name)}</title>
<style>{REPORT_CSS}</style></head>
<body><div class="container">
<h1>📊 Отчёт о точности профиля</h1>
<p style="color:#666">Профиль: <b>{e(profile_name)}</b> • Сгенерирован: {ts}</p>

<h2>Итоговые метрики</h2>
<div style="display:flex; gap:40px; margin-top:10px">
  <div><div class="metric">{peak if peak is not None else '—'}</div>
       <div style="color:#666; font-size:12px">Peak ΔE</div></div>
  <div><div class="metric">{avg if avg is not None else '—'}</div>
       <div style="color:#666; font-size:12px">Avg ΔE</div></div>
  <div><div class="metric">{rms if rms is not None else '—'}</div>
       <div style="color:#666; font-size:12px">RMS</div></div>
  <div><div class="metric" style="font-size:18px">{_badge(avg, meta.get("status"))}</div>
       <div style="color:#666; font-size:12px">Оценка</div></div>
</div>

<h2>Метаданные профиля</h2>
<table>{meta_html}</table>

<h2>Оценка</h2>
<p style="font-size:15px">{e(quality)}</p>

<h2>Сырой вывод profcheck</h2>
<pre>{raw}</pre>

<div class="footer">Argyll Printer Profiler • {ts}</div>
</div></body></html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    if open_after:
        try:
            os.startfile(output_path)
        except Exception:
            pass
    return output_path