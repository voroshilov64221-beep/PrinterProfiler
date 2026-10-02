# Argyll Printer Profiler — Premium

GUI для профилирования принтеров через ArgyllCMS с тёмным интерфейсом,
поддержкой лицензирования и полным циклом построения ICC-профиля.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4)
![License](https://img.shields.io/badge/License-AGPL--3.0-orange)

---

## Возможности

### Профилирование
- **Полный цикл** — targen → printtarg → chartread → colprof → ICC
- **Только измерение** — для уже напечатанной мишени
- **Продолжить измерение** — resume после прерывания
- **Улучшить (качество)** — перепрофилирование с бо́льшим числом патчей
- **Проверить точность + HTML** — DeltaE-отчёт с визуализацией
- **Сравнить два профиля** — profcheck -C
- Автовыбор количества патчей по шаблону бумаги
- Ручное управление патчами (50–10000)
- Автопоиск ArgyllCMS при первом запуске
- Страховочные бэкапы перед операциями

### Интерфейс
- Тёмная и светлая темы (`theme.json` / `theme_light.json`)
- Кастомизируемая палитра и шрифты
- DPI-масштабирование для 4K-мониторов
- Автоподбор размера окна по разрешению экрана
- Дневные логи `logs/YYYY-MM-DD.log`

### Лицензирование
- Пробный период: **5 запусков** без регистрации
- Активация через сервис (Яндекс.Облако + Supabase)
- Подпись Ed25519 — защита от подделки ключей
- Привязка к HWID (SHA-256 от MachineGuid + VolumeSerial)
- Офлайн-кэш лицензии на 24 часа

### Сервис
- Проверка прибора (ColorMunki Design)
- Справка по установке драйвера через Zadig
- Перезапуск GUI без выхода

---

## Скриншоты

_Добавьте скриншоты в папку `docs/screenshots/` и вставьте сюда._

---

## Установка

### Требования
- **Windows 10/11** (x64)
- **Python 3.10+**
- **ArgyllCMS** — [скачать](https://www.argyllcms.com/)
- **Драйвер libusb-win32** через [Zadig](https://zadig.akeo.ie/) — для калибратора
- **Калибратор** — ColorMunki Design / Photo / i1Studio или любой другой, поддерживаемый ArgyllCMS

### Установка

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/voroshilov64221-beep/PrinterProfiler.git
   cd PrinterProfiler
   ```

2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

3. Установите ArgyllCMS в любую папку (например, `C:\ArgyllCMS\`).

4. Установите драйвер калибратора:
   - Скачайте Zadig.
   - Меню **Options** → **List All Devices**.
   - Выберите `colormunki` (Interface 0).
   - Выберите драйвер **libusb-win32 (v1.4.0.0)**.
   - Нажмите **Install Driver** / **Replace Driver**.

5. Запустите:
   ```bash
   python printer_menu.py
   ```

6. В окне **⚙ Настройки** укажите путь к папке `bin` ArgyllCMS.

---

## Использование

### Полный цикл профилирования

1. Выберите **шаблон бумаги** или настройте параметры вручную.
2. Укажите **принтер**, **поверхность**, **размер**, **количество патчей**.
3. Нажмите **🔄 Полный цикл** — программа:
   - сгенерирует мишень (`targen`),
   - подготовит TIFF для печати (`printtarg`),
   - предложит напечатать,
   - запустит измерение (`chartread`),
   - построит ICC-профиль (`colprof`).
4. Готовый профиль появится в `profiles/<имя>/`.

### Проверка точности

1. Нажмите **📊 Проверить точность + HTML**.
2. Выберите папку профиля.
3. Программа рассчитает DeltaE и создаст HTML-отчёт.

---

## Структура проекта

```
PrinterProfiler/
├── printer_menu.py              # главный GUI
├── licensing.py                 # модуль лицензирования
├── theme.json                   # тёмная тема
├── theme_light.json             # светлая тема
├── ui_settings.json             # выбор темы
├── dpi_override.txt             # ручной масштаб DPI
├── requirements.txt             # зависимости
├── argyll_profiler/             # модули логики
│   ├── config.py
│   ├── logger.py
│   ├── profiler.py
│   ├── metadata.py
│   ├── papers.py
│   ├── report.py
│   ├── backup.py
│   └── printers.py
├── admin_printer/
│   └── admin.html               # админка для генерации ключей
├── logs/                        # дневные логи
├── backups/                     # бэкапы профилей
└── profiles/                    # готовые ICC-профили
```

---

## Конфигурация

Все настройки хранятся в `printer_profiler_config.json` рядом со скриптом.

| Параметр | Описание |
|---|---|
| `argvll_path` | Путь к папке `bin` ArgyllCMS |
| `base_dir` | Папка для профилей |
| `backup_dir` | Папка для бэкапов |
| `printer_name` | Имя принтера по умолчанию |
| `default_patches` | Количество патчей по умолчанию |
| `quality_patches` | Патчи для «Улучшить (качество)» |
| `timeout_seconds` | Таймаут операций |

Настройки можно менять через **⚙ Настройки** в GUI.

---

## Совместимость с калибраторами

GUI работает с любым калибратором, который поддерживается ArgyllCMS.
Список: [argyllcms.com/doc/Installing.html](https://www.argyllcms.com/doc/Installing.html)

Проверенные модели:
- X-Rite ColorMunki Design / Photo
- X-Rite i1Studio / Calibrite ColorChecker Studio
- X-Rite i1Pro / i1Pro 2 / i1Pro 3
- Datacolor Spyder (некоторые модели)
- Другие спектрофотометры, поддерживаемые ArgyllCMS

Для работы нужен **спектрофотометр** (не колориметр).

---

## Лицензия

Проект распространяется под лицензией **AGPL-3.0** — см. файл [LICENSE](LICENSE).

Это связано с использованием [ArgyllCMS](https://www.argyllcms.com/),
который тоже распространяется под AGPL-3.0.

---

## Автор

**VOROSHILOV D.V.** · 2026 · ESSO

---

## Ссылки

- [ArgyllCMS](https://www.argyllcms.com/)
- [Zadig](https://zadig.akeo.ie/)
- [customtkinter](https://github.com/TomSchimansky/CustomTkinter)