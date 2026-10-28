"""Слой 1: недостающие проверки справочников, кошелька и отчётов.

Закрывает ACC-M-18, 19, 25, 26, 39, 40, 52…58, 60, 61, 65, 67, 87, 94, 108…113.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from student_planner.core.errors import InUseError, RuleViolationError, ValidationError
from student_planner.core.models import HomeworkStatus, PaymentMethod


# ---------------------------------------------------------------------------
# ACC-M-18 / ACC-M-19 — конфликты оверрайдов (OVR-08).
# ---------------------------------------------------------------------------
def test_acc_m_18_second_replace_same_slot_rejected(db, anchors, simple_bell,
                                                    simple_subjects, templates,
                                                    overrides) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)

    overrides.create(day, simple_bell.id, 1, "replace", subject_id=simple_subjects[1].id)
    with pytest.raises(RuleViolationError) as excinfo:
        overrides.create(day, simple_bell.id, 1, "replace", subject_id=simple_subjects[0].id)
    assert "изменение" in str(excinfo.value).lower() or "оверрайд" in str(excinfo.value).lower()


def test_acc_m_18_cancel_then_replace_same_slot_allowed(db, anchors, simple_bell,
                                                       simple_subjects, templates,
                                                       overrides) -> None:
    """OVR-05/SCH-18: замена поверх отмены того же блока разрешена.

    Пользователь убирает пару и сразу ставит другую на её место. Прежний
    ``cancel`` снимается: в блоке остаётся одна запись — ``replace``.
    """
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    overrides.create(day, simple_bell.id, 1, "cancel")

    created = overrides.create(
        day, simple_bell.id, 1, "replace", subject_id=simple_subjects[1].id
    )
    assert created.subject_id == simple_subjects[1].id

    items = overrides.for_date(day)
    assert len(items) == 1, f"в блоке должна остаться одна запись, а их {len(items)}"
    assert items[0].subject_id == simple_subjects[1].id


def test_acc_m_19_add_into_occupied_slot_rejected(db, anchors, simple_bell,
                                                 simple_subjects, templates,
                                                 overrides) -> None:
    """TPL-01: один слот — не более одного занятия в шаблоне."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)

    with pytest.raises(RuleViolationError) as excinfo:
        overrides.create(day, simple_bell.id, 1, "add", subject_id=simple_subjects[1].id)
    assert "занят" in str(excinfo.value).lower()


def test_acc_m_19_add_into_free_slot_allowed(db, anchors, simple_bell,
                                            simple_subjects, overrides) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    added = overrides.create(day, simple_bell.id, 2, "add",
                             subject_id=simple_subjects[0].id)
    assert added.override_type == "add"


# ---------------------------------------------------------------------------
# ACC-M-25 / ACC-M-26 — блокировка удаления при ссылках.
# ---------------------------------------------------------------------------
def test_acc_m_25_subject_with_references_not_deleted(db, anchors, simple_bell,
                                                     simple_subjects, templates,
                                                     subjects) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)
    with pytest.raises(InUseError) as excinfo:
        subjects.delete(subject.id)
    assert "отключите" in str(excinfo.value).lower() or "деактив" in str(excinfo.value).lower()


def test_acc_m_25_bell_profile_with_templates_not_deleted(db, anchors, simple_bell,
                                                         simple_subjects, templates,
                                                         bells) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    with pytest.raises(InUseError) as excinfo:
        bells.delete_profile(simple_bell.id)
    assert "деактив" in str(excinfo.value).lower()


