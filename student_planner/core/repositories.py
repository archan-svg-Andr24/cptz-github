"""Репозитории: чтение строк в модели и запись обратно (DATA-08, DATA-15).

Репозитории не открывают собственных транзакций: они работают внутри той,
которую открыл сервис. Это делает возможным каскадный пересчёт CALC-04 одной
атомарной операцией (ACC-M-100).

Ссылочная целостность обеспечивается внешними ключами (``PRAGMA
foreign_keys = ON``) и явными проверками «используется ли» перед удалением:
DATA-15 требует блокировать удаление используемой сущности или заменять его
деактивацией.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from . import dates as dt
from .database import Database
from .errors import InUseError, NotFoundError, RuleViolationError, ValidationError
from .models import (
    BellPart,
    BellProfile,
    BellSlot,
    Homework,
    HomeworkStatus,
    OverrideType,
    PaymentMethod,
    PeriodKind,
    Ride,
    ScheduleOverride,
    StudyPeriod,
    Subject,
    Tariff,
    TemplateCell,
    TopUp,
    TransportType,
    TripConfirmation,
    TripLeg,
    TripTemplate,
    WeekAnchor,
    WeekType,
)
from .money import ZERO, from_db, to_db
from .weektype import week_type_for


def _date(text: Any) -> date | None:
    if text is None or text == "":
        return None
    return dt.parse_iso(str(text))


def _opt_date(text: Any) -> date | None:
    return _date(text)


def _money(value: Any) -> Decimal:
    return from_db(value)


def _bool(value: Any) -> bool:
    return bool(value)


def _now() -> str:
    from . import clock

    return clock.now_iso()


#: Маркер «значение не передано» для частичных обновлений.
_UNSET: object = object()


# ===========================================================================
# Предметы (SUBJ-01…SUBJ-05, Прил. Б.2)
# ===========================================================================
def _subject(row: Any) -> Subject:
    return Subject(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        teacher=row["teacher"],
        room=row["room"],
        color=row["color"],
        is_active=_bool(row["is_active"]),
    )


class SubjectRepository:
    """Справочник предметов: добавление, правка, отключение, удаление."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self, *, include_inactive: bool = True) -> list[Subject]:
        sql = "SELECT * FROM subjects"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        return [_subject(row) for row in self.db.fetchall(sql + " ORDER BY name COLLATE NOCASE")]

    def active(self) -> list[Subject]:
        return self.all(include_inactive=False)

    def by_id(self, subject_id: int) -> Subject | None:
        row = self.db.fetchone("SELECT * FROM subjects WHERE id = ?", (subject_id,))
        return _subject(row) if row else None

    def require(self, subject_id: int) -> Subject:
        subject = self.by_id(subject_id)
        if subject is None:
            raise NotFoundError(f"Предмет с id={subject_id} не найден")
        return subject

    def create(
        self,
        name: str,
        *,
        code: str | None = None,
        teacher: str | None = None,
        room: str | None = None,
        color: str | None = None,
        is_active: bool = True,
    ) -> Subject:
        """Создать предмет; дубль пары ``(code, name)`` отклоняется (SUBJ-02)."""
        name = (name or "").strip()
        if not name:
            raise ValidationError("Название предмета не может быть пустым", field="name")
        code = (code or "").strip() or None
        self._check_unique(code, name, exclude_id=None)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO subjects(code, name, teacher, room, color, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (code, name, (teacher or "").strip() or None, (room or "").strip() or None,
                 color, 1 if is_active else 0),
            )
            new_id = int(cursor.lastrowid)
        return self.require(new_id)

    def update(
        self,
        subject_id: int,
        *,
        name: str | None = None,
        code: str | None = None,
        teacher: str | None = None,
        room: str | None = None,
        color: str | None = None,
        is_active: bool | None = None,
    ) -> Subject:
        current = self.require(subject_id)
        new_name = current.name if name is None else (name or "").strip()
        if not new_name:
            raise ValidationError("Название предмета не может быть пустым", field="name")
        new_code = current.code if code is None else ((code or "").strip() or None)
        self._check_unique(new_code, new_name, exclude_id=subject_id)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE subjects SET code = ?, name = ?, teacher = ?, room = ?, color = ?, "
                "is_active = ? WHERE id = ?",
                (
                    new_code,
                    new_name,
                    current.teacher if teacher is None else ((teacher or "").strip() or None),
                    current.room if room is None else ((room or "").strip() or None),
                    current.color if color is None else color,
                    (1 if current.is_active else 0) if is_active is None else (1 if is_active else 0),
                    subject_id,
                ),
            )
        return self.require(subject_id)

    def set_active(self, subject_id: int, active: bool) -> Subject:
        """Деактивация вместо удаления используемого предмета (SUBJ-04)."""
        self.require(subject_id)
        with self.db.transaction() as conn:
            conn.execute("UPDATE subjects SET is_active = ? WHERE id = ?", (1 if active else 0, subject_id))
        return self.require(subject_id)

    def delete(self, subject_id: int) -> None:
        """Удалить предмет, только если он нигде не используется (SUBJ-04, HW-09)."""
        self.require(subject_id)
        references = self.references(subject_id)
        if references:
            raise InUseError(
                f"Предмет используется ({references}). Удаление невозможно — "
                "отключите предмет, чтобы он остался в истории.",
                details={"references": references},
            )
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))

    def references(self, subject_id: int) -> str:
        """Описание ссылок на предмет (пустая строка — ссылок нет)."""
        checks = (
            ("schedule_templates", "в шаблоне расписания"),
            ("schedule_overrides", "в изменениях расписания"),
            ("homework", "в домашних заданиях"),
            ("exams", "в экзаменах"),
        )
        found: list[str] = []
        for table, label in checks:
            count = self.db.scalar(f"SELECT COUNT(*) FROM {table} WHERE subject_id = ?", (subject_id,))
            if count:
                found.append(f"{label}: {count}")
        return ", ".join(found)

    def _check_unique(self, code: str | None, name: str, *, exclude_id: int | None) -> None:
        """SUBJ-02: ``(code, name)`` уникальна; одинаковый код у разных предметов допустим."""
        if code is None:
            row = self.db.fetchone(
                "SELECT id FROM subjects WHERE code IS NULL AND name = ? AND id IS NOT ?",
                (name, exclude_id),
            )
        else:
            row = self.db.fetchone(
                "SELECT id FROM subjects WHERE code = ? AND name = ? AND id IS NOT ?",
                (code, name, exclude_id),
            )
        if row is not None:
            raise RuleViolationError(
                f"Предмет «{name}» с таким кодом уже существует (SUBJ-02)."
            )


# ===========================================================================
# Тарифы (FARE-01…FARE-14, ALG-09, Прил. Б.3)
# ===========================================================================
def _tariff(row: Any) -> Tariff:
    return Tariff(
        id=row["id"],
        kind=row["kind"],
        price=_money(row["price"]),
        effective_from=_date(row["effective_from"]),  # type: ignore[arg-type]
        effective_to=_opt_date(row["effective_to"]),
        vehicle=row["vehicle"],
        is_active=_bool(row["is_active"]),
        comment=row["comment"],
    )


