"""Пути приложения и хранение путей шаблоном (DATA-02, DATA-03, GEN-16).

Значения по умолчанию ``db_path`` и ``backup_dir`` хранятся **шаблоном**
(``%APPDATA%\\StudentPlanner\\…``), а не результатом раскрытия: раскрытый вид
``C:\\Users\\<имя>\\…`` содержал бы идентификатор пользователя и ломал бы
переносимость файла БД. Раскрытие происходит при каждом запуске.

Путь, введённый пользователем вручную, сохраняется как введён и раскрытию не
подлежит.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import APP_NAME

#: Шаблон пути к БД по умолчанию (§30, Прил. А.0).
DB_PATH_TEMPLATE = "%APPDATA%\\StudentPlanner\\student_planner.db"
#: Шаблон каталога резервных копий по умолчанию (§30).
BACKUP_DIR_TEMPLATE = "%APPDATA%\\StudentPlanner\\backups"

_DB_FILENAME = "student_planner.db"


def appdata_dir() -> Path:
    """``%APPDATA%\\StudentPlanner`` — каталог приложения (создаётся при первом запуске)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata)
    else:  # запасной путь для не-Windows окружений (тесты, отладка)
        base = Path.home() / "AppData" / "Roaming"
    return base / APP_NAME


def logs_dir() -> Path:
    """``%APPDATA%\\StudentPlanner\\logs`` (NFR-05)."""
    return appdata_dir() / "logs"


def default_db_path() -> Path:
    """Раскрытый путь БД по умолчанию: ``…\\student_planner.db``."""
    return appdata_dir() / _DB_FILENAME


def expand_path(value: str | Path) -> Path:
    """Раскрыть ``%VAR%`` и ``~`` в пути; ручной путь сохраняется как введён."""
    raw = str(value)
    expanded = os.path.expandvars(raw)
    if "%" in expanded:  # неизвестная переменная — не оставляем как есть
        expanded = expanded.replace("%APPDATA%", os.environ.get("APPDATA", str(Path.home())))
    return Path(os.path.expanduser(expanded))


def is_template_path(value: str) -> bool:
    """Содержит ли значение нераскрытую переменную вида ``%APPDATA%``."""
    return "%" in (value or "")


def ensure_dir(path: Path) -> Path:
    """Создать каталог, если его нет (DATA-03)."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> Path:
    """Создать каталог файла (родителя)."""
    ensure_dir(path.parent)
    return path


def resolve_db_path(stored_value: str | None) -> Path:
    """Путь БД из настройки: шаблон раскрывается, ручной путь берётся как есть."""
    from .settings_registry import SettingsKeys, default_registry

    value = stored_value
    if not value:
        value = default_registry().default_of(SettingsKeys.DB_PATH) or DB_PATH_TEMPLATE
    return expand_path(value)


def pointer_file() -> Path:
    """Файл-указатель на рабочую базу (DATA-02, ``db_path``).

    Настройка ``db_path`` живёт **внутри** самой базы: пока приложение не
    открыло файл, прочитать её невозможно. Поэтому выбранный пользователем
    путь дублируется маленьким текстовым файлом в каталоге приложения — по
    нему следующий запуск находит нужную базу. В самом файле БД остаётся
    актуальное значение настройки (SET-07).
    """
    return appdata_dir() / "database.path"


def read_pointer() -> Path | None:
    """Прочитать путь из файла-указателя; ``None``, если его нет или он пуст."""
    try:
        raw = pointer_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return expand_path(raw) if raw else None


def write_pointer(path: Path) -> None:
    """Запомнить рабочую базу для следующего запуска (DATA-02)."""
    target = pointer_file()
    ensure_dir(target.parent)
    target.write_text(str(Path(path)), encoding="utf-8")


def clear_pointer() -> None:
    """Забыть указатель (сброс на путь по умолчанию)."""
    try:
        pointer_file().unlink()
    except OSError:
        pass


def startup_db_path(db=None) -> Path:
    """Путь базы, который открывает запуск (DATA-02, SET-07).

    Приоритет:

    1. настройка ``db_path`` в уже открытой базе, если она задана и **не
       равна пути по умолчанию**;
    2. файл-указатель, оставленный прошлым запуском;
    3. путь по умолчанию.

    Значение по умолчанию намеренно не перебивает указатель: в стартовом
    наборе ``db_path`` содержит шаблон пути по умолчанию, и если считать его
    «заданным», выбор пользователя из настройки никогда бы не применился.
    """
    if db is not None:
        try:
            from .settings_registry import SettingsKeys, default_registry
            from .settings_service import SettingsService

            stored = SettingsService(db).raw(SettingsKeys.DB_PATH)
            default_value = default_registry().default_of(SettingsKeys.DB_PATH)
        except Exception:  # pragma: no cover - защита запуска
            stored, default_value = "", ""
        # Сравниваем со **значением по умолчанию из реестра** (шаблоном), а не
        # с раскрытым путём: иначе шаблон, раскрытый в другой каталог, считался
        # бы пользовательским выбором и перебивал файл-указатель.
        if stored and stored != default_value:
            return resolve_db_path(stored)
    pointed = read_pointer()
    if pointed is not None:
        return pointed
    return default_db_path()


__all__ = [
    "DB_PATH_TEMPLATE",
    "BACKUP_DIR_TEMPLATE",
    "appdata_dir",
    "logs_dir",
    "default_db_path",
    "expand_path",
    "is_template_path",
    "ensure_dir",
    "ensure_parent",
    "resolve_db_path",
    "pointer_file",
    "read_pointer",
    "write_pointer",
    "clear_pointer",
    "startup_db_path",
]
