"""TRIP-01…TRIP-20 — подтверждение поездок дня.

Подтверждение дня — центральный сценарий транспорта: студент выбирает шаблоны
рейсов «туда» и «обратно», приложение разворачивает их в поездки, считает
стоимость по тарифам (ALG-09), присваивает номера в скользящем периоде (ALG-02)
и сохраняет снапшоты.

Инварианты, которые держит сервис:

* повторное подтверждение даты **не плодит дубли** и не удаляет ручные поездки
  (TRIP-09, REP-14);
* удаление подтверждения удаляет только автоматические поездки (TRIP-10);
* правка рейсов дня не меняет шаблон (TRIP-04) — «сохранить как шаблон» —
  отдельное действие (TRIP-05);
* автоподстановка берёт последний использованный шаблон для этого дня недели
  и направления (TRIP-03);
* электричка оплачивается только студенческим билетом (RT-17), автобус —
  «Стрелкой» или дебетовой картой (FARE-05);
* дебетовая карта не получает номера периода и не двигает счётчик (DATA-14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from . import clock
from . import dates as dt
from .errors import NotFoundError, RuleViolationError, ValidationError
from .fares import TariffResolver, price_ride, stage_kind_for
from .models import (
    Direction,
    PaymentMethod,
    TransportType,
    TripConfirmation,
    TripLeg,
    TripTemplate,
)
from .money import ZERO
from .repositories import TariffRepository
from .strelka import StrellaPeriodCalculator
from .transport_repositories import (
    RideRepository,
    TripConfirmationRepository,
    TripTemplateRepository,
)


@dataclass
class DayPlan:
    """План поездок дня до подтверждения: то, что показывает UI-08."""

    day: date
    weekday: int
    outbound: TripTemplate | None = None
    return_trip: TripTemplate | None = None
    include_outbound: bool = True
    include_return: bool = True
    has_lessons: bool = True
    confirmation: TripConfirmation | None = None
    #: Замечания, которые UI показывает как предупреждения (например, нет тарифа).
    warnings: list[str] = field(default_factory=list)

    @property
    def is_confirmed(self) -> bool:
        return self.confirmation is not None

    @property
    def legs_count(self) -> int:
        total = 0
        if self.include_outbound and self.outbound is not None:
            total += len(self.outbound.legs)
        if self.include_return and self.return_trip is not None:
            total += len(self.return_trip.legs)
        return total

    @property
    def direction_labels(self) -> tuple[str, ...]:
        labels: list[str] = []
        if self.include_outbound and self.outbound is not None:
            labels.append(Direction.label(Direction.HOME_TO_COLLEGE))
        if self.include_return and self.return_trip is not None:
            labels.append(Direction.label(Direction.COLLEGE_TO_HOME))
        return tuple(labels)


@dataclass
class ConfirmResult:
    """Итог подтверждения дня."""

    day: date
    confirmation: TripConfirmation
    rides_created: int = 0
    rides_removed: int = 0
    rides_kept_manual: int = 0
    total_paid: Decimal = ZERO
    total_base: Decimal = ZERO
    total_saving: Decimal = ZERO
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.rides_created == 0 and self.rides_removed == 0:
            return f"Поездки на {dt.format_display(self.day)} уже подтверждены."
        return (
            f"Поездки на {dt.format_display(self.day)} подтверждены: "
            f"создано {self.rides_created}, удалено {self.rides_removed}, "
            f"итого {self.total_paid} ₽."
        )


class TripPlanService:
    """Подготовка и подтверждение поездок дня (TRIP-01…TRIP-20)."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self.templates = TripTemplateRepository(db)
        self.confirmations = TripConfirmationRepository(db)
        self.rides = RideRepository(db)

    # ------------------------------------------------------------- подготовка
    def plan(
        self,
        day: date,
        *,
        outbound_template_id: int | None = None,
        return_template_id: int | None = None,
        has_lessons: bool = True,
    ) -> DayPlan:
        """Собрать план дня с автоподстановкой шаблонов (TRIP-03, UI-08).

        Если шаблон не задан явно, подставляется последний использованный для
        этого дня недели и направления; если истории нет — первый активный.
        Уже подтверждённый день восстанавливает свой набор из подтверждения
        (TRIP-18), а не из шаблона.
        """
        weekday = day.isoweekday()
        confirmation = self.confirmations.by_date(day)
        plan = DayPlan(day=day, weekday=weekday, has_lessons=has_lessons,
                       confirmation=confirmation)

        if confirmation is not None:
            # TRIP-18: набор рейсов подтверждённой даты берётся из подтверждения.
            plan.outbound = (
                self.templates.by_id(confirmation.outbound_template_id)
                if confirmation.outbound_template_id
                else None
            )
            plan.return_trip = (
                self.templates.by_id(confirmation.return_template_id)
                if confirmation.return_template_id
                else None
            )
            plan.include_outbound = confirmation.include_outbound
            plan.include_return = confirmation.include_return
            return plan

        plan.outbound = self._pick_template(
            Direction.HOME_TO_COLLEGE, weekday, outbound_template_id
        )
        plan.return_trip = self._pick_template(
            Direction.COLLEGE_TO_HOME, weekday, return_template_id
        )
        if not has_lessons:
            plan.warnings.append(
                "В этот день занятий нет: автоподстановка не выполняется, "
                "подтвердить поездки можно вручную."
            )
        return plan

    def _pick_template(
        self, direction: str, weekday: int, explicit_id: int | None
    ) -> TripTemplate | None:
        if explicit_id is not None:
            template = self.templates.by_id(explicit_id)
            if template is None:
                raise NotFoundError(f"Шаблон поездки {explicit_id} не найден")
            return template
        # TRIP-03: последний использованный для этого дня недели и направления.
        last_id = self.rides.last_used_template(weekday, direction)
        if last_id is not None:
            remembered = self.templates.by_id(last_id)
            if remembered is not None and remembered.direction == direction:
                return remembered
        candidates = self.templates.by_direction(direction, include_inactive=False)
        return candidates[0] if candidates else None

    def available_templates(self, direction: str) -> list[TripTemplate]:
        return self.templates.by_direction(direction, include_inactive=False)

    # ------------------------------------------------------------- тарифы
    def _resolver(self) -> TariffResolver:
        return TariffResolver(TariffRepository(self.db).all(include_inactive=False))

    def _calculator(self, upto: date) -> StrellaPeriodCalculator:
        from .settings_service import SettingsService

        settings = SettingsService(self.db)
        counted = self.rides.strelka_rides()
        return StrellaPeriodCalculator(
            rides=[(ride.id, ride.ride_date) for ride in counted],
            anchor=settings.strelka_period_anchor_date(),
            initial_count=settings.strelka_initial_ride_count(),
            period_days=settings.strelka_period_days(),
            first_limit=settings.strelka_first_limit(),
        )

    # --------------------------------------------------------- подтверждение
    def confirm(
        self,
        day: date,
        *,
        outbound_template_id: int | None = None,
        return_template_id: int | None = None,
        include_outbound: bool = True,
        include_return: bool = True,
        has_lessons: bool = True,
    ) -> ConfirmResult:
        """Подтвердить поездки дня (TRIP-01, TRIP-02, TRIP-09).

        Повторный вызов на ту же дату обновляет подтверждение и пересобирает
        **только автоматические** поездки: ручные не трогаются (REP-14).
        """
        plan = self.plan(
            day,
            outbound_template_id=outbound_template_id,
            return_template_id=return_template_id,
            has_lessons=has_lessons,
        )
        outbound = plan.outbound if include_outbound else None
        return_trip = plan.return_trip if include_return else None

        if outbound is None and return_trip is None:
            raise RuleViolationError(
                f"На {dt.format_display(day)} не выбран ни один шаблон поездки: "
                "подтверждать нечего (TRIP-18)."
            )

        weeks = self._week_type(day)
        resolver = self._resolver()

        with self.db.transaction():
            # TRIP-09: повтор не плодит дублей — старые автоматические поездки
            # заменяются новыми, ручные остаются.
            removed = 0
            existing = self.confirmations.by_date(day)
            if existing is not None:
                removed = self.rides.delete_for_confirmation(existing.id)
            manual_kept = len([ride for ride in self.rides.for_date(day) if ride.is_manual])

            confirmation = self.confirmations.upsert(
                day,
                outbound_template_id=outbound.id if outbound else None,
                return_template_id=return_trip.id if return_trip else None,
                include_outbound=include_outbound,
                include_return=include_return,
                week_type_snapshot=weeks,
            )

            result = ConfirmResult(
                day=day,
                confirmation=confirmation,
                rides_removed=removed,
                rides_kept_manual=manual_kept,
            )
            for template, direction in (
                (outbound, Direction.HOME_TO_COLLEGE),
                (return_trip, Direction.COLLEGE_TO_HOME),
            ):
                if template is None:
                    continue
                for leg in template.legs:
                    ride = self._build_ride(
                        day, template, leg, direction, confirmation.id, weeks, resolver
                    )
                    result.rides_created += 1
                    result.total_paid += ride[1].paid_price
                    result.total_base += ride[1].base_price
                    result.total_saving += ride[1].discount_amount
                    if ride[1].benefit_expired:
                        result.warnings.append(
                            f"Льгота на {dt.format_display(day)} не действует: "
                            f"«{TransportType.label(leg.mode)} {leg.vehicle}» оплачена "
                            "по базовому тарифу."
                        )

        self.recalculate(from_date=day)
        return result

    def _build_ride(
        self,
        day: date,
        template: TripTemplate,
        leg: TripLeg,
        direction: str,
        confirmation_id: int,
        week_type: str | None,
        resolver: TariffResolver,
    ) -> tuple[int, Any]:
        """Создать одну поездку из рейса шаблона с номером периода (ALG-02)."""
        calculator = self._calculator(day)
        state = calculator.resolve(day, ride_id=None)
        stage = stage_kind_for(state.ride_number, calculator.first_limit)
        pricing = price_ride(
            resolver,
            ride_date=day,
            transport_type=leg.mode,
            payment_method=leg.payment_method,
            stage=stage if leg.payment_method == PaymentMethod.STRELKA else None,
        )
        is_strelka = leg.payment_method == PaymentMethod.STRELKA
        ride = self.rides.create(
            study_date=day,
            direction=direction,
            transport_type=leg.mode,
            vehicle=leg.vehicle,
            base_price=pricing.base_price,
            paid_price=pricing.paid_price,
            discount_amount=pricing.discount_amount,
            payment_method=leg.payment_method,
            confirmation_id=confirmation_id,
            template_id=template.id,
            template_leg_id=leg.id,
            tariff_id=pricing.tariff_id,
            # DATA-14: номер и начало периода — только у «Стрелки».
            period_start_date=state.period_start if is_strelka else None,
            ride_number_in_period=state.ride_number if is_strelka else None,
            week_type_snapshot=week_type,
        )
        return ride.id, pricing

    def _week_type(self, day: date) -> str | None:
        from .repositories import WeekAnchorRepository
        from .weektype import week_type_for

        try:
            return week_type_for(WeekAnchorRepository(self.db).all(), day)
        except Exception:  # pragma: no cover — якоря может не быть
            return None

    def recalculate(self, *, from_date: date | None = None):
        from .recalculation import RecalculationService

        return RecalculationService(self.db).recalculate(from_date=from_date)

    # ------------------------------------------------------------- отмена дня
    def unconfirm(self, day: date) -> int:
        """Снять подтверждение дня (TRIP-10): ручные поездки сохраняются."""
        confirmation = self.confirmations.by_date(day)
        if confirmation is None:
            raise NotFoundError(f"На {dt.format_display(day)} нет подтверждения поездок")
        with self.db.transaction():
            removed = self.rides.delete_for_confirmation(confirmation.id)
            self.confirmations.delete(day)
        self.recalculate(from_date=day)
        return removed

    # ------------------------------------------------- ручная поездка (REP-14)
    def add_manual_ride(
        self,
        day: date,
        *,
        direction: str,
        transport_type: str,
        vehicle: str,
        payment_method: str,
    ) -> Any:
        """Ручная поездка без подтверждения дня (ACC-M-88).

        Участвует в счётчике, остатке и отчётах наравне с остальными; при
        наличии подтверждения связывается с ним, но помечается ``is_manual``,
        поэтому переживает повторное подтверждение и снятие подтверждения.
        """
        confirmation = self.confirmations.by_date(day)
        calculator = self._calculator(day)
        state = calculator.resolve(day, ride_id=None)
        stage = stage_kind_for(state.ride_number, calculator.first_limit)
        pricing = price_ride(
            self._resolver(),
            ride_date=day,
            transport_type=transport_type,
            payment_method=payment_method,
            stage=stage if payment_method == PaymentMethod.STRELKA else None,
        )
        is_strelka = payment_method == PaymentMethod.STRELKA
        ride = self.rides.create(
            study_date=day,
            direction=direction,
            transport_type=transport_type,
            vehicle=vehicle,
            base_price=pricing.base_price,
            paid_price=pricing.paid_price,
            discount_amount=pricing.discount_amount,
            payment_method=payment_method,
            confirmation_id=confirmation.id if confirmation else None,
            tariff_id=pricing.tariff_id,
            period_start_date=state.period_start if is_strelka else None,
            ride_number_in_period=state.ride_number if is_strelka else None,
            week_type_snapshot=self._week_type(day),
            is_manual=True,
        )
        self.recalculate(from_date=day)
        return self.rides.require(ride.id)

    # --------------------------------------------------- шаблон из дня (TRIP-05)
    def save_as_template(
        self, day: date, *, name: str, direction: str | None = None
    ) -> TripTemplate:
        """«Сохранить как шаблон»: новый шаблон из поездок дня (TRIP-05).

        Исходный шаблон не изменяется (TRIP-04): создаётся новая запись.
        """
        rides = [
            ride
            for ride in self.rides.for_date(day)
            if direction is None or ride.direction == direction
        ]
        if not rides:
            raise RuleViolationError(
                f"На {dt.format_display(day)} нет поездок: сохранять в шаблон нечего (TRIP-05)."
            )
        target_direction = direction or rides[0].direction
        legs = []
        seen: set[tuple[str, str, str]] = set()
        for ride in rides:
            if ride.direction != target_direction:
                continue
            key = (ride.transport_type, ride.vehicle, ride.payment_method)
            if key in seen:
                continue
            seen.add(key)
            legs.append(
                {
                    "mode": ride.transport_type,
                    "vehicle": ride.vehicle,
                    "payment_method": ride.payment_method,
                    "is_paid": True,
                }
            )
        return self.templates.create(
            direction=target_direction,
            name=name,
            legs=legs,
        )

    # ------------------------------------------------------------ сводка дня
    def confirm_used_template(self, day: date) -> int | None:
        confirmation = self.confirmations.by_date(day)
        if confirmation is None:
            return None
        return confirmation.outbound_template_id