class TariffRepository:
    """Тарифы с диапазонами действия; пересечение одного вида недопустимо (FARE-02)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self, *, include_inactive: bool = True) -> list[Tariff]:
        sql = "SELECT * FROM tariffs"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        return [
            _tariff(row)
            for row in self.db.fetchall(sql + " ORDER BY kind, effective_from")
        ]

    def by_id(self, tariff_id: int) -> Tariff | None:
        row = self.db.fetchone("SELECT * FROM tariffs WHERE id = ?", (tariff_id,))
        return _tariff(row) if row else None

    def require(self, tariff_id: int) -> Tariff:
        tariff = self.by_id(tariff_id)
        if tariff is None:
            raise NotFoundError(f"Тариф с id={tariff_id} не найден")
        return tariff

    def of_kind(self, kind: str, *, include_inactive: bool = False) -> list[Tariff]:
        sql = "SELECT * FROM tariffs WHERE kind = ?"
        if not include_inactive:
            sql += " AND is_active = 1"
        return [
            _tariff(row)
            for row in self.db.fetchall(sql + " ORDER BY effective_from", (kind,))
        ]

    def create(
        self,
        kind: str,
        price: Any,
        effective_from: date | str,
        *,
        effective_to: date | str | None = None,
        vehicle: str | None = None,
        is_active: bool = True,
        comment: str | None = None,
    ) -> Tariff:
        from .models import TariffKind

        if kind not in TariffKind.ALL:
            raise ValidationError(
                f"Неизвестный вид тарифа: {kind}. Допустимые: {', '.join(TariffKind.ALL)}.",
                field="kind",
            )
        start = _coerce_date(effective_from, "effective_from")
        end = _coerce_date(effective_to, "effective_to") if effective_to else None
        if end is not None and end < start:
            raise ValidationError(
                "Дата окончания тарифа не может быть раньше даты начала (DATA-17).", field="effective_to"
            )
        self._check_overlap(kind, start, end, vehicle=vehicle, exclude_id=None)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO tariffs(kind, price, effective_from, effective_to, vehicle, "
                "is_active, comment) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    kind,
                    to_db(price),
                    dt.to_iso(start),
                    dt.to_iso(end) if end else None,
                    vehicle,
                    1 if is_active else 0,
                    comment,
                ),
            )
            new_id = int(cursor.lastrowid)
        return self.require(new_id)

    def update(
        self,
        tariff_id: int,
        *,
        kind: str | None = None,
        price: Any | None = None,
        effective_from: date | str | None = None,
        effective_to: date | str | None = None,
        clear_effective_to: bool = False,
        vehicle: str | None = None,
        is_active: bool | None = None,
        comment: str | None = None,
    ) -> Tariff:
        current = self.require(tariff_id)
        new_kind = kind or current.kind
        new_start = _coerce_date(effective_from, "effective_from") if effective_from else current.effective_from
        if clear_effective_to:
            new_end: date | None = None
        elif effective_to:
            new_end = _coerce_date(effective_to, "effective_to")
        else:
            new_end = current.effective_to
        if new_end is not None and new_end < new_start:
            raise ValidationError(
                "Дата окончания тарифа не может быть раньше даты начала (DATA-17).", field="effective_to"
            )
        new_price = current.price if price is None else from_db(to_db(price))
        new_active = current.is_active if is_active is None else is_active
        if new_active:
            self._check_overlap(
                new_kind, new_start, new_end,
                vehicle=current.vehicle if vehicle is None else vehicle,
                exclude_id=tariff_id,
            )
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tariffs SET kind = ?, price = ?, effective_from = ?, effective_to = ?, "
                "vehicle = ?, is_active = ?, comment = ? WHERE id = ?",
                (
                    new_kind,
                    to_db(new_price),
                    dt.to_iso(new_start),
                    dt.to_iso(new_end) if new_end else None,
                    current.vehicle if vehicle is None else vehicle,
                    1 if new_active else 0,
                    current.comment if comment is None else comment,
                    tariff_id,
                ),
            )
        return self.require(tariff_id)

    def delete(self, tariff_id: int) -> None:
        """Удаление тарифа, использованного поездками, блокируется (FARE-11, DATA-15)."""
        self.require(tariff_id)
        used = self.db.scalar("SELECT COUNT(*) FROM transport_rides WHERE tariff_id = ?", (tariff_id,))
        if used:
            raise InUseError(
                f"Тариф использован в {used} поездках: цены поездок — снапшоты, поэтому "
                "удаление невозможно. Деактивируйте тариф.",
                details={"rides": int(used)},
            )
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM tariffs WHERE id = ?", (tariff_id,))

    def _check_overlap(
        self,
        kind: str,
        start: date,
        end: date | None,
        *,
        vehicle: str | None,
        exclude_id: int | None,
    ) -> None:
        """FARE-02 / DATA-18: два активных тарифа одного вида не перекрывают дату."""
        row = self.db.fetchone(
            "SELECT id, effective_from, effective_to FROM tariffs "
            "WHERE id IS NOT ? AND kind = ? AND is_active = 1 AND vehicle IS ? "
            "AND effective_from <= COALESCE(?, '9999-12-31') "
            "AND COALESCE(effective_to, '9999-12-31') >= ?",
            (exclude_id, kind, vehicle, dt.to_iso(end) if end else None, dt.to_iso(start)),
        )
        if row is not None:
            raise RuleViolationError(
                f"Тариф «{kind}» пересекается по датам с существующим (с "
                f"{_fmt(row['effective_from'])} по {_fmt(row['effective_to'])}). "
                "На одну дату допускается один действующий тариф вида (FARE-02).",
                details={"conflict_id": row["id"]},
            )


def _fmt(value: Any) -> str:
    return dt.format_display(_date(value)) if value else "бессрочно"


def _coerce_date(value: date | str | None, field: str) -> date:
    if isinstance(value, date):
        return value
    if not value:
        raise ValidationError("Дата не задана", field=field)
    return dt.parse_iso(str(value), field=field)


# ===========================================================================
# Якоря недель (WEEK-01…WEEK-09, ALG-01, Прил. Б.11)
# ===========================================================================
def _anchor(row: Any) -> WeekAnchor:
    return WeekAnchor(
        id=row["id"],
        effective_from=_date(row["effective_from"]),  # type: ignore[arg-type]
        base_date=_date(row["base_date"]),  # type: ignore[arg-type]
        base_type=row["base_type"],
        cycle_length=int(row["cycle_length"]),
        comment=row["comment"],
    )


class WeekAnchorRepository:
    """Якоря: ``effective_from`` уникален (DATA-18); смена создаёт новый якорь (WEEK-05)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self) -> list[WeekAnchor]:
        return [_anchor(row) for row in self.db.fetchall("SELECT * FROM week_anchors ORDER BY effective_from")]

    def effective_for(self, value: date) -> WeekAnchor | None:
        """Якорь с максимальной ``effective_from <= value`` (ALG-01 шаг 1)."""
        row = self.db.fetchone(
            "SELECT * FROM week_anchors WHERE effective_from <= ? ORDER BY effective_from DESC LIMIT 1",
            (dt.to_iso(value),),
        )
        return _anchor(row) if row else None

    def current(self, today: date | None = None) -> WeekAnchor | None:
        return self.effective_for(today or __import__("datetime").date.today())

    def create(
        self,
        effective_from: date | str,
        base_date: date | str,
        base_type: str,
        *,
        cycle_length: int = 2,
        comment: str | None = None,
    ) -> WeekAnchor:
        start = _coerce_date(effective_from, "effective_from")
        base = _coerce_date(base_date, "base_date")
        if base_type not in (WeekType.UPPER, WeekType.LOWER):
            raise ValidationError("Тип опорной недели: только «верхняя» или «нижняя».", field="base_type")
        if cycle_length < 2:
            raise ValidationError("Длина цикла не может быть меньше 2 (Прил. Б.11).", field="cycle_length")
        existing = self.db.fetchone(
            "SELECT id FROM week_anchors WHERE effective_from = ?", (dt.to_iso(start),)
        )
        if existing is not None:
            raise RuleViolationError(
                f"Якорь с датой действия {dt.format_display(start)} уже существует "
                "(effective_from уникален, DATA-18)."
            )
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO week_anchors(effective_from, base_date, base_type, cycle_length, comment) "
                "VALUES (?, ?, ?, ?, ?)",
                (dt.to_iso(start), dt.to_iso(base), base_type, cycle_length, comment),
            )
            new_id = int(cursor.lastrowid)
        row = self.db.fetchone("SELECT * FROM week_anchors WHERE id = ?", (new_id,))
        return _anchor(row)  # type: ignore[arg-type]

    def update(
        self,
        anchor_id: int,
        *,
        base_date: date | str | None = None,
        base_type: str | None = None,
        comment: str | None = None,
    ) -> WeekAnchor:
        row = self.db.fetchone("SELECT * FROM week_anchors WHERE id = ?", (anchor_id,))
        if row is None:
            raise NotFoundError("Якорь недели не найден")
        current = _anchor(row)
        new_base = _coerce_date(base_date, "base_date") if base_date else current.base_date
        new_type = base_type or current.base_type
        if new_type not in (WeekType.UPPER, WeekType.LOWER):
            raise ValidationError("Тип опорной недели: только «верхняя» или «нижняя».", field="base_type")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE week_anchors SET base_date = ?, base_type = ?, comment = ? WHERE id = ?",
                (dt.to_iso(new_base), new_type,
                 current.comment if comment is None else comment, anchor_id),
            )
        row = self.db.fetchone("SELECT * FROM week_anchors WHERE id = ?", (anchor_id,))
        return _anchor(row)  # type: ignore[arg-type]

    def delete(self, anchor_id: int) -> None:
        """Удалить можно только исторический якорь, не последний действующий."""
        rows = self.all()
        if not rows:
            raise NotFoundError("Якоря недели отсутствуют")
        if rows[-1].id == anchor_id:
            raise RuleViolationError(
                "Нельзя удалить действующий якорь: сначала создайте новый якорь с более "
                "поздней датой действия (WEEK-05)."
            )
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM week_anchors WHERE id = ?", (anchor_id,))


