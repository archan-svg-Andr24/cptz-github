"""Реестр настроек — единственный источник значений (§30, SET-08).

Экран настроек строится из этого реестра: настройка с флагом «видима в UI» не
может на нём отсутствовать (SET-08). Тарифы и якоря недели в реестре **не**
хранятся — они живут в таблицах ``tariffs`` и ``week_anchors``.

Представление «не задано»: ``settings.value`` объявлен ``NOT NULL``, поэтому
``NULL`` хранится **пустой строкой** и читается как «не задано». Строки
``'NULL'`` и ``'0000-00-00'`` — ошибка валидации (Прил. А.0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from .errors import SettingsError
from .paths import BACKUP_DIR_TEMPLATE, DB_PATH_TEMPLATE
from . import dates as dt


class SettingsKeys:
    """Ключи реестра §30 (строковые константы, чтобы не опечататься)."""

    SCHEMA_VERSION = "schema_version"
    STRELKA_PERIOD_ANCHOR_DATE = "strelka_period_anchor_date"
    STRELKA_INITIAL_RIDE_COUNT = "strelka_initial_ride_count"
    STRELKA_PERIOD_DAYS = "strelka_period_days"
    STRELKA_FIRST_LIMIT = "strelka_first_limit"
    DEFAULT_BUS_PAYMENT_METHOD = "default_bus_payment_method"
    STRELKA_LOW_BALANCE_WARN = "strelka_low_balance_warn"
    FRIDAY_DEFAULT_VARIANT = "friday_default_variant"
    DATE_DISPLAY_FORMAT = "date_display_format"
    TIME_DISPLAY_FORMAT = "time_display_format"
    DB_PATH = "db_path"
    STUDENT_NAME = "student_name"
    GROUP_TITLE = "group_title"
    COLLEGE_NAME = "college_name"
    HOME_POINT_NAME = "home_point_name"
    BACKUP_DIR = "backup_dir"


class SettingType:
    """Типы значений реестра."""

    INT = "int"
    STRING = "string"
    DATE_OR_EMPTY = "date_or_empty"
    ENUM = "enum"
    PATH = "path"
    READONLY_INT = "readonly_int"


#: Разделы экрана настроек (SET-01).
class UiSection:
    NONE = ""
    GENERAL = "Общие"
    WEEKS = "Недели"
    BELLS = "Звонки"
    TRANSPORT = "Транспорт"
    CALENDAR = "Календарь"
    DATA = "Данные"

    ORDER: tuple[str, ...] = (GENERAL, WEEKS, BELLS, TRANSPORT, CALENDAR, DATA)


@dataclass(frozen=True)
class SettingSpec:
    """Описание одной настройки реестра."""

    key: str
    type: str
    default: str
    section: str
    label: str
    level: str = "[О]"
    visible: bool = True
    readonly: bool = False
    minimum: int | None = None
    choices: tuple[str, ...] = ()
    hint: str = ""
    #: Допустимые значения «пусто» (для типов с представлением «не задано»).
    empty_allowed: bool = False
    validator: Callable[[str], str] | None = field(default=None, compare=False)

    def coerce(self, raw: str) -> Any:
        """Преобразовать хранимую строку в значение Python."""
        if self.type in (SettingType.INT, SettingType.READONLY_INT):
            return int(raw) if raw != "" else 0
        return raw

    def to_storage(self, value: Any) -> str:
        """Преобразовать значение Python в хранимую строку."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, date):
            return dt.to_iso(value)
        return str(value)

    def validate(self, raw: str) -> str:
        """Проверить хранимое значение; вернуть нормализованное. Ошибка — SettingsError."""
        text = "" if raw is None else str(raw)
        if self.readonly:
            # Только чтение в UI; значение всё равно должно быть корректным.
            pass
        if self.type == SettingType.INT:
            if text.strip() == "":
                text = "0"
            try:
                number = int(text.strip())
            except ValueError as exc:
                raise SettingsError(
                    f"«{self.label}»: ожидается целое число, получено {raw!r}", field=self.key
                ) from exc
            if number < 0:
                raise SettingsError(f"«{self.label}»: значение не может быть отрицательным", field=self.key)
            if self.minimum is not None and number < self.minimum:
                raise SettingsError(
                    f"«{self.label}»: минимум {self.minimum}", field=self.key
                )
            return str(number)
        if self.type == SettingType.READONLY_INT:
            try:
                return str(int(text.strip()))
            except ValueError as exc:
                raise SettingsError(f"«{self.label}»: ожидается целое число", field=self.key) from exc
        if self.type == SettingType.DATE_OR_EMPTY:
            cleaned = text.strip()
            if cleaned == "":
                return ""
            if cleaned in ("NULL", "null", "None", "0000-00-00"):
                raise SettingsError(
                    f"«{self.label}»: недопустимое представление «не задано» ({cleaned!r}); "
                    "оставьте поле пустым",
                    field=self.key,
                )
            try:
                parsed = dt.parse_iso(cleaned, field=self.key)
            except Exception as exc:  # ValidationError
                raise SettingsError(str(exc), field=self.key) from exc
            return dt.to_iso(parsed)
        if self.type == SettingType.ENUM:
            cleaned = text.strip()
            if cleaned not in self.choices:
                raise SettingsError(
                    f"«{self.label}»: допустимые значения — {', '.join(self.choices)}", field=self.key
                )
            return cleaned
        if self.type == SettingType.PATH:
            if text.strip() in ("NULL", "0000-00-00"):
                raise SettingsError(f"«{self.label}»: недопустимое значение", field=self.key)
            return text
        # STRING
        cleaned = text.strip()
        if cleaned in ("NULL", "0000-00-00") and self.key != SettingsKeys.STUDENT_NAME:
            raise SettingsError(f"«{self.label}»: недопустимое значение {cleaned!r}", field=self.key)
        return cleaned


