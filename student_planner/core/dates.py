"""Даты и время (GEN-10, GEN-11, DATA-11, DATA-12).

В БД даты хранятся строками ``ГГГГ-ММ-ДД`` и сравниваются лексикографически,
что для ISO-формы эквивалентно сравнению дат. В интерфейсе — ``ДД.ММ.ГГГГ``.
Время — ``ЧЧ:ММ``, 24 часа.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import final

from .errors import ValidationError

ISO_FORMAT = "%Y-%m-%d"
#: Формат отображения по умолчанию (``date_display_format`` §30).
DEFAULT_DISPLAY_FORMAT = "DD.MM.YYYY"
DEFAULT_TIME_FORMAT = "HH:MM"

#: Допустимые значения настройки формата даты (SET-02).
DISPLAY_FORMATS: final[tuple[str, ...]] = ("DD.MM.YYYY", "YYYY-MM-DD", "DD.MM.YY")
#: Допустимые значения настройки формата времени.
TIME_FORMATS: final[tuple[str, ...]] = ("HH:MM", "HH:MM:SS")

#: Действующий формат отображения. Пустая строка — «не задан», тогда работает
#: значение по умолчанию. Заполняется из настроек при запуске и при смене
#: настройки на странице «Настройки» (см. :func:`set_display_format`).
_active_display_format: str = ""
_active_time_format: str = ""

WEEKDAY_NAMES: dict[int, str] = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}
WEEKDAY_SHORT: dict[int, str] = {
    1: "Пн",
    2: "Вт",
    3: "Ср",
    4: "Чт",
    5: "Пт",
    6: "Сб",
    7: "Вс",
}
MONTH_NAMES: dict[int, str] = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября",
    12: "декабря",
}
#: Именительный падеж — для заголовков («Октябрь 2026»), не для дат.
MONTH_NAMES_NOMINATIVE: dict[int, str] = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь",
    12: "Декабрь",
}

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def today_iso() -> str:
    """Сегодняшняя дата в ISO — через провайдер :mod:`clock` (подменяемый в тестах)."""
    from . import clock

    return to_iso(clock.today())


def to_iso(value: date | datetime) -> str:
    """Дата → ``ГГГГ-ММ-ДД``.

    ``isoformat()`` в разы быстрее ``strftime`` и даёт ровно тот же результат
    для ``date``/``datetime``; горячий путь пересчёта вызывает это на каждую
    поездку (NFR-10).
    """
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()


def parse_iso(text: str, *, field: str = "date") -> date:
    """Разобрать ``ГГГГ-ММ-ДД``; корректность проверяется (DATA-11)."""
    if not isinstance(text, str) or not _ISO_RE.match(text.strip()):
        raise ValidationError(f"Ожидается дата в формате ГГГГ-ММ-ДД, получено: {text!r}", field=field)
    # ``date.fromisoformat`` вместо ``strptime``: он не трогает локаль и в
    # несколько раз быстрее, а формат уже проверен регулярным выражением.
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:  # 2026-02-30 и подобное
        raise ValidationError(f"Некорректная дата: {text!r}", field=field) from exc


def try_parse_iso(text: str) -> date | None:
    """Мягкий разбор: ``None`` вместо исключения (для настроек «не задано»)."""
    try:
        return parse_iso(text)
    except ValidationError:
        return None


def is_valid_iso(text: str) -> bool:
    return try_parse_iso(text) is not None


def _to_strftime(fmt: str) -> str:
    """Преобразовать формат вида ``DD.MM.YYYY`` в ``format`` для ``strftime``."""
    mapping = (
        ("YYYY", "%Y"),
        ("YY", "%y"),
        ("DD", "%d"),
        ("MM", "%m"),
    )
    result = fmt
    for token, directive in mapping:
        result = result.replace(token, directive)
    return result


def format_display(value: date | None, fmt: str | None = None) -> str:
    """Дата → строка интерфейса.

    ``fmt=None`` означает «действующий формат приложения»: он задаётся
    настройкой ``date_display_format`` через :func:`set_display_format`.
    Пока настройка не прочитана, работает ``ДД.ММ.ГГГГ``.
    """
    if value is None:
        return ""
    resolved = fmt or _active_display_format or DEFAULT_DISPLAY_FORMAT
    try:
        return value.strftime(_to_strftime(resolved))
    except ValueError:
        return value.strftime("%d.%m.%Y")


def parse_display(text: str, fmt: str | None = None) -> date:
    """Разобрать дату из поля ввода интерфейса."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValidationError("Дата не задана", field="date")
    resolved = fmt or _active_display_format or DEFAULT_DISPLAY_FORMAT
    for candidate in (_to_strftime(resolved), "%d.%m.%Y", ISO_FORMAT):
        try:
            return datetime.strptime(cleaned, candidate).date()
        except ValueError:
            continue
    raise ValidationError(f"Некорректная дата: {text!r}", field="date")