# ===========================================================================
# Профили звонков, блоки и части (BELL-01…BELL-20, Прил. Б.4–Б.6)
# ===========================================================================
def _bell_part(row: Any) -> BellPart:
    return BellPart(
        id=row["id"], slot_id=row["slot_id"], seq=int(row["seq"]),
        part_type=row["part_type"], start_time=row["start_time"], end_time=row["end_time"],
    )


def _bell_slot(row: Any, parts: tuple[BellPart, ...]) -> BellSlot:
    return BellSlot(
        id=row["id"], profile_id=row["profile_id"], slot_no=int(row["slot_no"]),
        pair_no=row["pair_no"], block_type=row["block_type"],
        display_name=row["display_name"], sort_order=row["sort_order"], parts=parts,
    )


class BellRepository:
    """Сетка звонков: профили по дням недели с диапазонами действия."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------ чтение
    def profiles(self, *, include_inactive: bool = True) -> list[BellProfile]:
        sql = "SELECT * FROM bell_profiles"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        rows = self.db.fetchall(sql + " ORDER BY weekday, effective_from")
        return [self._profile(row) for row in rows]

    def profile(self, profile_id: int) -> BellProfile | None:
        row = self.db.fetchone("SELECT * FROM bell_profiles WHERE id = ?", (profile_id,))
        return self._profile(row) if row else None

    def require_profile(self, profile_id: int) -> BellProfile:
        profile = self.profile(profile_id)
        if profile is None:
            raise NotFoundError(f"Профиль звонков с id={profile_id} не найден")
        return profile

    def _profile(self, row: Any) -> BellProfile:
        slot_rows = self.db.fetchall(
            "SELECT * FROM bell_slots WHERE profile_id = ? ORDER BY slot_no", (row["id"],)
        )
        slots: list[BellSlot] = []
        for slot_row in slot_rows:
            part_rows = self.db.fetchall(
                "SELECT * FROM bell_slot_parts WHERE slot_id = ? ORDER BY seq", (slot_row["id"],)
            )
            slots.append(_bell_slot(slot_row, tuple(_bell_part(part) for part in part_rows)))
        return BellProfile(
            id=row["id"],
            weekday=int(row["weekday"]),
            variant=row["variant"],
            name=row["name"],
            effective_from=_opt_date(row["effective_from"]),
            effective_to=_opt_date(row["effective_to"]),
            is_active=_bool(row["is_active"]),
            slots=tuple(slots),
        )

    def profile_for(self, value: date, *, variant: str = "default") -> BellProfile | None:
        """BELL-18: профиль, действующий на дату; иначе ближайший предыдущий."""
        weekday = value.isoweekday()
        candidates = [
            profile
            for profile in self.profiles(include_inactive=False)
            if profile.weekday == weekday and profile.variant == variant
        ]
        active = [profile for profile in candidates if profile.covers(value)]
        if active:
            # При нескольких подходящих — самый поздний по effective_from.
            return max(active, key=lambda p: p.effective_from or date.min)
        previous = [
            profile
            for profile in candidates
            if profile.effective_from is None or profile.effective_from <= value
        ]
        if not previous:
            return None
        return max(previous, key=lambda p: p.effective_from or date.min)

    # ------------------------------------------------------------ запись
    def create_profile(
        self,
        weekday: int,
        name: str,
        *,
        variant: str = "default",
        effective_from: date | str | None = None,
        effective_to: date | str | None = None,
        is_active: bool = True,
    ) -> BellProfile:
        if not 1 <= int(weekday) <= 7:
            raise ValidationError("День недели: от 1 (Пн) до 7 (Вс).", field="weekday")
        start = _coerce_date(effective_from, "effective_from") if effective_from else None
        end = _coerce_date(effective_to, "effective_to") if effective_to else None
        _check_effective_range(start, end)
        with self.db.transaction() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO bell_profiles(weekday, variant, name, effective_from, "
                    "effective_to, is_active) VALUES (?, ?, ?, ?, ?, ?)",
                    (int(weekday), variant, name,
                     dt.to_iso(start) if start else None,
                     dt.to_iso(end) if end else None,
                     1 if is_active else 0),
                )
            except Exception as exc:  # UNIQUE(weekday, variant, effective_from)
                if "UNIQUE" in str(exc):
                    raise RuleViolationError(
                        f"Профиль на этот день недели с такой датой действия уже есть "
                        f"({variant}, {_fmt(start) if start else 'бессрочно'})."
                    ) from exc
                raise
            new_id = int(cursor.lastrowid)
        return self.require_profile(new_id)

    def update_profile(
        self,
        profile_id: int,
        *,
        name: str | None = None,
        effective_from: date | str | None = None,
        effective_to: date | str | None = None,
        clear_effective_to: bool = False,
        is_active: bool | None = None,
    ) -> BellProfile:
        current = self.require_profile(profile_id)
        start = _coerce_date(effective_from, "effective_from") if effective_from else current.effective_from
        if clear_effective_to:
            end: date | None = None
        elif effective_to:
            end = _coerce_date(effective_to, "effective_to")
        else:
            end = current.effective_to
        _check_effective_range(start, end)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE bell_profiles SET name = ?, effective_from = ?, effective_to = ?, "
                "is_active = ? WHERE id = ?",
                (
                    current.name if name is None else name,
                    dt.to_iso(start) if start else None,
                    dt.to_iso(end) if end else None,
                    (1 if current.is_active else 0) if is_active is None else (1 if is_active else 0),
                    profile_id,
                ),
            )
        return self.require_profile(profile_id)

    def delete_profile(self, profile_id: int) -> None:
        """BELL-20: удаление профиля со ссылками блокируется с предложением деактивации."""
        self.require_profile(profile_id)
        templates = self.db.scalar(
            "SELECT COUNT(*) FROM schedule_templates WHERE profile_id = ?", (profile_id,)
        )
        overrides = self.db.scalar(
            "SELECT COUNT(*) FROM schedule_overrides WHERE profile_id = ?", (profile_id,)
        )
        if templates or overrides:
            raise InUseError(
                "Профиль звонков используется: "
                f"занятий в шаблоне — {templates}, изменений расписания — {overrides}. "
                "Удаление невозможно, предлагается деактивация (BELL-20).",
                details={"templates": int(templates), "overrides": int(overrides)},
            )
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM bell_profiles WHERE id = ?", (profile_id,))

    # ------------------------------------------------------------- блоки
    def add_slot(
        self,
        profile_id: int,
        block_type: str,
        *,
        display_name: str | None = None,
        pair_no: int | None = None,
        parts: Iterable[tuple[str, str, str]] = (),
    ) -> BellSlot:
        """BELL-13: добавление блока — только в конец профиля."""
        profile = self.require_profile(profile_id)
        next_slot = max((slot.slot_no for slot in profile.slots), default=0) + 1
        part_list = list(parts)
        _validate_parts(part_list)
        self._check_no_overlap(profile, part_list)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO bell_slots(profile_id, slot_no, pair_no, block_type, display_name, "
                "sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                (profile_id, next_slot, pair_no, block_type, display_name, next_slot),
            )
            slot_id = int(cursor.lastrowid)
            for seq, (part_type, start, end) in enumerate(part_list, start=1):
                conn.execute(
                    "INSERT INTO bell_slot_parts(slot_id, seq, part_type, start_time, end_time) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (slot_id, seq, part_type, start, end),
                )
        slot = self.require_profile(profile_id).slot(next_slot)
        if slot is None:  # pragma: no cover — защита от рассогласования
            raise NotFoundError("Созданный блок не найден")
        return slot

    def _check_no_overlap(
        self, profile: BellProfile, parts: list[tuple[str, str, str]], *, skip_slot_id: int | None = None
    ) -> None:
        """BELL-17: блоки одного профиля не пересекаются по времени.

        Проверяются все *занятия* прочих блоков профиля: перемены внутри блока
        могут совпадать по времени с чем угодно, но занятие не должно
        накладываться на другое занятие.
        """
        new_lessons = [
            (dt.time_to_minutes(start), dt.time_to_minutes(end))
            for part_type, start, end in parts
            if part_type == "lesson"
        ]
        for slot in profile.slots:
            if skip_slot_id is not None and slot.id == skip_slot_id:
                continue
            for part in slot.parts:
                if part.part_type != "lesson":
                    continue
                start = dt.time_to_minutes(part.start_time)
                end = dt.time_to_minutes(part.end_time)
                for new_start, new_end in new_lessons:
                    if new_start < end and start < new_end:
                        raise ValidationError(
                            f"Блоки пересекаются по времени: новое занятие "
                            f"{dt.minutes_to_time(new_start)}–{dt.minutes_to_time(new_end)} "
                            f"накладывается на блок №{slot.slot_no} "
                            f"({part.start_time}–{part.end_time}) (BELL-17).",
                            field="parts",
                        )

    def update_slot_parts(self, slot_id: int, parts: Iterable[tuple[str, str, str]]) -> BellSlot:
        """BELL-12/BELL-15: правка частей с проверкой пересечений (BELL-17)."""
        slot_row = self.db.fetchone("SELECT * FROM bell_slots WHERE id = ?", (slot_id,))
        if slot_row is None:
            raise NotFoundError("Блок звонков не найден")
        part_list = list(parts)
        _validate_parts(part_list)
        self._check_no_overlap(self.require_profile(slot_row["profile_id"]), part_list,
                               skip_slot_id=slot_id)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM bell_slot_parts WHERE slot_id = ?", (slot_id,))
            for seq, (part_type, start, end) in enumerate(part_list, start=1):
                conn.execute(
                    "INSERT INTO bell_slot_parts(slot_id, seq, part_type, start_time, end_time) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (slot_id, seq, part_type, start, end),
                )
        return self._slot(slot_id)

    def delete_slot(self, slot_id: int) -> None:
        """BELL-16: удаление блока из середины запрещено при наличии ссылок."""
        slot_row = self.db.fetchone("SELECT * FROM bell_slots WHERE id = ?", (slot_id,))
        if slot_row is None:
            raise NotFoundError("Блок звонков не найден")
        profile_id = slot_row["profile_id"]
        slot_no = int(slot_row["slot_no"])
        profile = self.require_profile(profile_id)
        if slot_no != max((item.slot_no for item in profile.slots), default=slot_no):
            references = self._slot_references(profile_id, slot_no)
            if references:
                raise InUseError(
                    "Удаление блока из середины профиля запрещено, пока на него ссылаются "
                    f"шаблон или изменения расписания ({references}). Сначала очистите эти "
                    "ячейки или удаляйте блоки с конца (BELL-16).",
                    details={"references": references},
                )
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM bell_slots WHERE id = ?", (slot_id,))

    def _slot_references(self, profile_id: int, slot_no: int) -> str:
        templates = self.db.scalar(
            "SELECT COUNT(*) FROM schedule_templates WHERE profile_id = ? AND slot_no = ?",
            (profile_id, slot_no),
        )
        overrides = self.db.scalar(
            "SELECT COUNT(*) FROM schedule_overrides WHERE profile_id = ? AND slot_no = ?",
            (profile_id, slot_no),
        )
        parts = []
        if templates:
            parts.append(f"шаблон: {templates}")
        if overrides:
            parts.append(f"изменения: {overrides}")
        return ", ".join(parts)

    def _slot(self, slot_id: int) -> BellSlot:
        row = self.db.fetchone("SELECT * FROM bell_slots WHERE id = ?", (slot_id,))
        if row is None:
            raise NotFoundError("Блок звонков не найден")
        part_rows = self.db.fetchall(
            "SELECT * FROM bell_slot_parts WHERE slot_id = ? ORDER BY seq", (slot_id,)
        )
        return _bell_slot(row, tuple(_bell_part(part) for part in part_rows))

    def slots_for_week(self, weekday: int, *, variant: str = "default") -> tuple[BellSlot, ...]:
        """Все слоты профиля выбранного дня — для редактора сетки (GRID-01)."""
        profiles = [p for p in self.profiles(include_inactive=False) if p.weekday == weekday and p.variant == variant]
        if not profiles:
            return ()
        # Берём профиль без ограничения по датам (бессрочный), иначе самый ранний.
        chosen = next((p for p in profiles if p.effective_from is None and p.effective_to is None), profiles[0])
        return chosen.slots


def _check_effective_range(start: date | None, end: date | None) -> None:
    """DATA-17: ``effective_from < effective_to``."""
    if start and end and end < start:
        raise ValidationError(
            "Дата окончания действия не может быть раньше даты начала (DATA-17).",
            field="effective_to",
        )


def _validate_parts(parts: list[tuple[str, str, str]]) -> None:
    """BELL-17: начало < окончание, части не пересекаются, первая и последняя — lesson."""
    if not parts:
        raise ValidationError("У блока должна быть хотя бы одна часть (BELL-02).", field="parts")
    previous_end: int | None = None
    for index, (part_type, start, end) in enumerate(parts):
        if part_type not in ("lesson", "break"):
            raise ValidationError(f"Тип части блока: только lesson или break ({part_type!r}).", field="parts")
        start_minutes = dt.time_to_minutes(start)
        end_minutes = dt.time_to_minutes(end)
        if start_minutes >= end_minutes:
            raise ValidationError(
                f"Часть {index + 1}: начало ({start}) должно быть раньше окончания ({end}) (BELL-17).",
                field="parts",
            )
        if previous_end is not None and start_minutes < previous_end:
            raise ValidationError(
                f"Части блока пересекаются: часть {index + 1} начинается в {start} "
                f"раньше окончания предыдущей (BELL-17).",
                field="parts",
            )
        previous_end = end_minutes
    if parts[0][0] != "lesson" or parts[-1][0] != "lesson":
        raise ValidationError(
            "Первая и последняя часть блока должны быть занятием (BELL-17).", field="parts"
        )


# ===========================================================================
# Шаблоны расписания (TPL-01…TPL-07, GRID-01…GRID-08)
# ===========================================================================
def _cell(row: Any) -> TemplateCell:
    keys = row.keys()
    return TemplateCell(
        id=row["id"], profile_id=row["profile_id"], week_type=row["week_type"],
        slot_no=int(row["slot_no"]), subject_id=row["subject_id"], group_mark=row["group_mark"],
        effective_from=_date(row["effective_from"]) if "effective_from" in keys else None,
    )


#: TPL-08: дата-«дно» для версии, действующей с самого начала учёта.
BASE_DUE_DATE = "0001-01-01"
#: TPL-08: дата-«потолок»: при чтении без даты берётся самая поздняя версия.
LATEST_DUE_DATE = "9999-12-31"


class ScheduleTemplateRepository:
    """Шаблон недели с историей правок (TPL-01, TPL-08).

    На позицию ``(profile_id, week_type, slot_no, group_mark)`` хранится не одна
    строка, а цепочка версий по ``effective_from``. Чтение возвращает версию,
    действующую на запрошенную дату, поэтому правка сетки перестаёт менять
    прошлые недели. Строка с ``subject_id IS NULL`` — явная очистка
    (надгробие): она скрывает более старое значение, но не стирает историю.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _on_date(value: date | str | None) -> str:
        if value is None:
            return LATEST_DUE_DATE
        return value if isinstance(value, str) else dt.to_iso(value)

    def cells(
        self,
        week_type: str,
        *,
        profile_id: int | None = None,
        on_date: date | str | None = None,
    ) -> list[TemplateCell]:
        """Ячейки недели, действующие на дату ``on_date`` (TPL-08)."""
        limit = self._on_date(on_date)
        sql = (
            "SELECT t.* FROM schedule_templates t "
            "WHERE t.week_type = ? AND t.effective_from <= ? "
            "AND t.effective_from = ("
            "  SELECT MAX(x.effective_from) FROM schedule_templates x "
            "  WHERE x.profile_id = t.profile_id AND x.week_type = t.week_type "
            "    AND x.slot_no = t.slot_no AND x.group_mark IS t.group_mark "
            "    AND x.effective_from <= ?"
            ") "
        )
        params: list[Any] = [week_type, limit, limit]
        if profile_id is not None:
            sql += "AND t.profile_id = ? "
            params.append(profile_id)
        sql += "ORDER BY t.profile_id, t.slot_no"
        return [_cell(row) for row in self.db.fetchall(sql, tuple(params))]

    def cell(
        self,
        profile_id: int,
        week_type: str,
        slot_no: int,
        *,
        on_date: date | str | None = None,
    ) -> TemplateCell | None:
        """Версия ячейки, действующая на дату (TPL-08)."""
        row = self.db.fetchone(
            "SELECT * FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
            "AND slot_no = ? AND group_mark IS NULL AND effective_from <= ? "
            "ORDER BY effective_from DESC LIMIT 1",
            (profile_id, week_type, slot_no, self._on_date(on_date)),
        )
        return _cell(row) if row else None

    def subject_at(
        self,
        profile_id: int,
        week_type: str,
        slot_no: int,
        *,
        on_date: date | str | None = None,
    ) -> int | None:
        cell = self.cell(profile_id, week_type, slot_no, on_date=on_date)
        return None if cell is None else cell.subject_id

    def versions(
        self, profile_id: int, week_type: str, slot_no: int
    ) -> list[TemplateCell]:
        """История позиции от старых версий к новым (TPL-08); для проверок и UI."""
        return [
            _cell(row)
            for row in self.db.fetchall(
                "SELECT * FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
                "AND slot_no = ? AND group_mark IS NULL ORDER BY effective_from",
                (profile_id, week_type, slot_no),
            )
        ]

    def set_cell(
        self,
        profile_id: int,
        week_type: str,
        slot_no: int,
        subject_id: int | None,
        *,
        effective_from: date | str | None = None,
    ) -> TemplateCell | None:
        """GRID-02/DATA-20/TPL-08: запись ячейки, действующей с даты.

        С ``effective_from`` правка создаёт новую версию: более поздние версии
        этой позиции отбрасываются (они перекрыты), более ранние сохраняются —
        прошлые недели остаются прежними. Без даты поведение прежнее: история
        позиции заменяется одной базовой строкой.
        """
        if week_type not in (WeekType.UPPER, WeekType.LOWER):
            raise ValidationError("Тип недели: только upper или lower.", field="week_type")
        if subject_id is None:
            self.clear_cell(profile_id, week_type, slot_no, effective_from=effective_from)
            return None

        start = BASE_DUE_DATE if effective_from is None else self._on_date(effective_from)
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
                "AND slot_no = ? AND group_mark IS NULL AND effective_from >= ?",
                (profile_id, week_type, slot_no, start),
            )
            conn.execute(
                "INSERT INTO schedule_templates(profile_id, week_type, slot_no, "
                "group_mark, subject_id, effective_from) VALUES (?, ?, ?, NULL, ?, ?)",
                (profile_id, week_type, slot_no, subject_id, start),
            )
        return self.cell(profile_id, week_type, slot_no, on_date=start)

    def clear_cell(
        self,
        profile_id: int,
        week_type: str,
        slot_no: int,
        *,
        effective_from: date | str | None = None,
    ) -> None:
        """GRID-05/TPL-08: очистка ячейки с даты, слот остаётся.

        С датой ставится надгробие: занятия нет с этого дня, но прошлые недели
        сохраняют прежнюю пару. Без даты строки позиции удаляются полностью.
        """
        if effective_from is None:
            with self.db.transaction() as conn:
                conn.execute(
                    "DELETE FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
                    "AND slot_no = ? AND group_mark IS NULL",
                    (profile_id, week_type, slot_no),
                )
            return

        start = self._on_date(effective_from)
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
                "AND slot_no = ? AND group_mark IS NULL AND effective_from >= ?",
                (profile_id, week_type, slot_no, start),
            )
            # Надгробие нужно, только если раньше было что скрывать.
            earlier = conn.execute(
                "SELECT 1 FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
                "AND slot_no = ? AND group_mark IS NULL AND subject_id IS NOT NULL "
                "AND effective_from < ? LIMIT 1",
                (profile_id, week_type, slot_no, start),
            ).fetchone()
            if earlier is None:
                return
            conn.execute(
                "INSERT INTO schedule_templates(profile_id, week_type, slot_no, "
                "group_mark, subject_id, effective_from) VALUES (?, ?, ?, NULL, NULL, ?)",
                (profile_id, week_type, slot_no, start),
            )

    def clear_week(self, week_type: str) -> int:
        """GRID-04 — v1.1; метод оставлен для полноты и «Вернуть стартовый набор»."""
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM schedule_templates WHERE week_type = ?", (week_type,))
            return int(cursor.rowcount)

    def replace_week(
        self,
        week_type: str,
        entries: Iterable[tuple[int, int, int]],
        *,
        effective_from: date | str | None = None,
    ) -> int:
        """Перезаписать неделю набором ``(profile_id, slot_no, subject_id)`` (GRID-11).

        С датой создаётся новая версия каждой ячейки — прошлые недели целы.
        Без даты история недели заменяется базовыми строками.
        """
        rows = list(entries)
        start = BASE_DUE_DATE if effective_from is None else self._on_date(effective_from)
        with self.db.transaction() as conn:
            if effective_from is None:
                conn.execute(
                    "DELETE FROM schedule_templates WHERE week_type = ?", (week_type,)
                )
            else:
                # Позиции, которых нет в новом наборе, тоже нужно очистить —
                # иначе они «протекут» в новую версию недели.
                conn.execute(
                    "DELETE FROM schedule_templates WHERE week_type = ? AND effective_from >= ?",
                    (week_type, start),
                )
            for profile_id, slot_no, subject_id in rows:
                conn.execute(
                    "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, "
                    "subject_id, effective_from) VALUES (?, ?, ?, NULL, ?, ?)",
                    (profile_id, week_type, slot_no, subject_id, start),
                )
        return len(rows)

    def fill_missing_week(self, week_type: str, entries: Iterable[tuple[int, int, int]]) -> int:
        """FIRST-05/GRID-11: добавить только отсутствующие ячейки, изменённые не трогать."""
        added = 0
        with self.db.transaction() as conn:
            for profile_id, slot_no, subject_id in entries:
                exists = conn.execute(
                    "SELECT 1 FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
                    "AND slot_no = ? AND group_mark IS NULL",
                    (profile_id, week_type, slot_no),
                ).fetchone()
                if exists:
                    continue
                conn.execute(
                    "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, "
                    "subject_id, effective_from) VALUES (?, ?, ?, NULL, ?, ?)",
                    (profile_id, week_type, slot_no, subject_id, BASE_DUE_DATE),
                )
                added += 1
        return added

    def occupied_slots(
        self, profile_id: int, week_type: str, *, on_date: date | str | None = None
    ) -> set[int]:
        return {
            cell.slot_no
            for cell in self.cells(week_type, profile_id=profile_id, on_date=on_date)
            if cell.subject_id is not None
        }