#: Реестр §30 целиком. Порядок внутри разделов — порядок отображения.
_REGISTRY: tuple[SettingSpec, ...] = (
    SettingSpec(
        SettingsKeys.SCHEMA_VERSION, SettingType.READONLY_INT, "2", UiSection.NONE,
        "Версия схемы", visible=False, readonly=True,
        hint="Служебный ключ (DATA-19). Только чтение.",
    ),
    SettingSpec(
        SettingsKeys.DATE_DISPLAY_FORMAT, SettingType.STRING, "DD.MM.YYYY", UiSection.GENERAL,
        "Формат даты", choices=("DD.MM.YYYY",),
    ),
    SettingSpec(
        SettingsKeys.TIME_DISPLAY_FORMAT, SettingType.STRING, "HH:MM", UiSection.GENERAL,
        "Формат времени", choices=("HH:MM",),
    ),
    SettingSpec(
        SettingsKeys.STUDENT_NAME, SettingType.STRING, "", UiSection.GENERAL,
        "Имя студента",
        hint="Пустое значение отображается в профиле как «Не указано» (FIRST-15).",
    ),
    SettingSpec(SettingsKeys.GROUP_TITLE, SettingType.STRING, "", UiSection.GENERAL, "Группа"),
    SettingSpec(
        SettingsKeys.COLLEGE_NAME, SettingType.STRING, "", UiSection.GENERAL,
        "Название колледжа", level="v1.1 (резерв)",
    ),
    SettingSpec(
        SettingsKeys.HOME_POINT_NAME, SettingType.STRING, "пос. Авсюнино", UiSection.GENERAL,
        "Домашняя точка", level="v1.1 (резерв)",
    ),
    SettingSpec(
        SettingsKeys.FRIDAY_DEFAULT_VARIANT, SettingType.ENUM, "standard", UiSection.BELLS,
        "Вариант пятницы по умолчанию", level="v1.1 (резерв)",
        choices=("standard", "friday_class_hour"),
    ),
    SettingSpec(
        SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, SettingType.DATE_OR_EMPTY, "",
        UiSection.TRANSPORT, "Дата начала расчётного периода «Стрелки»",
        empty_allowed=True,
        hint="Пусто = период начнётся с первой поездки (FARE-12).",
    ),
    SettingSpec(
        SettingsKeys.STRELKA_INITIAL_RIDE_COUNT, SettingType.INT, "0", UiSection.TRANSPORT,
        "Поездок уже засчитано в периоде", minimum=0,
        hint="Применяется только к первому периоду цепочки (ALG-02 шаг 8).",
    ),
    SettingSpec(
        SettingsKeys.STRELKA_PERIOD_DAYS, SettingType.READONLY_INT, "30", UiSection.TRANSPORT,
        "Длина расчётного периода, дней", readonly=True,
    ),
    SettingSpec(
        SettingsKeys.STRELKA_FIRST_LIMIT, SettingType.INT, "35", UiSection.TRANSPORT,
        "Порог первой ступени, поездок", minimum=1,
    ),
    SettingSpec(
        SettingsKeys.DEFAULT_BUS_PAYMENT_METHOD, SettingType.ENUM, "strelka", UiSection.TRANSPORT,
        "Способ оплаты автобуса по умолчанию", choices=("strelka", "debit_card"),
    ),
    SettingSpec(
        SettingsKeys.STRELKA_LOW_BALANCE_WARN, SettingType.INT, "2", UiSection.TRANSPORT,
        "Порог предупреждения об остатке, поездок", minimum=0,
    ),
    SettingSpec(
        SettingsKeys.DB_PATH, SettingType.PATH, DB_PATH_TEMPLATE, UiSection.DATA,
        "Путь к базе данных",
        hint="Значение по умолчанию хранится шаблоном %APPDATA% и раскрывается при запуске (GEN-16).",
    ),
    SettingSpec(
        SettingsKeys.BACKUP_DIR, SettingType.PATH, BACKUP_DIR_TEMPLATE, UiSection.DATA,
        "Каталог резервных копий", level="v1.1 (резерв)",
        hint="Пустая строка = резервные копии не сохраняются.",
    ),
)

