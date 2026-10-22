"""Слой 1: настройки и реестр §30 (ACC-M-15, 71…73, 86; DATA-21, SET-01…SET-08).

Реестр — единственный источник значений (SET-08): экран настроек строится из
него, поэтому проверяется и состав ключей, и валидация значений.
"""

from __future__ import annotations

from datetime import date

import pytest

from student_planner.core.errors import SettingsError
from student_planner.core.seeding import Seeder
from student_planner.core.settings_registry import (
    RECALC_TRIGGER_KEYS,
    SettingType,
    SettingsKeys,
    UiSection,
    default_registry,
)
from student_planner.core.settings_service import SettingsService


# ---------------------------------------------------------------------------
# SET-08 — состав реестра и обязательные ключи стартового набора.
# ---------------------------------------------------------------------------
def test_settings_registry_has_all_required_keys() -> None:
    registry = default_registry()
    required = {
        SettingsKeys.SCHEMA_VERSION,
        SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE,
        SettingsKeys.STRELKA_INITIAL_RIDE_COUNT,
        SettingsKeys.STRELKA_PERIOD_DAYS,
        SettingsKeys.STRELKA_FIRST_LIMIT,
        SettingsKeys.DEFAULT_BUS_PAYMENT_METHOD,
        SettingsKeys.STRELKA_LOW_BALANCE_WARN,
        SettingsKeys.DATE_DISPLAY_FORMAT,
        SettingsKeys.TIME_DISPLAY_FORMAT,
        SettingsKeys.STUDENT_NAME,
        SettingsKeys.GROUP_TITLE,
        SettingsKeys.COLLEGE_NAME,
        SettingsKeys.HOME_POINT_NAME,
    }
    assert required <= set(registry.keys()), "Все ключи §30 должны быть в реестре"


def test_settings_defaults_match_appendix_a() -> None:
    """Значения стартового набора Прил. А.0."""
    defaults = default_registry().defaults()
    assert defaults[SettingsKeys.SCHEMA_VERSION] == "1"
    assert defaults[SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE] == ""
    assert defaults[SettingsKeys.STRELKA_INITIAL_RIDE_COUNT] == "0"
    assert defaults[SettingsKeys.STRELKA_PERIOD_DAYS] == "30"
    assert defaults[SettingsKeys.STRELKA_FIRST_LIMIT] == "35"
    assert defaults[SettingsKeys.DEFAULT_BUS_PAYMENT_METHOD] == "strelka"
    assert defaults[SettingsKeys.STRELKA_LOW_BALANCE_WARN] == "2"
    assert defaults[SettingsKeys.DATE_DISPLAY_FORMAT] == "DD.MM.YYYY"
    assert defaults[SettingsKeys.TIME_DISPLAY_FORMAT] == "HH:MM"
    assert defaults[SettingsKeys.HOME_POINT_NAME] == "пос. Авсюнино"


def test_removed_strelka_period_start_key_absent() -> None:
    """v1.6: ключ ``strelka_period_start`` удалён — период скользящий (ALG-02)."""
    assert not default_registry().has("strelka_period_start")


def test_visible_sections_non_empty() -> None:
    """SET-08: настройка с флагом «видима в UI» не может отсутствовать на экране."""
    registry = default_registry()
    sections = registry.sections()
    assert sections, "Должен быть хотя бы один раздел настроек"
    seen: set[str] = set()
    for section in sections:
        visible = registry.visible_in(section)
        assert visible, f"Раздел «{section}» объявлен, но пуст"
        for spec in visible:
            assert spec.key not in seen, f"Ключ {spec.key} показан дважды"
            seen.add(spec.key)
    # Ключи без раздела — только служебные (schema_version).
    hidden = [spec for spec in registry.all() if spec.section == UiSection.NONE]
    assert {spec.key for spec in hidden} <= {SettingsKeys.SCHEMA_VERSION}


# ---------------------------------------------------------------------------
# §30 правила — представление «не задано»: пустая строка; 'NULL' и '0000-00-00'
# отклоняются валидацией (DATA-21, FARE-12).
# ---------------------------------------------------------------------------
def test_settings_empty_string_means_not_set(db) -> None:
    service = SettingsService(db)
    service.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "")
    assert service.raw(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE) == ""
    assert service.strelka_period_anchor_date() is None


@pytest.mark.parametrize("bad", ["NULL", "0000-00-00", "None", "null"])
def test_settings_invalid_absent_representations_rejected(db, bad: str) -> None:
    service = SettingsService(db)
    with pytest.raises(SettingsError):
        service.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, bad)


