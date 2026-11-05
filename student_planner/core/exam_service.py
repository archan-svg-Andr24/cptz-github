"""Сервис экзаменов: подписи, обратный отсчёт, метки календаря (EXAM-01…EXAM-12).

Слой между репозиторием и интерфейсом: превращает записи в строки с готовыми
подписями, считает дни до испытания и отдаёт данные для виджета «Скоро сессия»
и меток мини-календаря.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import clock
from .database import Database
from .exam_repository import ExamRepository
from .models import DayExam, Exam, ExamKind, ExamStatus
from .repositories import StudyPeriodRepository, SubjectRepository


@dataclass(frozen=True)
class ExamRow:
    """Строка списка испытаний с подписями (EXAM-05)."""

    exam: Exam
    subject_name: str
    days_left: int
    is_overdue: bool = False

    @property
    def countdown(self) -> str:
        if self.is_passed:
            return "Сдан"
        if self.exam.status == ExamStatus.POSTPONED:
            return "Перенесён"
        if self.days_left < 0:
            return "Прошёл"
        if self.days_left == 0:
            return "Сегодня"
        if self.days_left == 1:
            return "Завтра"
        return f"Через {self.days_left} дн."

    @property
    def when_caption(self) -> str:
        """Дата с временем: «04.11.2026, 09:00».

        Формат даты берётся из настройки ``date_display_format`` (SET-02):
        раньше здесь стоял жёсткий ``strftime('%d.%m.%Y')``, и при выбранном
        «ГГГГ-ММ-ДД» дата испытания всё равно печаталась по-старому.
        """
        from .dates import format_display

        base = format_display(self.exam.date)
        return f"{base}, {self.exam.time}" if self.exam.time else base

    @property
    def is_passed(self) -> bool:
        return self.exam.status == ExamStatus.PASSED

    @property
    def is_postponed(self) -> bool:
        """Испытание перенесено на другую дату (EXAM-03).

        Перенос — это смена даты, а не отмена: запись остаётся в списках и
        отличается только пометкой «Перенесён».
        """
        return self.exam.status == ExamStatus.POSTPONED


class ExamService:
    """§13: испытания сессии (EXAM-01…EXAM-12)."""

    #: Порог, за сколько дней показывать предупреждение о сессии.
    UPCOMING_WINDOW_DAYS: int = 14

    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = ExamRepository(db)
        self.subjects = SubjectRepository(db)
        self.periods = StudyPeriodRepository(db)

    # ------------------------------------------------------------------ чтение
    def subject_name(self, subject_id: int) -> str:
        subject = self.subjects.by_id(subject_id)
        return subject.name if subject else "—"

    def _row(self, exam: Exam, today: date) -> ExamRow:
        days_left = exam.days_left(today)
        return ExamRow(
            exam=exam,
            subject_name=self.subject_name(exam.subject_id),
            days_left=days_left,
            # «Просрочено» — дата прошла и испытание не сдано. Перенесённое
            # сюда не относится: у него назначена новая дата, и оно не
            # «забыто», а просто ждёт своего срока (EXAM-03).
            is_overdue=(
                days_left < 0
                and exam.status not in (ExamStatus.PASSED, ExamStatus.POSTPONED)
            ),
        )

    def rows(
        self,
        *,
        today: date | None = None,
        include_passed: bool = True,
        subject_id: int | None = None,
        kind: str | None = None,
        status: str | None = None,
        query: str | None = None,
    ) -> list[ExamRow]:
        """EXAM-05: список испытаний с фильтрами."""
        base = today or clock.today()
        items = self.repo.all(include_passed=include_passed)
        if subject_id is not None:
            items = [item for item in items if item.subject_id == subject_id]
        if kind is not None:
            items = [item for item in items if item.kind == kind]
        if status is not None:
            items = [item for item in items if item.status == status]
        rows = [self._row(item, base) for item in items]
        needle = (query or "").strip().casefold()
        if needle:
            rows = [row for row in rows if _matches(row, needle)]
        return rows

    def upcoming(self, *, today: date | None = None, limit: int | None = None) -> list[ExamRow]:
        """EXAM-07: ближайшие предстоящие для виджета на главной."""
        base = today or clock.today()
        return [self._row(item, base) for item in self.repo.upcoming(base, limit=limit)]

    def next_exam(self, *, today: date | None = None) -> ExamRow | None:
        """Ближайшее несданное испытание или ``None``.

        Если у всех несданных дата уже прошла (например, всё перенесли и
        календарь ещё не обновили), показывается самое раннее из них — это
        честнее, чем «—»: работа не сдана, и о ней нужно помнить.
        """
        base = today or clock.today()
        items = self.upcoming(today=base, limit=1)
        if items:
            return items[0]
        pending = [row for row in self.rows(today=base) if not row.is_passed]
        return pending[0] if pending else None

    def day_exams(self, when: date, *, today: date | None = None) -> list[DayExam]:
        """EXAM-06: испытания конкретной даты для карточки дня."""
        base = today or clock.today()
        return [
            DayExam(
                exam=exam,
                subject_name=self.subject_name(exam.subject_id),
                days_left=exam.days_left(base),
            )
            for exam in self.repo.on_date(when)
        ]

    def upcoming_within(self, days: int, *, today: date | None = None) -> list[ExamRow]:
        """Испытания в ближайшие ``days`` дней — для уведомлений (EXAM-09)."""
        base = today or clock.today()
        return [row for row in self.upcoming(today=base) if row.days_left <= days]

    def dates_with_exams(self, start: date, end: date) -> set[date]:
        return self.repo.dates_with_exams(start, end)

    def month_marks(self, start: date, end: date) -> dict[date, set[str]]:
        """Метки мини-календаря: ``exam`` на датах испытаний (UI-05)."""
        return {day: {"exam"} for day in self.repo.dates_with_exams(start, end)}

    # ------------------------------------------------------------- подсказки
    @property
    def empty_hint(self) -> str:
        """Текст пустого состояния (EXAM-11)."""
        return "Испытаний нет"

    @property
    def has_subjects(self) -> bool:
        return bool(self.subjects.all(include_inactive=False))

    def subject_choices(self):
        """Предметы для выпадающего списка формы (EXAM-04)."""
        return self.subjects.all(include_inactive=False)

    def kind_choices(self) -> list[tuple[str, str]]:
        return [(kind, ExamKind.label(kind)) for kind in ExamKind.ALL]

    def status_choices(self) -> list[tuple[str, str]]:
        return [(status, ExamStatus.label(status)) for status in ExamStatus.ALL]

    # ------------------------------------------------------------------ запись
    def create(self, subject_id: int, when: date, **kwargs) -> Exam:
        return self.repo.create(subject_id, when, **kwargs)

    def update(self, exam_id: int, **kwargs) -> Exam:
        return self.repo.update(exam_id, **kwargs)

    def delete(self, exam_id: int) -> None:
        self.repo.delete(exam_id)

    def mark_passed(self, exam_id: int) -> Exam:
        return self.repo.set_status(exam_id, ExamStatus.PASSED)

    def mark_planned(self, exam_id: int) -> Exam:
        return self.repo.set_status(exam_id, ExamStatus.PLANNED)

    def mark_postponed(self, exam_id: int) -> Exam:
        return self.repo.set_status(exam_id, ExamStatus.POSTPONED)

    # ------------------------------------------------------------------ сводка
    def summary(self, *, today: date | None = None) -> dict[str, int]:
        """EXAM-10: счётчики для заголовка страницы.

        «Предстоит» считает всё, что ещё не сдано: и обычные, и перенесённые
        испытания. Дата при этом не важна — перенесённое на прошедшее число
        всё равно остаётся несданным, и скрывать его из счётчика значило бы
        показывать «0», когда работа ещё не сделана. Иначе после переноса
        строка «Предстоит» обнулялась и выглядела как потеря данных.
        """
        all_items = self.repo.all()
        passed = sum(1 for item in all_items if item.status == ExamStatus.PASSED)
        planned = sum(1 for item in all_items if item.status != ExamStatus.PASSED)
        return {
            "total": len(all_items),
            "planned": planned,
            "passed": passed,
        }


def _matches(row: ExamRow, needle: str) -> bool:
    """Поиск по предмету, кабинету, преподавателю и комментарию."""
    exam = row.exam
    haystack = " ".join(
        part
        for part in (row.subject_name, exam.room, exam.teacher, exam.comment, exam.kind_label)
        if part
    ).casefold()
    return all(word in haystack for word in needle.split())


__all__ = ["ExamService", "ExamRow"]
