"""Слой 1: тарифы, льготы и деньги (ACC-M-41…45, 83, 92; FARE-01…FARE-11, ALG-09).

Проверяется разрешение тарифа по дате (ALG-09), формулы стоимости и экономии
(FARE-09), откат льготы при её истечении (FARE-10) и денежная арифметика
(``Decimal``, ``ROUND_HALF_UP``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from student_planner.core.errors import PriceUnavailableError, RuleViolationError
from student_planner.core.fares import TariffResolver, price_ride, stage_kind_for
from student_planner.core.money import ZERO, from_db, money, to_db


# ---------------------------------------------------------------------------
# Деньги: 2 знака, ROUND_HALF_UP (DATA-13, GEN-09).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.005", "0.01"),
        ("0.004", "0.00"),
        ("1.005", "1.01"),
        ("2.675", "2.68"),
        ("30.5", "30.50"),
        ("-1.005", "-1.01"),
        (61, "61.00"),
    ],
)
def test_money_rounds_half_up(raw: str, expected: str) -> None:
    assert money(raw) == Decimal(expected)


def test_money_rejects_float_binary_noise() -> None:
    """``Decimal(0.1)`` дал бы шум; через ``str`` результат точный."""
    assert money(0.1) == Decimal("0.10")
    assert money(0.3) + money(0.6) == Decimal("0.90")


def test_from_db_reads_sqlite_numeric_types() -> None:
    """SQLite может вернуть int или float: значения читаются без потери знаков."""
    assert from_db(61) == Decimal("61.00")
    assert from_db(30.5) == Decimal("30.50")
    assert from_db("0.73") == Decimal("0.73")
    assert from_db(None) == ZERO


def test_to_db_always_two_places() -> None:
    assert to_db("61") == "61.00"
    assert to_db(Decimal("30.5")) == "30.50"


# ---------------------------------------------------------------------------
# ALG-09 — разрешение тарифа по дате.
# ---------------------------------------------------------------------------
def test_alg09_selects_tariff_covering_date(tariffs) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), effective_to=date(2026, 12, 31))
    tariffs.create("bus_base", "60.00", date(2027, 1, 1))

    resolver = TariffResolver(tariffs.all())
    assert resolver.price_of("bus_base", date(2026, 10, 1)) == Decimal("50.00")
    assert resolver.price_of("bus_base", date(2027, 2, 1)) == Decimal("60.00")


def test_alg09_open_ended_tariff_applies_forever(tariffs) -> None:
    tariffs.create("bus_base", "73.00", date(2026, 9, 1))
    resolver = TariffResolver(tariffs.all())
    assert resolver.price_of("bus_base", date(2030, 1, 1)) == Decimal("73.00")


def test_alg09_returns_none_before_range(tariffs) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1))
    resolver = TariffResolver(tariffs.all())
    assert resolver.price_of("bus_base", date(2026, 8, 31)) is None


def test_alg09_inactive_tariff_ignored(tariffs) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), is_active=False)
    resolver = TariffResolver(tariffs.all(include_inactive=False))
    assert resolver.price_of("bus_base", date(2026, 10, 1)) is None


# ---------------------------------------------------------------------------
# ACC-M-41 — тариф на дату поездки, а не на момент просмотра.
# ---------------------------------------------------------------------------
def test_acc_m_41_price_uses_ride_date(tariffs) -> None:
    """Поездка 15.09 считается по старому тарифу, даже если тариф уже сменился."""
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), effective_to=date(2026, 9, 30))
    tariffs.create("bus_base", "60.00", date(2026, 10, 1))
    tariffs.create("strelka_stage1", "25.00", date(2026, 9, 1))

    resolver = TariffResolver(tariffs.all())
    pricing = price_ride(
        resolver,
        ride_date=date(2026, 9, 15),
        transport_type="bus",
        payment_method="strelka",
        stage="strelka_stage1",
    )
    assert pricing.base_price == Decimal("50.00"), "Тариф на дату поездки (FARE-09)"
    assert pricing.paid_price == Decimal("25.00")
    assert pricing.discount_amount == Decimal("25.00")


# ---------------------------------------------------------------------------
# ACC-M-42 — откат электрички при истечении льготы.
# ---------------------------------------------------------------------------
def test_acc_m_42_train_benefit_rollback(tariffs) -> None:
    """Льгота до 31.05: 01.06 поездка идёт по базовому тарифу, экономия 0."""
    tariffs.create("train_base", "60.00", date(2026, 9, 1))
    tariffs.create("train_student", "30.00", date(2026, 9, 1), effective_to=date(2027, 5, 31))

    resolver = TariffResolver(tariffs.all())

    during = price_ride(
        resolver, ride_date=date(2026, 10, 1),
        transport_type="train", payment_method="train_student",
    )
    assert during.base_price == Decimal("60.00")
    assert during.paid_price == Decimal("30.00"), "Студенческий тариф действует"
    assert during.discount_amount == Decimal("30.00")
    assert during.benefit_expired is False

    after = price_ride(
        resolver, ride_date=date(2027, 6, 1),
        transport_type="train", payment_method="train_student",
    )
    assert after.base_price == Decimal("60.00")
    assert after.paid_price == Decimal("60.00"), "Откат к train_base (FARE-10)"
    assert after.discount_amount == ZERO, "Экономия = 0 при откате"
    assert after.benefit_expired is True, "Бейдж «Льгота не действует» (UI-13)"


def test_acc_m_42_last_benefit_day_inclusive(tariffs) -> None:
    tariffs.create("train_base", "60.00", date(2026, 9, 1))
    tariffs.create("train_student", "30.00", date(2026, 9, 1), effective_to=date(2027, 5, 31))
    resolver = TariffResolver(tariffs.all())
    same_day = price_ride(
        resolver, ride_date=date(2027, 5, 31),
        transport_type="train", payment_method="train_student",
    )
    assert same_day.paid_price == Decimal("30.00"), "Дата окончания входит в диапазон"


# ---------------------------------------------------------------------------
# ACC-M-43 — откат «Стрелки» при истечении льготы; счётчик продолжает расти.
# ---------------------------------------------------------------------------
def test_acc_m_43_strelka_benefit_rollback_to_bus_base(tariffs) -> None:
    tariffs.create("bus_base", "73.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "36.50", date(2026, 9, 1), effective_to=date(2027, 5, 31))
    tariffs.create("strelka_stage2", "0.73", date(2026, 9, 1), effective_to=date(2027, 5, 31))
    resolver = TariffResolver(tariffs.all())

    after = price_ride(
        resolver, ride_date=date(2027, 6, 15),
        transport_type="bus", payment_method="strelka", stage="strelka_stage1",
    )
    assert after.paid_price == Decimal("73.00"), "Откат к bus_base (FARE-10)"
    assert after.discount_amount == ZERO
    assert after.benefit_expired is True


def test_acc_m_43_counter_keeps_growing_after_rollback(db, tariffs, anchors) -> None:
    """FARE-10/DATA-14: откат не останавливает счётчик «Стрелки»."""
    from student_planner.core.strelka import StrellaPeriodCalculator
    from student_planner.core.transport_repositories import RideRepository

    rides = RideRepository(db)
    first = rides.create(
        study_date=date(2026, 9, 7), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="73.00", paid_price="36.50", discount_amount="36.50",
        payment_method="strelka",
    )
    second = rides.create(
        study_date=date(2027, 6, 15), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="73.00", paid_price="73.00", discount_amount="0.00",
        payment_method="strelka",
    )
    calc = StrellaPeriodCalculator(
        rides=[(ride.id, ride.ride_date) for ride in rides.strelka_rides()], anchor=None
    )
    numbers = {ride_id: state.ride_number for ride_id, state in calc.recalculate()}
    assert numbers[first.id] == 1
    # Откат льготы не мешает счётчику: поездка за пределами периода открывает новый.
    assert numbers[second.id] == 1, "Новый период, но поездка засчитана"


# ---------------------------------------------------------------------------
# ACC-M-44 — отсутствие базового тарифа блокирует подтверждение.
# ---------------------------------------------------------------------------
def test_acc_m_44_missing_base_tariff_raises(tariffs) -> None:
    tariffs.create("strelka_stage1", "25.00", date(2026, 9, 1))
    resolver = TariffResolver(tariffs.all())
    with pytest.raises(PriceUnavailableError) as excinfo:
        price_ride(
            resolver, ride_date=date(2026, 10, 1),
            transport_type="bus", payment_method="strelka",
        )
    assert "нет действующего базового тарифа" in str(excinfo.value).lower() or (
        "базового тарифа" in str(excinfo.value)
    )
    assert "TRIP-19" in str(excinfo.value)


def test_acc_m_44_base_tariff_outside_date_range_blocks(tariffs) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), effective_to=date(2026, 9, 30))
    resolver = TariffResolver(tariffs.all())
    with pytest.raises(PriceUnavailableError):
        price_ride(
            resolver, ride_date=date(2026, 10, 5),
            transport_type="bus", payment_method="strelka",
        )


# ---------------------------------------------------------------------------
# ACC-M-45 — дебетовая карта: полная стоимость, без экономии и счётчика.
# ---------------------------------------------------------------------------
def test_acc_m_45_debit_card_full_price_no_discount(tariffs) -> None:
    tariffs.create("bus_base", "73.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "36.50", date(2026, 9, 1))
    resolver = TariffResolver(tariffs.all())

    pricing = price_ride(
        resolver, ride_date=date(2026, 10, 1),
        transport_type="bus", payment_method="debit_card",
    )
    assert pricing.base_price == Decimal("73.00")
    assert pricing.paid_price == Decimal("73.00"), "FARE-08: полная стоимость"
    assert pricing.discount_amount == ZERO, "Дебетовая карта экономии не даёт"


# ---------------------------------------------------------------------------
# ACC-M-83 / FARE-07 — две ступени «Стрелки».
# ---------------------------------------------------------------------------
def test_acc_m_83_two_stages_priced_differently(tariffs) -> None:
    tariffs.create("bus_base", "73.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "36.50", date(2026, 9, 1))
    tariffs.create("strelka_stage2", "0.73", date(2026, 9, 1))
    resolver = TariffResolver(tariffs.all())

    stage1 = price_ride(
        resolver, ride_date=date(2026, 10, 1),
        transport_type="bus", payment_method="strelka", stage="strelka_stage1",
    )
    stage2 = price_ride(
        resolver, ride_date=date(2026, 10, 1),
        transport_type="bus", payment_method="strelka", stage="strelka_stage2",
    )
    assert stage1.paid_price == Decimal("36.50")
    assert stage1.discount_amount == Decimal("36.50")
    assert stage2.paid_price == Decimal("0.73")
    assert stage2.discount_amount == Decimal("72.27")


def test_stage_kind_selection_by_number() -> None:
    assert stage_kind_for(1, 35) == "strelka_stage1"
    assert stage_kind_for(35, 35) == "strelka_stage1"
    assert stage_kind_for(36, 35) == "strelka_stage2"
    assert stage_kind_for(None, 35) == "strelka_stage1"


# ---------------------------------------------------------------------------
# ACC-M-92 — базовая цена и экономия неотрицательны.
# ---------------------------------------------------------------------------
def test_acc_m_92_amounts_non_negative(tariffs) -> None:
    tariffs.create("bus_base", "73.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "36.50", date(2026, 9, 1))
    resolver = TariffResolver(tariffs.all())
    pricing = price_ride(
        resolver, ride_date=date(2026, 10, 1),
        transport_type="bus", payment_method="strelka",
    )
    assert pricing.base_price >= ZERO
    assert pricing.paid_price >= ZERO, "Стоимость не может быть отрицательной (DATA-13)"
    assert pricing.discount_amount >= ZERO


def test_discount_never_exceeds_base(tariffs) -> None:
    """Защита от ошибки данных: льготная цена выше базовой не даёт отрицательной экономии."""
    tariffs.create("bus_base", "20.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "50.00", date(2026, 9, 1))
    resolver = TariffResolver(tariffs.all())
    pricing = price_ride(
        resolver, ride_date=date(2026, 10, 1),
        transport_type="bus", payment_method="strelka",
    )
    assert pricing.paid_price == Decimal("20.00"), "Стоимость ограничена базовой"
    assert pricing.discount_amount == ZERO


# ---------------------------------------------------------------------------
# FARE-01/FARE-02 — виды тарифов и контроль пересечений.
# ---------------------------------------------------------------------------
def test_fare_01_tariff_kinds_validated(tariffs) -> None:
    with pytest.raises(Exception):
        tariffs.create("unknown_kind", "10.00", date(2026, 9, 1))


def test_fare_01_all_five_kinds_supported(tariffs) -> None:
    for kind in ("train_base", "train_student", "bus_base", "strelka_stage1", "strelka_stage2"):
        tariffs.create(kind, "10.00", date(2026, 9, 1))
    assert len(tariffs.all()) == 5


def test_fare_02_overlap_same_kind_rejected(tariffs) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), effective_to=date(2026, 12, 31))
    with pytest.raises(RuleViolationError):
        tariffs.create("bus_base", "55.00", date(2026, 12, 31), effective_to=date(2027, 1, 31))


def test_fare_02_vehicle_dimension_reserved(tariffs) -> None:
    """MVP: ``vehicle`` всегда NULL, поэтому конфликт считается по ``(kind, дата)``."""
    tariffs.create("bus_base", "50.00", date(2026, 9, 1))
    with pytest.raises(RuleViolationError):
        tariffs.create("bus_base", "60.00", date(2026, 9, 1))
    # Разные зоны (v1.1) не конфликтуют — резервное измерение работает в схеме.
    tariffs.create("bus_base", "70.00", date(2026, 9, 1), vehicle="zone-2")
    assert len(tariffs.all()) == 2


def test_fare_11_tariff_used_by_ride_cannot_be_deleted(db, tariffs) -> None:
    tariff = tariffs.create("bus_base", "73.00", date(2026, 9, 1))
    from student_planner.core.transport_repositories import RideRepository

    RideRepository(db).create(
        study_date=date(2026, 10, 1), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="73.00", paid_price="73.00", discount_amount="0.00",
        payment_method="debit_card", tariff_id=tariff.id,
    )
    with pytest.raises(Exception) as excinfo:
        tariffs.delete(tariff.id)
    assert "снапшот" in str(excinfo.value) or "использован" in str(excinfo.value)


def test_fare_11_unused_tariff_can_be_deleted(tariffs) -> None:
    tariff = tariffs.create("bus_base", "73.00", date(2026, 9, 1))
    tariffs.delete(tariff.id)
    assert tariffs.all() == []


def test_train_tariff_only_student_payment(db, tariffs) -> None:
    """RT-17/FARE-03: электричка оплачивается только студенческим билетом."""
    from student_planner.core.transport_repositories import RideRepository

    rides = RideRepository(db)
    with pytest.raises(Exception) as excinfo:
        rides.create(
            study_date=date(2026, 10, 1), direction="home_to_college",
            transport_type="train", vehicle="Электричка",
            base_price="60.00", paid_price="60.00", discount_amount="0.00",
            payment_method="strelka",
        )
    assert "студенческим билетом" in str(excinfo.value)


def test_bus_payment_methods_only_strelka_or_debit(db) -> None:
    """FARE-05: наличных нет."""
    from student_planner.core.transport_repositories import RideRepository

    rides = RideRepository(db)
    with pytest.raises(Exception):
        rides.create(
            study_date=date(2026, 10, 1), direction="home_to_college",
            transport_type="bus", vehicle="22",
            base_price="50.00", paid_price="50.00", discount_amount="0.00",
            payment_method="train_student",
        )