def test_not_set_is_not_null_in_db(db) -> None:
    """``settings.value`` объявлен NOT NULL: отсутствие значения — пустая строка."""
    service = SettingsService(db)
    service.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "")
    row = db.fetchone(
        "SELECT value FROM settings WHERE key = ?", (SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE,)
    )
    assert row is not None
    assert row["value"] == "", "Отсутствие значения хранится пустой строкой, не NULL"


# ---------------------------------------------------------------------------
# DATA-21 — валидация параметров начала учёта.
# ---------------------------------------------------------------------------
def test_data_21_initial_ride_count_negative_rejected(db) -> None:
    service = SettingsService(db)
    with pytest.raises(SettingsError):
        service.set(SettingsKeys.STRELKA_INITIAL_RIDE_COUNT, "-1")


def test_data_21_initial_ride_count_zero_allowed(db) -> None:
    service = SettingsService(db)
    assert service.set(SettingsKeys.STRELKA_INITIAL_RIDE_COUNT, "0") == "0"


def test_data_21_anchor_in_future_rejected(db) -> None:
    """Якорь позже сегодняшней даты — отказ сохранения (DATA-21)."""
    service = SettingsService(db)
    with pytest.raises(SettingsError) as excinfo:
        service.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "2099-01-01")
    assert "позже" in str(excinfo.value)


def test_data_21_anchor_in_past_allowed(db) -> None:
    service = SettingsService(db)
    assert service.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "2026-09-01") == "2026-09-01"
    assert service.strelka_period_anchor_date() == date(2026, 9, 1)


def test_data_21_anchor_before_earliest_ride_is_normal(db, base_tariffs, ride_repo_factory) -> None:
    """Якорь раньше самой ранней поездки — штатный случай, не ошибка (ALG-02 шаг 2)."""
    rides = ride_repo_factory(db)
    from conftest import add_strelka_ride

    add_strelka_ride(rides, date(2026, 9, 7))
    service = SettingsService(db)
    # Якорь на месяц раньше первой поездки сохраняется без ошибки.
    assert service.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "2026-08-01") == "2026-08-01"


def test_data_21_anchor_invalid_date_rejected(db) -> None:
    service = SettingsService(db)
    with pytest.raises(SettingsError):
        service.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "31.12.2026")


def test_data_21_anchor_february_30_rejected(db) -> None:
    service = SettingsService(db)
    with pytest.raises(SettingsError):
        service.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "2026-02-30")


# ---------------------------------------------------------------------------
# ACC-M-86 / CALC-04 — изменение ключей FARE-12 требует пересчёта.
# ---------------------------------------------------------------------------
def test_recalc_trigger_keys_declared() -> None:
    assert RECALC_TRIGGER_KEYS == {
        SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE,
        SettingsKeys.STRELKA_INITIAL_RIDE_COUNT,
    }


def test_changing_anchor_requests_recalculation(db) -> None:
    service = SettingsService(db)
    change = service.set_many({SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE: "2026-09-01"})
    assert change.needs_recalc is True, "Изменение якоря обязано запускать CALC-04"
    assert SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE in change.changed


def test_changing_initial_count_requests_recalculation(db) -> None:
    service = SettingsService(db)
    change = service.set_many({SettingsKeys.STRELKA_INITIAL_RIDE_COUNT: "5"})
    assert change.needs_recalc is True


def test_changing_cosmetic_setting_does_not_request_recalculation(db) -> None:
    service = SettingsService(db)
    change = service.set_many({SettingsKeys.STUDENT_NAME: "Иван"})
    assert change.needs_recalc is False


def test_unchanged_value_is_not_reported_as_change(db) -> None:
    service = SettingsService(db)
    service.set(SettingsKeys.STRELKA_INITIAL_RIDE_COUNT, "3")
    change = service.set_many({SettingsKeys.STRELKA_INITIAL_RIDE_COUNT: "3"})
    assert change.changed == {}, "Запись того же значения не является изменением"
    assert change.needs_recalc is False


# ---------------------------------------------------------------------------
# ACC-M-15 — перекрытие якоря/тарифа/периода отклоняется с сообщением.
# ---------------------------------------------------------------------------
def test_acc_m_15_overlapping_tariff_rejected(tariffs) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), effective_to=date(2026, 12, 31))
    with pytest.raises(Exception) as excinfo:
        tariffs.create("bus_base", "60.00", date(2026, 12, 1), effective_to=date(2027, 3, 1))
    assert "пересека" in str(excinfo.value).lower() or "FARE-02" in str(excinfo.value)


def test_acc_m_15_adjacent_tariffs_allowed(tariffs) -> None:
    """Смежные диапазоны не пересекаются: 30.11 — конец, 01.12 — начало."""
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), effective_to=date(2026, 11, 30))
    second = tariffs.create("bus_base", "60.00", date(2026, 12, 1), effective_to=date(2027, 3, 1))
    assert second.price == 60
    assert len(tariffs.of_kind("bus_base")) == 2


