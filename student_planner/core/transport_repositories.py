"""Репозитории транспорта, кошелька и домашних заданий.

Отдельный модуль, потому что эти сущности меняются вместе: подтверждение дня
создаёт поездки, поездки двигают счётчик «Стрелки» и остаток кошелька, а
домашние задания ссылаются на предметы.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from . import dates as dt
from .database import Database
from .errors import InUseError, NotFoundError, RuleViolationError, ValidationError
from .models import (
    Direction,
    Homework,
    HomeworkStatus,
    PaymentMethod,
    Ride,
    TopUp,
    TransportType,
    TripConfirmation,
    TripLeg,
    TripTemplate,
)
from .money import ZERO, from_db, to_db


def _d(text: Any) -> date | None:
    if text is None or text == "":
        return None
    return dt.parse_iso(str(text))


def _nb(value: Any) -> bool:
    return bool(value)


def _now() -> str:
    from . import clock

    return clock.now_iso()


# ===========================================================================
# Шаблоны поездок (RT-01…RT-17, Прил. Б.13–Б.14)
# ===========================================================================
def _leg(row: Any) -> TripLeg:
    return TripLeg(
        id=row["id"],
        template_id=row["template_id"],
        seq=int(row["seq"]),
        mode=row["mode"],
        vehicle=row["vehicle"],
        payment_method=row["payment_method"],
        is_paid=_nb(row["is_paid"]),
    )


class TripTemplateRepository:
    """Шаблоны поездок: направление + упорядоченные рейсы (RT-10)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------- чтение
    def all(self, *, include_inactive: bool = True) -> list[TripTemplate]:
        sql = "SELECT * FROM trip_templates"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        rows = self.db.fetchall(sql + " ORDER BY direction, COALESCE(sort_order, 999), id")
        return [self._template(row) for row in rows]

    def by_direction(self, direction: str, *, include_inactive: bool = False) -> list[TripTemplate]:
        return [item for item in self.all(include_inactive=include_inactive) if item.direction == direction]

    def active(self) -> list[TripTemplate]:
        return self.all(include_inactive=False)

    def by_id(self, template_id: int) -> TripTemplate | None:
        row = self.db.fetchone("SELECT * FROM trip_templates WHERE id = ?", (template_id,))
        return self._template(row) if row else None

    def require(self, template_id: int) -> TripTemplate:
        template = self.by_id(template_id)
        if template is None:
            raise NotFoundError(f"Шаблон поездки с id={template_id} не найден")
        return template

    def _template(self, row: Any) -> TripTemplate:
        leg_rows = self.db.fetchall(
            "SELECT * FROM trip_template_legs WHERE template_id = ? ORDER BY seq", (row["id"],)
        )
        return TripTemplate(
            id=row["id"],
            direction=row["direction"],
            name=row["name"],
            is_active=_nb(row["is_active"]),
            default_payment_method=row["default_payment_method"],
            depart_hint=row["depart_hint"],
            arrive_hint=row["arrive_hint"],
            note=row["note"],
            sort_order=row["sort_order"],
            legs=tuple(_leg(leg) for leg in leg_rows),
        )

    # ------------------------------------------------------------- запись
    def create(
        self,
        direction: str,
        name: str,
        legs: Iterable[dict[str, Any]],
        *,
        default_payment_method: str | None = None,
        depart_hint: str | None = None,
        arrive_hint: str | None = None,
        note: str | None = None,
        is_active: bool = True,
        sort_order: int | None = None,
    ) -> TripTemplate:
        """RT-16: минимум один рейс, номер обязателен, платный рейс — со способом оплаты."""
        leg_list = list(legs)
        _validate_template(direction, name, leg_list)
        with self.db.transaction() as conn:
            if sort_order is None:
                sort_order = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM trip_templates WHERE direction = ?",
                        (direction,),
                    ).fetchone()[0]
                )
            cursor = conn.execute(
                "INSERT INTO trip_templates(direction, name, is_active, default_payment_method, "
                "depart_hint, arrive_hint, note, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    direction, name.strip(), 1 if is_active else 0,
                    default_payment_method or _infer_default_payment(leg_list),
                    depart_hint, arrive_hint, note, sort_order,
                ),
            )
            template_id = int(cursor.lastrowid)
            for seq, leg in enumerate(leg_list, start=1):
                conn.execute(
                    "INSERT INTO trip_template_legs(template_id, seq, mode, vehicle, is_paid, "
                    "payment_method) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        template_id, seq, leg["mode"], str(leg["vehicle"]).strip(),
                        1 if leg.get("is_paid", True) else 0, leg["payment_method"],
                    ),
                )
        return self.require(template_id)

    def update(
        self,
        template_id: int,
        *,
        name: str | None = None,
        legs: Iterable[dict[str, Any]] | None = None,
        default_payment_method: str | None = None,
        depart_hint: str | None = None,
        arrive_hint: str | None = None,
        note: str | None = None,
        is_active: bool | None = None,
        direction: str | None = None,
    ) -> TripTemplate:
        current = self.require(template_id)
        new_direction = direction or current.direction
        new_name = (name if name is not None else current.name)
        leg_list = list(legs) if legs is not None else None
        if leg_list is not None:
            _validate_template(new_direction, new_name, leg_list)
        # Способ оплаты шаблона выводится из рейсов так же, как при создании:
        # схема (Б.13) допускает только 'strelka'/'debit_card', а у шаблона из
        # одной электрички автобусного рейса нет — тогда NULL.
        if default_payment_method is not None:
            new_default = default_payment_method
        elif leg_list is not None:
            new_default = _infer_default_payment(leg_list)
        else:
            new_default = current.default_payment_method
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE trip_templates SET direction = ?, name = ?, default_payment_method = ?, "
                "depart_hint = ?, arrive_hint = ?, note = ?, is_active = ? WHERE id = ?",
                (
                    new_direction,
                    new_name.strip(),
                    new_default,
                    current.depart_hint if depart_hint is None else depart_hint,
                    current.arrive_hint if arrive_hint is None else arrive_hint,
                    current.note if note is None else note,
                    (1 if current.is_active else 0) if is_active is None else (1 if is_active else 0),
                    template_id,
                ),
            )
            if leg_list is not None:
                conn.execute("DELETE FROM trip_template_legs WHERE template_id = ?", (template_id,))
                for seq, leg in enumerate(leg_list, start=1):
                    conn.execute(
                        "INSERT INTO trip_template_legs(template_id, seq, mode, vehicle, is_paid, "
                        "payment_method) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            template_id, seq, leg["mode"], str(leg["vehicle"]).strip(),
                            1 if leg.get("is_paid", True) else 0, leg["payment_method"],
                        ),
                    )
        return self.require(template_id)

    def copy(self, template_id: int, *, new_name: str | None = None) -> TripTemplate:
        """RT-13: копирование шаблона с теми же рейсами."""
        source = self.require(template_id)
        legs = [
            {
                "mode": leg.mode,
                "vehicle": leg.vehicle,
                "is_paid": leg.is_paid,
                "payment_method": leg.payment_method,
            }
            for leg in source.legs
        ]
        return self.create(
            source.direction,
            new_name or f"{source.name} (копия)",
            legs,
            default_payment_method=source.default_payment_method,
            depart_hint=source.depart_hint,
            arrive_hint=source.arrive_hint,
            note=source.note,
        )

    def set_active(self, template_id: int, active: bool) -> TripTemplate:
        self.require(template_id)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE trip_templates SET is_active = ? WHERE id = ?",
                (1 if active else 0, template_id),
            )
        return self.require(template_id)

    def delete(self, template_id: int, *, confirm_used: bool = False) -> None:
        """RT-14/RT-15: удаление не меняет поездки; использованный шаблон — с предупреждением."""
        self.require(template_id)
        used_rides = self.db.scalar(
            "SELECT COUNT(*) FROM transport_rides WHERE template_id = ?", (template_id,)
        )
        used_confirmations = self.db.scalar(
            "SELECT COUNT(*) FROM trip_confirmations "
            "WHERE outbound_template_id = ? OR return_template_id = ?",
            (template_id, template_id),
        )
        if (used_rides or used_confirmations) and not confirm_used:
            raise InUseError(
                f"Шаблон использован: поездок — {used_rides}, подтверждений дня — "
                f"{used_confirmations}. Удаление возможно только после подтверждения; "
                "предпочтительна деактивация (RT-15).",
                details={"rides": int(used_rides), "confirmations": int(used_confirmations)},
            )
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM trip_templates WHERE id = ?", (template_id,))

    def references(self, template_id: int) -> int:
        return int(
            self.db.scalar("SELECT COUNT(*) FROM transport_rides WHERE template_id = ?", (template_id,)) or 0
        )


