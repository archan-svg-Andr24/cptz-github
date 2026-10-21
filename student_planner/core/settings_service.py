"""Сервис настроек: чтение, запись и валидация реестра §30.

Настройки — единственный источник значений (SET-08). Изменение
``FARE-12``-ключей (``strelka_period_anchor_date``, ``strelka_initial_ride_count``)
обязано запускать полный каскадный пересчёт: сервис сообщает об этом через
``SettingsChange.needs_recalc``, а вызывающий (сервис поездок) выполняет CALC-04
в той же транзакции.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import dates as dt
from .database import Database
from .errors import SettingsError
from .settings_registry import (
    RECALC_TRIGGER_KEYS,
    SettingSpec,
    SettingsKeys,
    SettingsRegistry,
    UiSection,
    default_registry,
)


@dataclass
class SettingsChange:
    """Итог записи настроек: какие ключи изменились и нужен ли пересчёт."""

    changed: dict[str, tuple[str, str]] = field(default_factory=dict)
    needs_recalc: bool = False

    def __bool__(self) -> bool:
        return bool(self.changed)


class SettingsService:
    """Чтение и запись ключей ``settings`` с валидацией по реестру."""

    def __init__(self, db: Database, registry: SettingsRegistry | None = None) -> None:
        self.db = db
        self.registry = registry or default_registry()

    # ------------------------------------------------------------- чтение
    def raw(self, key: str) -> str:
        """Сырое хранимое значение; отсутствие ключа — ошибка реестра."""
        self.registry.get(key)  # проверка существования ключа
        row = self.db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return self.registry.default_of(key)
        return "" if row["value"] is None else str(row["value"])

    def get(self, key: str) -> Any:
        """Значение с приведением типа по реестру."""
        spec = self.registry.get(key)
        return spec.coerce(self.raw(key))

    def get_int(self, key: str) -> int:
        return int(self.get(key))

    def get_str(self, key: str) -> str:
        return str(self.get(key))

    def get_date(self, key: str) -> date | None:
        """Дата из настройки; пустая строка — «не задано» (``None``)."""
        value = self.raw(key)
        return None if value == "" else dt.parse_iso(value, field=key)

    def all(self) -> dict[str, str]:
        """Все ключи реестра с действующими значениями (для экрана настроек)."""
        stored = {
            str(row["key"]): ("" if row["value"] is None else str(row["value"]))
            for row in self.db.fetchall("SELECT key, value FROM settings")
        }
        return {spec.key: stored.get(spec.key, spec.default) for spec in self.registry.all()}

    def visible_for(self, section: str) -> list[SettingSpec]:
        """Настройки раздела, видимые в UI (SET-08)."""
        return list(self.registry.visible_in(section))

    # ------------------------------------------------------------- запись
    def set(self, key: str, raw: str, *, validate_anchor: bool = True) -> str:
        """Записать одну настройку; вернуть нормализованное значение."""
        spec = self.registry.get(key)
        if spec.readonly and key != SettingsKeys.SCHEMA_VERSION:
            raise SettingsError(
                f"«{spec.label}» только для чтения и не может быть изменена в MVP (SET-05).",
                field=key,
            )
        if key == SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE and validate_anchor:
            normalized = self.registry.validate_anchor_date(raw)
        else:
            normalized = spec.validate(raw)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, normalized),
            )
        return normalized

    def set_many(self, values: dict[str, str], *, validate_anchor: bool = True) -> SettingsChange:
        """Записать несколько настроек одной транзакцией.

        Возвращает :class:`SettingsChange`; ``needs_recalc`` истинно, если
        изменился ключ FARE-12 (CALC-04 обязателен).
        """
        change = SettingsChange()
        normalized: dict[str, str] = {}
        for key, raw in values.items():
            spec = self.registry.get(key)
            if key == SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE and validate_anchor:
                value = self.registry.validate_anchor_date(raw)
            else:
                value = spec.validate(raw)
            normalized[key] = value
        with self.db.transaction() as conn:
            for key, value in normalized.items():
                row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
                before = "" if row is None else str(row["value"])
                if before == value:
                    continue
                change.changed[key] = (before, value)
                if key in RECALC_TRIGGER_KEYS:
                    change.needs_recalc = True
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
        return change

    def set_display_formats(self, date_format: str, time_format: str) -> None:
        """Форматы отображения «Настройки → Общие» (SET-02)."""
        self.set_many(
            {
                SettingsKeys.DATE_DISPLAY_FORMAT: date_format,
                SettingsKeys.TIME_DISPLAY_FORMAT: time_format,
            }
        )

    def set_student_profile(self, name: str, group: str) -> None:
        """Имя и группа (FIRST-15); отказ допустим — пустые строки."""
        self.set_many({SettingsKeys.STUDENT_NAME: name, SettingsKeys.GROUP_TITLE: group})

    def set_strelka_start(self, anchor_raw: str, initial_count: int | str) -> SettingsChange:
        """Параметры начала учёта «Стрелки» (FARE-12, FIRST-14)."""
        return self.set_many(
            {
                SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE: anchor_raw,
                SettingsKeys.STRELKA_INITIAL_RIDE_COUNT: str(initial_count),
            }
        )

    # ------------------------------------------------- удобные «виды»
    def display_format(self) -> str:
        return self.get_str(SettingsKeys.DATE_DISPLAY_FORMAT) or dt.DEFAULT_DISPLAY_FORMAT

    def time_format(self) -> str:
        return self.get_str(SettingsKeys.TIME_DISPLAY_FORMAT) or dt.DEFAULT_TIME_FORMAT

    def student_name(self) -> str:
        """Имя для профиля; пусто → «Не указано» (UI-04, FIRST-15)."""
        return self.get_str(SettingsKeys.STUDENT_NAME)

    def group_title(self) -> str:
        return self.get_str(SettingsKeys.GROUP_TITLE)

    def profile_caption(self) -> tuple[str, str]:
        """Пара подписей профиля с подстановкой «Не указано»."""
        name = self.student_name().strip() or "Не указано"
        group = self.group_title().strip() or "Не указано"
        return name, group

    def strelka_period_days(self) -> int:
        return self.get_int(SettingsKeys.STRELKA_PERIOD_DAYS)

    def strelka_first_limit(self) -> int:
        return self.get_int(SettingsKeys.STRELKA_FIRST_LIMIT)

    def strelka_initial_ride_count(self) -> int:
        return self.get_int(SettingsKeys.STRELKA_INITIAL_RIDE_COUNT)

    def strelka_period_anchor_date(self) -> date | None:
        return self.get_date(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE)

    def strelka_low_balance_warn(self) -> int:
        return self.get_int(SettingsKeys.STRELKA_LOW_BALANCE_WARN)

    def default_bus_payment_method(self) -> str:
        return self.get_str(SettingsKeys.DEFAULT_BUS_PAYMENT_METHOD) or "strelka"

    def is_strelka_counter_approximate(self) -> bool:
        """«Счётчик приближённый»: отказ от FIRST-14 (``cnt0 = 0`` и якорь пуст)."""
        return (
            self.strelka_initial_ride_count() == 0
            and self.raw(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE) == ""
            and not self.has_any_strelka_ride()
        )

    def has_any_strelka_ride(self) -> bool:
        row = self.db.fetchone(
            "SELECT 1 FROM transport_rides WHERE payment_method = 'strelka' LIMIT 1"
        )
        return row is not None

    def section_specs(self) -> dict[str, list[SettingSpec]]:
        """Разделы экрана настроек с настройками (SET-01…SET-07)."""
        return {section: self.visible_for(section) for section in UiSection.ORDER if section}


def settings_for(db: Database, registry: SettingsRegistry | None = None) -> SettingsService:
    return SettingsService(db, registry)


__all__ = ["SettingsService", "SettingsChange", "settings_for"]
