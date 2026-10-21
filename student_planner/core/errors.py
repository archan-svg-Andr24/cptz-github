"""Иерархия ошибок приложения (§37.2).

Правило NFR-05: ни один сценарий не завершается необработанным исключением.
Поэтому всё, что предназначено пользователю, поднимается как :class:`AppError`
с русским текстом; UI показывает ``str(error)`` и пишет подробности в лог.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Базовая ошибка приложения с сообщением для пользователя."""

    code = "APP"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:  # pragma: no cover - тривиально
        return self.message


class ValidationError(AppError):
    """Некорректный ввод: форма не закрывается, поле подсвечивается (ERR)."""

    code = "VALIDATION"

    def __init__(self, message: str, *, field: str | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.field = field


class SchemaVersionError(AppError):
    """Версия схемы не совпадает с известной приложению (DATA-19).

    Файл БД при этом не изменяется. Механизм миграции — v1.1.
    """

    code = "SCHEMA_VERSION"


class DatabaseBusyError(AppError):
    """БД занята другим процессом (ERR: повтор до 5 попыток)."""

    code = "DB_BUSY"


class DatabaseCorruptedError(AppError):
    """БД повреждена: предлагается новая или восстановление из копии."""

    code = "DB_CORRUPTED"


class NotFoundError(AppError):
    """Запрошенная запись не найдена."""

    code = "NOT_FOUND"


class InUseError(AppError):
    """Сущность используется и не может быть удалена (DATA-15).

    Вместо удаления предлагается деактивация.
    """

    code = "IN_USE"


class PriceUnavailableError(AppError):
    """На дату нет действующего базового тарифа: подтверждение блокируется (TRIP-19)."""

    code = "PRICE_UNAVAILABLE"

    def __init__(self, message: str, *, kind: str | None = None, date: Any = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.kind = kind
        self.date = date


class RuleViolationError(AppError):
    """Нарушено правило предметной области (OVR-08, BELL-16, RT-16 …)."""

    code = "RULE"


class SettingsError(ValidationError):
    """Ошибка настройки реестра §30 (DATA-21)."""

    code = "SETTINGS"


__all__ = [
    "AppError",
    "ValidationError",
    "SchemaVersionError",
    "DatabaseBusyError",
    "DatabaseCorruptedError",
    "NotFoundError",
    "InUseError",
    "PriceUnavailableError",
    "RuleViolationError",
    "SettingsError",
]