def test_acc_m_26_delete_middle_slot_blocked_when_referenced(db, anchors, simple_bell,
                                                            simple_subjects, templates,
                                                            bells) -> None:
    """BELL-16: удаление блока из середины запрещено при ссылках."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    first_slot = simple_bell.slots[0]
    with pytest.raises(InUseError):
        bells.delete_slot(first_slot.id)


def test_acc_m_26_last_slot_deletable(db, simple_bell, bells) -> None:
    """Блок с конца удаляется, даже если он последний."""
    last = simple_bell.slots[-1]
    bells.delete_slot(last.id)
    refreshed = bells.profile_for(date(2026, 9, 7))
    assert refreshed is not None
    assert all(slot.id != last.id for slot in refreshed.slots)


# ---------------------------------------------------------------------------
# ACC-M-88 — ручная поездка без подтверждения дня, цена по тарифу её даты.
# ACC-M-85 — каскадный пересчёт номеров после удаления поездки.
# Проверки ACC-M-39 и ACC-M-40 отменены в v1.11 и ведутся в TZ-VNEMVP.md.
# ---------------------------------------------------------------------------
def test_acc_m_88_manual_ride_uses_tariff_of_its_date(db, tariffs,
                                                     trip_service) -> None:
    tariffs.create("bus_base", "50.00", date(2026, 9, 1), effective_to=date(2026, 9, 30))
    tariffs.create("bus_base", "60.00", date(2026, 10, 1))
    tariffs.create("strelka_stage1", "25.00", date(2026, 9, 1))

    ride = trip_service.add_manual_ride(
        date(2026, 10, 5), direction="home_to_college", transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    assert ride.base_price == Decimal("60.00"), "Тариф на дату поездки (ALG-09)"


def test_acc_m_85_bulk_delete_recalculates(db, base_tariffs, trip_service) -> None:
    """Удаление нескольких поездок запускает пересчёт один раз."""
    from student_planner.core.transport_repositories import RideRepository

    day = date(2026, 9, 7)
    rides = []
    for offset in range(3):
        rides.append(
            trip_service.add_manual_ride(
                day, direction="home_to_college", transport_type="bus",
                vehicle="22", payment_method=PaymentMethod.STRELKA,
            )
        )
    repo = RideRepository(db)
    assert [repo.require(ride.id).ride_number_in_period for ride in rides] == [1, 2, 3]

    repo.delete(rides[0].id)
    trip_service.recalculate(from_date=day)
    remaining = repo.for_date(day)
    assert [ride.ride_number_in_period for ride in remaining] == [1, 2], (
        "Номера сдвинулись после удаления (CALC-04)"
    )


# ---------------------------------------------------------------------------
# ACC-M-52…56 — предупреждение об остатке и независимость от номеров.
# ---------------------------------------------------------------------------
def test_acc_m_52_low_balance_warning_threshold(db, base_tariffs, settings) -> None:
    from student_planner.core.recalculation import wallet_balance
    from student_planner.core.transport_repositories import TopUpRepository

    topups = TopUpRepository(db)
    topups.create(date(2026, 9, 1), "40.00")

    warn = settings.strelka_low_balance_warn()
    next_price = Decimal("25.00")  # strelka_stage1 из base_tariffs
    assert warn == 2
    assert wallet_balance(db) < warn * next_price, (
        "WAL-05: 40 < 2 × 25 → предупреждение показывается"
    )


def test_acc_m_52_no_warning_when_balance_sufficient(db) -> None:
    from student_planner.core.recalculation import wallet_balance
    from student_planner.core.transport_repositories import TopUpRepository

    TopUpRepository(db).create(date(2026, 9, 1), "1000.00")
    warn = 2
    next_price = Decimal("25.00")
    assert wallet_balance(db) >= warn * next_price, "Предупреждения нет"


def test_acc_m_53_before_first_topup_balance_unset(db) -> None:
    from student_planner.core.recalculation import has_any_topup, wallet_balance

    assert has_any_topup(db) is False
    assert wallet_balance(db) == Decimal("0.00")
    # WAL-09: режим «Остаток не задан» — предупреждение не показывается.


def test_acc_m_54_topup_edit_does_not_touch_numbers(db, base_tariffs,
                                                    trip_service) -> None:
    """WAL-07: правка пополнения меняет остаток, но не номера поездок."""
    from student_planner.core.recalculation import wallet_balance
    from student_planner.core.transport_repositories import (
        RideRepository,
        TopUpRepository,
    )

    ride = trip_service.add_manual_ride(
        date(2026, 9, 7), direction="home_to_college", transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    topups = TopUpRepository(db)
    topup = topups.create(date(2026, 9, 1), "100.00")
    assert wallet_balance(db) == Decimal("75.00")

    topups.update(topup.id, amount="200.00")
    assert wallet_balance(db) == Decimal("175.00"), "Остаток изменился сразу"
    assert RideRepository(db).require(ride.id).ride_number_in_period == 1, (
        "Номер поездки не изменился"
    )


def test_acc_m_55_topups_and_spent_are_separate(db, base_tariffs, settings) -> None:
    """WAL-04/REP-09: «пополнено» и «потрачено» — разные показатели."""
    from student_planner.core.transport_repositories import (
        RideRepository,
        TopUpRepository,
    )

    topups = TopUpRepository(db)
    topups.create(date(2026, 9, 1), "500.00")
    RideRepository(db).create(
        study_date=date(2026, 9, 7), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="50.00", paid_price="25.00", discount_amount="25.00",
        payment_method=PaymentMethod.STRELKA,
    )
    added = topups.total_net()
    spent = sum(
        (ride.paid_price for ride in RideRepository(db).strelka_rides()), Decimal("0.00")
    )
    assert added == Decimal("500.00")
    assert spent == Decimal("25.00")
    assert added != spent, "Показатели не смешиваются (WAL-04)"


def test_acc_m_56_debit_card_excluded_from_wallet(db, base_tariffs) -> None:
    from student_planner.core.recalculation import wallet_balance
    from student_planner.core.transport_repositories import (
        RideRepository,
        TopUpRepository,
    )

    TopUpRepository(db).create(date(2026, 9, 1), "100.00")
    RideRepository(db).create(
        study_date=date(2026, 9, 7), direction="home_to_college",
        transport_type="bus", vehicle="22",
        base_price="50.00", paid_price="50.00", discount_amount="0.00",
        payment_method=PaymentMethod.DEBIT_CARD,
    )
    assert wallet_balance(db) == Decimal("100.00"), "WAL-08: карта не трогает остаток"


# ---------------------------------------------------------------------------
# ACC-M-57 / ACC-M-58 — отчёт по месяцам.
# ---------------------------------------------------------------------------
def test_acc_m_57_month_report_matches_manual_sums(db, base_tariffs,
                                                   trip_service) -> None:
    """REP-04: суммы по типам транспорта и способам оплаты, включая ручные."""
    from student_planner.core.transport_repositories import RideRepository

    trip_service.add_manual_ride(
        date(2026, 9, 7), direction="home_to_college", transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    trip_service.add_manual_ride(
        date(2026, 9, 8), direction="college_to_home", transport_type="train",
        vehicle="Электричка", payment_method=PaymentMethod.TRAIN_STUDENT,
    )
    trip_service.add_manual_ride(
        date(2026, 10, 1), direction="home_to_college", transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )

    rides = RideRepository(db)
    september = rides.filtered(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
    assert len(september) == 2, "REP-03: группировка по ride_date"

    by_mode: dict[str, Decimal] = {}
    for ride in september:
        by_mode[ride.transport_type] = by_mode.get(ride.transport_type, Decimal("0.00")) + ride.paid_price
    assert by_mode["bus"] == Decimal("25.00")
    assert by_mode["train"] == Decimal("30.00")
    assert sum(by_mode.values(), Decimal("0.00")) == Decimal("55.00")

    savings = {ride.transport_type: ride.discount_amount for ride in september}
    assert savings["bus"] == Decimal("25.00"), "Автобус: 50 − 25"
    assert savings["train"] == Decimal("30.00"), "Электричка: 60 − 30"
    assert sum(savings.values(), Decimal("0.00")) == Decimal("55.00")


def test_acc_m_58_report_uses_ride_date_not_study_date(db, base_tariffs) -> None:
    """REP-03: отчёт группируется по ``ride_date``."""
    from student_planner.core.transport_repositories import RideRepository

    RideRepository(db).create(
        study_date=date(2026, 9, 30), ride_date=date(2026, 10, 1),
        direction="home_to_college", transport_type="bus", vehicle="22",
        base_price="50.00", paid_price="25.00", discount_amount="25.00",
        payment_method=PaymentMethod.STRELKA,
    )
    rides = RideRepository(db)
    october = rides.filtered(date_from=date(2026, 10, 1), date_to=date(2026, 10, 31))
    assert len(october) == 1, "Поездка попала в октябрь по ride_date"
    september = rides.filtered(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
    assert september == []


# ---------------------------------------------------------------------------
# ACC-M-60 / ACC-M-61 / ACC-M-65 — редактор сетки.
# ---------------------------------------------------------------------------
def test_acc_m_60_cell_saved_immediately(db, simple_bell, simple_subjects,
                                        templates) -> None:
    """GRID-02/DATA-20: выбор предмета сразу создаёт ровно одну строку."""
    subject = simple_subjects[0]
    first = templates.set_cell(simple_bell.id, "lower", 1, subject.id)
    second = templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[1].id)

    rows = db.fetchall(
        "SELECT * FROM schedule_templates WHERE profile_id = ? AND week_type = 'lower' "
        "AND slot_no = 1",
        (simple_bell.id,),
    )
    assert len(rows) == 1, "Общего «Сохранить» нет: строка одна (ACC-M-60)"
    assert first.id == second.id, "Повторная запись обновила ту же строку"
    assert int(rows[0]["subject_id"]) == simple_subjects[1].id


def test_acc_m_61_clear_cell_keeps_slot_and_overrides(db, anchors, simple_bell,
                                                     simple_subjects, templates,
                                                     overrides) -> None:
    """GRID-05: очистка удаляет только строку шаблона."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    subject = simple_subjects[0]
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)
    override = overrides.create(day, simple_bell.id, 1, "cancel")

    slot_count_before = len(datetime_slots(simple_bell))
    templates.clear_cell(simple_bell.id, "lower", 1)

    assert db.fetchone(
        "SELECT * FROM schedule_templates WHERE profile_id = ? AND week_type = 'lower' "
        "AND slot_no = 1",
        (simple_bell.id,),
    ) is None, "Строка шаблона удалена"
    assert overrides.by_id(override.id) is not None, "Оверрайд остался (становится сиротским)"
    profile = db.fetchone("SELECT * FROM bell_slots WHERE profile_id = ?", (simple_bell.id,))
    assert profile is not None, "Слот и его части не тронуты"
    assert len(datetime_slots(simple_bell)) == slot_count_before