def _infer_default_payment(legs: list[dict[str, Any]]) -> str | None:
    """Способ оплаты шаблона по умолчанию: первый автобусный рейс."""
    for leg in legs:
        if leg["mode"] == TransportType.BUS:
            method = leg.get("payment_method")
            if method in PaymentMethod.BUS:
                return method
    return None


def _validate_template(direction: str, name: str, legs: list[dict[str, Any]]) -> None:
    """RT-06/RT-16 и правило RT-17 (электричка — только студенческий билет)."""
    if direction not in Direction.ALL:
        raise ValidationError(
            f"Направление: допустимы только {', '.join(Direction.ALL)} (RT-06).", field="direction"
        )
    if not (name or "").strip():
        raise ValidationError("Название шаблона обязательно (RT-16).", field="name")
    if not legs:
        raise ValidationError("Шаблон должен содержать хотя бы один рейс (RT-16).", field="legs")
    for index, leg in enumerate(legs, start=1):
        mode = leg.get("mode")
        if mode not in TransportType.ALL:
            raise ValidationError(
                f"Рейс {index}: тип транспорта — только электричка или автобус (RT-02).", field="legs"
            )
        vehicle = str(leg.get("vehicle") or "").strip()
        if not vehicle:
            raise ValidationError(
                f"Рейс {index}: не указан номер автобуса или название участка (RT-03, RT-16).",
                field="legs",
            )
        if not leg.get("is_paid", True):
            continue
        method = leg.get("payment_method")
        if not method:
            raise ValidationError(f"Рейс {index}: не указан способ оплаты (RT-16).", field="legs")
        if mode == TransportType.TRAIN:
            if method != PaymentMethod.TRAIN_STUDENT:
                raise ValidationError(
                    f"Рейс {index}: электричка оплачивается только студенческим билетом "
                    "(RT-17, FARE-03).",
                    field="legs",
                )
        elif method not in PaymentMethod.BUS:
            raise ValidationError(
                f"Рейс {index}: автобус оплачивается «Стрелкой» или дебетовой картой (FARE-05).",
                field="legs",
            )


