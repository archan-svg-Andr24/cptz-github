"""Слой 1: подтверждение поездок дня (ACC-M-29…38, 47…50, 88, 89, 102).

Проверяется TRIP-01…TRIP-20: разворот шаблона в поездки, идемпотентность
повторного подтверждения, сохранность ручных поездок, автоподстановка
шаблонов и правила оплаты по типу транспорта.

Все цены — синтетические (TEST-01): базовый автобус 50 ₽, «Стрелка» 1-я ступень
25 ₽, электричка 60 ₽ и студенческая 30 ₽.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from student_planner.core.errors import (
    NotFoundError,
    PriceUnavailableError,
    RuleViolationError,
    ValidationError,
)
from student_planner.core.models import Direction, PaymentMethod
from student_planner.core.trip_service import TripPlanService
from student_planner.core.transport_repositories import (
    RideRepository,
    TripConfirmationRepository,
    TripTemplateRepository,
)


@pytest.fixture
def trip_templates(db):
    return TripTemplateRepository(db)


@pytest.fixture
def service(db):
    return TripPlanService(db)


@pytest.fixture
def bus_template(trip_templates):
    """«Автобус №22» туда, одна поездка «Стрелкой»."""
    return trip_templates.create(
        Direction.HOME_TO_COLLEGE,
        "Автобус №22",
        [{"mode": "bus", "vehicle": "22", "payment_method": PaymentMethod.STRELKA}],
    )


@pytest.fixture
def bus_return(trip_templates):
    return trip_templates.create(
        Direction.COLLEGE_TO_HOME,
        "Автобус №22 обратно",
        [{"mode": "bus", "vehicle": "22", "payment_method": PaymentMethod.STRELKA}],
    )


@pytest.fixture
def mixed_template(trip_templates):
    """«Электричка + №22»: два рейса, разные способы оплаты (ACC-M-29)."""
    return trip_templates.create(
        Direction.HOME_TO_COLLEGE,
        "Электричка + №22",
        [
            {"mode": "train", "vehicle": "Электричка", "payment_method": PaymentMethod.TRAIN_STUDENT},
            {"mode": "bus", "vehicle": "22", "payment_method": PaymentMethod.STRELKA},
        ],
    )


# ---------------------------------------------------------------------------
# ACC-M-29 — шаблон из двух рейсов даёт две поездки по своим тарифам.
# ---------------------------------------------------------------------------
def test_acc_m_29_mixed_template_creates_two_rides(db, base_tariffs, service,
                                                   mixed_template) -> None:
    result = service.confirm(date(2026, 9, 7), outbound_template_id=mixed_template.id)

    assert result.rides_created == 2, "Два рейса → две поездки"
    rides = RideRepository(db).for_date(date(2026, 9, 7))
    assert len(rides) == 2

    by_mode = {ride.transport_type: ride for ride in rides}
    train = by_mode["train"]
    bus = by_mode["bus"]

    assert train.paid_price == Decimal("30.00"), "Электричка по студенческому тарифу"
    assert train.payment_method == PaymentMethod.TRAIN_STUDENT
    assert train.ride_number_in_period is None, "Электричка счётчик не трогает (RT-17)"
    assert train.period_start_date is None

    assert bus.paid_price == Decimal("25.00"), "Автобус по «Стрелке»"
    assert bus.ride_number_in_period == 1, "Автобус получает номер 1"
    assert bus.period_start_date == date(2026, 9, 7)


def test_acc_m_29_train_does_not_advance_counter(db, base_tariffs, service,
                                                 mixed_template) -> None:
    """RT-17: электричка не участвует в счётчике «Стрелки»."""
    service.confirm(date(2026, 9, 7), outbound_template_id=mixed_template.id)
    service.confirm(date(2026, 9, 8), outbound_template_id=mixed_template.id)

    rides = RideRepository(db)
    bus_rides = [ride for ride in rides.for_date(date(2026, 9, 8)) if ride.transport_type == "bus"]
    assert bus_rides[0].ride_number_in_period == 2, (
        "Вторая автобусная поездка получает номер 2: электричка его не заняла"
    )


# ---------------------------------------------------------------------------
# ACC-M-30 — ступени стоимости по номеру, а не по дате.
# ---------------------------------------------------------------------------
def test_acc_m_30_stage_follows_ride_number(db, base_tariffs, service,
                                            bus_template) -> None:
    """В периоде 34 поездки: №35 — первая ступень, №36 — вторая.

    Фикстура ``base_tariffs`` задаёт ступени 25.00 ₽ и 10.00 ₽.
    """
    rides = RideRepository(db)
    for _ in range(34):
        rides.create(
            study_date=date(2026, 9, 1), direction=Direction.HOME_TO_COLLEGE,
            transport_type="bus", vehicle="22",
            base_price="50.00", paid_price="25.00", discount_amount="25.00",
            payment_method=PaymentMethod.STRELKA,
        )
    service.recalculate()

    first = service.confirm(date(2026, 9, 7), outbound_template_id=bus_template.id)
    first_ride = RideRepository(db).for_date(date(2026, 9, 7))[0]
    assert first_ride.ride_number_in_period == 35, "35-я поездка"
    assert first_ride.paid_price == Decimal("25.00"), "Ещё первая ступень"
    assert first.rides_created == 1

    service.confirm(date(2026, 9, 8), outbound_template_id=bus_template.id)
    second_ride = RideRepository(db).for_date(date(2026, 9, 8))[0]
    assert second_ride.ride_number_in_period == 36, "36-я поездка"
    assert second_ride.paid_price == Decimal("10.00"), "Вторая ступень — свой тариф"


# ---------------------------------------------------------------------------
# ACC-M-31 — дебетовая карта: без номера и без счётчика.
# ---------------------------------------------------------------------------
def test_acc_m_31_debit_card_ride_has_no_period_fields(db, base_tariffs,
                                                       trip_templates, service) -> None:
    template = trip_templates.create(
        Direction.HOME_TO_COLLEGE, "Автобус картой",
        [{"mode": "bus", "vehicle": "22", "payment_method": PaymentMethod.DEBIT_CARD}],
    )
    service.confirm(date(2026, 9, 7), outbound_template_id=template.id)

    ride = RideRepository(db).for_date(date(2026, 9, 7))[0]
    assert ride.payment_method == PaymentMethod.DEBIT_CARD
    assert ride.paid_price == Decimal("50.00"), "Полная стоимость bus_base"
    assert ride.period_start_date is None, "DATA-14: NULL для дебетовой карты"
    assert ride.ride_number_in_period is None
    assert ride.discount_amount == Decimal("0.00")


def test_acc_m_31_debit_card_does_not_change_counter(db, base_tariffs,
                                                     trip_templates, service) -> None:
    debit = trip_templates.create(
        Direction.HOME_TO_COLLEGE, "Картой",
        [{"mode": "bus", "vehicle": "22", "payment_method": PaymentMethod.DEBIT_CARD}],
    )
    strelka = trip_templates.create(
        Direction.HOME_TO_COLLEGE, "Стрелкой",
        [{"mode": "bus", "vehicle": "42", "payment_method": PaymentMethod.STRELKA}],
    )
    service.confirm(date(2026, 9, 7), outbound_template_id=debit.id)
    service.confirm(date(2026, 9, 8), outbound_template_id=strelka.id)

    ride = RideRepository(db).for_date(date(2026, 9, 8))[0]
    assert ride.ride_number_in_period == 1, "Дебетовая поездка не заняла номер 1"


# ---------------------------------------------------------------------------
# ACC-M-32 — повторное подтверждение не создаёт дублей.
# ---------------------------------------------------------------------------
def test_acc_m_32_repeat_confirmation_is_idempotent(db, base_tariffs, service,
                                                    bus_template) -> None:
    day = date(2026, 9, 7)
    first = service.confirm(day, outbound_template_id=bus_template.id)
    assert first.rides_created == 1

    second = service.confirm(day, outbound_template_id=bus_template.id)
    assert len(RideRepository(db).for_date(day)) == 1, "Дубля нет (TRIP-09)"
    assert second.rides_created == 1, "Поездка пересоздана, а не добавлена второй"
    assert second.rides_removed == 1
    assert len(TripConfirmationRepository(db).all()) == 1, "Подтверждение одно"


def test_acc_m_32_repeat_keeps_manual_rides(db, base_tariffs, service,
                                            bus_template) -> None:
    """REP-14: повторное подтверждение не удаляет ручные поездки даты."""
    day = date(2026, 9, 7)
    service.confirm(day, outbound_template_id=bus_template.id)
    manual = service.add_manual_ride(
        day, direction=Direction.COLLEGE_TO_HOME, transport_type="bus",
        vehicle="777", payment_method=PaymentMethod.STRELKA,
    )

    service.confirm(day, outbound_template_id=bus_template.id)
    rides = RideRepository(db).for_date(day)
    assert any(ride.id == manual.id for ride in rides), "Ручная поездка сохранилась"
    assert len([ride for ride in rides if not ride.is_manual]) == 1, "Автоматическая одна"


def test_acc_m_32_manual_ride_without_confirmation(db, base_tariffs, service) -> None:
    """ACC-M-88: ручная поездка без подтверждения участвует в расчётах."""
    ride = service.add_manual_ride(
        date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE, transport_type="bus",
        vehicle="777", payment_method=PaymentMethod.STRELKA,
    )
    assert ride.ride_number_in_period == 1, "Участвует в счётчике"
    assert ride.is_manual is True
    assert TripConfirmationRepository(db).by_date(date(2026, 9, 7)) is None


# ---------------------------------------------------------------------------
# ACC-M-33 / ACC-M-34 / ACC-M-35 — шаблон и день независимы.
# ---------------------------------------------------------------------------
def test_acc_m_33_editing_day_does_not_change_template(db, base_tariffs, service,
                                                       bus_template) -> None:
    day = date(2026, 9, 7)
    service.confirm(day, outbound_template_id=bus_template.id)

    rides = RideRepository(db)
    ride = rides.for_date(day)[0]
    rides.update(ride.id, vehicle="99")

    template = TripTemplateRepository(db).require(bus_template.id)
    assert template.legs[0].vehicle == "22", "Шаблон не изменился (TRIP-04)"


def test_acc_m_34_save_day_as_new_template(db, base_tariffs, service,
                                           bus_template) -> None:
    day = date(2026, 9, 7)
    service.confirm(day, outbound_template_id=bus_template.id)

    created = service.save_as_template(day, name="Мой новый шаблон",
                                       direction=Direction.HOME_TO_COLLEGE)
    assert created.id != bus_template.id, "Создан новый шаблон (TRIP-05)"
    assert created.name == "Мой новый шаблон"
    assert len(created.legs) == 1
    assert created.legs[0].vehicle == "22"
    assert len(TripTemplateRepository(db).all()) == 2, "Исходный шаблон сохранён"


def test_acc_m_35_autofill_uses_last_used_template(db, base_tariffs, service,
                                                   trip_templates) -> None:
    """TRIP-03: для того же дня недели подставляется последний использованный."""
    first = trip_templates.create(
        Direction.HOME_TO_COLLEGE, "Утренний",
        [{"mode": "bus", "vehicle": "11", "payment_method": PaymentMethod.STRELKA}],
    )
    second = trip_templates.create(
        Direction.HOME_TO_COLLEGE, "Поздний",
        [{"mode": "bus", "vehicle": "33", "payment_method": PaymentMethod.STRELKA}],
    )
    # Понедельник 07.09 — «Утренний», следующий понедельник 14.09 — «Поздний».
    service.confirm(date(2026, 9, 7), outbound_template_id=first.id)
    service.confirm(date(2026, 9, 14), outbound_template_id=second.id)

    plan = service.plan(date(2026, 9, 21))  # следующий понедельник
    assert plan.outbound is not None
    assert plan.outbound.id == second.id, "Подставлен последний использованный"


def test_acc_m_35_autofill_falls_back_to_first_active(db, base_tariffs, service,
                                                      bus_template) -> None:
    plan = service.plan(date(2026, 9, 7))
    assert plan.outbound is not None and plan.outbound.id == bus_template.id


# ---------------------------------------------------------------------------
# ACC-M-36 — удаление шаблона не трогает поездки.
# ---------------------------------------------------------------------------
def test_acc_m_36_deleting_template_keeps_rides(db, base_tariffs, service,
                                                bus_template) -> None:
    day = date(2026, 9, 7)
    service.confirm(day, outbound_template_id=bus_template.id)
    assert len(RideRepository(db).for_date(day)) == 1

    TripTemplateRepository(db).delete(bus_template.id, confirm_used=True)
    rides = RideRepository(db).for_date(day)
    assert len(rides) == 1, "Поездки сохранились (RT-14)"
    assert rides[0].paid_price == Decimal("25.00"), "Снапшот цены цел"


def test_used_template_delete_requires_confirmation(db, base_tariffs, service,
                                                    bus_template) -> None:
    service.confirm(date(2026, 9, 7), outbound_template_id=bus_template.id)
    with pytest.raises(Exception) as excinfo:
        TripTemplateRepository(db).delete(bus_template.id)
    assert "использован" in str(excinfo.value).lower() or "подтверд" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# ACC-M-37 / ACC-M-38 — пересчёт при смене способа оплаты и снапшоты.
# ---------------------------------------------------------------------------
def test_acc_m_37_changing_payment_method_recalculates(db, base_tariffs, service,
                                                       mixed_template) -> None:
    day = date(2026, 9, 7)
    service.confirm(day, outbound_template_id=mixed_template.id)
    rides = RideRepository(db)
    bus = next(ride for ride in rides.for_date(day) if ride.transport_type == "bus")
    assert bus.ride_number_in_period == 1

    rides.update(bus.id, payment_method=PaymentMethod.DEBIT_CARD)
    service.recalculate(from_date=day)

    refreshed = rides.require(bus.id)
    assert refreshed.payment_method == PaymentMethod.DEBIT_CARD
    assert refreshed.paid_price == Decimal("50.00"), "Стоимость по базовому тарифу"


def test_acc_m_38_tariff_edit_does_not_touch_existing_rides(db, tariffs,
                                                            service, bus_template) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1))
    stage = tariffs.create("strelka_stage1", "25.00", date(2026, 9, 1))
    day = date(2026, 9, 7)
    service.confirm(day, outbound_template_id=bus_template.id)

    ride = RideRepository(db).for_date(day)[0]
    assert ride.paid_price == Decimal("25.00")

    tariffs.update(stage.id, price="40.00")
    unchanged = RideRepository(db).require(ride.id)
    assert unchanged.paid_price == Decimal("25.00"), (
        "Правка тарифа не меняет прошлые поездки (DATA-16)"
    )
    assert unchanged.tariff_id in (None, stage.id), "Ссылка на тариф сохранена"


# ---------------------------------------------------------------------------
# ACC-M-47 / ACC-M-48 — справка времени и снятое направление.
# ---------------------------------------------------------------------------
def test_acc_m_47_depart_arrive_hints_do_not_affect_price(db, base_tariffs,
                                                          trip_templates,
                                                          service) -> None:
    with_hints = trip_templates.create(
        Direction.HOME_TO_COLLEGE, "С подсказками",
        [{"mode": "bus", "vehicle": "22", "payment_method": PaymentMethod.STRELKA}],
        depart_hint="07:30", arrive_hint="08:20",
    )
    result = service.confirm(date(2026, 9, 7), outbound_template_id=with_hints.id)
    assert result.total_paid == Decimal("25.00"), (
        "RT-12: время в пути — справка, на стоимость не влияет"
    )


def test_acc_m_48_disabled_direction_creates_no_rides(db, base_tariffs, service,
                                                      bus_template, bus_return) -> None:
    result = service.confirm(
        date(2026, 9, 7), outbound_template_id=bus_template.id,
        return_template_id=bus_return.id, include_return=False,
    )
    assert result.rides_created == 1
    rides = RideRepository(db).for_date(date(2026, 9, 7))
    assert {ride.direction for ride in rides} == {Direction.HOME_TO_COLLEGE}, (
        "TRIP-06: снятое направление не создаёт поездок"
    )


def test_confirm_without_any_template_rejected(db, base_tariffs, service) -> None:
    with pytest.raises(RuleViolationError):
        service.confirm(date(2026, 9, 7))


# ---------------------------------------------------------------------------
# ACC-M-49 / ACC-M-50 — снятие подтверждения.
# ---------------------------------------------------------------------------
def test_acc_m_49_confirmed_day_restores_from_confirmation(db, base_tariffs,
                                                           service, bus_template) -> None:
    day = date(2026, 9, 7)
    service.confirm(day, outbound_template_id=bus_template.id)
    # Меняем шаблон: подтверждённый день должен остаться на прежнем.
    TripTemplateRepository(db).update(bus_template.id, name="Переименован")

    plan = service.plan(day)
    assert plan.is_confirmed
    assert plan.outbound is not None and plan.outbound.id == bus_template.id, (
        "TRIP-18: набор рейсов берётся из подтверждения"
    )


def test_acc_m_50_unconfirm_removes_auto_keeps_manual(db, base_tariffs, service,
                                                     bus_template) -> None:
    day = date(2026, 9, 7)
    service.confirm(day, outbound_template_id=bus_template.id)
    manual = service.add_manual_ride(
        day, direction=Direction.COLLEGE_TO_HOME, transport_type="bus",
        vehicle="777", payment_method=PaymentMethod.STRELKA,
    )

    removed = service.unconfirm(day)
    assert removed == 1, "Удалена только автоматическая поездка"
    rides = RideRepository(db).for_date(day)
    assert [ride.id for ride in rides] == [manual.id], "Ручная поездка сохранена"
    assert TripConfirmationRepository(db).by_date(day) is None


def test_unconfirm_unknown_day_raises(db, base_tariffs, service) -> None:
    with pytest.raises(NotFoundError):
        service.unconfirm(date(2026, 9, 7))


# ---------------------------------------------------------------------------
# ACC-M-89 — электричка со «Стрелкой» отклоняется приложением.
# ---------------------------------------------------------------------------
def test_acc_m_89_train_with_strelka_rejected(db, base_tariffs, service) -> None:
    """RT-17: правило проверяется приложением, не только CHECK схемы."""
    rides = RideRepository(db)
    with pytest.raises(ValidationError) as excinfo:
        rides.create(
            study_date=date(2026, 9, 7), direction=Direction.HOME_TO_COLLEGE,
            transport_type="train", vehicle="Электричка",
            base_price="60.00", paid_price="30.00", discount_amount="30.00",
            payment_method=PaymentMethod.STRELKA,
        )
    assert "студенческим" in str(excinfo.value)


def test_acc_m_89_template_validation_rejects_train_with_strelka(trip_templates) -> None:
    with pytest.raises(ValidationError):
        trip_templates.create(
            Direction.HOME_TO_COLLEGE, "Неправильный",
            [{"mode": "train", "vehicle": "Электричка",
              "payment_method": PaymentMethod.STRELKA}],
        )


# ---------------------------------------------------------------------------
# ACC-M-95 / ACC-M-96 / ACC-M-98 — жизненный цикл шаблонов.
# ---------------------------------------------------------------------------
def test_acc_m_95_empty_legs_rejected(trip_templates) -> None:
    with pytest.raises(ValidationError):
        trip_templates.create(Direction.HOME_TO_COLLEGE, "Пустой", [])


def test_acc_m_95_leg_without_vehicle_rejected(trip_templates) -> None:
    """RT-16: рейс без номера/названия отклоняется."""
    with pytest.raises(ValidationError):
        trip_templates.create(
            Direction.HOME_TO_COLLEGE, "Без номера",
            [{"mode": "bus", "vehicle": "   ", "payment_method": PaymentMethod.STRELKA}],
        )


def test_acc_m_96_unknown_vehicle_number_accepted(trip_templates) -> None:
    """RT-02: справочника номеров нет — «777» принимается без правки кода."""
    template = trip_templates.create(
        Direction.HOME_TO_COLLEGE, "Нестандартный",
        [{"mode": "bus", "vehicle": "777", "payment_method": PaymentMethod.STRELKA}],
    )
    assert template.legs[0].vehicle == "777"


def test_acc_m_98_template_lifecycle(trip_templates) -> None:
    original = trip_templates.create(
        Direction.HOME_TO_COLLEGE, "Исходный",
        [{"mode": "bus", "vehicle": "22", "payment_method": PaymentMethod.STRELKA}],
    )
    renamed = trip_templates.update(original.id, name="Переименованный")
    assert renamed.name == "Переименованный"

    copied = trip_templates.copy(original.id, new_name="Копия")
    assert copied.id != original.id
    assert copied.name == "Копия"
    assert len(copied.legs) == 1, "Рейсы скопированы"

    deactivated = trip_templates.set_active(copied.id, False)
    assert deactivated.is_active is False

    trip_templates.delete(original.id)
    assert trip_templates.by_id(original.id) is None

    unused = trip_templates.create(
        Direction.COLLEGE_TO_HOME, "Ненужный",
        [{"mode": "bus", "vehicle": "5", "payment_method": PaymentMethod.STRELKA}],
    )
    trip_templates.delete(unused.id)
    assert trip_templates.by_id(unused.id) is None


# ---------------------------------------------------------------------------
# ACC-M-102 — имя и группа необязательны при первом запуске.
# ---------------------------------------------------------------------------
def test_acc_m_102_empty_profile_allowed(db) -> None:
    from student_planner.core.settings_registry import SettingsKeys
    from student_planner.core.settings_service import SettingsService

    settings = SettingsService(db)
    settings.set(SettingsKeys.STUDENT_NAME, "")
    settings.set(SettingsKeys.GROUP_TITLE, "")
    assert settings.profile_caption() == ("Не указано", "Не указано"), (
        "FIRST-15: отказ от имени и группы не блокирует работу"
    )


# ---------------------------------------------------------------------------
# ACC-M-70 — работа без начального пополнения.
# ---------------------------------------------------------------------------
def test_acc_m_70_works_without_initial_topup(db, base_tariffs, service,
                                              bus_template) -> None:
    """FIRST-06: отказ от пополнения — режим «Остаток не задан»."""
    from student_planner.core.recalculation import has_any_topup, wallet_balance

    assert has_any_topup(db) is False
    result = service.confirm(date(2026, 9, 7), outbound_template_id=bus_template.id)
    assert result.rides_created == 1, "Подтверждение работает без пополнения"
    assert wallet_balance(db) == Decimal("-25.00"), (
        "Остаток уходит в минус: это предупреждение, не блокировка"
    )