def datetime_slots(profile):
    return profile.slots


def test_acc_m_65_new_subject_from_cell(db, simple_bell, subjects, templates) -> None:
    """SUBJ-05: новый предмет создаётся и сразу подставляется в клетку."""
    created = subjects.create("Новый предмет", code="NEW")
    cell = templates.set_cell(simple_bell.id, "lower", 1, created.id)
    assert cell.subject_id == created.id
    assert subjects.require(created.id).name == "Новый предмет"


# ---------------------------------------------------------------------------
# ACC-M-67 — add не сиротский, массовое удаление только cancel/replace.
# ---------------------------------------------------------------------------
def test_acc_m_67_add_never_orphan(db, anchors, simple_bell, simple_subjects,
                                   overrides) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    added = overrides.create(day, simple_bell.id, 2, "add",
                             subject_id=simple_subjects[0].id)

    assert overrides.is_orphan(added, "lower") is False
    assert overrides.delete_orphans() == []
    assert overrides.by_id(added.id) is not None


# ---------------------------------------------------------------------------
# ACC-M-58 — отчёт группируется по `ride_date` и не выходит за границы периода
# (REP-03). ACC-M-87 в ТЗ не присвоен: нумерация В.1 его пропускает.
# ---------------------------------------------------------------------------
def test_acc_m_58_report_respects_period_bounds(db, base_tariffs, trip_service) -> None:
    from student_planner.core.models import PaymentMethod as PM
    from student_planner.core.repositories import TariffRepository
    from student_planner.core.transport_repositories import RideRepository

    # Расширяем действие тарифов на весь проверяемый диапазон (TRIP-19):
    # 31.08 попадает в отчёт только если тариф на него есть.
    tariffs = TariffRepository(db)
    for kind, price in (("bus_base", "50.00"), ("strelka_stage1", "25.00")):
        existing = tariffs.of_kind(kind)[0]
        tariffs.update(existing.id, effective_from=date(2026, 8, 1))

    for offset, day in enumerate((date(2026, 8, 31), date(2026, 9, 1),
                                  date(2026, 9, 30), date(2026, 10, 1))):
        trip_service.add_manual_ride(
            day, direction="home_to_college", transport_type="bus",
            vehicle=str(20 + offset), payment_method=PM.STRELKA,
        )
    rides = RideRepository(db)
    september = rides.filtered(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
    assert len(september) == 2, "Границы периода включительны, соседние месяцы не попадают"


# ---------------------------------------------------------------------------
# ACC-M-94 — справочник предметов: поля и дубли.
# ---------------------------------------------------------------------------
def test_acc_m_94_subject_fields_persisted(subjects) -> None:
    created = subjects.create(
        "Операционные системы", code="OS", teacher="Сидоров С. С.",
        room="Каб. №33", color="#336699",
    )
    stored = subjects.require(created.id)
    assert stored.code == "OS"
    assert stored.name == "Операционные системы"
    assert stored.teacher == "Сидоров С. С."
    assert stored.room == "Каб. №33"
    assert stored.color == "#336699"
    assert stored.is_active is True


def test_acc_m_94_duplicate_codes_coexist(subjects) -> None:
    """Два предмета с одинаковым ``code`` сосуществуют (нет UNIQUE)."""
    first = subjects.create("Первый", code="SAME")
    second = subjects.create("Второй", code="SAME")
    assert first.id != second.id
    assert len(subjects.all()) == 2


def test_acc_m_94_duplicate_code_name_pair_rejected(subjects) -> None:
    """SUBJ-02: дубль пары ``(code, name)`` отклоняется."""
    subjects.create("Физика", code="PHY", teacher="Иванов", room="101")
    with pytest.raises(RuleViolationError) as excinfo:
        subjects.create("Физика", code="PHY", teacher="Петров", room="102")
    assert "SUBJ-02" in str(excinfo.value)


def test_acc_m_94_same_code_different_name_allowed(subjects) -> None:
    """SUBJ-02: одинаковый код у разных предметов — норма (МДК.01.02 дважды)."""
    first = subjects.create("МДК.01.02 (теория)", code="MDK0102")
    second = subjects.create("МДК.01.02 (практика)", code="MDK0102")
    assert first.id != second.id
    assert first.code == second.code == "MDK0102"


# ---------------------------------------------------------------------------
# ACC-M-108…113 — бейдж ДЗ и фильтры.
# ---------------------------------------------------------------------------
def test_acc_m_110_homework_badge_on_matching_lesson(db, anchors, simple_bell,
                                                     simple_subjects, templates,
                                                     homework_repo_factory) -> None:
    """HW-06: бейдж на карточке занятия того же предмета в день сдачи."""
    from student_planner.core.day_resolution import DayResolver

    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)

    homework = homework_repo_factory(db)
    homework.create(subject.id, day, "Подготовить отчёт")

    lesson = DayResolver(db).resolve(day).lessons[0]
    assert lesson.homework_count == 1, "Бейдж homework_count = 1"