# ===========================================================================
# Подтверждения дня (TRIP-01…TRIP-19, Прил. Б.15)
# ===========================================================================
def _confirmation(row: Any) -> TripConfirmation:
    return TripConfirmation(
        id=row["id"],
        study_date=_d(row["study_date"]),  # type: ignore[arg-type]
        outbound_template_id=row["outbound_template_id"],
        return_template_id=row["return_template_id"],
        include_outbound=_nb(row["include_outbound"]),
        include_return=_nb(row["include_return"]),
        confirmed_at=row["confirmed_at"],
        week_type_snapshot=row["week_type_snapshot"],
        comment=row["comment"],
    )


class TripConfirmationRepository:
    """Подтверждение дня: ``UNIQUE(study_date)`` — идемпотентность (TRIP-09)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def by_date(self, value: date) -> TripConfirmation | None:
        row = self.db.fetchone(
            "SELECT * FROM trip_confirmations WHERE study_date = ?", (dt.to_iso(value),)
        )
        return _confirmation(row) if row else None

    def all(self) -> list[TripConfirmation]:
        return [
            _confirmation(row)
            for row in self.db.fetchall("SELECT * FROM trip_confirmations ORDER BY study_date")
        ]

    def dates(self) -> set[date]:
        """Даты с подтверждениями — точки-метки мини-календаря (UI-05)."""
        return {_d(row["study_date"]) for row in self.db.fetchall("SELECT study_date FROM trip_confirmations")}  # type: ignore[misc]

    def upsert(
        self,
        value: date,
        *,
        outbound_template_id: int | None,
        return_template_id: int | None,
        include_outbound: bool = True,
        include_return: bool = True,
        week_type_snapshot: str | None = None,
        comment: str | None = None,
    ) -> TripConfirmation:
        """Создать или обновить подтверждение даты (TRIP-09: повтор не плодит дублей)."""
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO trip_confirmations(study_date, outbound_template_id, "
                "return_template_id, include_outbound, include_return, week_type_snapshot, "
                "confirmed_at, comment) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(study_date) DO UPDATE SET "
                "outbound_template_id = excluded.outbound_template_id, "
                "return_template_id = excluded.return_template_id, "
                "include_outbound = excluded.include_outbound, "
                "include_return = excluded.include_return, "
                "week_type_snapshot = excluded.week_type_snapshot, "
                "confirmed_at = excluded.confirmed_at, "
                "comment = excluded.comment",
                (
                    dt.to_iso(value), outbound_template_id, return_template_id,
                    1 if include_outbound else 0, 1 if include_return else 0,
                    week_type_snapshot, _now(), comment,
                ),
            )
        created = self.by_date(value)
        if created is None:  # pragma: no cover
            raise NotFoundError("Подтверждение дня не сохранено")
        return created

    def delete(self, value: date) -> int:
        """Удалить подтверждение (TRIP-10: поездки дня обрабатывает сервис)."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM trip_confirmations WHERE study_date = ?", (dt.to_iso(value),)
            )
            return int(cursor.rowcount)


