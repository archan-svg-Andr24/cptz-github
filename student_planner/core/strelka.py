"""ALG-02 — скользящий расчётный период «Стрелки»; ALG-03 — номер поездки.

Это самая ответственная часть MVP. Границы периода — **функция от истории**
засчитанных поездок, а не справочник дат: отдельной таблицы нет, а начало
периода, относящееся к поездке, хранится снапшотом ``period_start_date``
и обновляется каскадным пересчётом (CALC-04).

Реализация повторяет шаги ALG-02 дословно, включая три состояния
(«учёт не начат», «до начала учёта», обычный случай) и разделение шагов 6–7
(``n_prev`` — поездки строго раньше даты; ``k`` — порядковый номер среди
поездок этой даты), которое лечит офф-бай-у-он при пересчёте.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

STATE_UNSTARTED = "unstarted"
"""ALG-02 шаг 1: засчитанных поездок нет и якорь не задан."""
STATE_BEFORE_ANCHOR = "before_anchor"
"""ALG-02 шаг 3: дата раньше начала учёта."""
STATE_ACTIVE = "active"
"""ALG-02 шаг 4: обычный случай."""


@dataclass(frozen=True)
class PeriodState:
    """Результат ALG-02 для даты: границы, номер и ступень."""

    period_start: date | None
    period_end: date | None
    ride_number: int | None
    stage: str
    state: str = STATE_ACTIVE
    #: Границы предварительные: период открыт запросом, а не поездкой (REP-05).
    provisional: bool = False

    @property
    def is_first_period_of_chain(self) -> bool:
        return self.state == STATE_UNSTARTED

    @property
    def has_bounds(self) -> bool:
        return self.period_start is not None

    @property
    def bounds_caption(self) -> str:
        """Подпись границ для виджета «Стрелка» (REP-05)."""
        from .dates import format_display

        if self.state == STATE_UNSTARTED:
            return "Период начнётся с первой поездки"
        if self.state == STATE_BEFORE_ANCHOR or self.period_start is None:
            return "До начала учёта"
        text = f"{format_display(self.period_start)} — {format_display(self.period_end)}"
        if self.provisional:
            text += " (предварительно)"
        return text

    @property
    def badge(self) -> str | None:
        """Бейджи UI-13: «До начала учёта», «Счётчик приближённый»."""
        if self.state == STATE_BEFORE_ANCHOR:
            return "До начала учёта"
        return None


@dataclass(frozen=True)
class _CountedRide:
    """Минимальные данные засчитанной поездки, нужные ALG-02."""

    id: int
    ride_date: date


class StrellaPeriodCalculator:
    """ALG-02: границы периода, номер поездки (ALG-03) и ступень.

    Экземпляр держит **все** засчитанные поездки (``payment_method =
    'strelka'``) и настройки начала учёта. Один экземпляр используется для
    каскадного пересчёта всей истории, поэтому бисекция по возрастанию дат не
    пересчитывает окно заново на каждую поездку.
    """

    def __init__(
        self,
        *,
        rides: list[_CountedRide] | list[tuple[int, date]],
        anchor: date | None,
        initial_count: int = 0,
        period_days: int = 30,
        first_limit: int = 35,
    ) -> None:
        normalized = [
            item if isinstance(item, _CountedRide) else _CountedRide(id=item[0], ride_date=item[1])
            for item in rides
        ]
        normalized.sort(key=lambda item: (item.ride_date, item.id))
        self._rides = normalized
        self._anchor0 = anchor
        self.initial_count = max(0, int(initial_count))
        self.period_days = max(1, int(period_days))
        self.first_limit = max(1, int(first_limit))
        # Даты поездок по возрастанию (с дублями) — для шага 4 и шагов 6–7.
        self._dates = [item.ride_date for item in normalized]
        self._earliest = self._dates[0] if self._dates else None
        # ALG-02 шаг 7: порядковый номер поездки среди поездок своей даты.
        # Предвычисляется один раз: иначе пакетный пересчёт 5000 поездок был бы
        # квадратичным (NFR-10 требует ≤ 1 с).
        self._ordinals: dict[int, int] = {}
        running_date: date | None = None
        running_index = 0
        for item in normalized:
            if item.ride_date != running_date:
                running_date = item.ride_date
                running_index = 1
            else:
                running_index += 1
            self._ordinals[item.id] = running_index
        #: Кэш шага 4: для каждой запрошенной даты — (начало, конец, предварительность).
        #: Границы зависят только от даты, поэтому при пакетном пересчёте они
        #: считаются один раз на дату, а не на каждую поездку (NFR-10).
        self._bounds_cache: dict[date, tuple[date, date, bool]] = {}
        #: Известные начала периодов по возрастанию — цепочка шага 4 проходится
        #: от последнего из них, а не от якоря.
        self._known_starts: list[date] = []
        #: Признак «границы периода предварительные» по началу периода (REP-05):
        #: период открыт запросом, а не поездкой. Якорный период — окончательный.
        self._start_provisional: dict[date, bool] = {}
        # Якорь известен заранее: первый период цепочки — от него.
        if self._anchor0 is not None:
            self._known_starts.append(self._anchor0)
            self._start_provisional[self._anchor0] = False
        elif self._earliest is not None:
            self._known_starts.append(self._earliest)
            self._start_provisional[self._earliest] = False

    # ------------------------------------------------------------ свойства
    @property
    def has_rides(self) -> bool:
        return bool(self._rides)

    @property
    def anchor(self) -> date | None:
        """ALG-02 шаг 2: ``anchor0``, если задана, иначе дата самой ранней поездки."""
        if self._anchor0 is not None:
            return self._anchor0
        return self._earliest

    def stage_of(self, number: int | None) -> str:
        """ALG-02 шаг 9: ступень по номеру."""
        if number is None:
            return "strelka_stage1"
        return "strelka_stage1" if number <= self.first_limit else "strelka_stage2"

    # -------------------------------------------------------------- расчёт
    def resolve(self, when: date, *, ride_id: int | None = None) -> PeriodState:
        """ALG-02 для даты ``when``.

        ``ride_id`` — пересчитываемая поездка (шаг 7): её порядковый номер среди
        поездок этой даты. ``None`` — запрос «следующая поездка» (``k = 1``).
        """
        anchor = self.anchor
        # --- шаг 1: учёт не начат -----------------------------------------
        if not self.has_rides and self._anchor0 is None:
            number = self.initial_count + 1
            return PeriodState(
                period_start=None,
                period_end=None,
                ride_number=number,
                stage=self.stage_of(number),
                state=STATE_UNSTARTED,
            )
        # anchor не может быть None начиная отсюда: либо anchor0 задана, либо
        # есть хотя бы одна поездка (шаг 2).
        if anchor is None:  # pragma: no cover — защита от рассогласования
            number = self.initial_count + 1
            return PeriodState(None, None, number, self.stage_of(number), STATE_UNSTARTED)

        # --- шаг 3: до начала учёта ---------------------------------------
        if when < anchor:
            return PeriodState(None, None, None, "strelka_stage1", STATE_BEFORE_ANCHOR)

        # --- шаг 4: цепочка границ ----------------------------------------
        period_start, period_end, provisional = self._bounds_for(when)

        # --- шаг 6: n_prev — поездки строго раньше даты -------------------
        n_prev = self._count_between(period_start, when, include_end=False)

        # --- шаг 7: k — порядковый номер среди поездок даты ----------------
        if ride_id is None:
            k = 1
        else:
            k = self._ordinal_on_date(when, ride_id)

        # --- шаг 8: номер --------------------------------------------------
        number = n_prev + k
        if self._is_first_period_of_chain(period_start, anchor):
            number += self.initial_count
        return PeriodState(
            period_start=period_start,
            period_end=period_end,
            ride_number=number,
            stage=self.stage_of(number),
            state=STATE_ACTIVE,
            provisional=provisional,
        )

    # ------------------------------------------------------- вспомогательное
    def _is_first_period_of_chain(self, period_start: date, anchor: date) -> bool:
        """ALG-02 шаг 8: ``cnt0`` применяется только к первому периоду цепочки."""
        return period_start == anchor

    def _next_ride_date_after(self, value: date) -> date | None:
        """Самая ранняя дата поездки строго позже ``value`` (бисекция)."""
        index = _bisect_right(self._dates, value)
        return self._dates[index] if index < len(self._dates) else None

    def _count_between(self, start: date, end: date, *, include_end: bool) -> int:
        """Число засчитанных поездок в ``[start, end)`` или ``[start, end]``."""
        left = _bisect_left(self._dates, start)
        right = _bisect_right(self._dates, end) if include_end else _bisect_left(self._dates, end)
        return max(0, right - left)

    def _ordinal_on_date(self, when: date, ride_id: int) -> int:
        """Порядковый номер поездки среди поездок той же даты, в порядке ``id``."""
        known = self._ordinals.get(ride_id)
        if known is not None:
            return known
        # Пересчитываемая поездка ещё не в списке (новая запись) — она последняя.
        return sum(1 for item in self._rides if item.ride_date == when) + 1

    # ------------------------------------------------------ пакетный пересчёт
    def recalculate(self) -> list[tuple[int, PeriodState]]:
        """Пересчитать номера и границы для **всех** засчитанных поездок.

        Идёт в порядке ``(ride_date, id)``; разделение шагов 6–7 гарантирует,
        что поездка не засчитывается в собственный счётчик дважды
        (ACC-M-76a). Возвращает список ``(ride_id, состояние)``.

        Состояние периода зависит только от даты, поэтому расчёт для всех
        поездок одной даты переиспользуется (``_bounds_cache``): это тот же
        результат, что и поэлементный :meth:`resolve`, но без повторного
        прохода по цепочке периодов на каждую поездку (NFR-10).
        """
        return [
            (item.id, self.resolve(item.ride_date, ride_id=item.id))
            for item in self._rides
        ]

    def _bounds_for(self, when: date) -> tuple[date, date, bool]:
        """ALG-02 шаг 4 с кэшем: границы периода, содержащего ``when``.

        Границы — функция даты, поэтому результат кэшируется. Сама цепочка
        проходится от последнего известного начала периода, а не от якоря:
        иначе пакетный пересчёт 5000 поездок за 2.5 года делал бы квадратичное
        число шагов (NFR-10).
        """
        cached = self._bounds_cache.get(when)
        if cached is not None:
            return cached

        anchor = self.anchor
        assert anchor is not None  # вызывается только для when >= anchor
        span = self.period_days - 1

        # Стартуем с ближайшего известного начала периода не позже `when`.
        import bisect

        position = bisect.bisect_right(self._known_starts, when)
        start = self._known_starts[position - 1] if position else anchor
        last_day = start + timedelta(days=span)

        if when <= last_day:
            # Период уже определён — уточнять нечего.
            result = (start, last_day, self._start_provisional.get(start, False))
            self._bounds_cache[when] = result
            return result

        provisional = False
        while when > last_day:
            nxt = self._next_ride_date_after(last_day)
            if nxt is not None and nxt <= when:
                start = nxt
                last_day = start + timedelta(days=span)
                continue
            # «нет next», «next > when» и «next == when» дают один результат.
            start = when
            last_day = start + timedelta(days=span)
            provisional = self._next_ride_date_after(when) is None
            break

        self._remember_start(start, provisional=provisional)
        result = (start, last_day, provisional)
        self._bounds_cache[when] = result
        return result

    def _remember_start(self, start: date, *, provisional: bool) -> None:
        """Запомнить начало периода для последующих запросов (монотонно)."""
        import bisect

        index = bisect.bisect_left(self._known_starts, start)
        if index == len(self._known_starts) or self._known_starts[index] != start:
            self._known_starts.insert(index, start)
        # Признак может уточниться: если период позже открыла поездка, границы
        # перестают быть предварительными.
        self._start_provisional[start] = self._start_provisional.get(start, True) and provisional

    # ------------------------------------------------------- «Стрелка»-виджет
    def next_state(self, when: date) -> PeriodState:
        """Состояние для «следующей поездки» на дату (виджет REP-05)."""
        return self.resolve(when, ride_id=None)


def _bisect_left(values: list[date], target: date) -> int:
    """``bisect.bisect_left`` без импорта ради читаемости сигнатуры."""
    import bisect

    return bisect.bisect_left(values, target)


def _bisect_right(values: list[date], target: date) -> int:
    import bisect

    return bisect.bisect_right(values, target)


__all__ = [
    "PeriodState",
    "StrellaPeriodCalculator",
    "STATE_UNSTARTED",
    "STATE_BEFORE_ANCHOR",
    "STATE_ACTIVE",
]
