"""Сервисы транспорта и денег: журнал, кошелёк, отчёты, тарифы.

Этап 3 §1.12: REP-01…REP-14, WAL-01…WAL-09, FARE-01…FARE-14. Как и остальные
сервисы, модуль не знает о PySide6 (PLAN-05) — интерфейс строится поверх него
на этапе 4.

Ключевое правило денег (WAL-04): «пополнено», «потрачено», «остаток» и
«экономия» — четыре независимые величины. Складывать их нельзя, поэтому в
отчёте они лежат в разных полях и не сводятся в одно число.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import clock
from .dates import add_days, format_display, month_bounds, to_iso, week_dates
from .errors import NotFoundError, ValidationError
from .fares import TariffResolver, stage_kind_for
from .models import Direction, PaymentMethod, TariffKind, TransportType
from .money import ZERO, from_db, money
from .recalculation import RecalcResult, RecalculationService, has_any_topup, wallet_balance
from .repositories import TariffRepository
from .transport_repositories import (
    RideRepository,
    TopUpRepository,
    TripTemplateRepository,
)

log = logging.getLogger(__name__)


def _zero() -> Decimal:
    return ZERO


# ===========================================================================
# Состояние «Стрелки» (REP-05, UI-09, WAL-05)
# ===========================================================================
@dataclass(frozen=True)
class StrellaState:
    """Виджет «Стрелка» (REP-05/UI-09).

    Пока учёт не начат (нет ни поездок, ни пополнений), ``started = False``:
    интерфейс показывает «Остаток не задан», а предупреждение WAL-05 не
    выводится (WAL-05).
    """

    started: bool
    period_start: date | None = None
    period_end: date | None = None
    next_ride_number: int = 1
    next_ride_price: Decimal = ZERO
    next_ride_stage: str = ""
    rides_in_period: int = 0
    savings_in_period: Decimal = ZERO
    spent_in_period: Decimal = ZERO
    balance: Decimal = ZERO
    has_topup: bool = False
    low_balance: bool = False
    initial_count: int = 0
    approximate: bool = False

    @property
    def bounds_caption(self) -> str:
        """REP-05: вычисленные границы текущего расчётного периода."""
        if self.period_start is None or self.period_end is None:
            return "—"
        return (
            f"{format_display(self.period_start)} — {format_display(self.period_end)}"
        )

    @property
    def next_ride_caption(self) -> str:
        if not self.started:
            return "Поездок ещё не было"
        return f"№{self.next_ride_number} — {self.next_ride_price} ₽"

    @property
    def balance_caption(self) -> str:
        """WAL-05: до первого пополнения — «Остаток не задан»."""
        if not self.has_topup:
            return "Остаток не задан"
        return f"{self.balance} ₽"

    @property
    def warning_caption(self) -> str:
        """WAL-06: жёлтый бейдж предупреждения об остатке."""
        if not self.low_balance:
            return ""
        return (
            f"Остаток {self.balance} ₽ меньше стоимости "
            f"{self.low_balance_rides_text} поездок"
        )

    @property
    def low_balance_rides_text(self) -> str:
        return "следующих"

    @property
    def initial_count_note(self) -> str:
        """REP-05: пометка при ``strelka_initial_ride_count > 0``."""
        if self.initial_count <= 0:
            return ""
        return f"С учётом {self.initial_count} поездок до начала учёта"


# ===========================================================================
# Журнал поездок (REP-01, REP-02, REP-10, REP-14)
# ===========================================================================
@dataclass(frozen=True)
class JournalFilter:
    """Фильтры журнала (REP-02/REP-10)."""

    date_from: date | None = None
    date_to: date | None = None
    transport_type: str | None = None
    payment_method: str | None = None
    direction: str | None = None

    @classmethod
    def for_day(cls, value: date) -> "JournalFilter":
        return cls(date_from=value, date_to=value)

    @classmethod
    def for_week(cls, value: date) -> "JournalFilter":
        days = week_dates(value)
        return cls(date_from=days[0], date_to=days[-1])

    @classmethod
    def for_month(cls, value: date) -> "JournalFilter":
        start, end = month_bounds(value)
        return cls(date_from=start, date_to=end)

    @property
    def caption(self) -> str:
        if self.date_from and self.date_to and self.date_from == self.date_to:
            return format_display(self.date_from)
        if self.date_from and self.date_to:
            return f"{format_display(self.date_from)} — {format_display(self.date_to)}"
        if self.date_from:
            return f"с {format_display(self.date_from)}"
        if self.date_to:
            return f"по {format_display(self.date_to)}"
        return "Все поездки"


@dataclass(frozen=True)
class JournalRow:
    """Строка журнала поездок (REP-01)."""

    ride_id: int
    ride_date: date
    study_date: date
    week_type: str
    direction: str
    template_name: str
    transport_type: str
    vehicle: str
    base_price: Decimal
    paid_price: Decimal
    discount: Decimal
    payment_method: str
    period_start: date | None
    ride_number: int | None
    is_manual: bool
    comment: str

    @property
    def ride_date_caption(self) -> str:
        return format_display(self.ride_date)

    @property
    def direction_caption(self) -> str:
        return Direction.label(self.direction)

    @property
    def transport_caption(self) -> str:
        return TransportType.label(self.transport_type)

    @property
    def payment_caption(self) -> str:
        return PaymentMethod.label(self.payment_method)

    @property
    def period_caption(self) -> str:
        """REP-01: границы вычисленного периода и номер в нём."""
        if self.period_start is None:
            return "—"
        if self.ride_number is None:
            return format_display(self.period_start)
        return f"с {format_display(self.period_start)}, №{self.ride_number}"

    @property
    def manual_caption(self) -> str:
        return "вручную" if self.is_manual else ""


# ===========================================================================
# Отчёты (REP-03, REP-04, REP-09)
# ===========================================================================
@dataclass
class ReportTotals:
    """Показатели отчёта (REP-04). Четыре величины не суммируются (WAL-04)."""

    period_caption: str = ""
    date_from: date | None = None
    date_to: date | None = None

    # REP-04: «потрачено» и разбивки по нему.
    spent: Decimal = ZERO
    spent_train: Decimal = ZERO
    spent_bus: Decimal = ZERO
    spent_strelka: Decimal = ZERO
    spent_debit_card: Decimal = ZERO
    savings: Decimal = ZERO

    rides_total: int = 0
    rides_strelka: int = 0
    rides_debit_card: int = 0
    rides_train: int = 0

    # REP-09: кошелёк — отдельный блок, не входящий в «потрачено».
    topups: Decimal = ZERO
    fees: Decimal = ZERO
    balance_end: Decimal = ZERO

    @property
    def topups_net(self) -> Decimal:
        return money(self.topups - self.fees)

    @property
    def has_rides(self) -> bool:
        return self.rides_total > 0

    @property
    def empty_caption(self) -> str:
        """REP-07: пустое состояние отчёта."""
        return "Поездок за период нет" if not self.has_rides else ""

    @property
    def average_ride(self) -> Decimal:
        if not self.rides_total:
            return ZERO
        return money(self.spent / Decimal(self.rides_total))

    def structure(self) -> list[tuple[str, Decimal, float]]:
        """REP-04: структура расходов — (подпись, сумма, доля в процентах)."""
        if self.spent == ZERO:
            return []
        items = [
            ("Электричка", self.spent_train),
            ("Автобусы по «Стрелке»", self.spent_strelka),
            ("Автобусы по карте", self.spent_debit_card),
        ]
        return [
            (label, amount, float(money(amount / self.spent * Decimal(100))))
            for label, amount in items
            if amount != ZERO
        ]


# ===========================================================================
# Тарифы (FARE-01…FARE-14)
# ===========================================================================
@dataclass(frozen=True)
class TariffRow:
    """Строка справочника тарифов для интерфейса."""

    tariff_id: int
    kind: str
    price: Decimal
    effective_from: date
    effective_to: date | None
    is_active: bool
    comment: str

    @property
    def kind_caption(self) -> str:
        return TariffKind.label(self.kind)

    @property
    def bounds_caption(self) -> str:
        right = format_display(self.effective_to) if self.effective_to else "бессрочно"
        return f"{format_display(self.effective_from)} — {right}"


class TariffService:
    """§17.1: тарифы — таблица, а не настройки (правило 3 §0)."""

    def __init__(self, db) -> None:
        self.db = db
        self.repo = TariffRepository(db)

    def rows(self, *, include_inactive: bool = True) -> list[TariffRow]:
        return [self._row(item) for item in self.repo.all(include_inactive=include_inactive)]

    def create(
        self,
        kind: str,
        price,
        effective_from: date,
        *,
        effective_to: date | None = None,
        comment: str | None = None,
        is_active: bool = True,
    ) -> TariffRow:
        """FARE-02: два действующих тарифа одного вида не перекрывают дату."""
        if kind not in TariffKind.ALL:
            raise ValidationError("Неизвестный вид тарифа.", field="kind")
        tariff = self.repo.create(
            kind, price, effective_from,
            effective_to=effective_to, comment=comment, is_active=is_active,
        )
        return self._row(tariff)

    def update(self, tariff_id: int, **fields) -> TariffRow:
        """DATA-16: правка тарифа не переписывает прошлые поездки."""
        return self._row(self.repo.update(tariff_id, **fields))

    def delete(self, tariff_id: int) -> None:
        self.repo.delete(tariff_id)

    def resolver(self) -> TariffResolver:
        """ALG-09: разрешение тарифа по дате среди действующих рядов."""
        return TariffResolver(self.repo.all(include_inactive=False))

    def price_on(self, kind: str, when: date) -> Decimal | None:
        """ALG-09: цена вида тарифа на дату."""
        tariff = self.resolver().find(kind, when)
        return tariff.price if tariff else None

    @staticmethod
    def _row(tariff) -> TariffRow:
        return TariffRow(
            tariff_id=tariff.id,
            kind=tariff.kind,
            price=tariff.price,
            effective_from=tariff.effective_from,
            effective_to=tariff.effective_to,
            is_active=bool(tariff.is_active),
            comment=tariff.comment or "",
        )


# ===========================================================================
# Кошелёк (WAL-01…WAL-09)
# ===========================================================================
@dataclass(frozen=True)
class TopUpRow:
    """Строка журнала пополнений (REP-11)."""

    topup_id: int
    topup_date: date
    amount: Decimal
    fee: Decimal
    method: str
    comment: str

    @property
    def date_caption(self) -> str:
        return format_display(self.topup_date)

    @property
    def net(self) -> Decimal:
        return money(self.amount - self.fee)


class WalletService:
    """WAL-01…WAL-09: кошелёк только для «Стрелки» (WAL-08)."""

    def __init__(self, db) -> None:
        self.db = db
        self.topups = TopUpRepository(db)

    # ------------------------------------------------------------------ чтение
    def balance(self, *, until: date | None = None) -> Decimal:
        """WAL-03/ALG-07: остаток = пополнения − комиссии − оплаченные «Стрелкой»."""
        return wallet_balance(self.db, until=until)

    @property
    def started(self) -> bool:
        """WAL-05: до первого пополнения остаток недостоверен."""
        return has_any_topup(self.db)

    @property
    def balance_caption(self) -> str:
        if not self.started:
            return "Остаток не задан"
        return f"{self.balance()} ₽"

    def rows(self) -> list[TopUpRow]:
        """REP-11: журнал пополнений."""
        return [
            TopUpRow(
                topup_id=item.id,
                topup_date=item.topup_date,
                amount=item.amount,
                fee=item.fee,
                method=item.method or "",
                comment=item.comment or "",
            )
            for item in self.topups.all()
        ]

    def total_topups(self, *, until: date | None = None) -> Decimal:
        return self.topups.total_net(until=until)

    def fees(self) -> Decimal:
        return money(sum((item.fee for item in self.topups.all()), ZERO))

    # ------------------------------------------------------------------ запись
    def add(
        self,
        topup_date: date,
        amount,
        *,
        fee=None,
        method: str | None = None,
        comment: str | None = None,
    ) -> TopUpRow:
        """WAL-01: дата, сумма, способ пополнения, комментарий."""
        created = self.topups.create(
            topup_date, amount, fee=fee if fee is not None else ZERO,
            method=method, comment=comment,
        )
        log.info("Пополнение %s на %s", to_iso(topup_date), created.amount)
        return self._row(created)

    def add_initial(self, amount, *, topup_date: date | None = None) -> TopUpRow:
        """WAL-09/FIRST-06: первое пополнение = фактический остаток на карте."""
        return self.add(
            topup_date or clock.today(),
            amount,
            comment="начальный остаток",
        )

    def update(self, topup_id: int, **fields) -> TopUpRow:
        """WAL-07: правка пополнения пересчитывает остаток немедленно."""
        return self._row(self.topups.update(topup_id, **fields))

    def delete(self, topup_id: int) -> None:
        """WAL-07: удаление пополнения пересчитывает остаток немедленно."""
        self.topups.delete(topup_id)

    @staticmethod
    def _row(item) -> TopUpRow:
        return TopUpRow(
            topup_id=item.id,
            topup_date=item.topup_date,
            amount=item.amount,
            fee=item.fee,
            method=item.method or "",
            comment=item.comment or "",
        )


# ===========================================================================
# Сводный сервис транспорта
# ===========================================================================
class TransportService:
    """Журнал, состояние «Стрелки», отчёты и пересчёт (REP-*, WAL-*, CALC-04)."""

    def __init__(self, db) -> None:
        self.db = db
        self.rides = RideRepository(db)
        self.templates = TripTemplateRepository(db)
        self.topups = TopUpRepository(db)
        self.tariffs = TariffRepository(db)
        self.recalculator = RecalculationService(db)

    # ------------------------------------------------------------------ журнал
    def journal(self, criteria: JournalFilter | None = None) -> list[JournalRow]:
        """REP-01/REP-02: журнал поездок с фильтрами."""
        criteria = criteria or JournalFilter()
        rides = self.rides.filtered(
            date_from=criteria.date_from,
            date_to=criteria.date_to,
            transport_type=criteria.transport_type,
            payment_method=criteria.payment_method,
            direction=criteria.direction,
        )
        names = {item.id: item.name for item in self.templates.all()}
        return [
            JournalRow(
                ride_id=ride.id,
                ride_date=ride.ride_date,
                study_date=ride.study_date,
                week_type=ride.week_type_snapshot or "",
                direction=ride.direction,
                template_name=names.get(ride.template_id, "") if ride.template_id else "",
                transport_type=ride.transport_type,
                vehicle=ride.vehicle,
                base_price=ride.base_price,
                paid_price=ride.paid_price,
                discount=ride.discount_amount,
                payment_method=ride.payment_method,
                period_start=ride.period_start_date,
                ride_number=ride.ride_number_in_period,
                is_manual=ride.is_manual,
                comment=ride.comment or "",
            )
            for ride in rides
        ]

    @property
    def journal_empty_caption(self) -> str:
        """REP-07: пустое состояние журнала."""
        return "Поездок за период нет"

    def period_choices(self) -> list[tuple[str, JournalFilter]]:
        """REP-03: день, неделя, месяц. Полугодие и год — v1.1."""
        today = clock.today()
        return [
            ("День", JournalFilter.for_day(today)),
            ("Неделя", JournalFilter.for_week(today)),
            ("Месяц", JournalFilter.for_month(today)),
        ]

    # ------------------------------------------------------------------ отчёты
    def report(self, criteria: JournalFilter | None = None) -> ReportTotals:
        """REP-04/REP-09: показатели за период по ``ride_date`` (REP-03)."""
        criteria = criteria or JournalFilter()
        rides = self.rides.filtered(
            date_from=criteria.date_from,
            date_to=criteria.date_to,
            transport_type=criteria.transport_type,
            payment_method=criteria.payment_method,
            direction=criteria.direction,
        )
        totals = ReportTotals(
            period_caption=criteria.caption,
            date_from=criteria.date_from,
            date_to=criteria.date_to,
        )
        for ride in rides:
            totals.spent += ride.paid_price
            totals.savings += ride.discount_amount
            totals.rides_total += 1
            if ride.transport_type == TransportType.TRAIN:
                totals.spent_train += ride.paid_price
                totals.rides_train += 1
            else:
                totals.spent_bus += ride.paid_price
            if ride.payment_method == PaymentMethod.STRELKA:
                totals.spent_strelka += ride.paid_price
                totals.rides_strelka += 1
            elif ride.payment_method == PaymentMethod.DEBIT_CARD:
                totals.spent_debit_card += ride.paid_price
                totals.rides_debit_card += 1

        totals.spent = money(totals.spent)
        totals.spent_train = money(totals.spent_train)
        totals.spent_bus = money(totals.spent_bus)
        totals.spent_strelka = money(totals.spent_strelka)
        totals.spent_debit_card = money(totals.spent_debit_card)
        totals.savings = money(totals.savings)

        # REP-09: блок кошелька — отдельно, в «потрачено» не входит (WAL-04).
        # «Пополнено» показывается суммой до комиссий: комиссии — своя колонка.
        until = criteria.date_to
        period_topups = [
            item
            for item in self.topups.all()
            if until is None or item.topup_date <= until
        ]
        totals.topups = money(sum((item.amount for item in period_topups), ZERO))
        totals.fees = money(sum((item.fee for item in period_topups), ZERO))
        totals.balance_end = wallet_balance(self.db, until=until)
        return totals

    # --------------------------------------------------------------- «Стрелка»
    def strella_state(self, *, today: date | None = None) -> StrellaState:
        """REP-05/UI-09: границы периода, следующая поездка, остаток, предупреждение."""
        from .strelka import StrellaPeriodCalculator

        base = today or clock.today()
        settings = self._strella_settings()
        resolver = self._resolver()

        counted = self.rides.strelka_rides()
        state = StrellaState(
            started=bool(counted) or has_any_topup(self.db),
            has_topup=has_any_topup(self.db),
            balance=wallet_balance(self.db),
            initial_count=settings["initial_count"],
            approximate=bool(counted),
        )
        if not counted:
            state = self._with_next_ride(state, base, 1, settings, resolver)
            return self._with_warning(state, settings, resolver, base)

        calculator = StrellaPeriodCalculator(
            rides=[(ride.id, ride.ride_date) for ride in counted],
            anchor=settings["anchor"],
            initial_count=settings["initial_count"],
            period_days=settings["period_days"],
            first_limit=settings["first_limit"],
        )
        resolved = calculator.resolve(base)
        period_start = resolved.period_start or base
        period_end = add_days(period_start, settings["period_days"] - 1)
        in_period = [
            ride
            for ride in counted
            if period_start <= ride.ride_date <= period_end
        ]
        state = StrellaState(
            started=True,
            period_start=period_start,
            period_end=period_end,
            rides_in_period=len(in_period),
            savings_in_period=money(
                sum((ride.discount_amount for ride in in_period), ZERO)
            ),
            spent_in_period=money(sum((ride.paid_price for ride in in_period), ZERO)),
            balance=wallet_balance(self.db),
            has_topup=has_any_topup(self.db),
            initial_count=settings["initial_count"],
            approximate=resolved.provisional,
        )
        state = self._with_next_ride(state, base, resolved.ride_number, settings, resolver)
        return self._with_warning(state, settings, resolver, base)

    def _with_next_ride(self, state: StrellaState, base: date, number: int,
                        settings: dict, resolver: TariffResolver) -> StrellaState:
        stage = stage_kind_for(number, settings["first_limit"])
        tariff = resolver.find(stage, base)
        price = tariff.price if tariff else ZERO
        return StrellaState(
            started=state.started,
            period_start=state.period_start,
            period_end=state.period_end,
            next_ride_number=number,
            next_ride_price=price,
            next_ride_stage=stage,
            rides_in_period=state.rides_in_period,
            savings_in_period=state.savings_in_period,
            spent_in_period=state.spent_in_period,
            balance=state.balance,
            has_topup=state.has_topup,
            low_balance=False,
            initial_count=state.initial_count,
            approximate=state.approximate,
        )

    def _with_warning(self, state: StrellaState, settings: dict,
                      resolver: TariffResolver, base: date) -> StrellaState:
        """WAL-05: предупреждение только после первого пополнения."""
        if not state.has_topup:
            return state
        warn_rides = settings["low_balance_warn"]
        threshold = money(state.next_ride_price * Decimal(warn_rides))
        low = state.balance < threshold
        return StrellaState(
            started=state.started,
            period_start=state.period_start,
            period_end=state.period_end,
            next_ride_number=state.next_ride_number,
            next_ride_price=state.next_ride_price,
            next_ride_stage=state.next_ride_stage,
            rides_in_period=state.rides_in_period,
            savings_in_period=state.savings_in_period,
            spent_in_period=state.spent_in_period,
            balance=state.balance,
            has_topup=state.has_topup,
            low_balance=low,
            initial_count=state.initial_count,
            approximate=state.approximate,
        )

    def _resolver(self) -> TariffResolver:
        return TariffResolver(self.tariffs.all(include_inactive=False))

    def _strella_settings(self) -> dict:
        from .settings_registry import SettingsKeys
        from .settings_service import SettingsService

        service = SettingsService(self.db)
        return {
            "anchor": service.strelka_period_anchor_date(),
            "initial_count": service.strelka_initial_ride_count(),
            "period_days": service.strelka_period_days(),
            "first_limit": service.strelka_first_limit(),
            "low_balance_warn": service.strelka_low_balance_warn(),
        }

    # --------------------------------------------------------------- пересчёт
    def recalculate(self, *, from_date: date | None = None) -> RecalcResult:
        """REP-08/CALC-04: «Пересчитать счётчик «Стрелки»» в полном объёме."""
        return self.recalculator.recalculate(from_date=from_date)

    # ------------------------------------------------------------ ручная поездка
    def delete_ride(self, ride_id: int, *, from_date: date | None = None) -> RecalcResult:
        """REP-02: удаление поездки с пересчётом (CALC-04)."""
        ride = self.rides.require(ride_id)
        self.rides.delete(ride_id)
        return self.recalculator.recalculate(from_date=from_date or ride.ride_date)

    def update_ride(self, ride_id: int, **fields) -> RecalcResult:
        """REP-02: правка поездки; смена способа оплаты пересчитывает (CALC-04)."""
        ride = self.rides.require(ride_id)
        self.rides.update(ride_id, **fields)
        return self.recalculator.recalculate(from_date=ride.ride_date)

    def add_ride(self, **fields) -> RecalcResult:
        """REP-14: ручная поездка через журнал."""
        from .trip_service import TripPlanService

        ride = TripPlanService(self.db).add_manual_ride(**fields)
        return self.recalculator.recalculate(from_date=ride.ride_date)


__all__ = [
    "StrellaState",
    "JournalFilter",
    "JournalRow",
    "ReportTotals",
    "TariffService",
    "TariffRow",
    "WalletService",
    "TopUpRow",
    "TransportService",
]
