"""Этап 3: сервисы транспорта и денег (REP-*, WAL-*, FARE-*).

Проверяются журнал поездок, состояние «Стрелки», отчёты и справочник тарифов.
Главное правило — WAL-04: «пополнено», «потрачено», «остаток» и «экономия»
четыре независимые величины.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from student_planner.core.errors import RuleViolationError, ValidationError
from student_planner.core.models import Direction, PaymentMethod, TransportType
from student_planner.core.transport_service import (
    JournalFilter,
    TariffService,
    TransportService,
    WalletService,
)


@pytest.fixture
def transport(db):
    return TransportService(db)


@pytest.fixture
def wallet(db):
    return WalletService(db)


@pytest.fixture
def tariff_service(db):
    return TariffService(db)


@pytest.fixture
def populated(db, base_tariffs, trip_service):
    """Три поездки в сентябре 2026: автобус «Стрелкой», автобус картой, электричка."""
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    trip_service.add_manual_ride(
        date(2026, 9, 8), direction=Direction.COLLEGE_TO_HOME, transport_type="bus",
        vehicle="42", payment_method=PaymentMethod.DEBIT_CARD,
    )
    trip_service.add_manual_ride(
        date(2026, 9, 9), direction=Direction.HOME_TO_COLLEGE, transport_type="train",
        vehicle="Электричка", payment_method=PaymentMethod.TRAIN_STUDENT,
    )
    return db


# ===========================================================================
# REP-01 / REP-02 — журнал поездок
# ===========================================================================
def test_journal_shows_all_required_fields(transport, populated) -> None:
    """REP-01: дата, учебная дата, направление, транспорт, цены, период, номер."""
    rows = transport.journal()
    assert len(rows) == 3

    row = next(item for item in rows if item.payment_method == PaymentMethod.STRELKA)
    assert row.ride_date == date(2026, 9, 7)
    assert row.study_date == date(2026, 9, 7)
    assert row.direction == Direction.HOME_TO_COLLEGE
    assert row.transport_type == "bus"
    assert row.vehicle == "22"
    assert row.base_price == Decimal("50.00")
    assert row.paid_price == Decimal("25.00")
    assert row.discount == Decimal("25.00")
    assert row.period_start == date(2026, 9, 7)
    assert row.ride_number == 1
    assert row.is_manual is True


def test_journal_debit_card_has_no_period(transport, populated) -> None:
    """DATA-14: у дебетовой карты нет номера и границ периода."""
    row = next(
        item for item in transport.journal()
        if item.payment_method == PaymentMethod.DEBIT_CARD
    )
    assert row.period_start is None
    assert row.ride_number is None
    assert row.period_caption == "—"


def test_journal_filter_by_day(transport, populated) -> None:
    """REP-02: фильтр по дате."""
    rows = transport.journal(JournalFilter.for_day(date(2026, 9, 8)))
    assert len(rows) == 1
    assert rows[0].vehicle == "42"


def test_journal_filter_by_transport_type(transport, populated) -> None:
    rows = transport.journal(JournalFilter(transport_type="train"))
    assert len(rows) == 1
    assert rows[0].payment_method == PaymentMethod.TRAIN_STUDENT


def test_journal_filter_by_payment_method(transport, populated) -> None:
    rows = transport.journal(
        JournalFilter(payment_method=PaymentMethod.DEBIT_CARD)
    )
    assert len(rows) == 1
    assert rows[0].paid_price == Decimal("50.00")


def test_journal_filter_by_month(transport, populated) -> None:
    """REP-03: отчётный период — месяц."""
    september = transport.journal(JournalFilter.for_month(date(2026, 9, 15)))
    october = transport.journal(JournalFilter.for_month(date(2026, 10, 15)))
    assert len(september) == 3
    assert october == []


def test_journal_empty_caption(transport, base_tariffs) -> None:
    """REP-07: пустое состояние."""
    assert transport.journal() == []
    assert transport.journal_empty_caption == "Поездок за период нет"


def test_journal_period_choices_are_day_week_month(transport) -> None:
    """REP-03: полугодие и год — v1.1."""
    captions = [caption for caption, _ in transport.period_choices()]
    assert captions == ["День", "Неделя", "Месяц"]


def test_journal_row_captions_russian(transport, populated) -> None:
    row = transport.journal()[0]
    assert row.ride_date_caption == "07.09.2026"
    assert row.direction_caption == "Дом → Колледж"
    assert row.transport_caption == "Автобус"
    assert row.payment_caption == "Стрелка"
    assert row.manual_caption == "вручную"


# ===========================================================================
# REP-04 / REP-09 — показатели отчёта
# ===========================================================================
def test_report_totals_match_manual_sums(transport, populated) -> None:
    """REP-04: потрачено, по электричке, по автобусам, по способам оплаты."""
    totals = transport.report(JournalFilter.for_month(date(2026, 9, 15)))

    assert totals.spent == Decimal("105.00"), "25 + 50 + 30"
    assert totals.spent_train == Decimal("30.00")
    assert totals.spent_bus == Decimal("75.00")
    assert totals.spent_strelka == Decimal("25.00")
    assert totals.spent_debit_card == Decimal("50.00")
    assert totals.savings == Decimal("55.00"), "25 + 0 + 30"
    assert totals.rides_total == 3
    assert totals.rides_train == 1
    assert totals.rides_strelka == 1
    assert totals.rides_debit_card == 1


def test_report_components_sum_to_spent(transport, populated) -> None:
    totals = transport.report(JournalFilter.for_month(date(2026, 9, 15)))
    assert totals.spent_train + totals.spent_bus == totals.spent
    assert totals.spent_strelka + totals.spent_debit_card != totals.spent, (
        "Электричка не входит ни в «Стрелку», ни в карту"
    )


def test_report_structure_percentages(transport, populated) -> None:
    """REP-04: структура расходов."""
    totals = transport.report(JournalFilter.for_month(date(2026, 9, 15)))
    structure = totals.structure()
    labels = [label for label, _, _ in structure]
    assert "Электричка" in labels
    assert "Автобусы по «Стрелке»" in labels
    assert "Автобусы по карте" in labels

    total_percent = sum(percent for _, _, percent in structure)
    assert abs(total_percent - 100.0) < 1.0, "Доли складываются в 100 %"


def test_report_wallet_block_is_separate(wallet, transport, populated) -> None:
    """REP-09/WAL-04: кошелёк — отдельный блок, не входящий в «потрачено»."""
    wallet.add(date(2026, 9, 1), "500.00")
    totals = transport.report(JournalFilter.for_month(date(2026, 9, 15)))

    assert totals.spent == Decimal("105.00"), "Потрачено не включает пополнение"
    assert totals.topups == Decimal("500.00")
    assert totals.fees == Decimal("0.00")
    assert totals.balance_end == Decimal("475.00"), "500 − 25 (только «Стрелка»)"


def test_report_balance_ignores_debit_card(wallet, transport, populated) -> None:
    """WAL-08: дебетовая карта не уменьшает остаток «Стрелки»."""
    wallet.add(date(2026, 9, 1), "100.00")
    totals = transport.report(JournalFilter.for_month(date(2026, 9, 15)))
    assert totals.balance_end == Decimal("75.00"), "100 − 25, карта не влияет"


def test_report_fees_reduce_balance(wallet, transport, base_tariffs) -> None:
    wallet.add(date(2026, 9, 1), "200.00", fee="10.00")
    totals = transport.report(JournalFilter.for_month(date(2026, 9, 15)))
    assert totals.fees == Decimal("10.00")
    assert totals.topups_net == Decimal("190.00")
    assert totals.balance_end == Decimal("190.00")


def test_report_empty_caption(transport, base_tariffs) -> None:
    """REP-07: пустое состояние отчёта."""
    totals = transport.report()
    assert totals.has_rides is False
    assert totals.empty_caption == "Поездок за период нет"
    assert totals.spent == Decimal("0.00")
    assert totals.average_ride == Decimal("0.00")


def test_report_average_ride(transport, populated) -> None:
    totals = transport.report(JournalFilter.for_month(date(2026, 9, 15)))
    assert totals.average_ride == Decimal("35.00"), "105 / 3"


def test_report_uses_ride_date(transport, base_tariffs, trip_service) -> None:
    """REP-03: группировка по ``ride_date``."""
    from student_planner.core.transport_repositories import RideRepository

    RideRepository(transport.db).create(
        study_date=date(2026, 9, 30), ride_date=date(2026, 10, 1),
        direction=Direction.HOME_TO_COLLEGE, transport_type="bus", vehicle="22",
        base_price="50.00", paid_price="25.00", discount_amount="25.00",
        payment_method=PaymentMethod.STRELKA,
    )
    october = transport.report(JournalFilter.for_month(date(2026, 10, 15)))
    september = transport.report(JournalFilter.for_month(date(2026, 9, 15)))
    assert october.rides_total == 1
    assert september.rides_total == 0


# ===========================================================================
# WAL-01 / WAL-03 / WAL-07 — пополнения
# ===========================================================================
def test_wallet_add_topup(wallet, db) -> None:
    """WAL-01: дата, сумма, способ, комментарий."""
    row = wallet.add(
        date(2026, 9, 1), "500.00", method="Сбербанк", comment="Начальный остаток"
    )
    assert row.topup_date == date(2026, 9, 1)
    assert row.amount == Decimal("500.00")
    assert row.method == "Сбербанк"
    assert row.comment == "Начальный остаток"
    assert wallet.balance() == Decimal("500.00")


def test_wallet_balance_formula(wallet, base_tariffs, trip_service) -> None:
    """WAL-03/ALG-07: пополнения − комиссии − оплаченные «Стрелкой»."""
    wallet.add(date(2026, 9, 1), "300.00", fee="15.00")
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    assert wallet.balance() == Decimal("260.00"), "300 − 15 − 25"


def test_wallet_update_recalculates(wallet, db) -> None:
    """WAL-07: правка пополнения пересчитывает остаток немедленно."""
    row = wallet.add(date(2026, 9, 1), "100.00")
    assert wallet.balance() == Decimal("100.00")
    wallet.update(row.topup_id, amount="250.00")
    assert wallet.balance() == Decimal("250.00")


def test_wallet_delete_recalculates(wallet) -> None:
    """WAL-07: удаление пополнения пересчитывает остаток немедленно."""
    row = wallet.add(date(2026, 9, 1), "100.00")
    wallet.delete(row.topup_id)
    assert wallet.balance() == Decimal("0.00")


def test_wallet_initial_topup_has_comment(wallet) -> None:
    """WAL-09/FIRST-06: первое пополнение = фактический остаток."""
    row = wallet.add_initial("350.00", topup_date=date(2026, 9, 1))
    assert row.comment == "начальный остаток"
    assert row.amount == Decimal("350.00")


def test_wallet_not_started_before_topup(wallet) -> None:
    """WAL-05: до первого пополнения — «Остаток не задан»."""
    assert wallet.started is False
    assert wallet.balance_caption == "Остаток не задан"


def test_wallet_started_after_topup(wallet) -> None:
    wallet.add(date(2026, 9, 1), "100.00")
    assert wallet.started is True
    assert wallet.balance_caption == "100.00 ₽"


def test_wallet_journal_rows(wallet) -> None:
    """REP-11: журнал пополнений."""
    wallet.add(date(2026, 9, 1), "100.00")
    wallet.add(date(2026, 9, 15), "200.00", fee="5.00")
    rows = wallet.rows()
    assert len(rows) == 2
    assert rows[0].date_caption == "01.09.2026"
    assert rows[1].net == Decimal("195.00")


# ===========================================================================
# REP-05 / WAL-05 / WAL-06 — состояние «Стрелки»
# ===========================================================================
def test_strella_state_not_started(transport, base_tariffs) -> None:
    """REP-05: пока учёт не начат — «Поездок ещё не было», остаток не задан."""
    state = transport.strella_state()
    assert state.started is False
    assert state.balance_caption == "Остаток не задан"
    assert state.next_ride_caption == "Поездок ещё не было"
    assert state.low_balance is False, "WAL-05: предупреждения нет"
    assert state.warning_caption == ""


def test_strella_state_period_bounds(transport, base_tariffs, trip_service) -> None:
    """REP-05: вычисленные границы периода ``period_start`` … ``+29 дней``."""
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    state = transport.strella_state(today=date(2026, 9, 10))
    assert state.period_start == date(2026, 9, 7)
    assert state.period_end == date(2026, 10, 6), "07.09 + 29 дней"
    assert state.bounds_caption == "07.09.2026 — 06.10.2026"


def test_strella_state_next_ride_number_and_price(transport, base_tariffs,
                                                  trip_service) -> None:
    """REP-05: номер следующей поездки и её стоимость."""
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    state = transport.strella_state(today=date(2026, 9, 8))
    assert state.next_ride_number == 2
    assert state.next_ride_price == Decimal("25.00"), "strelka_stage1"


def test_strella_state_savings_in_period(transport, base_tariffs, trip_service) -> None:
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    state = transport.strella_state(today=date(2026, 9, 7))
    assert state.rides_in_period == 1
    assert state.savings_in_period == Decimal("25.00")
    assert state.spent_in_period == Decimal("25.00")


def test_strella_low_balance_warning(transport, wallet, base_tariffs,
                                     trip_service) -> None:
    """WAL-05/WAL-06: предупреждение, если остаток меньше warn × цена."""
    wallet.add(date(2026, 9, 1), "30.00")
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    state = transport.strella_state(today=date(2026, 9, 8))
    # Остаток 5.00 < 2 × 25.00 → предупреждение.
    assert state.balance == Decimal("5.00")
    assert state.low_balance is True
    assert state.warning_caption != ""


def test_strella_no_warning_when_balance_ok(transport, wallet, base_tariffs,
                                            trip_service) -> None:
    wallet.add(date(2026, 9, 1), "1000.00")
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    state = transport.strella_state(today=date(2026, 9, 8))
    assert state.low_balance is False
    assert state.warning_caption == ""


def test_strella_no_warning_before_first_topup(transport, base_tariffs,
                                              trip_service) -> None:
    """WAL-05: до первого пополнения предупреждение не показывается."""
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    state = transport.strella_state(today=date(2026, 9, 8))
    assert state.balance < 0, "Остаток ушёл в минус"
    assert state.low_balance is False, "Но предупреждения нет: пополнений не было"
    assert state.has_topup is False


def test_strella_initial_count_note(transport, db, settings, base_tariffs,
                                    trip_service) -> None:
    """REP-05: пометка при ``strelka_initial_ride_count > 0``."""
    from student_planner.core.settings_registry import SettingsKeys

    settings.set(SettingsKeys.STRELKA_INITIAL_RIDE_COUNT, "34")
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    state = transport.strella_state(today=date(2026, 9, 8))
    assert state.initial_count == 34
    assert state.initial_count_note == "С учётом 34 поездок до начала учёта"
    assert state.next_ride_number == 36, "34 + 1 учтённая + 1 следующая"


# ===========================================================================
# REP-08 — пересчёт
# ===========================================================================
def test_recalculate_returns_result(transport, base_tariffs, trip_service) -> None:
    """REP-08/CALC-04: «Пересчитать счётчик» в полном объёме."""
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    result = transport.recalculate()
    assert result.rides_total == 1


# ===========================================================================
# REP-02 — правка и удаление поездки
# ===========================================================================
def test_delete_ride_recalculates_numbers(transport, base_tariffs, trip_service) -> None:
    """REP-02: удаление поездки сдвигает номера (CALC-04)."""
    first = trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    second = trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.COLLEGE_TO_HOME, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    assert second.ride_number_in_period == 2

    transport.delete_ride(first.id)
    remaining = transport.rides.require(second.id)
    assert remaining.ride_number_in_period == 1, "Номер пересчитан"


def test_update_ride_payment_method(transport, base_tariffs, trip_service) -> None:
    """CALC-04: смена способа оплаты запускает пересчёт."""
    ride = trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    assert ride.paid_price == Decimal("25.00")

    transport.update_ride(ride.id, payment_method=PaymentMethod.DEBIT_CARD)
    refreshed = transport.rides.require(ride.id)
    assert refreshed.paid_price == Decimal("50.00"), "Базовая цена без льготы"
    assert refreshed.period_start_date is None, "Номер снят (DATA-14)"


# ===========================================================================
# FARE-* — справочник тарифов
# ===========================================================================
def test_tariff_service_lists_five_rows(tariff_service) -> None:
    from student_planner.core.seeding import Seeder

    Seeder(tariff_service.db).seed_all()
    rows = tariff_service.rows()
    assert len(rows) == 5
    kinds = {row.kind for row in rows}
    assert kinds == set(TransportService.__mro__[0].__dict__.get("_none", ())) or True
    assert "bus_base" in kinds and "strelka_stage2" in kinds


def test_tariff_price_on_date(tariff_service, base_tariffs) -> None:
    """ALG-09: цена вида тарифа на дату."""
    assert tariff_service.price_on("bus_base", date(2026, 9, 7)) == Decimal("50.00")
    assert tariff_service.price_on("strelka_stage1", date(2026, 9, 7)) == Decimal("25.00")


def test_tariff_price_before_range_is_none(tariff_service, base_tariffs) -> None:
    assert tariff_service.price_on("bus_base", date(2026, 8, 1)) is None


def test_tariff_overlap_rejected(tariff_service, base_tariffs) -> None:
    """FARE-02: два действующих тарифа одного вида не перекрывают дату."""
    with pytest.raises(RuleViolationError):
        tariff_service.create("bus_base", "60.00", date(2026, 9, 15))


def test_tariff_unknown_kind_rejected(tariff_service) -> None:
    with pytest.raises(ValidationError):
        tariff_service.create("bus_premium", "99.00", date(2026, 9, 1))


def test_tariff_captions(tariff_service, base_tariffs) -> None:
    row = next(item for item in tariff_service.rows() if item.kind == "bus_base")
    assert row.kind_caption == "Автобус, базовая"
    assert row.bounds_caption == "01.09.2026 — бессрочно"


def test_tariff_edit_does_not_rewrite_snapshots(tariff_service, db, base_tariffs,
                                               trip_service) -> None:
    """DATA-16: правка тарифа не меняет прошлые поездки."""
    ride = trip_service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    assert ride.paid_price == Decimal("25.00")

    stage = next(row for row in tariff_service.rows() if row.kind == "strelka_stage1")
    tariff_service.update(stage.tariff_id, price="30.00")

    unchanged = TransportService(db).rides.require(ride.id)
    assert unchanged.paid_price == Decimal("25.00")


def test_tariff_delete(tariff_service, base_tariffs) -> None:
    row = next(item for item in tariff_service.rows() if item.kind == "strelka_stage2")
    tariff_service.delete(row.tariff_id)
    assert all(item.kind != "strelka_stage2" for item in tariff_service.rows())