_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in _REGISTRY}

#: Ключи, изменение которых запускает полный каскадный пересчёт (FARE-12, CALC-04).
RECALC_TRIGGER_KEYS: frozenset[str] = frozenset(
    {SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, SettingsKeys.STRELKA_INITIAL_RIDE_COUNT}
)


class SettingsRegistry:
    """Доступ к реестру §30."""

    def __init__(self, specs: tuple[SettingSpec, ...] = _REGISTRY) -> None:
        self._specs = specs
        self._index = {spec.key: spec for spec in specs}

    # -- доступ к описаниям -------------------------------------------------
    def all(self) -> tuple[SettingSpec, ...]:
        return self._specs

    def get(self, key: str) -> SettingSpec:
        try:
            return self._index[key]
        except KeyError as exc:
            raise SettingsError(f"Неизвестный ключ настройки: {key}", field=key) from exc

    def has(self, key: str) -> bool:
        return key in self._index

    def keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self._specs)

    def default_of(self, key: str) -> str:
        return self.get(key).default

    def defaults(self) -> dict[str, str]:
        """Значения стартового набора А.0 (все ключи реестра)."""
        return {spec.key: spec.default for spec in self._specs}

    # -- экран настроек -----------------------------------------------------
    def visible_in(self, section: str) -> tuple[SettingSpec, ...]:
        """Настройки раздела, видимые в UI (SET-08)."""
        return tuple(spec for spec in self._specs if spec.visible and spec.section == section)

    def sections(self) -> tuple[str, ...]:
        return tuple(section for section in UiSection.ORDER if self.visible_in(section))

    # -- валидация ----------------------------------------------------------
    def validate(self, key: str, raw: str) -> str:
        return self.get(key).validate(raw)

    def validate_anchor_date(self, raw: str, *, today: date | None = None) -> str:
        """DATA-21: пусто допустимо; иначе корректная дата не позже сегодня.

        Дата **раньше самой ранней поездки допускается** — это штатный случай
        «период на карте начался до начала учёта»: устаревший якорь
        самокорректируется по ALG-02 шагу 4.
        """
        normalized = self.validate(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, raw)
        if normalized:
            anchor = dt.parse_iso(normalized)
            current = today or date.today()
            if anchor > current:
                raise SettingsError(
                    "Дата начала расчётного периода не может быть позже сегодняшней "
                    f"({dt.format_display(current)}).",
                    field=SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE,
                )
        return normalized


_DEFAULT_REGISTRY = SettingsRegistry()


def default_registry() -> SettingsRegistry:
    """Синглтон реестра §30."""
    return _DEFAULT_REGISTRY


__all__ = [
    "SettingsKeys",
    "SettingType",
    "UiSection",
    "SettingSpec",
    "SettingsRegistry",
    "default_registry",
    "RECALC_TRIGGER_KEYS",
]