def test_acc_m_110_badge_counter_for_several_tasks(db, anchors, simple_bell,
                                                   simple_subjects, templates,
                                                   homework_repo_factory) -> None:
    from student_planner.core.day_resolution import DayResolver

    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)

    homework = homework_repo_factory(db)
    homework.create(subject.id, day, "Задание 1")
    homework.create(subject.id, day, "Задание 2")

    lesson = DayResolver(db).resolve(day).lessons[0]
    assert lesson.homework_count == 2, "При нескольких заданиях — счётчик"


def test_acc_m_110_no_badge_for_other_subject(db, anchors, simple_bell,
                                              simple_subjects, templates,
                                              homework_repo_factory) -> None:
    from student_planner.core.day_resolution import DayResolver

    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    first, second = simple_subjects
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, first.id)

    homework = homework_repo_factory(db)
    homework.create(second.id, day, "Чужое задание")

    lesson = DayResolver(db).resolve(day).lessons[0]
    assert lesson.homework_count == 0, "На паре другого предмета бейджа нет"


def test_homework_status_labels() -> None:
    assert HomeworkStatus.LABELS[HomeworkStatus.ACTIVE] == "Активное"
    assert HomeworkStatus.LABELS[HomeworkStatus.DONE] == "Выполнено"


def test_acc_m_109_overdue_filter(db, simple_subjects, homework_repo_factory) -> None:
    repo = homework_repo_factory(db)
    subject = simple_subjects[0]
    overdue = repo.create(subject.id, date(2026, 10, 1), "Просрочено")
    repo.create(subject.id, date(2026, 10, 25), "Впереди")

    found = repo.filtered(only_overdue=True, overdue_before=date(2026, 10, 20))
    assert [item.id for item in found] == [overdue.id]