def set_display_format(fmt: str | None) -> None:
    """SET-02: применить выбранный в настройках формат даты ко всему UI.

    Формат — глобальная настройка отображения, а не свойство отдельного окна:
    держим его в модуле, чтобы ``format_display()`` без аргументов давал
    ровно то, что выбрал пользователь. Неизвестный формат игнорируется.
    """
    global _active_display_format
    value = (fmt or "").strip()
    _active_display_format = value if value in DISPLAY_FORMATS else ""


def active_display_format() -> str:
    """Действующий формат даты (``DD.MM.YYYY``, если не задан)."""
    return _active_display_format or DEFAULT_DISPLAY_FORMAT


def set_time_format(fmt: str | None) -> None:
    """SET-02: применить выбранный формат времени (``HH:MM``/``HH:MM:SS``)."""
    global _active_time_format
    value = (fmt or "").strip()
    _active_time_format = value if value in TIME_FORMATS else ""


def active_time_format() -> str:
    """Действующий формат времени."""
    return _active_time_format or DEFAULT_TIME_FORMAT


def format_time_display(value: str | None, fmt: str | None = None) -> str:
    """Время ``ЧЧ:ММ`` → строка по действующему формату.

    Хранится время всегда как ``ЧЧ:ММ`` (схема БД); настройка влияет только
    на показ. ``HH:MM:SS`` добавляет секунды — они всегда нулевые, потому что
    в сетке звонков секунд нет.
    """
    if not value:
        return ""
    cleaned = str(value).strip()
    resolved = fmt or _active_time_format or DEFAULT_TIME_FORMAT
    if resolved == "HH:MM:SS" and len(cleaned) == 5:
        return f"{cleaned}:00"
    return cleaned[:5] if len(cleaned) > 5 else cleaned


def monday_of(value: date) -> date:
    """Понедельник недели даты (неделя — Пн…Вс, WEEK-01)."""
    return value - timedelta(days=value.isoweekday() - 1)


def week_dates(start: date, days: int = 7) -> list[date]:
    """Даты недели от ``start`` (по умолчанию 7 дней)."""
    return [start + timedelta(days=offset) for offset in range(days)]


def add_days(value: date, days: int) -> date:
    return value + timedelta(days=days)


def weeks_between(first: date, second: date) -> int:
    """Разница в неделях между понедельниками двух дат (может быть отрицательной)."""
    return (monday_of(second) - monday_of(first)).days // 7


def parse_time(text: str, *, field: str = "time") -> tuple[int, int]:
    """Разобрать ``ЧЧ:ММ`` (GEN-10, DATA-12)."""
    if not isinstance(text, str) or not _TIME_RE.match(text.strip()):
        raise ValidationError(f"Ожидается время в формате ЧЧ:ММ, получено: {text!r}", field=field)
    hour, minute = text.strip().split(":")
    return int(hour), int(minute)


def is_valid_time(text: str) -> bool:
    return isinstance(text, str) and bool(_TIME_RE.match(text.strip()))


def time_to_minutes(text: str) -> int:
    """``'08:30'`` → 510 — для сравнения и проверки пересечений (BELL-17)."""
    hour, minute = parse_time(text)
    return hour * 60 + minute


def minutes_to_time(minutes: int) -> str:
    if not 0 <= minutes < 24 * 60:
        raise ValidationError(f"Время вне суток: {minutes} минут", field="time")
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def human_date(value: date) -> str:
    """``7 сентября 2026`` — для заголовков и сообщений."""
    return f"{value.day} {MONTH_NAMES[value.month]} {value.year}"


def date_range(start: date, end: date) -> list[date]:
    """Даты диапазона включительно."""
    if end < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def month_bounds(value: date) -> tuple[date, date]:
    """Границы месяца для отчётов REP-03."""
    first = value.replace(day=1)
    if first.month == 12:
        nxt = date(first.year + 1, 1, 1)
    else:
        nxt = date(first.year, first.month + 1, 1)
    return first, nxt - timedelta(days=1)


__all__ = [
    "ISO_FORMAT",
    "DEFAULT_DISPLAY_FORMAT",
    "DEFAULT_TIME_FORMAT",
    "DISPLAY_FORMATS",
    "TIME_FORMATS",
    "WEEKDAY_NAMES",
    "WEEKDAY_SHORT",
    "MONTH_NAMES",
    "MONTH_NAMES_NOMINATIVE",
    "to_iso",
    "parse_iso",
    "try_parse_iso",
    "is_valid_iso",
    "today_iso",
    "format_display",
    "parse_display",
    "set_display_format",
    "active_display_format",
    "set_time_format",
    "active_time_format",
    "format_time_display",
    "monday_of",
    "week_dates",
    "add_days",
    "weeks_between",
    "parse_time",
    "is_valid_time",
    "time_to_minutes",
    "minutes_to_time",
    "human_date",
    "date_range",
    "month_bounds",
]
