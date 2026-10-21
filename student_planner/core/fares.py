"""ALG-09 — разрешение тарифа; FARE-09/FARE-10 — стоимость и откат льготы.

Стоимость определяется **на дату поездки**, а не на момент просмотра, и
фиксируется в записи снапшотом: правка тарифа не переписывает историю
(DATA-16, ACC-M-38).

Льгота имеет срок. Если на ``ride_date`` действующего льготного тарифа нет,
стоимость откатывается к базовой, экономия = 0, а способ оплаты **не
меняется** (FARE-10). Счётчик «Стрелки» при этом продолжает расти — поэтому
откат влияет на цену, но не на номер поездки.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .errors import PriceUnavailableError
from .models import PaymentMethod, Tariff, TariffKind, TransportType
from .money import ZERO, money


class TariffResolver:
    """ALG-09: выбор действующего тарифа вида на дату.

    Шаг 2: среди активных тарифов вида выбрать действующий на дату
    (``effective_from <= date <= effective_to``, ``effective_to IS NULL`` —
    бессрочно). Шаг 4 (пересечение двух тарифов) предотвращён при сохранении
    (FARE-02), но если данные всё же испорчены, выбирается последний по
    ``effective_from``, чтобы приложение не падало.
    """

    def __init__(self, tariffs: list[Tariff]) -> None:
        self._by_kind: dict[str, list[Tariff]] = {}
        for tariff in tariffs:
            self._by_kind.setdefault(tariff.kind, []).append(tariff)
        for items in self._by_kind.values():
            items.sort(key=lambda item: item.effective_from)

    def find(self, kind: str, when: date) -> Tariff | None:
        matches = [tariff for tariff in self._by_kind.get(kind, ()) if tariff.covers(when)]
        if not matches:
            return None
        return max(matches, key=lambda item: item.effective_from)

    def price_of(self, kind: str, when: date) -> Decimal | None:
        tariff = self.find(kind, when)
        return None if tariff is None else tariff.price

    def require_base(self, kind: str, when: date) -> Tariff:
        """Базовый тариф обязателен: иначе подтверждение блокируется (TRIP-19)."""
        tariff = self.find(kind, when)
        if tariff is None:
            from .dates import format_display

            raise PriceUnavailableError(
                f"На {format_display(when)} нет действующего базового тарифа "
                f"«{TariffKind.label(kind)}». Задайте тариф, чтобы подтвердить поездку "
                "(TRIP-19).",
                kind=kind,
                date=when,
            )
        return tariff


@dataclass(frozen=True)
class RidePricing:
    """Результат расчёта одной поездки (FARE-09): готовая запись-снапшот."""

    base_price: Decimal
    paid_price: Decimal
    discount_amount: Decimal
    tariff_id: int | None
    #: Льгота не действует на дату — бейдж UI-13 (FARE-10).
    benefit_expired: bool = False
    base_tariff_id: int | None = None
    stage: str | None = None


def base_kind_for(transport_type: str) -> str:
    """Базовый вид тарифа для типа транспорта."""
    return TariffKind.TRAIN_BASE if transport_type == TransportType.TRAIN else TariffKind.BUS_BASE


def price_ride(
    resolver: TariffResolver,
    *,
    ride_date: date,
    transport_type: str,
    payment_method: str,
    stage: str = TariffKind.STRELKA_STAGE1,
) -> RidePricing:
    """FARE-09: стоимость и экономия поездки на дату.

    * Электричка: ``train_base`` — база; ``train_student`` — льгота. Нет льготы
      на дату → откат к ``train_base``, экономия 0 (FARE-10, ACC-M-42).
    * Автобус «Стрелкой»: ``bus_base`` — база; ``strelka_stage1/2`` — льгота по
      ступени (ALG-02 шаг 9). Нет льготы → откат к ``bus_base`` (ACC-M-43).
    * Автобус дебетовой картой: полная ``bus_base``, экономии нет (FARE-08).
    """
    base_kind = base_kind_for(transport_type)
    base_tariff = resolver.require_base(base_kind, ride_date)
    base_price = money(base_tariff.price)

    if transport_type == TransportType.TRAIN:
        if payment_method != PaymentMethod.TRAIN_STUDENT:  # защита; правило проверено выше
            return RidePricing(
                base_price=base_price,
                paid_price=base_price,
                discount_amount=ZERO,
                tariff_id=base_tariff.id,
                base_tariff_id=base_tariff.id,
            )
        student = resolver.find(TariffKind.TRAIN_STUDENT, ride_date)
        if student is None:
            return RidePricing(
                base_price=base_price,
                paid_price=base_price,
                discount_amount=ZERO,
                tariff_id=base_tariff.id,
                base_tariff_id=base_tariff.id,
                benefit_expired=True,
            )
        paid = _cap(money(student.price), base_price)
        return RidePricing(
            base_price=base_price,
            paid_price=paid,
            discount_amount=money(base_price - paid),
            tariff_id=student.id,
            base_tariff_id=base_tariff.id,
            benefit_expired=False,
        )

    # Автобус.
    if payment_method == PaymentMethod.DEBIT_CARD:
        return RidePricing(
            base_price=base_price,
            paid_price=base_price,
            discount_amount=ZERO,
            tariff_id=base_tariff.id,
            base_tariff_id=base_tariff.id,
        )
    stage_tariff = resolver.find(stage, ride_date)
    if stage_tariff is None:
        return RidePricing(
            base_price=base_price,
            paid_price=base_price,
            discount_amount=ZERO,
            tariff_id=base_tariff.id,
            base_tariff_id=base_tariff.id,
            benefit_expired=True,
            stage=stage,
        )
    paid = _cap(money(stage_tariff.price), base_price)
    return RidePricing(
        base_price=base_price,
        paid_price=paid,
        discount_amount=money(base_price - paid),
        tariff_id=stage_tariff.id,
        base_tariff_id=base_tariff.id,
        benefit_expired=False,
        stage=stage,
    )


def _cap(paid: Decimal, base: Decimal) -> Decimal:
    """Стоимость со скидкой не может превышать базовую (защита от ошибок данных)."""
    return money(paid if paid <= base else base)


def stage_kind_for(number: int | None, first_limit: int) -> str:
    """ALG-02 шаг 9 → вид тарифа ступени."""
    if number is None:
        return TariffKind.STRELKA_STAGE1
    return TariffKind.STRELKA_STAGE1 if number <= first_limit else TariffKind.STRELKA_STAGE2


__all__ = [
    "TariffResolver",
    "RidePricing",
    "price_ride",
    "base_kind_for",
    "stage_kind_for",
]