def test_acc_m_112_homework_subject_reference_protects_delete(db, simple_subjects,
                                                              homework_repo_factory,
                                                              subjects) -> None:
    repo = homework_repo_factory(db)
    subject = simple_subjects[0]
    repo.create(subject.id, date(2026, 9, 14), "Задание")
    references = subjects.references(subject.id)
    assert references, "Ссылка на предмет зафиксирована"
    with pytest.raises(InUseError):
        subjects.delete(subject.id)


# ---------------------------------------------------------------------------
# ACC-M-29 / ACC-M-31: отчёт включает электричку, но счётчик её не считает
# (RT-17: электричка оплачивается только студенческим билетом).
# ---------------------------------------------------------------------------
def test_report_excludes_train_from_strelka_counter(db, base_tariffs,
                                                    trip_service) -> None:
    from student_planner.core.transport_repositories import RideRepository

    trip_service.add_manual_ride(
        date(2026, 9, 7), direction="home_to_college", transport_type="train",
        vehicle="Электричка", payment_method=PaymentMethod.TRAIN_STUDENT,
    )
    trip_service.add_manual_ride(
        date(2026, 9, 7), direction="home_to_college", transport_type="bus",
        vehicle="22", payment_method=PaymentMethod.STRELKA,
    )
    rides = RideRepository(db)
    assert len(rides.for_date(date(2026, 9, 7))) == 2, "В отчёте обе поездки"
    assert len(rides.strelka_rides()) == 1, "В счётчике только «Стрелка»"
