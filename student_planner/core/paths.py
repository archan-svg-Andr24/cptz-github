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
]
