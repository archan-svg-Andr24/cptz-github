"""Точка входа приложения «Студенческий органайзер» (§2, §31, §32, §33).

Порядок запуска (NFR-05, DATA-18…DATA-21, FIRST-01):
1. проверка версии схемы — при несовпадении приложение отказывается стартовать
   и не изменяет файл (DATA-19);
2. открытие или создание базы в каталоге данных пользователя;
3. при первом запуске — мастер из трёх шагов (FIRST-03…FIRST-15);
4. главное окно с тремя колонками (UI-06).

Сеть не используется (NFR-01). Все данные хранятся в одном файле SQLite.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import shutil
import sys
import traceback
from pathlib import Path

from . import APP_NAME, APP_TITLE, APP_VERSION, SCHEMA_VERSION
from .core.database import is_initialized, open_database
from .core.errors import AppError, SchemaVersionError
from .core.paths import default_db_path, ensure_dir, logs_dir
from .core.seeding import initialize_database

LOG_FILENAME = "student_planner.log"


def configure_logging(verbose: bool = False) -> Path:
    """NFR-05: журнал в файл с ротацией, без падения при недоступном каталоге."""
    target_dir = logs_dir()
    try:
        ensure_dir(target_dir)
    except OSError:
        target_dir = Path.cwd()

    path = target_dir / LOG_FILENAME
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
        root.addHandler(file_handler)
    except OSError:
        pass

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    return path


def _install_excepthook() -> None:
    """ERR-14: непойманное исключение пишется в журнал, приложение не молчит."""

    def handler(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger(__name__).critical(
            "Необработанная ошибка:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handler


def open_or_create_database():
    """DATA-18: существующая база проверяется, новая создаётся со стартовым набором.

    V2-SCHEMA: база предыдущей версии схемы не блокирует запуск. Она
    сохраняется рядом как резервная копия и создаётся заново со стартовым
    набором — механизма миграции в MVP нет (§34.1 п. 48).

    Возвращает ``(db, created, backup_path)``: ``backup_path`` заполнен, если
    база была пересоздана из-за несовпадения версии схемы.
    """
    path = default_db_path()
    if is_initialized(path):
        try:
            # DATA-19: несовпадение версии схемы — отказ без изменения файла.
            return open_database(path), False, None
        except SchemaVersionError as error:
            details = getattr(error, "details", {}) or {}
            stored = details.get("stored")
            if stored is None or int(stored) >= SCHEMA_VERSION:
                # Файл новее приложения или без версии — не трогаем.
                raise
            backup = _backup_old_database(path, int(stored))
            logging.getLogger(__name__).warning(
                "База версии схемы %s сохранена как %s и создаётся заново",
                stored, backup.name,
            )
            path.unlink()
            initialize_database(path)
            return open_database(path), True, backup
    initialize_database(path)
    return open_database(path), True, None


def _backup_old_database(path: Path, stored_version: int) -> Path:
    """V2-SCHEMA: сохранить базу прежней версии рядом с рабочей."""
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(
        f"{path.stem}-schema{stored_version}-{stamp}{path.suffix}.bak"
    )
    shutil.copy2(path, backup)
    return backup


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    verbose = "--verbose" in argv or "-v" in argv

    log_path = configure_logging(verbose)
    _install_excepthook()
    log = logging.getLogger(__name__)
    log.info("Запуск %s %s (схема %d)", APP_NAME, APP_VERSION, SCHEMA_VERSION)
    log.info("Файл журнала: %s", log_path)

    # Импорт Qt после настройки журнала: ошибки импорта тоже попадут в файл.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)

    try:
        db, created, backup = open_or_create_database()
    except SchemaVersionError as error:
        # DATA-19, ACC-M-72: файл не изменён, приложение не стартует.
        QMessageBox.critical(
            None, "Несовместимая версия базы данных",
            f"{error.message}\n\nФайл базы данных не изменён. "
            f"Закройте приложение и обратитесь к резервной копии.",
        )
        log.error("Отказ запуска: %s", error)
        return 2
    except AppError as error:
        QMessageBox.critical(None, "Ошибка базы данных", error.message)
        log.error("Не удалось открыть базу: %s", error)
        return 3

    from .ui.first_run import FirstRunWizard
    from .ui.main_window import MainWindow

    if created:
        # FIRST-03…FIRST-15: мастер первого запуска.
        wizard = FirstRunWizard(db)
        wizard.exec()
    if backup is not None:
        # V2-SCHEMA: база прежней версии сохранена в резервную копию.
        QMessageBox.information(
            None, "База данных обновлена",
            "Файл базы данных был создан предыдущей версией приложения. "
            "Он сохранён как резервная копия рядом с рабочей базой, а рабочий "
            "файл создан заново со стартовым набором.\n\n"
            f"Резервная копия: {backup}",
        )

    window = MainWindow(db)
    window.show()
    log.info("Главное окно открыто")
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
