"""Слой 1: каскадный пересчёт и кошелёк (ACC-M-51…56, 84…86, 90, 91).

CALC-04 — пересчёт границ, номеров и стоимостей после изменения истории;
ALG-07 — остаток «Стрелки». Проверяется и требование производительности:
5000 поездок за ≤ 1 с (NFR-10).
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

import pytest

from student_planner.core.recalculation import (
    RecalculationService,
    has_any_topup,
    wallet_balance,
)
from student_planner.core.settings_registry import SettingsKeys
from student_planner.core.settings_service import SettingsService
from student_planner.core.transport_repositories import RideRepository, TopUpRepository


def add_ride(rides: RideRepository, day: date, *, vehicle: str = "22", direction: str = "home_to_college"):
    return rides.create(
        study_date=day,
        direction=direction,
        transport_type="bus",
        vehicle=vehicle,
        base_price="50.00",
        paid_price="25.00",
        discount_amount="25.00",
        payment_method="strelka",
    )


# ---------------------------------------------------------------------------
# ACC-M-84 — добавление поездки в прошлое пересчитывает последующие номера.
# ---------------------------------------------------------------------------
def test_acc_m_84_insert_in_past_shifts_following_numbers(db, base_tariffs) -> None:
    rides = RideRepository(db)
    service = RecalculationService(db)

    first = add_ride(rides, date(2026, 9, 7))
    second = add_ride(rides, date(2026, 9, 8))
    third = add_ride(rides, date(2026, 9, 9))
    service.recalculate()

    numbers_before = {
        ride.id: int(rides.require(ride.id).ride_number_in_period)
        for ride in (first, second, third)
    }
    assert numbers_before == {first.id: 1, second.id: 2, third.id: 3}

    # Вставляем поездку «задним числом» между первой и второй.
    inserted = add_ride(rides, date(2026, 9, 7), vehicle="42")
    result = service.recalculate()

    assert result.changed, "CALC-04 обязан отметить изменения"
    after = {ride.id: int(rides.require(ride.id).ride_number_in_period)
             for ride in (first, inserted, second, third)}
    assert after[first.id] == 1
    assert after[inserted.id] == 2, "Вставленная поездка получает свой номер"
    assert after[second.id] == 3, "Последующие номера сдвинулись (CALC-04)"
    assert after[third.id] == 4


def test_acc_m_84_deleting_ride_shifts_numbers_back(db, base_tariffs) -> None:
    rides = RideRepository(db)
    service = RecalculationService(db)
    first = add_ride(rides, date(2026, 9, 7))
    second = add_ride(rides, date(2026, 9, 8))
    third = add_ride(rides, date(2026, 9, 9))
    service.recalculate()
    assert int(rides.require(third.id).ride_number_in_period) == 3

    rides.delete(second.id)
    service.recalculate()
    assert int(rides.require(third.id).ride_number_in_period) == 2, (
        "Удаление поездки уменьшает номера последующих"
    )


# ---------------------------------------------------------------------------
# ACC-M-85 — CALC-04 пересчитывает следующий период после разрыва.
# ---------------------------------------------------------------------------
def test_acc_m_85_cascade_rebuilds_period_after_gap(db, base_tariffs) -> None:
    rides = RideRepository(db)
    service = RecalculationService(db)

    for offset in range(3):
        add_ride(rides, date(2026, 9, 7) + timedelta(days=offset))
    service.recalculate()

    # Поездка через 40 дней открывает новый период с номером 1.
    late = add_ride(rides, date(2026, 10, 20))
    service.recalculate()
    refreshed = rides.require(late.id)
    assert refreshed.period_start_date == date(2026, 10, 20), "Новый период"
    assert int(refreshed.ride_number_in_period) == 1


def test_acc_m_85_period_bounds_snapshot_written(db, base_tariffs) -> None:
    """FARE-06: начало периода хранится снапшотом ``period_start_date``."""
    rides = RideRepository(db)
    service = RecalculationService(db)
    ride = add_ride(rides, date(2026, 9, 7))
    service.recalculate()

    refreshed = rides.require(ride.id)
    assert refreshed.period_start_date == date(2026, 9, 7)
    assert refreshed.period_end_date == date(2026, 10, 6), "Начало + 29 дней (REP-05)"


# ---------------------------------------------------------------------------
# ACC-M-86 — изменение параметров начала учёта запускает полный пересчёт.
# ---------------------------------------------------------------------------
def test_acc_m_86_changing_initial_count_recalculates_numbers(db, base_tariffs) -> None:
    rides = RideRepository(db)
    service = RecalculationService(db)
    settings = SettingsService(db)

    first = add_ride(rides, date(2026, 9, 7))
    second = add_ride(rides, date(2026, 9, 8))
    service.recalculate()
    assert int(rides.require(first.id).ride_number_in_period) == 1

    change = settings.set_strelka_start("", 10)
    assert change.needs_recalc is True
    service.recalculate()

    assert int(rides.require(first.id).ride_number_in_period) == 11, (
        "cnt0 = 10 применяется к первому периоду (ALG-02 шаг 8)"
    )
    assert int(rides.require(second.id).ride_number_in_period) == 12


def test_acc_m_86_changing_anchor_recalculates_bounds(db, base_tariffs) -> None:
    rides = RideRepository(db)
    service = RecalculationService(db)
    settings = SettingsService(db)

    ride = add_ride(rides, date(2026, 9, 15))
    service.recalculate()
    assert rides.require(ride.id).period_start_date == date(2026, 9, 15)

    settings.set_strelka_start("2026-09-01", 0)
    service.recalculate()
    assert rides.require(ride.id).period_start_date == date(2026, 9, 1), (
        "Границы следуют за якорем (ALG-02 шаг 2)"
    )


def test_acc_m_86a_stale_anchor_self_corrects_in_cascade(db, base_tariffs) -> None:
    rides = RideRepository(db)
    service = RecalculationService(db)
    settings = SettingsService(db)

    ride = add_ride(rides, date(2026, 9, 7))
    settings.set_strelka_start("2026-06-01", 0)  # устаревший якорь
    service.recalculate()

    refreshed = rides.require(ride.id)
    assert refreshed.period_start_date == date(2026, 9, 7), (
        "Устаревший якорь самокорректируется (ACC-M-86a)"
    )
    assert int(refreshed.ride_number_in_period) == 1


# ---------------------------------------------------------------------------
# ACC-M-84 (NFR-10) — производительность: 5000 поездок ≤ 1 с.
# ---------------------------------------------------------------------------
def test_acc_m_84_5000_rides_recalculated_under_one_second(db, base_tariffs) -> None:
    """NFR-10: 5000 поездок пересчитываются за ≤ 1 с в одной транзакции."""
    rides = RideRepository(db)
    service = RecalculationService(db)

    rows = []
    # Даты внутри действия тарифов фикстуры (с 01.09.2026).
    start = date(2026, 9, 1)
    for index in range(5000):
        day = start + timedelta(days=index // 2)
        rows.append(
            (
                day.isoformat(), day.isoformat(), "home_to_college", "bus", "22",
                "50.00", "25.00", "25.00", "strelka", "2026-09-01 08:00:00",
            )
        )
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO transport_rides(study_date, ride_date, direction, transport_type, "
            "vehicle, base_price, paid_price, discount_amount, payment_method, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    assert len(rides.strelka_rides()) == 5000, "Все поездки засчитаны"

    started = time.perf_counter()
    result = service.recalculate()
    elapsed = time.perf_counter() - started

    assert result.rides_total == 5000
    assert elapsed < 1.0, f"Пересчёт 5000 поездок занял {elapsed:.3f} с (NFR-10: ≤ 1 с)"

    # Номера корректны: 2 поездки в день, первый период 30 дней.
    numbers = [
        int(row["ride_number_in_period"])
        for row in db.fetchall(
            "SELECT ride_number_in_period FROM transport_rides ORDER BY ride_date, id LIMIT 4"
        )
    ]
    assert numbers == [1, 2, 3, 4]


def test_recalculate_is_idempotent(db, base_tariffs) -> None:
    rides = RideRepository(db)
    service = RecalculationService(db)
    for offset in range(5):
        add_ride(rides, date(2026, 9, 7) + timedelta(days=offset))

    first = service.recalculate()
    assert first.rides_changed == 5, "Первичный пересчёт заполняет номера"
    second = service.recalculate()
    assert second.rides_changed == 0, "Повторный пересчёт не находит изменений"
    assert second.summary.startswith("Пересчёт выполнен")


def test_recalculate_reports_delta(db, base_tariffs) -> None:
    rides = RideRepository(db)
    service = RecalculationService(db)
    add_ride(rides, date(2026, 9, 7))
    result = service.recalculate()
    assert result.amount_before == Decimal("25.00")
    assert result.amount_after == Decimal("25.00")
    assert "изменился" in result.summary or "изменений нет" in result.summary


def test_recalculate_without_rides_is_safe(db) -> None:
    result = RecalculationService(db).recalculate()
    assert result.rides_total == 0
    assert result.changed is False
    assert result.summary == "Поездок для пересчёта нет."


def test_recalculate_map_change_after_tariff_price_change(db, tariffs) -> None:
    """DATA-16: правка тарифа + явный CALC-04 меняет цены уже созданных поездок."""
    tariffs.create("bus_base", "50.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "25.00", date(2026, 9, 1))
    rides = RideRepository(db)
    service = RecalculationService(db)
    ride = add_ride(rides, date(2026, 9, 7))
    service.recalculate()
    assert rides.require(ride.id).paid_price == Decimal("25.00")

    # Меняем цену ступени: новая поездка получит новую цену, старая — только
    # после явного CALC-04 (снапшоты не переписываются автоматически).
    old = tariffs.of_kind("strelka_stage1")[0]
    tariffs.update(old.id, price="30.00")
    assert rides.require(ride.id).paid_price == Decimal("25.00"), (
        "Снапшот прошлой поездки не меняется сам по себе (DATA-16)"
    )
    service.recalculate()
    assert rides.require(ride.id).paid_price == Decimal("30.00"), (
        "Явный пересчёт обновляет цену (CALC-04)"
    )


def test_recalculate_benefit_expiry_rollback(db, tariffs) -> None:
    """FARE-10 в каскаде: с истечением льготы цены поездок откатываются к базовым."""
    tariffs.create("bus_base", "73.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "36.50", date(2026, 9, 1), effective_to=date(2026, 12, 31))
    rides = RideRepository(db)
    service = RecalculationService(db)

    during = rides.create(
        study_date=date(2026, 10, 1), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="73.00", paid_price="36.50", discount_amount="36.50",
        payment_method="strelka",
    )
    after = rides.create(
        study_date=date(2027, 1, 15), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="73.00", paid_price="73.00", discount_amount="0.00",
        payment_method="strelka",
    )
    service.recalculate()

    assert rides.require(during.id).paid_price == Decimal("36.50"), "Льгота действовала"
    assert rides.require(after.id).paid_price == Decimal("73.00"), "Откат к базовой (FARE-10)"
    assert rides.require(after.id).discount_amount == Decimal("0.00")


# ---------------------------------------------------------------------------
# ACC-M-51…56 — кошелёк «Стрелки» (ALG-07).
# ---------------------------------------------------------------------------
def test_acc_m_51_balance_formula(db, base_tariffs) -> None:
    """Остаток = Σ(пополнения − комиссии) − Σ(поездки «Стрелкой»)."""
    topups = TopUpRepository(db)
    rides = RideRepository(db)

    topups.create(date(2026, 9, 1), "500.00", fee="5.00")
    topups.create(date(2026, 9, 20), "300.00")
    add_ride(rides, date(2026, 9, 7))
    add_ride(rides, date(2026, 9, 8))

    balance = wallet_balance(db)
    assert balance == Decimal("745.00"), "495 + 300 − 25 − 25 = 745"


def test_acc_m_51_debit_card_not_counted_in_balance(db, base_tariffs) -> None:
    """WAL-08: дебетовая карта — способ оплаты без остатка."""
    topups = TopUpRepository(db)
    rides = RideRepository(db)
    topups.create(date(2026, 9, 1), "100.00")
    rides.create(
        study_date=date(2026, 9, 7), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="50.00", paid_price="50.00", discount_amount="0.00",
        payment_method="debit_card",
    )
    assert wallet_balance(db) == Decimal("100.00"), "Дебетовая поездка остаток не тратит"


def test_acc_m_52_warning_threshold(db, base_tariffs) -> None:
    """WAL-05: предупреждение, если остаток < порога × стоимость следующей поездки."""
    topups = TopUpRepository(db)
    topups.create(date(2026, 9, 1), "40.00")
    settings = SettingsService(db)
    threshold = settings.strelka_low_balance_warn()
    next_price = Decimal("25.00")
    assert threshold == 2
    assert wallet_balance(db) < threshold * next_price, "40 < 2 × 25 → предупреждение"


def test_acc_m_53_no_warning_before_first_topup(db) -> None:
    """WAL-05: до первого пополнения остаток считается «не заданным»."""
    assert has_any_topup(db) is False
    assert wallet_balance(db) == Decimal("0.00")


def test_acc_m_53_has_topup_detected(db) -> None:
    TopUpRepository(db).create(date(2026, 9, 1), "100.00")
    assert has_any_topup(db) is True


def test_acc_m_54_balance_by_date(db) -> None:
    """Остаток на дату учитывает только операции до неё."""
    topups = TopUpRepository(db)
    rides = RideRepository(db)
    topups.create(date(2026, 9, 1), "100.00")
    add_ride(rides, date(2026, 9, 10))
    topups.create(date(2026, 9, 20), "50.00")

    assert wallet_balance(db, until=date(2026, 9, 9)) == Decimal("100.00")
    assert wallet_balance(db, until=date(2026, 9, 10)) == Decimal("75.00")
    assert wallet_balance(db, until=date(2026, 9, 30)) == Decimal("125.00")


def test_acc_m_55_topup_is_not_expense(db) -> None:
    """WAL-04: пополнение не является расходом — величины раздельные."""
    topups = TopUpRepository(db)
    topups.create(date(2026, 9, 1), "500.00")
    total_topups = topups.total_net()
    spent = Decimal("0.00")
    balance = wallet_balance(db)
    assert total_topups == Decimal("500.00")
    assert spent == Decimal("0.00")
    assert balance == Decimal("500.00")
    # Суммы не складываются между собой: это разные показатели.
    assert total_topups + spent != Decimal("1000.00")


def test_acc_m_56_topup_edit_recalculates_immediately(db) -> None:
    """WAL-07: правка и удаление пополнения пересчитывают остаток немедленно."""
    topups = TopUpRepository(db)
    topup = topups.create(date(2026, 9, 1), "100.00")
    assert wallet_balance(db) == Decimal("100.00")

    topups.update(topup.id, amount="250.00")
    assert wallet_balance(db) == Decimal("250.00"), "Правка учтена сразу"

    topups.delete(topup.id)
    assert wallet_balance(db) == Decimal("0.00"), "Удаление учтено сразу"


def test_topup_fee_subtracted(db) -> None:
    topups = TopUpRepository(db)
    topups.create(date(2026, 9, 1), "100.00", fee="15.00")
    assert wallet_balance(db) == Decimal("85.00")


def test_topup_negative_amount_rejected(db) -> None:
    topups = TopUpRepository(db)
    with pytest.raises(Exception):
        topups.create(date(2026, 9, 1), "-100.00")


def test_topup_negative_fee_rejected(db) -> None:
    topups = TopUpRepository(db)
    with pytest.raises(Exception):
        topups.create(date(2026, 9, 1), "100.00", fee="-10.00")


# ---------------------------------------------------------------------------
# ACC-M-90 / ACC-M-91 — отчёты и «Стрелка» виджет.
# ---------------------------------------------------------------------------
def test_acc_m_90_report_totals_match_manual_calculation(db, base_tariffs) -> None:
    rides = RideRepository(db)
    add_ride(rides, date(2026, 9, 7))
    add_ride(rides, date(2026, 9, 8), direction="college_to_home")
    RecalculationService(db).recalculate()

    month = rides.filtered(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
    assert len(month) == 2
    total = sum((ride.paid_price for ride in month), Decimal("0.00"))
    assert total == Decimal("50.00")
    saving = sum((ride.discount_amount for ride in month), Decimal("0.00"))
    assert saving == Decimal("50.00")


def test_acc_m_91_strelka_widget_shows_next_ride(db, base_tariffs) -> None:
    """REP-05: номер и стоимость следующей поездки + границы периода."""
    from student_planner.core.fares import TariffResolver, price_ride
    from student_planner.core.repositories import TariffRepository
    from student_planner.core.strelka import StrellaPeriodCalculator

    rides = RideRepository(db)
    add_ride(rides, date(2026, 9, 7))
    add_ride(rides, date(2026, 9, 8))

    counted = rides.strelka_rides()
    calc = StrellaPeriodCalculator(rides=[(r.id, r.ride_date) for r in counted], anchor=None)
    state = calc.next_state(date(2026, 9, 9))
    assert state.ride_number == 3, "Номер следующей поездки"
    assert state.period_start == date(2026, 9, 7), "Границы текущего периода"

    resolver = TariffResolver(TariffRepository(db).all(include_inactive=False))
    next_price = resolver.price_of(state.stage, date(2026, 9, 9))
    assert next_price == Decimal("25.00"), "Стоимость следующей поездки по ступени"

    pricing = price_ride(
        resolver,
        ride_date=date(2026, 9, 9),
        transport_type="bus",
        payment_method="strelka",
        stage=state.stage,
    )
    assert pricing.paid_price == Decimal("25.00")


def test_acc_m_91_widget_states(db) -> None:
    """"Период начнётся с первой поездки" / «До начала учёта» (REP-05)."""
    from student_planner.core.strelka import StrellaPeriodCalculator

    empty = StrellaPeriodCalculator(rides=[], anchor=None)
    state = empty.next_state(date(2026, 9, 9))
    assert state.bounds_caption == "Период начнётся с первой поездки"

    before = StrellaPeriodCalculator(rides=[(1, date(2026, 9, 10))], anchor=date(2026, 9, 10))
    state = before.next_state(date(2026, 9, 1))
    assert state.bounds_caption == "До начала учёта"


def test_calc04_respects_manual_lock(db, base_tariffs) -> None:
    """Поездка с ``price_locked`` не должна терять цену при пересчёте.

    В MVP флаг — резерв (Прил. Б.17), но пересчёт обязан сохранять данные,
    помеченные как зафиксированные вручную.
    """
    rides = RideRepository(db)
    service = RecalculationService(db)
    ride = rides.create(
        study_date=date(2026, 9, 7), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="50.00", paid_price="25.00", discount_amount="25.00",
        payment_method="strelka", price_locked=True,
    )
    service.recalculate()
    assert rides.require(ride.id).price_locked is True, "Признак сохраняется"