# ===========================================================================
# Поездки (REP-01…REP-14, Прил. Б.17)
# ===========================================================================
def _ride(row: Any) -> Ride:
    return Ride(
        id=row["id"],
        study_date=_d(row["study_date"]),  # type: ignore[arg-type]
        ride_date=_d(row["ride_date"]),  # type: ignore[arg-type]
        direction=row["direction"],
        transport_type=row["transport_type"],
        vehicle=row["vehicle"],
        base_price=from_db(row["base_price"]),
        paid_price=from_db(row["paid_price"]),
        discount_amount=from_db(row["discount_amount"]),
        payment_method=row["payment_method"],
        confirmation_id=row["confirmation_id"],
        template_id=row["template_id"],
        template_leg_id=row["template_leg_id"],
        period_id=row["period_id"],
        tariff_id=row["tariff_id"],
        period_start_date=_d(row["period_start_date"]),
        ride_number_in_period=row["ride_number_in_period"],
        week_type_snapshot=row["week_type_snapshot"],
        is_manual=_nb(row["is_manual"]),
        price_locked=_nb(row["price_locked"]),
        comment=row["comment"],
        created_at=row["created_at"],
    )


class RideRepository:
    """Журнал поездок: чтение, вставка, правка, удаление, выборки для ALG-02."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------- чтение
    def by_id(self, ride_id: int) -> Ride | None:
        row = self.db.fetchone("SELECT * FROM transport_rides WHERE id = ?", (ride_id,))
        return _ride(row) if row else None

    def require(self, ride_id: int) -> Ride:
        ride = self.by_id(ride_id)
        if ride is None:
            raise NotFoundError(f"Поездка с id={ride_id} не найдена")
        return ride

    def for_date(self, value: date) -> list[Ride]:
        return [
            _ride(row)
            for row in self.db.fetchall(
                "SELECT * FROM transport_rides WHERE study_date = ? ORDER BY id", (dt.to_iso(value),)
            )
        ]

    def for_confirmation(self, confirmation_id: int) -> list[Ride]:
        return [
            _ride(row)
            for row in self.db.fetchall(
                "SELECT * FROM transport_rides WHERE confirmation_id = ? ORDER BY id",
                (confirmation_id,),
            )
        ]

    def all(self, *, limit: int | None = None) -> list[Ride]:
        sql = "SELECT * FROM transport_rides ORDER BY ride_date, id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [_ride(row) for row in self.db.fetchall(sql)]

    def filtered(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        transport_type: str | None = None,
        payment_method: str | None = None,
        direction: str | None = None,
        limit: int | None = None,
    ) -> list[Ride]:
        """Фильтры журнала (REP-02): по дате, типу транспорта, способу оплаты."""
        clauses: list[str] = []
        params: list[Any] = []
        if date_from:
            clauses.append("ride_date >= ?")
            params.append(dt.to_iso(date_from))
        if date_to:
            clauses.append("ride_date <= ?")
            params.append(dt.to_iso(date_to))
        if transport_type:
            clauses.append("transport_type = ?")
            params.append(transport_type)
        if payment_method:
            clauses.append("payment_method = ?")
            params.append(payment_method)
        if direction:
            clauses.append("direction = ?")
            params.append(direction)
        sql = "SELECT * FROM transport_rides"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ride_date, id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [_ride(row) for row in self.db.fetchall(sql, tuple(params))]

    def dates(self) -> set[date]:
        return {_d(row["ride_date"]) for row in self.db.fetchall("SELECT DISTINCT ride_date FROM transport_rides")}  # type: ignore[misc]

    def strelka_rides(self, *, after: date | None = None) -> list[Ride]:
        """Засчитанные поездки в порядке ``(ride_date, id)`` — вход ALG-02."""
        sql = "SELECT * FROM transport_rides WHERE payment_method = 'strelka'"
        params: tuple[Any, ...] = ()
        if after is not None:
            sql += " AND ride_date >= ?"
            params = (dt.to_iso(after),)
        sql += " ORDER BY ride_date, id"
        return [_ride(row) for row in self.db.fetchall(sql, params)]

    def strelka_date_list(self) -> list[date]:
        """Все даты засчитанных поездок, отсортированные (для ALG-02 шаг 4)."""
        rows = self.db.fetchall(
            "SELECT DISTINCT ride_date FROM transport_rides WHERE payment_method = 'strelka' "
            "ORDER BY ride_date"
        )
        return [dt.parse_iso(str(row["ride_date"])) for row in rows]

    def earliest_strelka_date(self) -> date | None:
        row = self.db.fetchone(
            "SELECT MIN(ride_date) AS value FROM transport_rides WHERE payment_method = 'strelka'"
        )
        return _d(row["value"]) if row and row["value"] else None

    def count_strelka(self, date_from: date | None = None, date_to: date | None = None) -> int:
        sql = "SELECT COUNT(*) FROM transport_rides WHERE payment_method = 'strelka'"
        params: list[Any] = []
        if date_from:
            sql += " AND ride_date >= ?"
            params.append(dt.to_iso(date_from))
        if date_to:
            sql += " AND ride_date <= ?"
            params.append(dt.to_iso(date_to))
        return int(self.db.scalar(sql, tuple(params)) or 0)

    def last_used_template(self, weekday: int, direction: str) -> int | None:
        """TRIP-03: последний использованный шаблон для дня недели и направления."""
        row = self.db.fetchone(
            "SELECT template_id FROM transport_rides "
            "WHERE direction = ? AND template_id IS NOT NULL "
            "AND CAST(strftime('%w', study_date) AS INTEGER) = ? "
            "ORDER BY study_date DESC, id DESC LIMIT 1",
            (direction, weekday % 7),
        )
        return int(row["template_id"]) if row else None

    # ------------------------------------------------------------- запись
    def create(
        self,
        *,
        study_date: date,
        ride_date: date | None = None,
        direction: str,
        transport_type: str,
        vehicle: str,
        base_price: Any,
        paid_price: Any,
        discount_amount: Any,
        payment_method: str,
        confirmation_id: int | None = None,
        template_id: int | None = None,
        template_leg_id: int | None = None,
        period_id: int | None = None,
        tariff_id: int | None = None,
        period_start_date: date | None = None,
        ride_number_in_period: int | None = None,
        week_type_snapshot: str | None = None,
        is_manual: bool = False,
        price_locked: bool = False,
        comment: str | None = None,
    ) -> Ride:
        """Вставить поездку. Правила DATA-14 и RT-17 проверяются здесь же."""
        _validate_ride(payment_method, transport_type, period_start_date, ride_number_in_period)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO transport_rides(confirmation_id, study_date, ride_date, direction, "
                "template_id, template_leg_id, period_id, transport_type, vehicle, base_price, "
                "paid_price, discount_amount, payment_method, tariff_id, period_start_date, "
                "ride_number_in_period, week_type_snapshot, is_manual, price_locked, comment, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    confirmation_id,
                    dt.to_iso(study_date),
                    dt.to_iso(ride_date or study_date),
                    direction,
                    template_id,
                    template_leg_id,
                    period_id,
                    transport_type,
                    vehicle,
                    to_db(base_price),
                    to_db(paid_price),
                    to_db(discount_amount),
                    payment_method,
                    tariff_id,
                    dt.to_iso(period_start_date) if period_start_date else None,
                    ride_number_in_period,
                    week_type_snapshot,
                    1 if is_manual else 0,
                    1 if price_locked else 0,
                    comment,
                    _now(),
                ),
            )
            new_id = int(cursor.lastrowid)
        created = self.by_id(new_id)
        if created is None:  # pragma: no cover
            raise NotFoundError("Поездка не сохранена")
        return created

    def update(
        self,
        ride_id: int,
        *,
        vehicle: str | None = None,
        transport_type: str | None = None,
        payment_method: str | None = None,
        direction: str | None = None,
        comment: str | None = None,
        template_id: int | None = None,
    ) -> Ride:
        current = self.require(ride_id)
        new_method = payment_method or current.payment_method
        new_type = transport_type or current.transport_type
        _validate_ride(new_method, new_type, None, None)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE transport_rides SET vehicle = ?, transport_type = ?, payment_method = ?, "
                "direction = ?, comment = ?, template_id = ? WHERE id = ?",
                (
                    (vehicle or current.vehicle).strip(),
                    new_type,
                    new_method,
                    direction or current.direction,
                    current.comment if comment is None else comment,
                    current.template_id if template_id is None else template_id,
                    ride_id,
                ),
            )
        updated = self.by_id(ride_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Поездка не найдена")
        return updated

    def save_calculation(
        self,
        ride_id: int,
        *,
        base_price: Any,
        paid_price: Any,
        discount_amount: Any,
        tariff_id: int | None,
        period_start_date: date | None,
        ride_number_in_period: int | None,
    ) -> None:
        """Сохранить результат пересчёта (CALC-04): цена-снапшот и номер в периоде."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE transport_rides SET base_price = ?, paid_price = ?, discount_amount = ?, "
                "tariff_id = ?, period_start_date = ?, ride_number_in_period = ? WHERE id = ?",
                (
                    to_db(base_price),
                    to_db(paid_price),
                    to_db(discount_amount),
                    tariff_id,
                    dt.to_iso(period_start_date) if period_start_date else None,
                    ride_number_in_period,
                    ride_id,
                ),
            )

    def delete(self, ride_id: int) -> None:
        if self.by_id(ride_id) is None:
            raise NotFoundError(f"Поездка с id={ride_id} не найдена")
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM transport_rides WHERE id = ?", (ride_id,))

    def delete_for_confirmation(self, confirmation_id: int, *, automatic_only: bool = True) -> int:
        """TRIP-10: удаление подтверждения стирает только автоматические поездки.

        ``automatic_only`` (по умолчанию) — ручные поездки даты сохраняются:
        снятие подтверждения не должно стирать то, что студент ввёл сам
        (REP-14). Передайте ``False``, чтобы удалить все поездки подтверждения,
        включая помеченные как ручные.
        """
        with self.db.transaction() as conn:
            if automatic_only:
                cursor = conn.execute(
                    "DELETE FROM transport_rides WHERE confirmation_id = ? AND is_manual = 0",
                    (confirmation_id,),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM transport_rides WHERE confirmation_id = ?", (confirmation_id,)
                )
            return int(cursor.rowcount)


