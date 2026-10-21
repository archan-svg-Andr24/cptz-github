"""CALC-04 — каскадный пересчёт; ALG-07 — остаток кошелька.

Почему пересчёт **обязателен, а не оптимален**: расчётный период «Стрелки»
скользящий (ALG-02), поэтому вставка одной поездки в прошлое меняет границы и,
как следствие, номера и ступени **всех последующих** поездок (CALC-04,
NFR-10). Требование производительности — 5000 поездок за ≤ 1 с в одной
транзакции.

Алгоритм пересчёта:

1. Взять все засчитанные поездки в порядке ``(ride_date, id)``.
2. Для каждой вычислить состояние ALG-02 с учётом её собственного ``k``.
3. По номеру выбрать ступень (шаг 9) → вид тарифа → цену на ``ride_date``
   (ALG-09), с откатом льготы (FARE-10).
4. Записать изменившиеся ``period_start_date``, ``ride_number_in_period``,
   ``base_price``, ``paid_price``, ``discount_amount``, ``tariff_id``.
5. Пересчитать остаток (CALC-06) и вернуть итог пользователю (число записей и
   сумму) — он показывается в UI (CALC-04, NFR-10).

Снапшоты **прошлых** поездок, не затронутых изменением, не переписываются
(DATA-16): обновляются только те записи, у которых фактически изменилось
значение.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .database import Database
from .dates import to_iso
from .models import PaymentMethod, TariffKind, TransportType
from .money import ZERO, from_db, money
from .fares import TariffResolver, price_ride, stage_kind_for
from .strelka import StrellaPeriodCalculator, _CountedRide


@dataclass
class RecalcResult:
    """Итог CALC-04 для показа пользователю."""

    rides_total: int = 0
    rides_changed: int = 0
    amount_before: Decimal = ZERO
    amount_after: Decimal = ZERO
    from_date: date | None = None
    #: Подробности изменившихся записей (для журнала и тестов).
    changes: list[tuple[int, str]] = field(default_factory=list)

    @property
    def delta(self) -> Decimal:
        return money(self.amount_after - self.amount_before)

    @property
    def changed(self) -> bool:
        return self.rides_changed > 0

    @property
    def summary(self) -> str:
        """Сообщение пользователю об итоге пересчёта (CALC-04)."""
        if self.rides_total == 0:
            return "Поездок для пересчёта нет."
        if not self.changed:
            return f"Пересчёт выполнен: {self.rides_total} поездок, изменений нет."
        sign = "+" if self.delta >= ZERO else "−"
        return (
            f"Пересчитано {self.rides_changed} из {self.rides_total} поездок; "
            f"итог по оплате изменился на {sign}{abs(self.delta):.2f} ₽."
        )

    @property
    def needs_confirmation(self) -> bool:
        """ERR: пересчёт более 500 записей требует подтверждения пользователя."""
        return self.rides_changed > 500


class RecalculationService:
    """CALC-04: пересчёт номеров, границ и стоимостей с даты изменения и далее."""

    def __init__(self, db: Database, settings: object | None = None) -> None:
        self.db = db
        self._settings = settings

    # -------------------------------------------------------------- конфиг
    def _load_settings(self) -> tuple[date | None, int, int, int]:
        """``strelka_period_anchor_date``, ``cnt0``, ``period_days``, ``first_limit``."""
        from .settings_service import SettingsService

        service = self._settings if isinstance(self._settings, SettingsService) else SettingsService(self.db)
        anchor = service.strelka_period_anchor_date()
        return (
            anchor,
            service.strelka_initial_ride_count(),
            service.strelka_period_days(),
            service.strelka_first_limit(),
        )

    def _tariff_resolver(self) -> TariffResolver:
        from .repositories import TariffRepository

        return TariffResolver(TariffRepository(self.db).all(include_inactive=False))

    # ------------------------------------------------------------ пересчёт
    def recalculate(self, *, from_date: date | None = None) -> RecalcResult:
        """Пересчитать все ``strelka``-поездки (CALC-04).

        ``from_date`` — дата самого раннего изменения; параметр влияет только на
        сообщение (``from_date`` в результате), потому что номера и границы
        зависят от всей предшествующей истории, и «пересчитать только отсюда»
        дало бы неверные номера. Стоимость обновляется для всех поездок: тариф
        мог измениться, а откат льготы (FARE-10) — свойство даты.
        """
        anchor, cnt0, period_days, first_limit = self._load_settings()
        rows = self.db.fetchall(
            "SELECT id, ride_date, direction, payment_method, transport_type, base_price, "
            "paid_price, discount_amount, tariff_id, period_start_date, ride_number_in_period "
            "FROM transport_rides ORDER BY ride_date, id"
        )
        if not rows:
            return RecalcResult()

        calculator = StrellaPeriodCalculator(
            rides=[
                _CountedRide(id=int(row["id"]), ride_date=_parse(row["ride_date"]))
                for row in rows
                if row["payment_method"] == PaymentMethod.STRELKA
            ],
            anchor=anchor,
            initial_count=cnt0,
            period_days=period_days,
            first_limit=first_limit,
        )
        resolver = self._tariff_resolver()

        result = RecalcResult(rides_total=len(rows), from_date=from_date)
        updates: list[tuple] = []
        for row in rows:
            ride_date = _parse(row["ride_date"])
            is_strelka = row["payment_method"] == PaymentMethod.STRELKA
            old_paid = from_db(row["paid_price"])
            result.amount_before += old_paid

            if is_strelka:
                # ALG-02 действует только для засчитанных поездок «Стрелки».
                state = calculator.resolve(ride_date, ride_id=int(row["id"]))
                stage = stage_kind_for(state.ride_number, first_limit)
                new_period = to_iso(state.period_start) if state.period_start else None
                new_number = state.ride_number
            else:
                # Дебетовая карта и студенческий билет: номера нет (DATA-14),
                # но стоимость обязана следовать действующему тарифу (CALC-04).
                stage = None
                new_period = None
                new_number = None

            pricing = price_ride(
                resolver,
                ride_date=ride_date,
                transport_type=row["transport_type"],
                payment_method=row["payment_method"],
                stage=stage,
            )
            result.amount_after += pricing.paid_price

            changed = (
                row["period_start_date"] != new_period
                or row["ride_number_in_period"] != new_number
                or money(old_paid) != pricing.paid_price
                or from_db(row["base_price"]) != pricing.base_price
                or from_db(row["discount_amount"]) != pricing.discount_amount
                or row["tariff_id"] != pricing.tariff_id
            )
            if not changed:
                continue
            updates.append(
                (
                    _money_text(pricing.base_price),
                    _money_text(pricing.paid_price),
                    _money_text(pricing.discount_amount),
                    pricing.tariff_id,
                    new_period,
                    new_number,
                    int(row["id"]),
                )
            )
            result.rides_changed += 1
            if len(result.changes) < 50:
                result.changes.append(
                    (int(row["id"]),
                     f"{row['ride_number_in_period']} → {new_number}, "
                     f"{old_paid} → {pricing.paid_price}")
                )

        if updates:
            with self.db.transaction() as conn:
                conn.executemany(
                    "UPDATE transport_rides SET base_price = ?, paid_price = ?, "
                    "discount_amount = ?, tariff_id = ?, period_start_date = ?, "
                    "ride_number_in_period = ? WHERE id = ?",
                    updates,
                )
        return result

    def recalculate_for_ride(self, ride_id: int) -> RecalcResult:
        """Полный пересчёт после правки одной поездки (CALC-04 от самой ранней даты)."""
        row = self.db.fetchone("SELECT ride_date FROM transport_rides WHERE id = ?", (ride_id,))
        from_date = _parse(row["ride_date"]) if row else None
        return self.recalculate(from_date=from_date)

    # ------------------------------------------------------------- остаток
    def wallet_balance(self, *, until: date | None = None) -> Decimal:
        """ALG-07: Σ(пополнения − комиссии) − Σ(оплаченные поездки «Стрелкой»)."""
        return wallet_balance(self.db, until=until)


def wallet_balance(db: Database, *, until: date | None = None) -> Decimal:
    """ALG-07: остаток карты на дату (по всем датам ``<= until``).

    Считается по снапшотам ``paid_price`` после пересчёта (ACC-M-51).
    Дебетовая карта не участвует (WAL-08).
    """
    topup_sql = "SELECT amount, fee FROM strelka_topups"
    ride_sql = "SELECT paid_price FROM transport_rides WHERE payment_method = 'strelka'"
    params_top: tuple = ()
    params_ride: tuple = ()
    if until is not None:
        topup_sql += " WHERE topup_date <= ?"
        ride_sql += " AND ride_date <= ?"
        params_top = (to_iso(until),)
        params_ride = (to_iso(until),)
    total = ZERO
    for row in db.fetchall(topup_sql, params_top):
        total += from_db(row["amount"]) - from_db(row["fee"])
    for row in db.fetchall(ride_sql, params_ride):
        total -= from_db(row["paid_price"])
    return money(total)


def has_any_topup(db: Database) -> bool:
    """До первого пополнения остаток считается «не заданным» (WAL-05, ACC-M-53)."""
    return db.fetchone("SELECT 1 FROM strelka_topups LIMIT 1") is not None


def _parse(text: object) -> date:
    from .dates import parse_iso

    return parse_iso(str(text))


def _money_text(value: Decimal) -> str:
    from .money import to_db

    return to_db(value)


__all__ = [
    "RecalcResult",
    "RecalculationService",
    "wallet_balance",
    "has_any_topup",
]
