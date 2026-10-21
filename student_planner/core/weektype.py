"""ALG-01: тип недели по действующему якорю — чистая функция.

Вынесено отдельно, чтобы этой логикой могли пользоваться и репозитории, и
сервисы, и UI без циклических импортов. Функция не трогает БД: якоря
передаются списком.

ALG-01:
    1. Найти якорь с максимальной ``effective_from <= дата``.
    2. Найти понедельник недели даты и понедельник ``base_date``.
    3. ``n = (разница_недель mod cycle_length)``.
    4. При ``cycle_length = 2``: ``n = 0`` → тип совпадает с ``base_type``,
       ``n = 1`` → противоположный.
    5. При ``cycle_length > 2`` поведение в MVP не определено (TODO-15).
"""

from __future__ import annotations

from datetime import date

from .dates import weeks_between
from .models import WeekAnchor, WeekType


def effective_anchor(anchors: list[WeekAnchor] | tuple[WeekAnchor, ...], value: date) -> WeekAnchor | None:
    """Якорь с максимальной ``effective_from <= value`` (шаг 1)."""
    applicable = [anchor for anchor in anchors if anchor.effective_from <= value]
    if not applicable:
        return None
    return max(applicable, key=lambda anchor: anchor.effective_from)


def week_type_for(
    anchors: list[WeekAnchor] | tuple[WeekAnchor, ...], value: date
) -> str | None:
    """Тип недели для даты; ``None``, если действующего якоря нет."""
    anchor = effective_anchor(anchors, value)
    if anchor is None:
        return None
    cycle = anchor.cycle_length or 2
    if cycle <= 0:
        return anchor.base_type
    shift = weeks_between(anchor.base_date, value) % cycle
    if shift == 0:
        return anchor.base_type
    if cycle == 2 and shift == 1:
        return WeekType.opposite(anchor.base_type)
    # cycle_length > 2: в MVP отображение не определено (TODO-15). Сохраняем
    # детерминированное поведение: чередование по кругу от опорного типа.
    if shift % 2 == 1:
        return WeekType.opposite(anchor.base_type)
    return anchor.base_type


def type_starting(value: date) -> date:
    """Понедельник недели даты — начало «недели» WEEK-01."""
    from .dates import monday_of

    return monday_of(value)


__all__ = ["effective_anchor", "week_type_for", "type_starting"]