def _validate_ride(
    payment_method: str,
    transport_type: str,
    period_start_date: date | None,
    ride_number: int | None,
) -> None:
    """DATA-14 и RT-17 — на уровне приложения, а не только CHECK схемы (ACC-M-89)."""
    if payment_method not in PaymentMethod.ALL:
        raise ValidationError(f"Неизвестный способ оплаты: {payment_method!r}", field="payment_method")
    if transport_type not in TransportType.ALL:
        raise ValidationError(f"Неизвестный тип транспорта: {transport_type!r}", field="transport_type")
    if transport_type == TransportType.TRAIN and payment_method != PaymentMethod.TRAIN_STUDENT:
        raise ValidationError(
            "Электричка оплачивается только студенческим билетом (RT-17, FARE-03, [У-13]).",
            field="payment_method",
        )
    if transport_type == TransportType.BUS and payment_method not in PaymentMethod.BUS:
        raise ValidationError(
            "Автобус оплачивается «Стрелкой» или дебетовой картой; наличных нет (FARE-05).",
            field="payment_method",
        )
    if payment_method != PaymentMethod.STRELKA and (period_start_date or ride_number is not None):
        raise ValidationError(
            "Границы периода и номер поездки заполняются только для оплаты «Стрелкой» "
            "(DATA-14).",
            field="payment_method",
        )


