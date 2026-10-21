"""Стартовый набор данных — Приложение А ТЗ v1.11.

Набор загружается целиком при первом запуске (FIRST-01), восстанавливается
точечно (FIRST-05, «добавляет только отсутствующие записи») и полностью
редактируем (GEN-07, FIRST-02): ни одно значение не является константой кода.

**Что набор сознательно не содержит** (А.5):
* учебных периодов — даты каникул и праздников пользователь вносит сам;
* пометок дня — сущность v1.1 (таблица в схеме как заготовка);
* домашних заданий — задание всегда относится к конкретному дню (ACC-S-20);
* экзаменов — модуль v1.1;
* начального пополнения «Стрелки» — это фактический остаток на карте (WAL-09).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .money import money

#: Якорь недели по умолчанию (А.0): 07.09.2026 — понедельник, нижняя неделя.
ANCHOR_EFFECTIVE_FROM = date(2026, 9, 7)
ANCHOR_BASE_DATE = date(2026, 9, 7)
ANCHOR_BASE_TYPE = "lower"
ANCHOR_CYCLE_LENGTH = 2
ANCHOR_COMMENT = "стартовый"


# ===========================================================================
# Тарифы (А.0)
# ===========================================================================
@dataclass(frozen=True)
class SeedTariff:
    kind: str
    price: Decimal
    effective_from: date
    effective_to: date | None
    vehicle: str | None
    comment: str


TARIFFS: tuple[SeedTariff, ...] = (
    SeedTariff("train_base", money("61.00"), date(2026, 9, 1), None, None,
               "базовый, бессрочно, весь участок"),
    SeedTariff("train_student", money("30.50"), date(2026, 9, 1), date(2027, 5, 31), None,
               "студенческий, только учебный год"),
    SeedTariff("bus_base", money("73.00"), date(2026, 9, 1), None, None,
               "базовый, единый для всех маршрутов"),
    SeedTariff("strelka_stage1", money("36.50"), date(2026, 9, 1), date(2027, 5, 31), None,
               "поездки 1–35 периода, льгота"),
    SeedTariff("strelka_stage2", money("0.73"), date(2026, 9, 1), date(2027, 5, 31), None,
               "поездки 36+ периода, льгота"),
)


# ===========================================================================
# Предметы (А.2)
# ===========================================================================
@dataclass(frozen=True)
class SeedSubject:
    key: str
    code: str | None
    name: str
    teacher: str | None
    room: str | None


SUBJECTS: tuple[SeedSubject, ...] = (
    SeedSubject("class_hour", None, "Классный час", "Ветрова К.В.", "Каб. №44"),
    SeedSubject("mdk0101", "МДК.01.01", "Разработка программных модулей", "Кузьмина Е.Е.", "Каб. №44"),
    SeedSubject("mdk0102_support", "МДК.01.02",
                "Поддержка и тестирование программных модулей", "Кузьмина Е.Е.", "Каб. №44"),
    SeedSubject("mdk0102_docs", "МДК.01.02",
                "Документирование программных средств", "Ветрова К.В.", "Каб. №44"),
    SeedSubject("mdk1101", "МДК.11.01",
                "Технология разработки и защиты баз данных", "Гжегожевский С.В.", "Каб. №43"),
    SeedSubject("networks", None, "Компьютерные сети", "Пронина А.Ю.", "Каб. №42"),
    SeedSubject("psychology", None, "Психология общения", "Быкина Г.Н.", "Каб. №32п"),
    SeedSubject("physcult", None, "Физическая культура", "Худов П.В.", "Спортзал"),
    SeedSubject("foreign", None, "Иностранный язык в профессиональной деятельности",
                "Платонова О.В.", "Каб. №14"),
)


# ===========================================================================
# Сетки звонков (А.1)
# ===========================================================================
@dataclass(frozen=True)
class SeedBlock:
    """Блок профиля: тип, отображаемое имя, номер пары и части ``(тип, начало, конец)``."""

    block_type: str
    display_name: str
    pair_no: int | None
    parts: tuple[tuple[str, str, str], ...]


def _solid(pair_no: int, start: str, end: str) -> SeedBlock:
    """Цельный блок: одна часть ``lesson`` (BELL-02)."""
    return SeedBlock("pair", f"{pair_no} пара", pair_no, (("lesson", start, end),))


def _two_part(pair_no: int, start1: str, end_break_start: str, break_end: str, end: str) -> SeedBlock:
    """Двухчастный блок: ``lesson | break | lesson`` (BELL-02)."""
    return SeedBlock(
        "pair",
        f"{pair_no} пара",
        pair_no,
        (
            ("lesson", start1, end_break_start),
            ("break", end_break_start, break_end),
            ("lesson", break_end, end),
        ),
    )


#: Понедельник — цельные блоки, включая классный час (А.1).
MONDAY_BLOCKS: tuple[SeedBlock, ...] = (
    SeedBlock("class_hour", "Классный час", None, (("lesson", "08:30", "09:15"),)),
    _solid(1, "09:25", "10:45"),
    _solid(2, "11:00", "12:20"),
    _solid(3, "12:40", "14:00"),
    _solid(4, "14:10", "15:30"),
)

#: Вторник–пятница — двухчастные блоки (А.1).
WEEKDAY_BLOCKS: tuple[SeedBlock, ...] = (
    _two_part(1, "08:30", "09:15", "09:25", "10:10"),
    _two_part(2, "10:25", "11:10", "11:20", "12:05"),
    _two_part(3, "12:25", "13:10", "13:20", "14:05"),
    _two_part(4, "14:15", "15:00", "15:10", "15:55"),
)

#: Суббота — цельные блоки (А.1).
SATURDAY_BLOCKS: tuple[SeedBlock, ...] = (
    _solid(1, "08:30", "09:50"),
    _solid(2, "10:00", "11:20"),
    _solid(3, "11:30", "12:50"),
    _solid(4, "13:00", "14:20"),
)

#: Профили по дням недели: 1 — Пн … 6 — Сб; воскресенье — профиль без блоков (А.1).
PROFILE_BLOCKS: dict[int, tuple[SeedBlock, ...]] = {
    1: MONDAY_BLOCKS,
    2: WEEKDAY_BLOCKS,
    3: WEEKDAY_BLOCKS,
    4: WEEKDAY_BLOCKS,
    5: WEEKDAY_BLOCKS,
    6: SATURDAY_BLOCKS,
    7: (),
}

PROFILE_NAMES: dict[int, str] = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}


# ===========================================================================
# Шаблоны недель (А.3)
# ===========================================================================
#: Верхняя неделя: ``weekday → {slot_no: subject_key}``. Пустая ячейка — отсутствие
#: строки в ``schedule_templates``, а не ``subject_id IS NULL`` (А.7 п. 4).
UPPER_WEEK: dict[int, dict[int, str]] = {
    1: {1: "class_hour", 2: "mdk0101", 3: "mdk0102_support"},
    2: {1: "networks", 2: "mdk0101", 3: "mdk0102_support"},
    3: {1: "mdk0101", 2: "psychology"},
    4: {1: "mdk0102_docs", 2: "networks", 3: "mdk1101"},
    5: {1: "networks", 2: "mdk0101"},
    6: {1: "physcult", 2: "foreign", 3: "mdk1101"},
}

#: Нижняя неделя совпадает с верхней, кроме четверга (А.3).
LOWER_WEEK: dict[int, dict[int, str]] = {
    1: {1: "class_hour", 2: "mdk0101", 3: "mdk0102_support"},
    2: {1: "networks", 2: "mdk0101", 3: "mdk0102_support"},
    3: {1: "mdk0101", 2: "psychology"},
    4: {1: "mdk0102_docs", 2: "psychology", 3: "mdk1101"},
    5: {1: "networks", 2: "mdk0101"},
    6: {1: "physcult", 2: "foreign", 3: "mdk1101"},
}

WEEK_TEMPLATES: dict[str, dict[int, dict[int, str]]] = {
    "upper": UPPER_WEEK,
    "lower": LOWER_WEEK,
}

#: Ожидаемое число заполненных ячеек стартового набора (А.7 п. 2, ACC-S-11).
EXPECTED_FILLED_CELLS = 16


# ===========================================================================
# Шаблоны поездок (А.4)
# ===========================================================================
@dataclass(frozen=True)
class SeedLeg:
    mode: str
    vehicle: str
    payment_method: str


@dataclass(frozen=True)
class SeedTemplate:
    direction: str
    name: str
    legs: tuple[SeedLeg, ...]


TRIP_TEMPLATES: tuple[SeedTemplate, ...] = (
    SeedTemplate("home_to_college", "Электричка + №22", (
        SeedLeg("train", "Электричка", "train_student"),
        SeedLeg("bus", "22", "strelka"),
    )),
    SeedTemplate("home_to_college", "Прямой №42", (
        SeedLeg("bus", "42", "strelka"),
    )),
    SeedTemplate("home_to_college", "№35 + №22", (
        SeedLeg("bus", "35", "strelka"),
        SeedLeg("bus", "22", "strelka"),
    )),
    SeedTemplate("college_to_home", "Прямой №42", (
        SeedLeg("bus", "42", "strelka"),
    )),
    SeedTemplate("college_to_home", "№22 + №35", (
        SeedLeg("bus", "22", "strelka"),
        SeedLeg("bus", "35", "strelka"),
    )),
    SeedTemplate("college_to_home", "№22 + электричка", (
        SeedLeg("bus", "22", "strelka"),
        SeedLeg("train", "Электричка", "train_student"),
    )),
    SeedTemplate("college_to_home", "№22 + №44", (
        SeedLeg("bus", "22", "strelka"),
        SeedLeg("bus", "44", "strelka"),
    )),
)


@dataclass(frozen=True)
class SeedSummary:
    """Что именно загружено — для проверок слоя 2 и сообщений пользователю."""

    settings_added: int = 0
    anchor_added: bool = False
    subjects_added: int = 0
    profiles_added: int = 0
    slots_added: int = 0
    cells_added: int = 0
    tariffs_added: int = 0
    templates_added: int = 0

    @property
    def total(self) -> int:
        return (
            self.settings_added
            + int(self.anchor_added)
            + self.subjects_added
            + self.profiles_added
            + self.slots_added
            + self.cells_added
            + self.tariffs_added
            + self.templates_added
        )


__all__ = [
    "ANCHOR_EFFECTIVE_FROM",
    "ANCHOR_BASE_DATE",
    "ANCHOR_BASE_TYPE",
    "ANCHOR_CYCLE_LENGTH",
    "ANCHOR_COMMENT",
    "SeedTariff",
    "TARIFFS",
    "SeedSubject",
    "SUBJECTS",
    "SeedBlock",
    "PROFILE_BLOCKS",
    "PROFILE_NAMES",
    "UPPER_WEEK",
    "LOWER_WEEK",
    "WEEK_TEMPLATES",
    "EXPECTED_FILLED_CELLS",
    "SeedLeg",
    "SeedTemplate",
    "TRIP_TEMPLATES",
    "SeedSummary",
]
