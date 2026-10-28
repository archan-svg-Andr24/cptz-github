"""Сервисы расписания: редактор сетки, оверрайды, календарь, домашние задания.

Слой сервисов стоит между репозиториями и интерфейсом (этап 2 §1.12): он
содержит правила, которым нужно несколько репозиториев одновременно, и не
содержит ни одного обращения к PySide6 (PLAN-05).

* :class:`GridService` — §9.2: сетка недели, сохранение и очистка ячейки
  (GRID-01…GRID-11, SUBJ-05, DATA-20).
* :class:`OverrideService` — §10.2: отмена, замена, добавление, сброс даты,
  сиротские оверрайды (OVR-01…OVR-12, ALG-10).
* :class:`CalendarService` — §11: каникулы и праздники (CAL-01…CAL-09).
* :class:`HomeworkService` — §12: задания, фильтры, группировка (HW-01…HW-16).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from . import clock
from .dates import to_iso
from .day_resolution import DayResolver
from .errors import NotFoundError, ValidationError
from .models import (
    Direction,
    Homework,
    HomeworkStatus,
    OverrideType,
    ScheduleOverride,
    Subject,
    TemplateCell,
    WeekType,
)
from .repositories import (
    _UNSET,
    BellRepository,
    ScheduleOverrideRepository,
    ScheduleTemplateRepository,
    SubjectRepository,
    StudyPeriodRepository,
)
from .transport_repositories import HomeworkRepository

log = logging.getLogger(__name__)


# ===========================================================================
# §9.2 Редактор недельной сетки
# ===========================================================================
@dataclass(frozen=True)
class GridSlot:
    """Строка редактора: слот профиля дня и его содержимое в выбранной неделе."""

    slot_no: int
    block_type: str
    display_name: str
    pair_no: int | None
    start_time: str
    end_time: str
    is_two_part: bool
    subject_id: int | None = None
    subject_name: str = ""
    teacher: str = ""
    room: str = ""

    @property
    def is_empty(self) -> bool:
        """GRID-07: при отсутствии предмета ячейка пуста, «Очистить» неактивна."""
        return self.subject_id is None

    @property
    def caption(self) -> str:
        """GRID-07: в ячейке название, преподаватель и кабинет."""
        if self.is_empty:
            return ""
        parts = [self.subject_name]
        if self.teacher:
            parts.append(self.teacher)
        if self.room:
            parts.append(self.room)
        return ", ".join(parts)

    @property
    def time_caption(self) -> str:
        return f"{self.start_time}–{self.end_time}"


@dataclass(frozen=True)
class GridColumn:
    """Колонка редактора — один день недели (Пн–Сб)."""

    weekday: int
    caption: str
    profile_id: int | None
    slots: tuple[GridSlot, ...] = ()

    @property
    def has_profile(self) -> bool:
        return self.profile_id is not None


@dataclass
class GridView:
    """Вся недельная сетка на одном экране (GRID-01)."""

    week_type: str
    columns: tuple[GridColumn, ...] = ()
    orphan_warnings: list[str] = field(default_factory=list)

    @property
    def max_slots(self) -> int:
        """Число строк: максимум слотов по профилям недели."""
        return max((len(column.slots) for column in self.columns), default=0)

    @property
    def filled_count(self) -> int:
        return sum(
            1 for column in self.columns for slot in column.slots if not slot.is_empty
        )

    @property
    def week_type_caption(self) -> str:
        return "Верхняя неделя" if self.week_type == WeekType.UPPER else "Нижняя неделя"


class GridService:
    """§9.2: правка недельной сетки по одной ячейке (GRID-01…GRID-11)."""

    def __init__(self, db) -> None:
        self.db = db
        self.templates = ScheduleTemplateRepository(db)
        self.subjects = SubjectRepository(db)
        self.bells = BellRepository(db)
        self.overrides = ScheduleOverrideRepository(db)

    # ------------------------------------------------------------------ чтение
    def view(
        self,
        week_type: str,
        *,
        weekdays: tuple[int, ...] = (1, 2, 3, 4, 5, 6),
        on_date: date | str | None = None,
    ) -> GridView:
        """GRID-01/TPL-08: Пн–Сб × все слоты профиля на дату, включая пустые."""
        self._check_week_type(week_type)
        subjects = {item.id: item for item in self.subjects.all()}
        columns: list[GridColumn] = []

        for weekday in weekdays:
            profile = self._profile_of_weekday(weekday)
            if profile is None:
                columns.append(
                    GridColumn(weekday=weekday, caption=_weekday_caption(weekday), profile_id=None)
                )
                continue
            slots: list[GridSlot] = []
            for slot in profile.slots:
                cell = self.templates.cell(profile.id, week_type, slot.slot_no, on_date=on_date)
                subject = subjects.get(cell.subject_id) if cell else None  # type: ignore[union-attr]
                slots.append(
                    GridSlot(
                        slot_no=slot.slot_no,
                        block_type=slot.block_type,
                        display_name=slot.display_name,
                        pair_no=slot.pair_no,
                        start_time=slot.start_time,
                        end_time=slot.end_time,
                        is_two_part=slot.is_two_part,
                        subject_id=subject.id if subject else None,
                        subject_name=subject.name if subject else "",
                        teacher=subject.teacher if subject and subject.teacher else "",
                        room=subject.room if subject and subject.room else "",
                    )
                )
            columns.append(
                GridColumn(
                    weekday=weekday,
                    caption=_weekday_caption(weekday),
                    profile_id=profile.id,
                    slots=tuple(slots),
                )
            )

        return GridView(
            week_type=week_type,
            columns=tuple(columns),
            orphan_warnings=self._orphan_warnings(week_type),
        )

    def _profile_of_weekday(self, weekday: int):
        """Активный профиль дня по номеру дня недели (BELL-18)."""
        for profile in self.bells.profiles(include_inactive=False):
            if profile.weekday == weekday and profile.variant == "default":
                return profile
        return None

    def _orphan_warnings(self, week_type: str) -> list[str]:
        """GRID-06/ALG-10: сиротские оверрайды видны предупреждением, не удаляются."""
        found = self.overrides.orphans(week_type_for_date=lambda _value: week_type)
        if not found:
            return []
        return [
            f"Изменение от {item.date.strftime('%d.%m.%Y')} ссылается на занятие, "
            f"которого больше нет в сетке (блок {item.slot_no})."
            for item in found
        ]

    def subjects_for_cell(self) -> list[Subject]:
        """GRID-02: выпадающий список — только активные предметы."""
        return self.subjects.all(include_inactive=False)

    def search_subjects(self, query: str) -> list[Subject]:
        """GRID-02: автодополнение по названию, преподавателю и коду."""
        needle = query.strip().casefold()
        active = self.subjects_for_cell()
        if not needle:
            return active
        return [
            item
            for item in active
            if needle in item.name.casefold()
            or needle in (item.teacher or "").casefold()
            or needle in (item.code or "").casefold()
        ]

    # ------------------------------------------------------------------ запись
    def set_cell(
        self,
        profile_id: int,
        week_type: str,
        slot_no: int,
        subject_id: int | None,
        *,
        effective_from: date | str | None = None,
    ) -> TemplateCell | None:
        """GRID-02/DATA-20/TPL-08: выбор сохраняет ячейку сразу; ``None`` очищает.

        ``effective_from`` — дата, с которой действует правка: прошлые недели
        сохраняют прежнее расписание.
        """
        self._check_week_type(week_type)
        self._require_slot(profile_id, slot_no)
        if subject_id is not None:
            subject = self.subjects.by_id(subject_id)
            if subject is None:
                raise NotFoundError("Предмет не найден", details={"subject_id": subject_id})
            if not subject.is_active:
                raise ValidationError(
                    f"Предмет «{subject.name}» отключён: включите его в справочнике (SUBJ-03).",
                    field="subject_id",
                )
        return self.templates.set_cell(
            profile_id, week_type, slot_no, subject_id, effective_from=effective_from
        )

    def clear_cell(
        self,
        profile_id: int,
        week_type: str,
        slot_no: int,
        *,
        effective_from: date | str | None = None,
    ) -> None:
        """GRID-05/DATA-20/TPL-08: пара убирается с даты; прошлые недели целы."""
        self._check_week_type(week_type)
        self.templates.clear_cell(
            profile_id, week_type, slot_no, effective_from=effective_from
        )

    def create_subject_for_cell(
        self,
        profile_id: int,
        week_type: str,
        slot_no: int,
        *,
        name: str,
        code: str | None = None,
        teacher: str | None = None,
        room: str | None = None,
        effective_from: date | str | None = None,
    ) -> Subject:
        """SUBJ-05/GRID-02: новый предмет создаётся прямо из ячейки."""
        self._check_week_type(week_type)
        self._require_slot(profile_id, slot_no)
        subject = self.subjects.create(name, code=code, teacher=teacher, room=room)
        self.templates.set_cell(
            profile_id, week_type, slot_no, subject.id, effective_from=effective_from
        )
        return subject

    # ------------------------------------------------- GRID-11 восстановление
    def restore_seed_week(
        self, week_type: str, *, effective_from: date | str | None = None
    ) -> int:
        """GRID-11: вернуть строки выбранного типа недели из Прил. А.3.

        Оверрайды дат, профили звонков и второй тип недели не затрагиваются;
        повторный вызов идемпотентен (ACC-M-104).
        """
        from . import seed_data as seed

        self._check_week_type(week_type)
        entries: list[tuple[int, int, int]] = []
        for weekday, cells in seed.WEEK_TEMPLATES[week_type].items():
            profile = self._profile_of_weekday(weekday)
            if profile is None:
                continue
            for slot_no, subject_key in cells.items():
                subject_id = self._seed_subject_id(subject_key)
                if subject_id is None:
                    log.warning("Стартовый предмет %s отсутствует — ячейка пропущена", subject_key)
                    continue
                entries.append((profile.id, slot_no, subject_id))
        return self.templates.replace_week(week_type, entries, effective_from=effective_from)

    def _seed_subject_id(self, key: str) -> int | None:
        from . import seed_data as seed

        item = next((entry for entry in seed.SUBJECTS if entry.key == key), None)
        if item is None:  # pragma: no cover - набор статичен
            return None
        row = self.db.fetchone(
            "SELECT id FROM subjects WHERE name = ? AND code IS ?", (item.name, item.code)
        )
        return int(row["id"]) if row else None

    # ---------------------------------------------------------------- служебное
    @staticmethod
    def _check_week_type(week_type: str) -> None:
        if week_type not in (WeekType.UPPER, WeekType.LOWER):
            raise ValidationError(
                "Тип недели: только верхняя или нижняя (GRID-03).", field="week_type"
            )

    def _require_slot(self, profile_id: int, slot_no: int) -> None:
        row = self.db.fetchone(
            "SELECT 1 FROM bell_slots WHERE profile_id = ? AND slot_no = ?",
            (profile_id, slot_no),
        )
        if row is None:
            raise NotFoundError(
                "Блок звонков не найден: слоты настраиваются в справочнике звонков (GRID-05).",
                details={"profile_id": profile_id, "slot_no": slot_no},
            )


def _weekday_caption(weekday: int) -> str:
    from .dates import WEEKDAY_SHORT

    return WEEKDAY_SHORT[weekday]


# ===========================================================================
# §10.2 Оверрайды
# ===========================================================================
@dataclass
class DayChangeResult:
    """Итог правки оверрайда для показа пользователю."""

    override: ScheduleOverride | None
    removed: int = 0
    warnings: list[str] = field(default_factory=list)


class OverrideService:
    """§10.2: отмена, замена, добавление и сброс изменений даты (OVR-01…OVR-12)."""

    def __init__(self, db) -> None:
        self.db = db
        self.overrides = ScheduleOverrideRepository(db)
        self.templates = ScheduleTemplateRepository(db)
        self.bells = BellRepository(db)
        self.periods = StudyPeriodRepository(db)

    # ------------------------------------------------------------------ чтение
    def for_date(self, value: date) -> list[ScheduleOverride]:
        return self.overrides.for_date(value)

    def applied_for_date(self, value: date) -> list[ScheduleOverride]:
        """OVR-10: внутри периода ``no_classes = 1`` оверрайды не применяются."""
        if self.periods.covering(value, no_classes_only=True) is not None:
            return []
        return self.overrides.for_date(value)

    def week_type_of(self, value: date) -> str:
        return self.overrides.week_type_for(value)

    # ------------------------------------------------------------------ отмена
    def cancel(
        self,
        value: date,
        profile_id: int,
        slot_no: int,
        *,
        comment: str | None = None,
    ) -> ScheduleOverride:
        """OVR-04: блок помечается отменённым, остальные не смещаются.

        Если блок существует только благодаря ``add`` (в сетке пусто), отмена
        означает **удаление этой пары**. Иначе создавался бы ``cancel`` без
        занятия в сетке: ALG-10 считает его сиротским, показывается
        предупреждение, а повторная отмена упирается в OVR-08 — пользователь
        попадал в замкнутый круг.
        """
        subject_id = self.templates.subject_at(
            profile_id, self.week_type_of(value), slot_no, on_date=value
        )
        if subject_id is None:
            existing = self.overrides.for_date(value, profile_id=profile_id)
            added = [
                item for item in existing
                if item.slot_no == slot_no and item.override_type == OverrideType.ADD
            ]
            if added:
                # Убираем и саму добавленную пару, и осиротевшие cancel/replace
                # этого блока: без занятия в сетке они не имеют смысла.
                with self.db.transaction() as conn:
                    conn.execute(
                        "DELETE FROM schedule_overrides WHERE date = ? AND profile_id = ? "
                        "AND slot_no = ?",
                        (to_iso(value), profile_id, slot_no),
                    )
                log.info(
                    "Удалена добавленная пара %s, блок %s (OVR-04)",
                    to_iso(value), slot_no,
                )
                return added[-1]
        return self.overrides.create(
            value, profile_id, slot_no, OverrideType.CANCEL,
            subject_id=subject_id, comment=comment,
        )

    # ------------------------------------------------------------------ замена
    def replace(
        self,
        value: date,
        profile_id: int,
        slot_no: int,
        *,
        subject_id: int,
        teacher: str | None = None,
        room: str | None = None,
        custom_start: str | None = None,
        custom_end: str | None = None,
        comment: str | None = None,
    ) -> ScheduleOverride:
        """OVR-05: замена предмета; время по умолчанию сохраняется."""
        return self.overrides.create(
            value, profile_id, slot_no, OverrideType.REPLACE,
            subject_id=subject_id, teacher=teacher, room=room,
            custom_start=custom_start, custom_end=custom_end, comment=comment,
        )

    # --------------------------------------------------------------- добавление
    def add(
        self,
        value: date,
        profile_id: int,
        slot_no: int,
        *,
        subject_id: int,
        teacher: str | None = None,
        room: str | None = None,
        custom_start: str | None = None,
        custom_end: str | None = None,
        comment: str | None = None,
    ) -> ScheduleOverride:
        """OVR-07: добавление в свободный слот или на своё время."""
        return self.overrides.create(
            value, profile_id, slot_no, OverrideType.ADD,
            subject_id=subject_id, teacher=teacher, room=room,
            custom_start=custom_start, custom_end=custom_end, comment=comment,
        )

    # ------------------------------------------------------------- редактирование
    def edit(
        self,
        override_id: int,
        *,
        subject_id: int | None = None,
        teacher: str | None = None,
        room: str | None = None,
        custom_start: str | None = None,
        custom_end: str | None = None,
        comment: str | None = None,
    ) -> ScheduleOverride:
        """Правка подробностей; тип оверрайда не меняется (OVR-08).

        ``ScheduleOverrideRepository.update`` принимает изменения только через
        ``new_*``-аргументы: одноимённые ``subject_id``/``teacher``/``room``
        оставлены для обратной совместимости и игнорируются. Передаём именно
        ``new_*``, иначе правка молча не сохранялась.
        """
        return self.overrides.update(
            override_id,
            new_subject_id=subject_id if subject_id is not None else _UNSET,
            new_teacher=teacher if teacher is not None else _UNSET,
            new_room=room if room is not None else _UNSET,
            new_custom_start=custom_start if custom_start is not None else _UNSET,
            new_custom_end=custom_end if custom_end is not None else _UNSET,
            new_comment=comment if comment is not None else _UNSET,
        )

    def delete(self, override_id: int) -> None:
        self.overrides.delete(override_id)

    # --------------------------------------------------------------- сброс даты
    def reset_day(self, value: date, *, dry_run: bool = False) -> DayChangeResult:
        """SCH-09: сброс изменений даты — удаляются все оверрайды этой даты."""
        existing = self.overrides.for_date(value)
        if dry_run:
            return DayChangeResult(override=None, removed=len(existing))
        removed = self.overrides.delete_for_date(value)
        log.info("Сброшены изменения даты %s: %d записей", to_iso(value), removed)
        return DayChangeResult(override=None, removed=removed)

    # ------------------------------------------------------------------ сироты
    def orphans(self) -> list[ScheduleOverride]:
        """ALG-10: ``cancel``/``replace`` без занятия в шаблоне."""
        return self.overrides.orphans(week_type_for_date=self.week_type_of)

    def delete_orphans(self) -> list[ScheduleOverride]:
        return self.overrides.delete_orphans(week_type_for_date=self.week_type_of)

    def warnings_for_date(self, value: date) -> list[str]:
        """SCH-17: сиротские изменения не применяются, но показываются предупреждением."""
        week_type = self.week_type_of(value)
        return [
            f"Изменение на {item.date.strftime('%d.%m.%Y')} (блок {item.slot_no}) "
            "ссылается на занятие, которого нет в сетке: оно не применено."
            for item in self.overrides.for_date(value)
            if self.overrides.is_orphan(item, week_type)
        ]

    # ---------------------------------------------------------------- проверки
    def can_cancel(self, value: date, profile_id: int, slot_no: int) -> bool:
        """Кнопка «Отменить пару» активна только при занятии по шаблону."""
        return (
            self.templates.subject_at(
                profile_id, self.week_type_of(value), slot_no, on_date=value
            ) is not None
        )


# ===========================================================================
# §11 Учебный календарь
# ===========================================================================
@dataclass(frozen=True)
class CalendarEntry:
    """Строка календаря: период с подписью вида и числа дней."""

    period_id: int
    kind: str
    title: str
    start_date: date
    end_date: date
    no_classes: bool
    comment: str = ""

    @property
    def kind_caption(self) -> str:
        from .models import PeriodKind

        return PeriodKind.label(self.kind)

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def bounds_caption(self) -> str:
        return (
            f"{self.start_date.strftime('%d.%m.%Y')} — "
            f"{self.end_date.strftime('%d.%m.%Y')}"
        )


class CalendarService:
    """§11: каникулы и праздники вносит пользователь (CAL-01…CAL-09)."""

    #: CAL-02: виды MVP. Остальные виды — v1.1.
    MVP_KINDS = ("vacation", "holiday")

    def __init__(self, db) -> None:
        self.db = db
        self.periods = StudyPeriodRepository(db)

    def all(self, *, start: date | None = None, end: date | None = None) -> list[CalendarEntry]:
        items = (
            self.periods.for_range(start, end)
            if start and end
            else self.periods.all()
        )
        return [self._entry(item) for item in items]

    def for_month(self, year: int, month: int) -> list[CalendarEntry]:
        from .dates import month_bounds

        start, end = month_bounds(date(year, month, 1))
        return self.all(start=start, end=end)

    def entry(self, period_id: int) -> CalendarEntry:
        found = self.periods.by_id(period_id)
        if found is None:
            raise NotFoundError("Период не найден", details={"period_id": period_id})
        return self._entry(found)

    def create(
        self,
        kind: str,
        title: str,
        start_date: date,
        end_date: date,
        *,
        comment: str | None = None,
    ) -> CalendarEntry:
        """CAL-01/CAL-04: пользователь создаёт период вручную."""
        self._check_kind(kind)
        period = self.periods.create(
            kind, title, start_date, end_date, no_classes=True, comment=comment
        )
        return self._entry(period)

    def update(
        self,
        period_id: int,
        *,
        kind: str | None = None,
        title: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        comment: str | None = None,
    ) -> CalendarEntry:
        if kind is not None:
            self._check_kind(kind)
        return self._entry(
            self.periods.update(
                period_id,
                kind=kind,
                title=title,
                date_from=start_date,
                date_to=end_date,
                comment=comment,
            )
        )

    def delete(self, period_id: int) -> None:
        self.periods.delete(period_id)

    def period_at(self, value: date) -> CalendarEntry | None:
        """CAL-09: страница расписания показывает название периода вместо сетки."""
        found = self.periods.covering(value)
        return self._entry(found) if found else None

    def is_day_off(self, value: date) -> bool:
        found = self.periods.covering(value)
        return bool(found and found.no_classes)

    # ---------------------------------------------------------------- служебное
    @classmethod
    def _check_kind(cls, kind: str) -> None:
        if kind not in cls.MVP_KINDS:
            raise ValidationError(
                "Вид периода в MVP: каникулы или праздник (CAL-02).", field="kind"
            )

    @staticmethod
    def _entry(period) -> CalendarEntry:
        return CalendarEntry(
            period_id=period.id,
            kind=period.kind,
            title=period.title,
            start_date=period.date_from,
            end_date=period.date_to,
            no_classes=bool(period.no_classes),
            comment=period.comment or "",
        )


# ===========================================================================
# §12 Домашние задания
# ===========================================================================
@dataclass(frozen=True)
class HomeworkGroup:
    """Группа списка заданий: заголовок и записи (HW-12)."""

    caption: str
    items: tuple[Homework, ...]
    is_overdue: bool = False

    @property
    def count(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class HomeworkRow:
    """Строка списка: задание и подписи для интерфейса (HW-12)."""

    homework: Homework
    subject_name: str
    due_caption: str
    status_caption: str
    is_overdue: bool

    @property
    def description(self) -> str:
        return self.homework.description or ""

    @property
    def short_description(self) -> str:
        text = self.description
        return text if len(text) <= 80 else text[:77] + "…"


class HomeworkService:
    """§12: задания с фильтрами и группировкой по дате сдачи (HW-01…HW-16)."""

    def __init__(self, db) -> None:
        self.db = db
        self.repo = HomeworkRepository(db)
        self.subjects = SubjectRepository(db)

    # ------------------------------------------------------------------ чтение
    def rows(
        self,
        *,
        status: str | None = None,
        subject_id: int | None = None,
        only_overdue: bool = False,
        today: date | None = None,
        include_inactive_subjects: bool = True,
    ) -> list[HomeworkRow]:
        """HW-13: фильтры «Активные», «Выполненные», «Просроченные», «Все», по предмету."""
        base = today or clock.today()
        items = self.repo.filtered(
            status=status,
            subject_id=subject_id,
            only_overdue=only_overdue,
            overdue_before=base if only_overdue else None,
            include_inactive_subjects=include_inactive_subjects,
        )
        names = {item.id: item.name for item in self.subjects.all()}
        return [
            HomeworkRow(
                homework=item,
                subject_name=names.get(item.subject_id, "—"),
                due_caption=item.due_date.strftime("%d.%m.%Y"),
                status_caption=HomeworkStatus.LABELS[item.status],
                is_overdue=item.is_overdue(base),
            )
            for item in items
        ]

    def groups(
        self,
        *,
        status: str | None = None,
        subject_id: int | None = None,
        only_overdue: bool = False,
        today: date | None = None,
    ) -> list[HomeworkGroup]:
        """HW-12: группировка по дате сдачи, просроченные — отдельной группой."""
        base = today or clock.today()
        rows = self.rows(
            status=status, subject_id=subject_id, only_overdue=only_overdue, today=base
        )
        overdue = tuple(row for row in rows if row.is_overdue)
        upcoming = [row for row in rows if not row.is_overdue]

        result: list[HomeworkGroup] = []
        if overdue:
            result.append(
                HomeworkGroup(caption="Просроченные", items=overdue, is_overdue=True)
            )
        by_date: dict[date, list[HomeworkRow]] = {}
        for row in upcoming:
            by_date.setdefault(row.homework.due_date, []).append(row)
        for due_date in sorted(by_date):
            items = by_date[due_date]
            result.append(
                HomeworkGroup(
                    caption=_due_caption(due_date, base),
                    items=tuple(sorted(items, key=lambda row: row.homework.id)),
                )
            )
        return result

    def upcoming(self, *, today: date | None = None) -> list[HomeworkRow]:
        """HW-05/UI-10: задания на текущую и следующую недели (кроме просроченных)."""
        base = today or clock.today()
        items = self.repo.upcoming(today=base)
        names = {item.id: item.name for item in self.subjects.all()}
        return [
            HomeworkRow(
                homework=item,
                subject_name=names.get(item.subject_id, "—"),
                due_caption=item.due_date.strftime("%d.%m.%Y"),
                status_caption=HomeworkStatus.LABELS[item.status],
                is_overdue=False,
            )
            for item in items
        ]

    @property
    def upcoming_empty_caption(self) -> str:
        """HW-05/HW-14: состояние «Заданий нет»."""
        return "Заданий нет"

    def badge(self, subject_id: int, value: date) -> int:
        """HW-06: счётчик заданий для бейджа на карточке занятия."""
        return sum(
            1
            for item in self.repo.for_subject_date(subject_id, value)
            if item.is_active
        )

    def due_dates(self, start: date | None = None, end: date | None = None) -> set[date]:
        return self.repo.due_dates(start, end)

    def subject_choices(self) -> list[Subject]:
        """HW-14: при пустом справочнике предметов показывается подсказка."""
        return self.subjects.all(include_inactive=False)

    @property
    def has_subjects(self) -> bool:
        return bool(self.subject_choices())

    @property
    def empty_hint(self) -> str:
        """HW-14: подсказка при пустом справочнике предметов."""
        return (
            "Сначала добавьте предмет"
            if not self.has_subjects
            else self.upcoming_empty_caption
        )

    # ------------------------------------------------------------------ запись
    def create(
        self,
        subject_id: int,
        due_date: date,
        description: str | None = None,
    ) -> Homework:
        """HW-07: быстрый ввод в пределах трёх полей (UI-14)."""
        return self.repo.create(subject_id, due_date, description)

    def update(
        self,
        homework_id: int,
        *,
        subject_id: int | None = None,
        due_date: date | None = None,
        description: str | None = None,
    ) -> Homework:
        return self.repo.update(
            homework_id,
            subject_id=subject_id,
            due_date=due_date,
            description=description,
        )

    def toggle(self, homework_id: int) -> Homework:
        """HW-15: отметка выполнения одним действием, без диалога."""
        return self.repo.toggle(homework_id)

    def set_done(self, homework_id: int, done: bool = True) -> Homework:
        return self.repo.set_status(
            homework_id, HomeworkStatus.DONE if done else HomeworkStatus.ACTIVE
        )

    def delete(self, homework_id: int, *, confirmed: bool = False) -> None:
        """HW-16: ``active`` удаляется без подтверждения, ``done`` — с подтверждением."""
        current = self.repo.require(homework_id)
        if current.status == HomeworkStatus.DONE and not confirmed:
            raise ValidationError(
                "Выполненное задание удаляется только после подтверждения (HW-16).",
                field="confirmed",
            )
        self.repo.delete(homework_id)

    def needs_confirmation(self, homework_id: int) -> bool:
        """HW-16: интерфейс спрашивает подтверждение только для ``done``."""
        return self.repo.require(homework_id).status == HomeworkStatus.DONE


def _due_caption(due_date: date, today: date) -> str:
    """Заголовок группы: «Сегодня», «Завтра» или дата с днём недели."""
    from .dates import WEEKDAY_NAMES

    delta = (due_date - today).days
    if delta == 0:
        return "Сегодня"
    if delta == 1:
        return "Завтра"
    return f"{due_date.strftime('%d.%m.%Y')}, {WEEKDAY_NAMES[due_date.isoweekday()]}"


__all__ = [
    "GridService",
    "GridView",
    "GridColumn",
    "GridSlot",
    "OverrideService",
    "DayChangeResult",
    "CalendarService",
    "CalendarEntry",
    "HomeworkService",
    "HomeworkGroup",
    "HomeworkRow",
]
