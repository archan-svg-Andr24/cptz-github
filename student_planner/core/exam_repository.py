"""Репозиторий экзаменов и зачётов (EXAM-01…EXAM-12, Прил. Б.12).

Таблица ``exams`` присутствовала в схеме с самого начала как заготовка v1.1.
Модуль не меняет схему — он заполняет её и читает. Отдельный файл, а не
``repositories.py``, потому что экзамены не участвуют в разрешении дня
(ALG-04) и ссылаются на предметы только для подписи.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import clock, dates as dt
from .database import Database
from .errors import NotFoundError, ValidationError
from .models import Exam, ExamKind, ExamStatus


def _exam(row: Any) -> Exam:
    return Exam(
        id=row["id"],
        subject_id=int(row["subject_id"]),
        period_id=row["period_id"],
        kind=row["kind"],
        date=dt.parse_iso(row["date"]),
        time=row["time"],
        room=row["room"],
        teacher=row["teacher"],
        status=row["status"],
        comment=row["comment"],
        created_at=row["created_at"] or "",
    )


def _validate_kind(kind: str) -> str:
    if kind not in ExamKind.ALL:
        raise ValidationError(
            f"Неизвестный вид испытания: {kind!r}. "
            f"Допустимо: {', '.join(ExamKind.ALL)}.",
            field="kind",
        )
    return kind


def _validate_status(status: str) -> str:
    if status not in ExamStatus.ALL:
        raise ValidationError(
            f"Неизвестное состояние: {status!r}. Допустимо: {', '.join(ExamStatus.ALL)}.",
            field="status",
        )
    return status


def _validate_time(value: str | None) -> str | None:
    """Время начала: пусто или ``ЧЧ:ММ`` (схема хранит TEXT)."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if not dt.is_valid_time(cleaned):
        raise ValidationError(
            f"Время должно быть в виде ЧЧ:ММ, получено {value!r}.", field="time"
        )
    return cleaned


