"""Модели предметной области (неизменяемые снимки строк БД).

Модели — это **значения**, а не ORM-сущности: репозитории читают строки и
возвращают объекты, а запись выполняется явными SQL-операциями. Такой подход
сохраняет контроль над транзакциями (DATA-08, CALC-04) и не тянет зависимость
SQLAlchemy (GEN-14 допускает ``sqlite3``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Final

from .money import ZERO


# ---------------------------------------------------------------- статусы
class WeekType:
    UPPER: Final = "upper"
    LOWER: Final = "lower"

    LABELS: Final = {UPPER: "Верхняя", LOWER: "Нижняя"}

    @classmethod
    def opposite(cls, value: str) -> str:
        return cls.LOWER if value == cls.UPPER else cls.UPPER

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", "—")


class PaymentMethod:
    STRELKA: Final = "strelka"
    DEBIT_CARD: Final = "debit_card"
    TRAIN_STUDENT: Final = "train_student"

    ALL: Final = (STRELKA, DEBIT_CARD, TRAIN_STUDENT)
    LABELS: Final = {
        STRELKA: "Стрелка",
        DEBIT_CARD: "Дебетовая карта",
        TRAIN_STUDENT: "Студенческий билет",
    }
    #: Способы оплаты автобуса (FARE-05): наличных нет.
    BUS: Final = (STRELKA, DEBIT_CARD)

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", value or "—")


class TransportType:
    TRAIN: Final = "train"
    BUS: Final = "bus"

    ALL: Final = (TRAIN, BUS)
    LABELS: Final = {TRAIN: "Электричка", BUS: "Автобус"}

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", value or "—")


class Direction:
    HOME_TO_COLLEGE: Final = "home_to_college"
    COLLEGE_TO_HOME: Final = "college_to_home"

    ALL: Final = (HOME_TO_COLLEGE, COLLEGE_TO_HOME)
    LABELS: Final = {HOME_TO_COLLEGE: "Дом → Колледж", COLLEGE_TO_HOME: "Колледж → Дом"}
    SHORT: Final = {HOME_TO_COLLEGE: "Туда", COLLEGE_TO_HOME: "Обратно"}

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", value or "—")

    @classmethod
    def short(cls, value: str | None) -> str:
        return cls.SHORT.get(value or "", value or "—")


class TariffKind:
    TRAIN_BASE: Final = "train_base"
    TRAIN_STUDENT: Final = "train_student"
    BUS_BASE: Final = "bus_base"
    STRELKA_STAGE1: Final = "strelka_stage1"
    STRELKA_STAGE2: Final = "strelka_stage2"

    ALL: Final = (TRAIN_BASE, TRAIN_STUDENT, BUS_BASE, STRELKA_STAGE1, STRELKA_STAGE2)
    LABELS: Final = {
        TRAIN_BASE: "Электричка, базовая",
        TRAIN_STUDENT: "Электричка, студенческая",
        BUS_BASE: "Автобус, базовая",
        STRELKA_STAGE1: "«Стрелка», 1-я ступень",
        STRELKA_STAGE2: "«Стрелка», 2-я ступень",
    }
    BASE_KINDS: Final = (TRAIN_BASE, BUS_BASE)
    STAGE_KINDS: Final = (STRELKA_STAGE1, STRELKA_STAGE2)

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", value or "—")

    @classmethod
    def is_base(cls, value: str) -> bool:
        return value in cls.BASE_KINDS


class OverrideType:
    CANCEL: Final = "cancel"
    REPLACE: Final = "replace"
    ADD: Final = "add"
    MOVE: Final = "move"

    #: Допустимые типы в MVP: перенос (`move`) относится к v1.1 (OVR-02, ACC-M-103).
    MVP: Final = (CANCEL, REPLACE, ADD)
    ALL: Final = (CANCEL, REPLACE, ADD, MOVE)
    LABELS: Final = {
        CANCEL: "Отменено",
        REPLACE: "Заменено",
        ADD: "Добавлено",
        MOVE: "Перенесено",
    }

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", value or "—")


class LessonStatus:
    """Статусы карточки занятия (SCH-05)."""

    PLANNED: Final = "planned"
    CANCELLED: Final = "cancelled"
    REPLACED: Final = "replaced"
    ADDED: Final = "added"

    LABELS: Final = {
        PLANNED: "По плану",
        CANCELLED: "Отменено",
        REPLACED: "Заменено",
        ADDED: "Добавлено",
    }

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", value or "—")


class PeriodKind:
    VACATION: Final = "vacation"
    HOLIDAY: Final = "holiday"
    PRACTICE_EDUCATIONAL: Final = "practice_educational"
    PRACTICE_INDUSTRIAL: Final = "practice_industrial"
    EXAM_SESSION: Final = "exam_session"

    #: Виды MVP (CAL-02). Остальные — резерв v1.1.
    MVP: Final = (VACATION, HOLIDAY)
    ALL: Final = (VACATION, HOLIDAY, PRACTICE_EDUCATIONAL, PRACTICE_INDUSTRIAL, EXAM_SESSION)
    LABELS: Final = {
        VACATION: "Каникулы",
        HOLIDAY: "Праздник",
        PRACTICE_EDUCATIONAL: "Практика (учебная)",
        PRACTICE_INDUSTRIAL: "Практика (производственная)",
        EXAM_SESSION: "Экзаменационная сессия",
    }

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", value or "—")

    @classmethod
    def icon(cls, value: str | None) -> str:
        return {cls.VACATION: "☀", cls.HOLIDAY: "★"}.get(value or "", "•")


class HomeworkStatus:
    ACTIVE: Final = "active"
    DONE: Final = "done"

    ALL: Final = (ACTIVE, DONE)
    LABELS: Final = {ACTIVE: "Активное", DONE: "Выполнено"}

    @classmethod
    def label(cls, value: str | None) -> str:
        return cls.LABELS.get(value or "", value or "—")


# ------------------------------------------------------------------ записи
@dataclass(frozen=True)
class Subject:
    id: int
    code: str | None
    name: str
    teacher: str | None = None
    room: str | None = None
    color: str | None = None
    is_active: bool = True

    @property
    def caption(self) -> str:
        """Название с преподавателем и кабинетом (SUBJ-03)."""
        extras = [part for part in (self.teacher, self.room) if part]
        return f"{self.name} · " + " · ".join(extras) if extras else self.name

    @property
    def search_text(self) -> str:
        """Текст для автодополнения по названию, преподавателю и коду (GRID-02)."""
        return " ".join(part for part in (self.name, self.code, self.teacher, self.room) if part).lower()


@dataclass(frozen=True)
class Tariff:
    id: int
    kind: str
    price: Decimal
    effective_from: date
    effective_to: date | None
    vehicle: str | None = None
    is_active: bool = True
    comment: str | None = None

    def covers(self, value: date) -> bool:
        """Действует ли тариф на дату (ALG-09 шаг 2)."""
        if not self.is_active:
            return False
        if value < self.effective_from:
            return False
        return self.effective_to is None or value <= self.effective_to


@dataclass(frozen=True)
class WeekAnchor:
    id: int
    effective_from: date
    base_date: date
    base_type: str
    cycle_length: int = 2
    comment: str | None = None


@dataclass(frozen=True)
class BellPart:
    id: int
    slot_id: int
    seq: int
    part_type: str
    start_time: str
    end_time: str


@dataclass(frozen=True)
class BellSlot:
    id: int
    profile_id: int
    slot_no: int
    pair_no: int | None
    block_type: str
    display_name: str | None
    sort_order: int | None
    parts: tuple[BellPart, ...] = ()

    @property
    def start_time(self) -> str | None:
        """Начало блока = начало первой части (BELL-06)."""
        return self.parts[0].start_time if self.parts else None

    @property
    def end_time(self) -> str | None:
        """Окончание блока = окончание последней части (BELL-06)."""
        return self.parts[-1].end_time if self.parts else None

    @property
    def time_range(self) -> str:
        if not self.parts:
            return ""
        return f"{self.start_time}–{self.end_time}"

    @property
    def is_two_part(self) -> bool:
        return len([part for part in self.parts if part.part_type == "lesson"]) > 1

    @property
    def caption(self) -> str:
        if self.display_name:
            return self.display_name
        if self.pair_no is not None:
            return f"{self.pair_no} пара"
        return f"Блок {self.slot_no}"


@dataclass(frozen=True)
class BellProfile:
    id: int
    weekday: int
    variant: str
    name: str
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool = True
    slots: tuple[BellSlot, ...] = ()

    def covers(self, value: date) -> bool:
        if not self.is_active:
            return False
        if self.effective_from and value < self.effective_from:
            return False
        if self.effective_to and value > self.effective_to:
            return False
        return True

    def slot(self, slot_no: int) -> BellSlot | None:
        for item in self.slots:
            if item.slot_no == slot_no:
                return item
        return None


@dataclass(frozen=True)
class TemplateCell:
    """Занятие шаблона: ``(profile_id, week_type, slot_no) → subject_id`` (TPL-01)."""

    id: int
    profile_id: int
    week_type: str
    slot_no: int
    subject_id: int | None
    group_mark: int | None = None


@dataclass(frozen=True)
class ScheduleOverride:
    id: int
    date: date
    profile_id: int
    slot_no: int
    override_type: str
    subject_id: int | None = None
    teacher: str | None = None
    room: str | None = None
    custom_start: str | None = None
    custom_end: str | None = None
    target_slot_no: int | None = None
    keep_original: int = 0
    comment: str | None = None
    created_at: str = ""
    group_mark: int | None = None
    part_seq: int | None = None


@dataclass(frozen=True)
class StudyPeriod:
    id: int
    kind: str
    title: str
    date_from: date
    date_to: date
    no_classes: bool = True
    place: str | None = None
    is_active: bool = True
    comment: str | None = None
    outbound_template_id: int | None = None
    return_template_id: int | None = None

    def covers(self, value: date) -> bool:
        return self.is_active and self.date_from <= value <= self.date_to

    @property
    def kind_label(self) -> str:
        return PeriodKind.label(self.kind)


@dataclass(frozen=True)
class TripLeg:
    id: int
    template_id: int
    seq: int
    mode: str
    vehicle: str
    payment_method: str
    is_paid: bool = True

    @property
    def caption(self) -> str:
        return f"{TransportType.label(self.mode)} {self.vehicle}"


@dataclass(frozen=True)
class TripTemplate:
    id: int
    direction: str
    name: str
    is_active: bool = True
    default_payment_method: str | None = None
    depart_hint: str | None = None
    arrive_hint: str | None = None
    note: str | None = None
    sort_order: int | None = None
    legs: tuple[TripLeg, ...] = ()

    @property
    def caption(self) -> str:
        if not self.legs:
            return self.name
        return f"{self.name} ({', '.join(leg.caption for leg in self.legs)})"

    @property
    def modes(self) -> tuple[str, ...]:
        return tuple(sorted({leg.mode for leg in self.legs}))


@dataclass(frozen=True)
class TripConfirmation:
    id: int
    study_date: date
    outbound_template_id: int | None
    return_template_id: int | None
    include_outbound: bool
    include_return: bool
    confirmed_at: str
    week_type_snapshot: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class Ride:
    id: int
    study_date: date
    ride_date: date
    direction: str
    transport_type: str
    vehicle: str
    base_price: Decimal
    paid_price: Decimal
    discount_amount: Decimal
    payment_method: str
    confirmation_id: int | None = None
    template_id: int | None = None
    template_leg_id: int | None = None
    period_id: int | None = None
    tariff_id: int | None = None
    period_start_date: date | None = None
    ride_number_in_period: int | None = None
    week_type_snapshot: str | None = None
    is_manual: bool = False
    price_locked: bool = False
    comment: str | None = None
    created_at: str = ""

    @property
    def is_counted(self) -> bool:
        """Засчитанная поездка — только ``strelka`` (DATA-14)."""
        return self.payment_method == PaymentMethod.STRELKA

    @property
    def period_end_date(self) -> date | None:
        """Конец периода = начало + 29 дней (REP-05)."""
        if self.period_start_date is None:
            return None
        from datetime import timedelta

        return self.period_start_date + timedelta(days=29)


@dataclass(frozen=True)
class TopUp:
    id: int
    topup_date: date
    amount: Decimal
    fee: Decimal = ZERO
    method: str | None = None
    comment: str | None = None
    created_at: str = ""

    @property
    def net(self) -> Decimal:
        return self.amount - self.fee


@dataclass(frozen=True)
class Homework:
    id: int
    subject_id: int
    due_date: date
    description: str | None = None
    status: str = HomeworkStatus.ACTIVE
    created_at: str = ""
    completed_at: str | None = None
    group_mark: int | None = None

    @property
    def is_active(self) -> bool:
        return self.status == HomeworkStatus.ACTIVE

    def is_overdue(self, today: date) -> bool:
        """Просрочка вычисляется, а не хранится (HW-08)."""
        return self.is_active and self.due_date < today

    def days_left(self, today: date) -> int:
        return (self.due_date - today).days


# ------------------------------------------------------- разрешение дня
@dataclass(frozen=True)
class DayLesson:
    """Занятие фактического расписания даты (ALG-04 шаг 4)."""

    slot_no: int
    profile_id: int
    subject: Subject | None = None
    teacher: str | None = None
    room: str | None = None
    status: str = LessonStatus.PLANNED
    override_id: int | None = None
    custom_start: str | None = None
    custom_end: str | None = None
    block: BellSlot | None = None
    comment: str | None = None
    homework_count: int = 0

    @property
    def slot(self) -> BellSlot | None:
        return self.block

    @property
    def pair_no(self) -> int | None:
        return self.block.pair_no if self.block else None

    @property
    def start_time(self) -> str | None:
        return self.custom_start or (self.block.start_time if self.block else None)

    @property
    def end_time(self) -> str | None:
        return self.custom_end or (self.block.end_time if self.block else None)

    @property
    def time_range(self) -> str:
        if not self.start_time:
            return ""
        return f"{self.start_time}–{self.end_time}"

    @property
    def subject_name(self) -> str:
        return self.subject.name if self.subject else (self.block.caption if self.block else "Занятие")

    @property
    def is_cancelled(self) -> bool:
        return self.status == LessonStatus.CANCELLED

    @property
    def status_label(self) -> str:
        return LessonStatus.label(self.status)


@dataclass(frozen=True)
class DayResolution:
    """Результат ALG-04: что показывать на дату."""

    date: date
    week_type: str | None = None
    weekday: int = 1
    lessons: tuple[DayLesson, ...] = ()
    period: StudyPeriod | None = None
    profile: BellProfile | None = None
    orphan_overrides: tuple[ScheduleOverride, ...] = ()
    reason: str = ""

    @property
    def is_day_off(self) -> bool:
        """Занятий нет из-за периода с ``no_classes = 1`` (CAL-09)."""
        return self.period is not None and self.period.no_classes

    @property
    def has_lessons(self) -> bool:
        return any(not lesson.is_cancelled for lesson in self.lessons)

    @property
    def has_any_block(self) -> bool:
        """Есть ли что показывать (включая отменённые блоки)."""
        return bool(self.lessons)

    @property
    def time_bounds(self) -> tuple[str | None, str | None]:
        """``T_start`` / ``T_end`` (ALG-05): первое и последнее неотменённое занятие."""
        active = [lesson for lesson in self.lessons if not lesson.is_cancelled and lesson.start_time]
        if not active:
            return None, None
        starts = [lesson.start_time or "" for lesson in active]
        ends = [lesson.end_time or "" for lesson in active if lesson.end_time]
        return min(starts) or None, (max(ends) if ends else None)

    @property
    def empty_caption(self) -> str:
        if self.is_day_off and self.period is not None:
            return f"{self.period.kind_label}: {self.period.title}"
        return "Занятий нет"

    @property
    def week_type_label(self) -> str:
        return WeekType.label(self.week_type)


__all__ = [
    "WeekType",
    "PaymentMethod",
    "TransportType",
    "Direction",
    "TariffKind",
    "OverrideType",
    "LessonStatus",
    "PeriodKind",
    "HomeworkStatus",
    "Subject",
    "Tariff",
    "WeekAnchor",
    "BellPart",
    "BellSlot",
    "BellProfile",
    "TemplateCell",
    "ScheduleOverride",
    "StudyPeriod",
    "TripLeg",
    "TripTemplate",
    "TripConfirmation",
    "Ride",
    "TopUp",
    "Homework",
    "DayLesson",
    "DayResolution",
]