def test_acc_m_15_different_kinds_may_overlap(tariffs) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "25.00", date(2026, 9, 1))
    assert len(tariffs.all()) == 2


def test_acc_m_15_inactive_tariff_does_not_conflict(tariffs) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), is_active=False)
    active = tariffs.create("bus_base", "60.00", date(2026, 9, 1))
    assert active.is_active


def test_acc_m_15_duplicate_anchor_date_rejected(anchors) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    with pytest.raises(Exception) as excinfo:
        anchors.create(date(2026, 9, 7), date(2026, 9, 7), "upper")
    assert "уже существует" in str(excinfo.value)


def test_acc_m_15_period_end_before_start_rejected(periods) -> None:
    with pytest.raises(Exception):
        periods.create("vacation", "Каникулы", date(2026, 11, 10), date(2026, 11, 1))


# ---------------------------------------------------------------------------
# SET-05 — служебные ключи только для чтения.
# ---------------------------------------------------------------------------
def test_readonly_settings_cannot_be_changed(db) -> None:
    service = SettingsService(db)
    with pytest.raises(SettingsError):
        service.set(SettingsKeys.STRELKA_PERIOD_DAYS, "10")
    with pytest.raises(SettingsError):
        service.set(SettingsKeys.STRELKA_PERIOD_DAYS, "10")


def test_schema_version_readonly_but_consistent(db) -> None:
    service = SettingsService(db)
    assert service.get_int(SettingsKeys.SCHEMA_VERSION) == 1


# ---------------------------------------------------------------------------
# SET-02 — форматы отображения и профиль.
# ---------------------------------------------------------------------------
def test_display_formats_default(db) -> None:
    service = SettingsService(db)
    assert service.display_format() == "DD.MM.YYYY"
    assert service.time_format() == "HH:MM"


def test_student_profile_empty_shows_not_specified(db) -> None:
    """FIRST-15: пустые строки отображаются как «Не указано»."""
    service = SettingsService(db)
    assert service.profile_caption() == ("Не указано", "Не указано")
    service.set_student_profile("Иван Петров", "ИС-31")
    assert service.profile_caption() == ("Иван Петров", "ИС-31")


def test_setting_written_to_settings_table(db) -> None:
    service = SettingsService(db)
    service.set(SettingsKeys.STRELKA_LOW_BALANCE_WARN, "3")
    row = db.fetchone(
        "SELECT value FROM settings WHERE key = ?", (SettingsKeys.STRELKA_LOW_BALANCE_WARN,)
    )
    assert row is not None and row["value"] == "3"


def test_enum_setting_rejects_unknown_value(db) -> None:
    service = SettingsService(db)
    with pytest.raises(SettingsError):
        service.set(SettingsKeys.DEFAULT_BUS_PAYMENT_METHOD, "cash")


def test_all_settings_readable_after_seed(db) -> None:
    Seeder(db).seed_all()
    service = SettingsService(db)
    values = service.all()
    registry = default_registry()
    assert set(values) == set(registry.keys()), "Стартовый набор задаёт все ключи реестра"

    # Ключи, которые заполняет пользователь (Прил. А.0), остаются пустыми:
    # их спрашивает первый запуск (FIRST-15), а не стартовый набор.
    user_filled = {
        SettingsKeys.STUDENT_NAME,
        SettingsKeys.GROUP_TITLE,
        SettingsKeys.COLLEGE_NAME,
    }
    # Якорь «Стрелки» по умолчанию — пустая строка, то есть «не задано»:
    # период начнётся с первой поездки (FARE-12, ALG-02 шаг 1).
    intentionally_empty = {SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE}
    for spec in registry.all():
        if spec.key in user_filled:
            continue
        if spec.key in intentionally_empty:
            assert values[spec.key] == "", "Якорь по умолчанию — «не задано»"
            continue
        if spec.type == SettingType.PATH:
            assert values[spec.key], f"Путь «{spec.label}» должен быть задан шаблоном"
            continue
        assert values[spec.key] != "", f"Стартовый набор должен задать «{spec.label}»"

    for key in user_filled:
        assert values[key] == "", "Эти ключи вводятся пользователем, не стартовым набором"


def test_strelka_counter_approximate_flag(db, base_tariffs) -> None:
    """Бейдж «Счётчик приближённый»: отказ от FIRST-14 (cnt0 = 0, якорь пуст)."""
    service = SettingsService(db)
    assert service.is_strelka_counter_approximate() is True

    service.set_strelka_start("2026-09-01", 0)
    assert service.is_strelka_counter_approximate() is False