# ===========================================================================
# Оверрайды (OVR-01…OVR-12, ALG-10)
# ===========================================================================
def _override(row: Any) -> ScheduleOverride:
    return ScheduleOverride(
        id=row["id"],
        date=_date(row["date"]),  # type: ignore[arg-type]
        profile_id=row["profile_id"],
        slot_no=int(row["slot_no"]),
        override_type=row["override_type"],
        subject_id=row["subject_id"],
        teacher=row["teacher"],
        room=row["room"],
        custom_start=row["custom_start"],
        custom_end=row["custom_end"],
        target_slot_no=row["target_slot_no"],
        keep_original=int(row["keep_original"]),
        comment=row["comment"],
        created_at=row["created_at"],
        group_mark=row["group_mark"],
        part_seq=row["part_seq"],
    )


class ScheduleOverrideRepository:
    """Разовые изменения расписания на дату; шаблон не затрагивают (OVR-01)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self, *, profile_id: int | None = None) -> list[ScheduleOverride]:
        if profile_id is None:
            rows = self.db.fetchall("SELECT * FROM schedule_overrides ORDER BY date, slot_no")
        else:
            rows = self.db.fetchall(
                "SELECT * FROM schedule_overrides WHERE profile_id = ? ORDER BY date, slot_no",
                (profile_id,),
            )
        return [_override(row) for row in rows]

    def for_date(self, value: date, *, profile_id: int | None = None) -> list[ScheduleOverride]:
        if profile_id is None:
            rows = self.db.fetchall(
                "SELECT * FROM schedule_overrides WHERE date = ? ORDER BY slot_no", (dt.to_iso(value),)
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM schedule_overrides WHERE date = ? AND profile_id = ? ORDER BY slot_no",
                (dt.to_iso(value), profile_id),
            )
        return [_override(row) for row in rows]

    def dates_with_overrides(self, start: date | None = None, end: date | None = None) -> set[date]:
        sql = "SELECT DISTINCT date FROM schedule_overrides WHERE 1 = 1"
        params: list[str] = []
        if start:
            sql += " AND date >= ?"
            params.append(dt.to_iso(start))
        if end:
            sql += " AND date <= ?"
            params.append(dt.to_iso(end))
        return {_date(row["date"]) for row in self.db.fetchall(sql, tuple(params))}  # type: ignore[misc]

    def by_id(self, override_id: int) -> ScheduleOverride | None:
        row = self.db.fetchone("SELECT * FROM schedule_overrides WHERE id = ?", (override_id,))
        return _override(row) if row else None

    def create(
        self,
        value: date | str,
        profile_id: int,
        slot_no: int,
        override_type: str,
        *,
        subject_id: int | None = None,
        teacher: str | None = None,
        room: str | None = None,
        custom_start: str | None = None,
        custom_end: str | None = None,
        comment: str | None = None,
        target_slot_no: int | None = None,
        keep_original: int = 0,
        template_subject_id: int | None = None,
        template_exists: bool | None = None,
    ) -> ScheduleOverride:
        """Создать оверрайд с проверками OVR-08 (конфликты) и OVR-02 (типы MVP)."""
        day = _coerce_date(value, "date")
        if override_type not in OverrideType_MVP:
            raise ValidationError(
                f"Тип изменения {override_type!r} в MVP недоступен: перенос пары выражается "
                "отменой на исходном слоте и добавлением в свободный (OVR-02, ACC-M-103).",
                field="override_type",
            )
        if override_type in (OverrideType.REPLACE, OverrideType.ADD) and subject_id is None:
            # OVR-05/OVR-07: замена и добавление обязаны указывать предмет.
            raise ValidationError(
                f"Тип «{OverrideType.label(override_type)}» требует предмета: "
                "выберите предмет замены или добавления (OVR-05, OVR-07).",
                field="subject_id",
            )
        if override_type in (OverrideType.CANCEL, OverrideType.REPLACE):
            # Не более одного оверрайда из cancel/replace на (date, profile, slot) — OVR-08.
            existing = self.db.fetchone(
                "SELECT id, override_type FROM schedule_overrides WHERE date = ? AND profile_id = ? "
                "AND slot_no = ? AND group_mark IS NULL AND override_type IN ('cancel','replace')",
                (dt.to_iso(day), profile_id, slot_no),
            )
            if existing is not None:
                if (
                    override_type == OverrideType.REPLACE
                    and existing["override_type"] == OverrideType.CANCEL
                ):
                    # OVR-05/SCH-18: замена поверх отмены того же блока — это
                    # «убрал пару, поставил другую». Прежний cancel снимаем,
                    # иначе правило «одно изменение на блок» блокировало путь.
                    with self.db.transaction() as conn:
                        conn.execute(
                            "DELETE FROM schedule_overrides WHERE id = ?", (existing["id"],)
                        )
                else:
                    raise RuleViolationError(
                        f"На {dt.format_display(day)} для этого блока уже есть изменение "
                        f"«{existing['override_type']}»: допускается только одно из отмены или "
                        "замены на дату и блок (OVR-08)."
                    )
        if override_type == OverrideType.ADD:
            # OVR-07/OVR-08: add в занятый слот запрещён, но отменённый блок
            # (оверрайд ``cancel`` на эту дату) считаем свободным: пара в этот
            # день не показывается (SCH-18), значит место освободилось. Иначе
            # цепочка «отменил пару → поставил другую» упиралась в отказ, и
            # пользователь не мог вернуть занятие в освободившийся блок.
            cancelled = self.db.fetchone(
                "SELECT 1 FROM schedule_overrides WHERE date = ? AND profile_id = ? "
                "AND slot_no = ? AND group_mark IS NULL AND override_type = 'cancel'",
                (dt.to_iso(day), profile_id, slot_no),
            )
            if template_exists is not None:
                occupied = bool(template_exists)
            else:
                occupied = self._has_template(profile_id, day, slot_no)
            if (occupied or template_subject_id is not None) and cancelled is None:
                raise RuleViolationError(
                    "Нельзя добавить занятие в занятый блок: выберите свободный слот или "
                    "пользуйтесь заменой (OVR-08)."
                )
            if cancelled is not None and occupied:
                # В блоке есть пара по шаблону, но она отменена на эту дату.
                # Поставить новую «вместо» отменённой — это замена, а не
                # добавление: ``add`` на слот с шаблоном ALG-04 игнорирует
                # (показывает занятие по плану). Меняем тип на ``replace``.
                with self.db.transaction() as conn:
                    conn.execute(
                        "DELETE FROM schedule_overrides WHERE date = ? AND profile_id = ? "
                        "AND slot_no = ? AND group_mark IS NULL AND override_type = 'cancel'",
                        (dt.to_iso(day), profile_id, slot_no),
                    )
                override_type = OverrideType.REPLACE
            elif cancelled is not None:
                # Слота в шаблоне нет — отмена не нужна, блок и так свободен.
                with self.db.transaction() as conn:
                    conn.execute(
                        "DELETE FROM schedule_overrides WHERE date = ? AND profile_id = ? "
                        "AND slot_no = ? AND group_mark IS NULL AND override_type = 'cancel'",
                        (dt.to_iso(day), profile_id, slot_no),
                    )
            # Второй add на тот же блок дал бы две пары в одном слоте: одна
            # показывалась бы, вторая висела бы скрытым дублем.
            existing_add = self.db.fetchone(
                "SELECT id FROM schedule_overrides WHERE date = ? AND profile_id = ? "
                "AND slot_no = ? AND group_mark IS NULL AND override_type = 'add'",
                (dt.to_iso(day), profile_id, slot_no),
            )
            if existing_add is not None:
                raise RuleViolationError(
                    f"На {dt.format_display(day)} в этом блоке уже есть добавленное "
                    "занятие: измените его или выберите другой блок (OVR-08)."
                )
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO schedule_overrides(date, profile_id, slot_no, group_mark, part_seq, "
                "override_type, subject_id, teacher, room, custom_start, custom_end, "
                "target_slot_no, keep_original, comment, created_at) "
                "VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dt.to_iso(day), profile_id, slot_no, override_type, subject_id,
                    (teacher or "").strip() or None, (room or "").strip() or None,
                    custom_start, custom_end, target_slot_no, keep_original, comment, _now(),
                ),
            )
            new_id = int(cursor.lastrowid)
        created = self.by_id(new_id)
        if created is None:  # pragma: no cover
            raise NotFoundError("Созданное изменение не найдено")
        return created

    def update(
        self,
        override_id: int,
        *,
        subject_id: int | None = None,
        teacher: str | None = None,
        room: str | None = None,
        custom_start: str | None = None,
        custom_end: str | None = None,
        comment: str | None = None,
        new_subject_id: object = _UNSET,
        new_teacher: object = _UNSET,
        new_room: object = _UNSET,
        new_custom_start: object = _UNSET,
        new_custom_end: object = _UNSET,
        new_comment: object = _UNSET,
    ) -> ScheduleOverride:
        """Правка замены: время по умолчанию сохраняется, может быть задано своё (OVR-05)."""
        current = self.by_id(override_id)
        if current is None:
            raise NotFoundError("Изменение расписания не найдено")

        def pick(new: object, old: Any) -> Any:
            return old if new is _UNSET else new

        def clean(value: object) -> Any:
            if value is _UNSET:
                return _UNSET
            return (str(value).strip() or None) if value is not None else None

        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE schedule_overrides SET subject_id = ?, teacher = ?, room = ?, "
                "custom_start = ?, custom_end = ?, comment = ? WHERE id = ?",
                (
                    pick(new_subject_id, current.subject_id),
                    pick(clean(new_teacher), current.teacher),
                    pick(clean(new_room), current.room),
                    pick(new_custom_start, current.custom_start),
                    pick(new_custom_end, current.custom_end),
                    pick(new_comment, current.comment),
                    override_id,
                ),
            )
        updated = self.by_id(override_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Изменение расписания не найдено")
        return updated

    def delete(self, override_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM schedule_overrides WHERE id = ?", (override_id,))

    def delete_for_date(self, value: date, *, profile_id: int | None = None) -> int:
        """SCH-08: «Сбросить изменения на эту дату» — удаление оверрайдов даты."""
        with self.db.transaction() as conn:
            if profile_id is None:
                cursor = conn.execute(
                    "DELETE FROM schedule_overrides WHERE date = ?", (dt.to_iso(value),)
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM schedule_overrides WHERE date = ? AND profile_id = ?",
                    (dt.to_iso(value), profile_id),
                )
            return int(cursor.rowcount)

    def orphans(self, *, week_type_for_date: Any = None) -> list[ScheduleOverride]:
        """ALG-10: оверрайды ``cancel``/``replace`` без занятия в шаблоне.

        Сиротство — производное состояние: вычисляется при чтении, отдельного
        столбца нет. Оверрайд типа ``add`` сиротским не считается (ALG-10 п. 4),
        потому что существует независимо от шаблона.
        """
        resolver = week_type_for_date or self.week_type_for
        rows = self.db.fetchall(
            "SELECT * FROM schedule_overrides WHERE override_type IN ('cancel','replace') "
            "ORDER BY date, slot_no"
        )
        result: list[ScheduleOverride] = []
        for row in rows:
            item = _override(row)
            if self.is_orphan(item, resolver(item.date)):
                result.append(item)
        return result

    def is_orphan(self, override: ScheduleOverride, week_type: str) -> bool:
        """ALG-10 п. 2: ``add`` не бывает сиротским; остальные — без занятия в шаблоне."""
        if override.override_type == OverrideType.ADD:
            return False
        return not self._has_template_on(
            override.profile_id, week_type, override.slot_no, override.date
        )

    def _has_template_on(
        self, profile_id: int, week_type: str, slot_no: int, value: date
    ) -> bool:
        """TPL-08: занятие есть в версии шаблона, действующей на эту дату."""
        row = self.db.fetchone(
            "SELECT 1 FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
            "AND slot_no = ? AND subject_id IS NOT NULL AND effective_from <= ? LIMIT 1",
            (profile_id, week_type, slot_no, dt.to_iso(value)),
        )
        return row is not None

    def delete_orphans(self, *, week_type_for_date: Any = None) -> list[ScheduleOverride]:
        """ALG-10 п. 5: массовое удаление сиротских одной кнопкой."""
        orphans = self.orphans(week_type_for_date=week_type_for_date)
        if orphans:
            with self.db.transaction() as conn:
                conn.executemany(
                    "DELETE FROM schedule_overrides WHERE id = ?",
                    [(item.id,) for item in orphans],
                )
        return orphans

    def _has_template(self, profile_id: int, value: date, slot_no: int) -> bool:
        """Занят ли блок в шаблоне на дату (с учётом типа недели по ALG-01)."""
        week_type = self.week_type_for(value)
        return self._has_template_on(profile_id, week_type, slot_no, value)

    def week_type_for(self, value: date) -> str:
        """Тип недели даты по действующему якорю; при отсутствии якорей — lower."""
        anchors = [_anchor(row) for row in self.db.fetchall("SELECT * FROM week_anchors")]
        resolved = week_type_for(anchors, value)
        return resolved or WeekType.LOWER


#: Типы оверрайдов, допустимые в MVP (OVR-02; ACC-M-103).
OverrideType_MVP = ("cancel", "replace", "add")


# ===========================================================================
# Учебные периоды (CAL-01…CAL-14)
# ===========================================================================
def _period(row: Any) -> StudyPeriod:
    return StudyPeriod(
        id=row["id"],
        kind=row["kind"],
        title=row["title"],
        date_from=_date(row["date_from"]),  # type: ignore[arg-type]
        date_to=_date(row["date_to"]),  # type: ignore[arg-type]
        no_classes=_bool(row["no_classes"]),
        place=row["place"],
        is_active=_bool(row["is_active"]),
        comment=row["comment"],
        outbound_template_id=row["outbound_template_id"],
        return_template_id=row["return_template_id"],
    )


class StudyPeriodRepository:
    """Учебные периоды: каникулы и праздник отменяют занятия (CAL-02)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self, *, include_inactive: bool = True) -> list[StudyPeriod]:
        sql = "SELECT * FROM study_periods"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        return [
            _period(row)
            for row in self.db.fetchall(sql + " ORDER BY date_from, id")
        ]

    def by_id(self, period_id: int) -> StudyPeriod | None:
        row = self.db.fetchone("SELECT * FROM study_periods WHERE id = ?", (period_id,))
        return _period(row) if row else None

    def covering(self, value: date, *, no_classes_only: bool = False) -> StudyPeriod | None:
        """CAL-03/ALG-04 шаг 1: период, содержащий дату; при пересечении — последний созданный."""
        sql = "SELECT * FROM study_periods WHERE is_active = 1 AND date_from <= ? AND date_to >= ?"
        if no_classes_only:
            sql += " AND no_classes = 1"
        row = self.db.fetchone(sql + " ORDER BY id DESC LIMIT 1", (dt.to_iso(value), dt.to_iso(value)))
        return _period(row) if row else None

    def for_range(self, start: date, end: date) -> list[StudyPeriod]:
        return [
            _period(row)
            for row in self.db.fetchall(
                "SELECT * FROM study_periods WHERE is_active = 1 AND date_from <= ? AND date_to >= ? "
                "ORDER BY date_from",
                (dt.to_iso(end), dt.to_iso(start)),
            )
        ]

    def dates_with_periods(self, start: date | None = None, end: date | None = None) -> dict[date, StudyPeriod]:
        """Даты с периодами — точки-метки мини-календаря (UI-05)."""
        result: dict[date, StudyPeriod] = {}
        for period in self.all(include_inactive=False):
            if start and period.date_to < start:
                continue
            if end and period.date_from > end:
                continue
            for day in dt.date_range(period.date_from, period.date_to):
                if start and day < start:
                    continue
                if end and day > end:
                    continue
                result.setdefault(day, period)
        return result

    def create(
        self,
        kind: str,
        title: str,
        date_from: date | str,
        date_to: date | str,
        *,
        no_classes: bool = True,
        place: str | None = None,
        comment: str | None = None,
        is_active: bool = True,
    ) -> StudyPeriod:
        if kind not in PeriodKind.ALL:
            raise ValidationError(f"Неизвестный вид периода: {kind}", field="kind")
        start = _coerce_date(date_from, "date_from")
        end = _coerce_date(date_to, "date_to")
        if end < start:
            raise ValidationError(
                "Дата окончания периода не может быть раньше даты начала (DATA-17).", field="date_to"
            )
        if not (title or "").strip():
            raise ValidationError("Название периода обязательно (CAL-01).", field="title")
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO study_periods(kind, title, date_from, date_to, no_classes, place, "
                "is_active, comment) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, title.strip(), dt.to_iso(start), dt.to_iso(end), 1 if no_classes else 0,
                 place, 1 if is_active else 0, comment),
            )
            new_id = int(cursor.lastrowid)
        created = self.by_id(new_id)
        if created is None:  # pragma: no cover
            raise NotFoundError("Созданный период не найден")
        return created

    def update(
        self,
        period_id: int,
        *,
        kind: str | None = None,
        title: str | None = None,
        date_from: date | str | None = None,
        date_to: date | str | None = None,
        no_classes: bool | None = None,
        place: str | None = None,
        comment: str | None = None,
        is_active: bool | None = None,
    ) -> StudyPeriod:
        current = self.by_id(period_id)
        if current is None:
            raise NotFoundError("Учебный период не найден")
        start = _coerce_date(date_from, "date_from") if date_from else current.date_from
        end = _coerce_date(date_to, "date_to") if date_to else current.date_to
        if end < start:
            raise ValidationError(
                "Дата окончания периода не может быть раньше даты начала (DATA-17).", field="date_to"
            )
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE study_periods SET kind = ?, title = ?, date_from = ?, date_to = ?, "
                "no_classes = ?, place = ?, comment = ?, is_active = ? WHERE id = ?",
                (
                    kind or current.kind,
                    (title or current.title).strip(),
                    dt.to_iso(start),
                    dt.to_iso(end),
                    (1 if current.no_classes else 0) if no_classes is None else (1 if no_classes else 0),
                    current.place if place is None else place,
                    current.comment if comment is None else comment,
                    (1 if current.is_active else 0) if is_active is None else (1 if is_active else 0),
                    period_id,
                ),
            )
        updated = self.by_id(period_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Учебный период не найден")
        return updated

    def delete(self, period_id: int) -> None:
        if self.by_id(period_id) is None:
            raise NotFoundError("Учебный период не найден")
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM study_periods WHERE id = ?", (period_id,))


__all__ = [
    "SubjectRepository",
    "TariffRepository",
    "WeekAnchorRepository",
    "BellRepository",
    "ScheduleTemplateRepository",
    "ScheduleOverrideRepository",
    "StudyPeriodRepository",
]