# ===========================================================================
# Пополнения «Стрелки» (WAL-01…WAL-09, Прил. Б.16)
# ===========================================================================
def _topup(row: Any) -> TopUp:
    return TopUp(
        id=row["id"],
        topup_date=_d(row["topup_date"]),  # type: ignore[arg-type]
        amount=from_db(row["amount"]),
        fee=from_db(row["fee"]),
        method=row["method"],
        comment=row["comment"],
        created_at=row["created_at"],
    )


class TopUpRepository:
    """Пополнения карты: только приход, в расход не входят (WAL-04)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self) -> list[TopUp]:
        return [
            _topup(row)
            for row in self.db.fetchall("SELECT * FROM strelka_topups ORDER BY topup_date, id")
        ]

    def by_id(self, topup_id: int) -> TopUp | None:
        row = self.db.fetchone("SELECT * FROM strelka_topups WHERE id = ?", (topup_id,))
        return _topup(row) if row else None

    def require(self, topup_id: int) -> TopUp:
        topup = self.by_id(topup_id)
        if topup is None:
            raise NotFoundError(f"Пополнение с id={topup_id} не найдено")
        return topup

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM strelka_topups") or 0)

    def total_net(self, *, until: date | None = None) -> Any:
        """Σ(пополнения − комиссии) по всем датам ≤ ``until``."""
        sql = "SELECT amount, fee FROM strelka_topups"
        params: list[Any] = []
        if until is not None:
            sql += " WHERE topup_date <= ?"
            params.append(dt.to_iso(until))
        total = ZERO
        for row in self.db.fetchall(sql, tuple(params)):
            total += from_db(row["amount"]) - from_db(row["fee"])
        return total

    def dates(self) -> set[date]:
        return {_d(row["topup_date"]) for row in self.db.fetchall("SELECT DISTINCT topup_date FROM strelka_topups")}  # type: ignore[misc]

    def create(
        self,
        topup_date: date,
        amount: Any,
        *,
        fee: Any = ZERO,
        method: str | None = None,
        comment: str | None = None,
    ) -> TopUp:
        amount_value = from_db(to_db(amount))
        fee_value = from_db(to_db(fee))
        if amount_value < ZERO:
            raise ValidationError("Сумма пополнения не может быть отрицательной (WAL-01).", field="amount")
        if fee_value < ZERO:
            raise ValidationError("Комиссия не может быть отрицательной (WAL-01).", field="fee")
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO strelka_topups(topup_date, amount, fee, method, comment, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (dt.to_iso(topup_date), to_db(amount_value), to_db(fee_value), method, comment, _now()),
            )
            new_id = int(cursor.lastrowid)
        created = self.by_id(new_id)
        if created is None:  # pragma: no cover
            raise NotFoundError("Пополнение не сохранено")
        return created

    def update(
        self,
        topup_id: int,
        *,
        amount: Any | None = None,
        fee: Any | None = None,
        topup_date: date | None = None,
        method: str | None = None,
        comment: str | None = None,
    ) -> TopUp:
        current = self.require(topup_id)
        new_amount = current.amount if amount is None else from_db(to_db(amount))
        new_fee = current.fee if fee is None else from_db(to_db(fee))
        if new_amount < ZERO or new_fee < ZERO:
            raise ValidationError("Суммы пополнения и комиссии не могут быть отрицательными.", field="amount")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE strelka_topups SET topup_date = ?, amount = ?, fee = ?, method = ?, "
                "comment = ? WHERE id = ?",
                (
                    dt.to_iso(topup_date or current.topup_date),
                    to_db(new_amount), to_db(new_fee),
                    current.method if method is None else method,
                    current.comment if comment is None else comment,
                    topup_id,
                ),
            )
        return self.require(topup_id)

    def delete(self, topup_id: int) -> None:
        """WAL-07: удаление мгновенно меняет остаток."""
        self.require(topup_id)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM strelka_topups WHERE id = ?", (topup_id,))


# ===========================================================================
# Домашние задания (HW-01…HW-10, Прил. Б.18)
# ===========================================================================
def _homework(row: Any) -> Homework:
    return Homework(
        id=row["id"],
        subject_id=row["subject_id"],
        due_date=_d(row["due_date"]),  # type: ignore[arg-type]
        description=row["description"],
        status=row["status"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        group_mark=row["group_mark"],
    )


class HomeworkRepository:
    """Задания: предмет + дата сдачи + описание; просрочка вычисляется (HW-08)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self) -> list[Homework]:
        return [
            _homework(row)
            for row in self.db.fetchall(
                "SELECT * FROM homework ORDER BY due_date, id"
            )
        ]

    def by_id(self, homework_id: int) -> Homework | None:
        row = self.db.fetchone("SELECT * FROM homework WHERE id = ?", (homework_id,))
        return _homework(row) if row else None

    def require(self, homework_id: int) -> Homework:
        item = self.by_id(homework_id)
        if item is None:
            raise NotFoundError(f"Домашнее задание с id={homework_id} не найдено")
        return item

    def filtered(
        self,
        *,
        status: str | None = None,
        subject_id: int | None = None,
        overdue_before: date | None = None,
        only_overdue: bool = False,
        include_inactive_subjects: bool = True,
    ) -> list[Homework]:
        """Фильтры «активные / выполненные / просроченные / по предмету» (HW-04)."""
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("h.status = ?")
            params.append(status)
        if subject_id is not None:
            clauses.append("h.subject_id = ?")
            params.append(subject_id)
        if only_overdue:
            if overdue_before is None:
                from . import clock

                overdue_before = clock.today()
            clauses.append("h.status = 'active' AND h.due_date < ?")
            params.append(dt.to_iso(overdue_before))
        sql = "SELECT h.* FROM homework h"
        if not include_inactive_subjects:
            sql += " JOIN subjects s ON s.id = h.subject_id AND s.is_active = 1"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY h.due_date, h.id"
        return [_homework(row) for row in self.db.fetchall(sql, tuple(params))]

    def upcoming(self, *, today: date | None = None) -> list[Homework]:
        """Виджет «Домашние задания»: текущая и следующая недели (HW-05).

        Окно — две календарные недели: от сегодняшнего дня до воскресенья
        следующей недели включительно. Прошедшие дедлайны (просроченные) в
        виджет не попадают: они видны на странице заданий отдельной группой.
        """
        from . import clock

        base = today or clock.today()
        # Конец следующей недели: понедельник текущей + 14 дней даёт
        # понедельник недели после следующей, поэтому берём -1.
        end = dt.monday_of(base) + timedelta(days=13)
        return [
            item
            for item in self.filtered(status="active")
            if base <= item.due_date <= end
        ]

    def for_subject_date(self, subject_id: int, value: date) -> list[Homework]:
        """Бейдж ДЗ на карточке занятия (HW-06): по ``subject_id`` и дате сдачи."""
        return [
            _homework(row)
            for row in self.db.fetchall(
                "SELECT * FROM homework WHERE subject_id = ? AND due_date = ? ORDER BY id",
                (subject_id, dt.to_iso(value)),
            )
        ]

    def due_dates(self, start: date | None = None, end: date | None = None) -> set[date]:
        """Дедлайны — точки-метки мини-календаря (UI-05)."""
        sql = "SELECT DISTINCT due_date FROM homework"
        clauses: list[str] = []
        params: list[Any] = []
        if start:
            clauses.append("due_date >= ?")
            params.append(dt.to_iso(start))
        if end:
            clauses.append("due_date <= ?")
            params.append(dt.to_iso(end))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return {_d(row["due_date"]) for row in self.db.fetchall(sql, tuple(params))}  # type: ignore[misc]

    def create(
        self,
        subject_id: int,
        due_date: date,
        description: str | None = None,
    ) -> Homework:
        """HW-07: быстрый ввод — предмет, дата, описание."""
        if self.db.fetchone("SELECT 1 FROM subjects WHERE id = ?", (subject_id,)) is None:
            raise ValidationError("Предмет не найден", field="subject_id")
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO homework(subject_id, group_mark, due_date, description, status, "
                "created_at) VALUES (?, NULL, ?, ?, 'active', ?)",
                (subject_id, dt.to_iso(due_date), (description or "").strip() or None, _now()),
            )
            new_id = int(cursor.lastrowid)
        created = self.by_id(new_id)
        if created is None:  # pragma: no cover
            raise NotFoundError("Домашнее задание не сохранено")
        return created

    def update(
        self,
        homework_id: int,
        *,
        subject_id: int | None = None,
        due_date: date | None = None,
        description: str | None = None,
    ) -> Homework:
        current = self.require(homework_id)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE homework SET subject_id = ?, due_date = ?, description = ? WHERE id = ?",
                (
                    current.subject_id if subject_id is None else subject_id,
                    dt.to_iso(due_date or current.due_date),
                    current.description if description is None else (description.strip() or None),
                    homework_id,
                ),
            )
        return self.require(homework_id)

    def set_status(self, homework_id: int, status: str) -> Homework:
        """HW-15: отметка выполнения одним действием, обратная возвращает ``active``."""
        if status not in HomeworkStatus.ALL:
            raise ValidationError(
                f"Статус задания: только «{HomeworkStatus.ACTIVE}» или «{HomeworkStatus.DONE}» (HW-03).",
                field="status",
            )
        self.require(homework_id)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE homework SET status = ?, completed_at = ? WHERE id = ?",
                (status, _now() if status == HomeworkStatus.DONE else None, homework_id),
            )
        return self.require(homework_id)

    def toggle(self, homework_id: int) -> Homework:
        current = self.require(homework_id)
        return self.set_status(
            homework_id,
            HomeworkStatus.DONE if current.status == HomeworkStatus.ACTIVE else HomeworkStatus.ACTIVE,
        )

    def delete(self, homework_id: int) -> None:
        self.require(homework_id)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM homework WHERE id = ?", (homework_id,))


__all__ = [
    "TripTemplateRepository",
    "TripConfirmationRepository",
    "RideRepository",
    "TopUpRepository",
    "HomeworkRepository",
]