class ExamRepository:
    """Чтение и запись испытаний (EXAM-01…EXAM-12)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ чтение
    def all(self, *, include_passed: bool = True) -> list[Exam]:
        sql = "SELECT * FROM exams"
        if not include_passed:
            sql += " WHERE status <> 'passed'"
        rows = self.db.fetchall(sql + " ORDER BY date, time, id")
        return [_exam(row) for row in rows]

    def get(self, exam_id: int) -> Exam | None:
        row = self.db.fetchone("SELECT * FROM exams WHERE id = ?", (exam_id,))
        return _exam(row) if row else None

    def require(self, exam_id: int) -> Exam:
        exam = self.get(exam_id)
        if exam is None:
            raise NotFoundError(f"Испытание с id={exam_id} не найдено")
        return exam

    def for_subject(self, subject_id: int) -> list[Exam]:
        rows = self.db.fetchall(
            "SELECT * FROM exams WHERE subject_id = ? ORDER BY date, time, id",
            (subject_id,),
        )
        return [_exam(row) for row in rows]

    def in_range(self, start: date, end: date, *, include_passed: bool = True) -> list[Exam]:
        """Испытания в диапазоне дат включительно (EXAM-06: метки календаря)."""
        sql = "SELECT * FROM exams WHERE date >= ? AND date <= ?"
        if not include_passed:
            sql += " AND status <> 'passed'"
        rows = self.db.fetchall(sql + " ORDER BY date, time, id", (dt.to_iso(start), dt.to_iso(end)))
        return [_exam(row) for row in rows]

    def on_date(self, when: date) -> list[Exam]:
        return self.in_range(when, when)

    def upcoming(self, today: date, *, limit: int | None = None) -> list[Exam]:
        """Ближайшие предстоящие испытания от ``today`` включительно.

        «Перенесённое» (``postponed``) тоже попадает в выборку: перенос — это
        смена даты, а не отмена, и запись обязана оставаться видимой. Иначе
        после переноса испытание исчезало из виджета и из списка «Предстоящие»,
        хотя метка в календаре продолжала гореть.
        """
        sql = (
            "SELECT * FROM exams WHERE date >= ? AND status <> 'passed' "
            "ORDER BY date, time, id"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = self.db.fetchall(sql, (dt.to_iso(today),))
        return [_exam(row) for row in rows]

    def dates_with_exams(self, start: date, end: date) -> set[date]:
        """Даты с испытаниями — для точек-меток мини-календаря (UI-05)."""
        rows = self.db.fetchall(
            "SELECT DISTINCT date FROM exams WHERE date >= ? AND date <= ?",
            (dt.to_iso(start), dt.to_iso(end)),
        )
        return {dt.parse_iso(row["date"]) for row in rows}

    # ------------------------------------------------------------------ запись
    def create(
        self,
        subject_id: int,
        when: date | str,
        *,
        kind: str = ExamKind.EXAM,
        time: str | None = None,
        room: str | None = None,
        teacher: str | None = None,
        period_id: int | None = None,
        status: str = ExamStatus.PLANNED,
        comment: str | None = None,
    ) -> Exam:
        _validate_kind(kind)
        _validate_status(status)
        exam_date = dt.parse_iso(when) if isinstance(when, str) else when
        if not isinstance(exam_date, date):
            raise ValidationError("Дата испытания не задана.", field="date")
        start = _validate_time(time)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO exams(subject_id, period_id, kind, date, time, room, teacher, "
                "status, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(subject_id),
                    period_id,
                    kind,
                    dt.to_iso(exam_date),
                    start,
                    (room or "").strip() or None,
                    (teacher or "").strip() or None,
                    status,
                    (comment or "").strip() or None,
                    clock.now_iso(),
                ),
            )
            new_id = int(cursor.lastrowid)
        return self.require(new_id)

    def update(
        self,
        exam_id: int,
        *,
        subject_id: int | None = None,
        when: date | str | None = None,
        kind: str | None = None,
        time: str | None = None,
        room: str | None = None,
        teacher: str | None = None,
        status: str | None = None,
        comment: str | None = None,
        clear_time: bool = False,
        clear_room: bool = False,
        clear_teacher: bool = False,
        clear_comment: bool = False,
    ) -> Exam:
        current = self.require(exam_id)
        if kind is not None:
            _validate_kind(kind)
        if status is not None:
            _validate_status(status)
        exam_date = current.date
        if when is not None:
            exam_date = dt.parse_iso(when) if isinstance(when, str) else when

        if clear_time:
            new_time = None
        elif time is not None:
            new_time = _validate_time(time)
        else:
            new_time = current.time

        def pick(new_value: str | None, old: str | None, clear: bool) -> str | None:
            if clear:
                return None
            if new_value is None:
                return old
            return (new_value or "").strip() or None

        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE exams SET subject_id = ?, kind = ?, date = ?, time = ?, room = ?, "
                "teacher = ?, status = ?, comment = ? WHERE id = ?",
                (
                    int(subject_id) if subject_id is not None else current.subject_id,
                    current.kind if kind is None else kind,
                    dt.to_iso(exam_date),
                    new_time,
                    pick(room, current.room, clear_room),
                    pick(teacher, current.teacher, clear_teacher),
                    current.status if status is None else status,
                    pick(comment, current.comment, clear_comment),
                    exam_id,
                ),
            )
        return self.require(exam_id)

    def set_status(self, exam_id: int, status: str) -> Exam:
        """Быстрая смена состояния: «сдан» / «перенесён» (EXAM-03)."""
        return self.update(exam_id, status=status)

    def delete(self, exam_id: int) -> None:
        self.require(exam_id)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))

    def delete_for_subject(self, subject_id: int) -> int:
        """Удалить испытания предмета (вызывается перед удалением предмета)."""
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM exams WHERE subject_id = ?", (subject_id,))
        return int(cursor.rowcount or 0)

    def count_for_subject(self, subject_id: int) -> int:
        value = self.db.scalar(
            "SELECT COUNT(*) FROM exams WHERE subject_id = ?", (subject_id,)
        )
        return int(value or 0)


__all__ = ["ExamRepository"]
