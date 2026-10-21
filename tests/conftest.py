"""Общие фикстуры тестов слоя 1 (TEST-01).

Слой 1 приёмки работает на **синтетических** данных, а не на стартовом наборе
Прил. А: механика проверяется независимо от значений конкретного колледжа
(FIRST-09, V.4 п. 18). Стартовый набор проверяется слоем 2 отдельно.

Обязательное покрытие TEST-01 (то, что должно быть в фикстурах):

* оба вида периодов MVP (``vacation``, ``holiday``, ``no_classes = 1``);
* тарифы с пересекающимися и непересекающимися диапазонами;
* откат льготы (FARE-10);
* якорь со сменой в середине истории;
* сиротский оверрайд после правки сетки (ALG-10);
* редактор сетки на пустой и полной неделе (GRID-01…GRID-05);
* цепочка скользящих периодов с разрывом > 30 дней и ненулевым ``cnt0``;
* несколько ``strelka``-поездок в одну дату;
* две автобусные поездки на разные номера маршрутов в один период.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from student_planner.core import clock  # noqa: E402
from student_planner.core.database import Database, create_database  # noqa: E402
from student_planner.core.repositories import (  # noqa: E402
    BellRepository,
    ScheduleOverrideRepository,
    ScheduleTemplateRepository,
    StudyPeriodRepository,
    SubjectRepository,
    TariffRepository,
    WeekAnchorRepository,
)
from student_planner.core.settings_service import SettingsService  # noqa: E402
from student_planner.core.settings_registry import SettingsKeys  # noqa: E402
from student_planner.core.strelka import StrellaPeriodCalculator  # noqa: E402


#: «Сегодня» для всех тестов — фиксированная дата, чтобы просрочка и якорь
#: (DATA-21) не зависели от календаря запуска.
FIXED_TODAY = date(2026, 10, 20)


@pytest.fixture(autouse=True)
def frozen_clock():
    """Зафиксировать «сегодня» на всё время теста (детерминизм)."""
    with clock.freeze(FIXED_TODAY):
        yield


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Пустая БД со схемой версии 1 и без стартового набора (слой 1)."""
    database = create_database(tmp_path / "test.db")
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Путь для тестов, создающих БД самостоятельно."""
    return tmp_path / "manual.db"


@pytest.fixture
def settings(db: Database) -> SettingsService:
    return SettingsService(db)


@pytest.fixture
def subjects(db: Database) -> SubjectRepository:
    return SubjectRepository(db)


@pytest.fixture
def tariffs(db: Database) -> TariffRepository:
    return TariffRepository(db)


@pytest.fixture
def anchors(db: Database) -> WeekAnchorRepository:
    return WeekAnchorRepository(db)


@pytest.fixture
def bells(db: Database) -> BellRepository:
    return BellRepository(db)


@pytest.fixture
def templates(db: Database) -> ScheduleTemplateRepository:
    return ScheduleTemplateRepository(db)


@pytest.fixture
def overrides(db: Database) -> ScheduleOverrideRepository:
    return ScheduleOverrideRepository(db)


@pytest.fixture
def periods(db: Database) -> StudyPeriodRepository:
    return StudyPeriodRepository(db)


# ===========================================================================
# Синтетические справочники
# ===========================================================================
@pytest.fixture
def base_tariffs(tariffs: TariffRepository):
    """Тарифы фикстуры: базовая и льготная цена, обе бессрочные.

    Значения намеренно не совпадают с Прил. А: слой 1 проверяет механику
    (FIRST-09), а не конкретные цены колледжа.
    """
    tariffs.create("bus_base", "50.00", date(2026, 9, 1))
    tariffs.create("train_base", "60.00", date(2026, 9, 1))
    tariffs.create("strelka_stage1", "25.00", date(2026, 9, 1))
    tariffs.create("strelka_stage2", "10.00", date(2026, 9, 1))
    tariffs.create("train_student", "30.00", date(2026, 9, 1))
    return tariffs


@pytest.fixture
def anchor_lower(anchors: WeekAnchorRepository):
    """Якорь 07.09.2026 (понедельник) — нижняя неделя, цикл 2 (ALG-01)."""
    return anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower", cycle_length=2)


@pytest.fixture
def simple_subjects(subjects: SubjectRepository):
    """Два предмета: «Алгебра» и «Физика» — для шаблона и оверрайдов."""
    first = subjects.create("Алгебра", code="ALG", teacher="Иванова", room="101")
    second = subjects.create("Физика", code="PHY", teacher="Петров", room="202")
    return first, second


@pytest.fixture
def simple_bell(bells: BellRepository):
    """Один профиль на понедельник: три цельных блока по 45 минут."""
    profile = bells.create_profile(1, "Понедельник (тест)")
    bells.add_slot(profile.id, "pair", display_name="1 пара", pair_no=1,
                   parts=[("lesson", "08:30", "09:15")])
    bells.add_slot(profile.id, "pair", display_name="2 пара", pair_no=2,
                   parts=[("lesson", "09:25", "10:10")])
    bells.add_slot(profile.id, "pair", display_name="3 пара", pair_no=3,
                   parts=[("lesson", "10:20", "11:05")])
    return bells.require_profile(profile.id)


@pytest.fixture
def two_part_bell(bells: BellRepository):
    """Профиль со двухчастным блоком — проверка BELL-02 и BELL-06."""
    profile = bells.create_profile(2, "Вторник (тест)")
    bells.add_slot(
        profile.id, "pair", display_name="1 пара", pair_no=1,
        parts=[("lesson", "08:30", "09:15"), ("break", "09:15", "09:25"),
               ("lesson", "09:25", "10:10")],
    )
    return bells.require_profile(profile.id)


# ===========================================================================
# Помощники для поездок
# ===========================================================================
def add_strelka_ride(rides, ride_date: date, *, vehicle: str = "22", **kwargs):
    """Добавить засчитанную (``strelka``) поездку с ценами-заглушками."""
    return rides.create(
        study_date=ride_date,
        direction=kwargs.pop("direction", "home_to_college"),
        transport_type="bus",
        vehicle=vehicle,
        base_price="50.00",
        paid_price="25.00",
        discount_amount="25.00",
        payment_method="strelka",
        **kwargs,
    )


def streak_of_days(start: date, count: int) -> list[date]:
    """Последовательность дат от ``start`` — для цепочки периодов."""
    return [start + timedelta(days=offset) for offset in range(count)]


def weekday_dates(start: date, end: date, weekdays: set[int] | None = None) -> list[date]:
    """Даты диапазона, попадающие на указанные дни недели (1 = Пн)."""
    allowed = weekdays or {1, 2, 3, 4, 5, 6}
    result: list[date] = []
    current = start
    while current <= end:
        if current.isoweekday() in allowed:
            result.append(current)
        current += timedelta(days=1)
    return result


@pytest.fixture
def calculator_factory(settings: SettingsService):
    """Фабрика калькулятора ALG-02 из поездок БД и настроек."""

    def build(rides_list, *, initial_count: int = 0, anchor: date | None = None,
              period_days: int = 30, first_limit: int = 35):
        return StrellaPeriodCalculator(
            rides=[(ride.id, ride.ride_date) for ride in rides_list],
            anchor=anchor,
            initial_count=initial_count,
            period_days=period_days,
            first_limit=first_limit,
        )

    return build


@pytest.fixture
def ride_repo_factory():
    """Фабрика репозитория поездок: ``ride_repo_factory(db)``."""

    def build(database: Database):
        from student_planner.core.transport_repositories import RideRepository

        return RideRepository(database)

    return build


@pytest.fixture
def topup_repo_factory():
    """Фабрика репозитория пополнений: ``topup_repo_factory(db)``."""

    def build(database: Database):
        from student_planner.core.transport_repositories import TopUpRepository

        return TopUpRepository(database)

    return build


@pytest.fixture
def homework_repo_factory():
    """Фабрика репозитория домашних заданий."""

    def build(database: Database):
        from student_planner.core.transport_repositories import HomeworkRepository

        return HomeworkRepository(database)

    return build


@pytest.fixture
def trip_service(db):
    """Сервис подтверждения поездок дня (TRIP-01…TRIP-20)."""
    from student_planner.core.trip_service import TripPlanService

    return TripPlanService(db)


@pytest.fixture
def template_repo_factory():
    """Фабрика репозитория шаблонов поездок."""

    def build(database: Database):
        from student_planner.core.transport_repositories import TripTemplateRepository

        return TripTemplateRepository(database)

    return build


__all__ = [
    "FIXED_TODAY",
    "add_strelka_ride",
    "streak_of_days",
    "weekday_dates",
    "SettingsKeys",
]
