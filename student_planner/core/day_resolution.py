"""ALG-04 — разрешение учебного дня; ALG-05 — границы времени дня.

Приоритет источников при ответе на вопрос «что сегодня»:
**период → профиль звонков → шаблон недели → оверрайд** (ALG-04).
Остановка на первом сработавшем шаге:

1. Период, содержащий дату, с ``no_classes = 1`` → занятий нет, показывается
   название (при пересечении — последний созданный период, CAL-03).
2. Профиль звонков: вариант для дня недели, действующий на дату (BELL-18).
   В MVP вариант всегда ``default``.
3. Шаблон расписания ``(profile_id, тип недели по ALG-01, slot_no)``.
4. Оверрайды даты (OVR-08, ALG-10) → фактическое расписание. Слоты без
   занятия и без оверрайда в дне не отображаются (SCH-03). Внутри периода с
   ``no_classes = 1`` оверрайды не применяются (OVR-10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .database import Database
from .dates import WEEKDAY_NAMES, date_range, format_display, monday_of
from .models import (
    BellProfile,
    DayLesson,
    DayResolution,
    Homework,
    LessonStatus,
    OverrideType,
    ScheduleOverride,
    StudyPeriod,
    Subject,
    WeekType,
)
from .repositories import (
    BellRepository,
    ScheduleOverrideRepository,
    ScheduleTemplateRepository,
    StudyPeriodRepository,
    SubjectRepository,
    WeekAnchorRepository,
)
from .transport_repositories import HomeworkRepository, TripConfirmationRepository
from .weektype import week_type_for


@dataclass
class _Context:
    """Кэш справочников на один вызов разрешения дня."""

    anchors: list
    subjects: dict[int, Subject]
    homework_by_subject: dict[int, list[Homework]]


class DayResolver:
    """ALG-04: фактическое расписание даты.

    Один экземпляр кэширует якоря, предметы и задания; для перерисовки недели
    вызывающий создаёт новый экземпляр (данные меняются во время работы).
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self._anchors = WeekAnchorRepository(db)
        self._bells = BellRepository(db)
        self._templates = ScheduleTemplateRepository(db)
        self._overrides = ScheduleOverrideRepository(db)
        self._periods = StudyPeriodRepository(db)
        self._subjects = SubjectRepository(db)
        self._homework = HomeworkRepository(db)
        self._context_cache: _Context | None = None

    # ------------------------------------------------------------ контекст
    def _context(self) -> _Context:
        if self._context_cache is None:
            subjects = {subject.id: subject for subject in self._subjects.all()}
            self._context_cache = _Context(
                anchors=self._anchors.all(),
                subjects=subjects,
                homework_by_subject={},
            )
        return self._context_cache

    def week_type(self, when: date) -> str | None:
        """ALG-01: тип недели даты по действующему якорю."""
        return week_type_for(self._context().anchors, when)

    def period_for(self, when: date) -> StudyPeriod | None:
        """Период, отменяющий занятия на дату (ALG-04 шаг 1)."""
        return self._periods.covering(when, no_classes_only=True)

    def profile_for(self, when: date) -> BellProfile | None:
        """Профиль звонков, действующий на дату (BELL-18)."""
        return self._bells.profile_for(when)

    # ------------------------------------------------------------- разрешение
    def resolve(self, when: date) -> DayResolution:
        """Полное разрешение дня по ALG-04."""
        context = self._context()
        weekday = when.isoweekday()
        week_type = week_type_for(context.anchors, when)

        # --- Шаг 1: период отменяет занятия целиком -----------------------
        period = self._periods.covering(when, no_classes_only=True)
        if period is not None:
            orphan_ids = self._orphan_ids_placeholder()
            return DayResolution(
                date=when,
                week_type=week_type,
                weekday=weekday,
                lessons=(),
                period=period,
                profile=self._bells.profile_for(when),
                orphan_overrides=orphan_ids,
                reason=f"{period.kind_label}: {period.title}",
            )

        # --- Шаг 2: профиль звонков ---------------------------------------
        if weekday == 7:
            # SCH-16: воскресенье в сетку не входит; отдельная строка — только для
            # периодов/событий (актуально с v1.1). В MVP содержимого нет.
            return DayResolution(
                date=when,
                week_type=week_type,
                weekday=weekday,
                lessons=(),
                period=None,
                profile=None,
                reason="Воскресенье",
            )

        profile = self._bells.profile_for(when)
        if profile is None:
            return DayResolution(
                date=when,
                week_type=week_type,
                weekday=weekday,
                lessons=(),
                profile=None,
                reason="Профиль звонков не задан",
            )

        # --- Шаг 3: шаблон недели на эту дату -------------------------------
        # TPL-08: шаблон версионный, поэтому читаем версию, действующую именно
        # на разрешаемую дату, а не «текущую».
        template = {
            cell.slot_no: cell
            for cell in self._templates.cells(
                week_type or WeekType.LOWER, profile_id=profile.id, on_date=when
            )
        }
        overrides = {
            item.slot_no: item for item in self._overrides.for_date(when, profile_id=profile.id)
        }
        orphan_overrides = tuple(
            item
            for item in overrides.values()
            if self._is_orphan(item, week_type, profile.id, template)
        )

        lessons: list[DayLesson] = []
        for slot in profile.slots:
            lesson = self._build_lesson(
                when=when,
                profile=profile,
                slot=slot,
                cell=template.get(slot.slot_no),
                override=overrides.get(slot.slot_no),
                week_type=week_type or WeekType.LOWER,
                context=context,
            )
            if lesson is not None:
                lessons.append(lesson)

        # Оверрайды `add` в слоты, которых нет в профиле (пользовательское время).
        for slot_no, override in sorted(overrides.items()):
            if override.override_type != OverrideType.ADD:
                continue
            if profile.slot(slot_no) is not None:
                continue
            # Слот удалён из профиля, но занятие добавлено — показываем без блока.
            lessons.append(
                DayLesson(
                    slot_no=slot_no,
                    profile_id=profile.id,
                    subject=context.subjects.get(override.subject_id or 0),
                    teacher=override.teacher,
                    room=override.room,
                    status=LessonStatus.ADDED,
                    override_id=override.id,
                    custom_start=override.custom_start,
                    custom_end=override.custom_end,
                    block=None,
                    comment=override.comment,
                    homework_count=0,
                )
            )

        lessons.sort(key=lambda item: (item.start_time or "99:99", item.slot_no))
        return DayResolution(
            date=when,
            week_type=week_type,
            weekday=weekday,
            lessons=tuple(lessons),
            period=None,
            profile=profile,
            orphan_overrides=orphan_overrides,
            reason="" if lessons else "Занятий нет",
        )

    def resolve_week(self, start: date) -> list[DayResolution]:
        """Неделя Пн–Вс от ``start``: текущая, следующая или выбранная (SCH-02)."""
        monday = monday_of(start)
        return [self.resolve(date.fromordinal(monday.toordinal() + offset)) for offset in range(7)]

    def resolve_range(self, start: date, end: date) -> list[DayResolution]:
        if end < start:
            return []
        return [self.resolve(date.fromordinal(start.toordinal() + offset))
                for offset in range((end - start).days + 1)]

    # ------------------------------------------------------------- занятия
    def _build_lesson(
        self,
        *,
        when: date,
        profile: BellProfile,
        slot,
        cell,
        override: ScheduleOverride | None,
        week_type: str,
        context: _Context,
    ) -> DayLesson | None:
        """Собрать карточку занятия для слота (ALG-04 шаги 3–4).

        Слот без занятия и без оверрайда в дне не отображается (SCH-03).
        """
        subject_id = cell.subject_id if cell is not None else None
        has_template = subject_id is not None

        if override is None:
            if not has_template:
                return None
            subject = context.subjects.get(subject_id)
            return DayLesson(
                slot_no=slot.slot_no,
                profile_id=profile.id,
                subject=subject,
                teacher=subject.teacher if subject else None,
                room=subject.room if subject else None,
                status=LessonStatus.PLANNED,
                block=slot,
                homework_count=self._homework_count(subject_id, when, context),
            )

        if override.override_type == OverrideType.CANCEL:
            if not has_template:
                # Сиротский cancel не применяется (ALG-10 п. 2) — SCH-17.
                return None
            subject = context.subjects.get(subject_id)
            return DayLesson(
                slot_no=slot.slot_no,
                profile_id=profile.id,
                subject=subject,
                teacher=subject.teacher if subject else None,
                room=subject.room if subject else None,
                status=LessonStatus.CANCELLED,
                override_id=override.id,
                block=slot,
                comment=override.comment,
            )

        if override.override_type == OverrideType.REPLACE:
            if not has_template:
                # Сиротский replace не применяется, занятие не показывается.
                return None
            replacement = context.subjects.get(override.subject_id or 0)
            original = context.subjects.get(subject_id)
            subject = replacement or original
            return DayLesson(
                slot_no=slot.slot_no,
                profile_id=profile.id,
                subject=subject,
                teacher=override.teacher or (subject.teacher if subject else None),
                room=override.room or (subject.room if subject else None),
                status=LessonStatus.REPLACED,
                override_id=override.id,
                custom_start=override.custom_start,
                custom_end=override.custom_end,
                block=slot,
                comment=override.comment,
                homework_count=self._homework_count(override.subject_id, when, context),
            )

        # override_type == ADD (OVR-07): в свободный слот или на своё время.
        if has_template:
            # OVR-08 запрещает add в занятый слот; если данные всё же такие —
            # не подменяем шаблон молча, показываем занятие по плану.
            subject = context.subjects.get(subject_id)
            return DayLesson(
                slot_no=slot.slot_no,
                profile_id=profile.id,
                subject=subject,
                teacher=subject.teacher if subject else None,
                room=subject.room if subject else None,
                status=LessonStatus.PLANNED,
                block=slot,
            )
        added = context.subjects.get(override.subject_id or 0)
        return DayLesson(
            slot_no=slot.slot_no,
            profile_id=profile.id,
            subject=added,
            teacher=override.teacher or (added.teacher if added else None),
            room=override.room or (added.room if added else None),
            status=LessonStatus.ADDED,
            override_id=override.id,
            custom_start=override.custom_start,
            custom_end=override.custom_end,
            block=slot,
            comment=override.comment,
            homework_count=self._homework_count(override.subject_id, when, context),
        )

    def _homework_count(self, subject_id: int | None, when: date, context: _Context) -> int:
        """HW-06: бейдж ДЗ на карточке занятия того же предмета в день сдачи."""
        if subject_id is None:
            return 0
        # Не кэшируем по дате ради простоты: заданий мало, а индекс по due_date есть.
        return len(self._homework.for_subject_date(subject_id, when))

    def _is_orphan(
        self,
        override: ScheduleOverride,
        week_type: str | None,
        profile_id: int,
        template: dict[int, object],
    ) -> bool:
        """ALG-10: ``cancel``/``replace`` без занятия в шаблоне; ``add`` — никогда."""
        if override.override_type == OverrideType.ADD:
            return False
        cell = template.get(override.slot_no)
        if cell is None:
            return True
        return getattr(cell, "subject_id", None) is None

    def _orphan_ids_placeholder(self) -> tuple[ScheduleOverride, ...]:
        """Внутри периода оверрайды не применяются, но сиротские всё равно видны."""
        return ()

    # -------------------------------------------------------------- ALG-05
    def day_time_bounds(self, when: date) -> tuple[str | None, str | None]:
        """ALG-05: начало первого и окончание последнего неотменённого блока."""
        return self.resolve(when).time_bounds

    # ------------------------------------------------------ мини-календарь
    def month_marks(self, start: date, end: date) -> dict[date, set[str]]:
        """Точки-метки мини-календаря (UI-05): оверрайд, поездки, период, ДЗ."""
        marks: dict[date, set[str]] = {}

        def add(day: date, kind: str) -> None:
            if start <= day <= end:
                marks.setdefault(day, set()).add(kind)

        for day in self._overrides.dates_with_overrides(start, end):
            add(day, "override")
        for period in self._periods.for_range(start, end):
            for day in date_range(max(period.date_from, start), min(period.date_to, end)):
                add(day, "period")
        for day in TripConfirmationRepository(self.db).dates():
            add(day, "ride")
        for day in HomeworkRepository(self.db).due_dates(start, end):
            add(day, "homework")
        return marks


__all__ = ["DayResolver"]
