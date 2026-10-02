# -*- coding: utf-8 -*-
"""CLI-интерфейс профилирования принтера."""
import argparse
import os
import sys

from .config import load_config
from .logger import ProfilerLogger
from .profiler import Profiler, ProfileRequest, ProfilerError
from .report import build_report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="profile_printer",
        description="Профилирование принтера через ArgyllCMS + ColorMunki",
    )
    p.add_argument(
        "mode", nargs="?", default=None,
        choices=["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
        help="1-полный, 2-измерение, 3-1200 патчей, "
             "4-проверка прибора, 5-настройки, 6-DeltaE+HTML, "
             "7-сравнить профили, 8-resume, 9-Zadig справка, 0-выход",
    )
    p.add_argument("--paper", help="Название бумаги")
    p.add_argument("--finish", choices=["Glossy", "Satin", "Matte"],
                   default="Glossy")
    p.add_argument("--size", choices=["A4", "A3", "Letter", "A2"],
                   default="A4")
    p.add_argument("--patches", type=int)
    p.add_argument("--printer", default="Canon_PixmaPro10S")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--config", default=None)
    p.add_argument("--open-report", action="store_true")
    return p


def interactive_menu(logger) -> str:
    logger.info("\n" + "=" * 60)
    logger.info("📋 ГЛАВНОЕ МЕНЮ")
    logger.info("=" * 60)
    logger.info("  1. Полный цикл")
    logger.info("  2. Только измерение")
    logger.info("  3. Улучшить точность (1200 патчей)")
    logger.info("  4. Проверить прибор")
    logger.info("  5. Настройки")
    logger.info("  6. Проверить точность (DeltaE + HTML)")
    logger.info("  7. Сравнить два профиля")
    logger.info("  8. Продолжить прерванное измерение")
    logger.info("  9. Установка драйвера через Zadig (справка)")
    logger.info("  0. Выход")
    logger.info("=" * 60)
    return input("Выберите пункт: ").strip()


def print_zadig_help() -> None:
    """Печатает пошаговую инструкцию по установке драйвера через Zadig."""
    print()
    print("=" * 62)
    print("  🔧  УСТАНОВКА ДРАЙВЕРА COLORMUNKI ЧЕРЕЗ ZADIG")
    print("=" * 62)
    print()
    print("  🎯 Что делать (5 минут):")
    print("    1. Скачайте Zadig:  https://zadig.akeo.ie/")
    print("    2. Запустите Zadig ОТ ИМЕНИ АДМИНИСТРАТОРА.")
    print("    3. Меню Options → галочка 'List All Devices'.")
    print("    4. Выберите 'colormunki' (Interface 0).")
    print("    5. Драйвер: libusb-win32 (v1.4.0.0).")
    print("    6. Нажмите 'Install Driver' / 'Replace Driver'.")
    print("    7. Дождитесь окончания (10-30 сек).")
    print("    8. Вернитесь сюда и запустите пункт 4 (Проверить прибор).")
    print()
    print("  ✅ Как понять, что всё сработало:")
    print("    • В пункте 4 → '✅ Прибор обнаружен и готов к работе'")
    print("    • В Диспетчере устройств появится 'libusb-win32 devices'")
    print()
    print("  🔄 Возврат родного драйвера (для i1Studio / Calibrite):")
    print("    • В Zadig выберите драйвер 'HID (Microsoft)' и Replace Driver.")
    print("    • Или через Диспетчер устройств: удалить устройство,")
    print("      отключить и снова подключить кабель — Windows поставит")
    print("      драйвер автоматически.")
    print()
    print("  📋 Если Zadig не помог:")
    print("    • Закройте i1Studio / Calibrite / X-Rite (они держат прибор).")
    print("    • Запустите GUI от администратора.")
    print("    • Попробуйте другой USB-порт или кабель.")
    print("=" * 62)
    print()
    input("Нажмите Enter для возврата в меню...")


def _pick_folder(cfg, logger) -> str:
    """Интерактивный выбор папки профиля из base_dir."""
    base = cfg.base_dir
    if not os.path.isdir(base):
        raise ProfilerError(f"Папка не найдена: {base}")
    folders = sorted(f for f in os.listdir(base)
                     if os.path.isdir(os.path.join(base, f)))
    if not folders:
        raise ProfilerError("Нет папок с профилями")
    for i, f in enumerate(folders, 1):
        logger.info(f"  {i}. {f}")
    raw = input("Номер папки: ").strip()
    try:
        idx = int(raw) - 1
        if idx < 0 or idx >= len(folders):
            raise ValueError
    except ValueError:
        raise ProfilerError("Неверный номер")
    return os.path.join(base, folders[idx])


def _find_icc_in_folder(folder: str) -> str:
    """Ищет .icc или .icm в папке."""
    name = os.path.basename(folder.rstrip("/\\"))
    for ext in (".icc", ".icm"):
        p = os.path.join(folder, f"{name}{ext}")
        if os.path.exists(p):
            return p
    for f in os.listdir(folder):
        if f.lower().endswith((".icc", ".icm")):
            return os.path.join(folder, f)
    raise ProfilerError(f"В {folder} не найден .icc/.icm")


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    if args.dry_run:
        cfg.dry_run = True

    logger = ProfilerLogger(cfg.base_dir, cfg.log_level)
    profiler = Profiler(cfg, logger)

    # Интерактивный цикл меню (если не задан режим)
    if args.mode is None:
        while True:
            try:
                mode = interactive_menu(logger)
            except (KeyboardInterrupt, EOFError):
                print("\n👋 До свидания!")
                return
            if mode == "0":
                logger.info("👋 До свидания!")
                return
            if mode == "9":
                print_zadig_help()
                continue
            break
    else:
        mode = args.mode

    try:
        # ---------- 1. Полный цикл ----------
        if mode == "1":
            paper = (args.paper
                     or input("Название бумаги: ").strip()
                     or "Unknown")
            patches = args.patches or cfg.default_patches
            icc = profiler.run_full(ProfileRequest(
                printer=args.printer, paper=paper, finish=args.finish,
                paper_size=args.size, patches=patches,
                overwrite=args.overwrite,
            ))
            logger.success(f"✅ Готово: {icc}")

        # ---------- 2. Только измерение ----------
        elif mode == "2":
            folder = _pick_folder(cfg, logger)
            icc = profiler.run_measurement(folder)
            logger.success(f"✅ Готово: {icc}")

        # ---------- 3. Улучшить точность (1200 патчей) ----------
        elif mode == "3":
            paper = (args.paper
                     or input("Название бумаги: ").strip()
                     or "Unknown")
            icc = profiler.run_full(ProfileRequest(
                printer=args.printer, paper=paper + "_1200",
                finish=args.finish, paper_size=args.size or "A3",
                patches=cfg.quality_patches, overwrite=True,
            ))
            logger.success(f"✅ Готово: {icc}")

        # ---------- 4. Проверка прибора ----------
        elif mode == "4":
            ok = profiler.argyll.check_instrument()
            sys.exit(0 if ok else 1)

        # ---------- 5. Настройки ----------
        elif mode == "5":
            logger.info(f"ArgyllCMS: {cfg.argvll_path}")
            logger.info(f"Profiles:  {cfg.base_dir}")
            logger.info(f"Backups:   {cfg.backup_dir}")
            logger.info(f"Patches:   default={cfg.default_patches}, "
                        f"quality={cfg.quality_patches}")
            logger.info(f"Timeout:   {cfg.timeout_seconds} сек")

        # ---------- 6. Проверка точности + HTML ----------
        elif mode == "6":
            folder = _pick_folder(cfg, logger)
            stats = profiler.check_accuracy(folder)
            logger.info("-" * 50)
            logger.info(f"Peak ΔE: {stats.get('peak')}")
            logger.info(f"Avg  ΔE: {stats.get('avg')}")
            logger.info(f"RMS:     {stats.get('rms')}")
            logger.success(stats.get("quality", ""))
            report = build_report(folder, stats,
                                  open_after=args.open_report)
            logger.info(f"📄 Отчёт: {report}")

        # ---------- 7. Сравнение двух профилей ----------
        elif mode == "7":
            logger.info("Выберите ПЕРВЫЙ профиль:")
            f1 = _pick_folder(cfg, logger)
            logger.info("Выберите ВТОРОЙ профиль:")
            f2 = _pick_folder(cfg, logger)
            icc1 = _find_icc_in_folder(f1)
            icc2 = _find_icc_in_folder(f2)
            stats = profiler.compare(icc1, icc2)
            logger.info("-" * 50)
            logger.info(f"Peak ΔE: {stats.get('peak')}")
            logger.info(f"Avg  ΔE: {stats.get('avg')}")
            logger.info(f"RMS:     {stats.get('rms')}")

        # ---------- 8. Продолжить прерванное измерение ----------
        elif mode == "8":
            folder = _pick_folder(cfg, logger)
            icc = profiler.run_measurement(folder, resume=True)
            logger.success(f"✅ Готово: {icc}")

        # ---------- 9. Справка по Zadig ----------
        elif mode == "9":
            print_zadig_help()

        # ---------- 0. Выход ----------
        elif mode == "0":
            logger.info("👋 До свидания!")
            return

        else:
            logger.error(f"❌ Неизвестный режим: {mode}")
            sys.exit(2)

    except ProfilerError as e:
        logger.error(f"❌ {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        logger.warning("\n⚠️ Прервано пользователем")
        sys.exit(130)


if __name__ == "__main__":
    main()