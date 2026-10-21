"""Слой 1: скользящий расчётный период «Стрелки» (ACC-M-76…86a).

Это ядро этапа 1 §1.12. Проверяется механика ALG-02 на **синтетических**
фикстурах (TEST-01): цепочка границ, три состояния, разделение шагов 6–7,
применение ``cnt0`` только к первому периоду, самокоррекция устаревшего якоря.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from student_planner.core.models import PaymentMethod
from student_planner.core.recalculation import RecalculationService, wallet_balance
from student_planner.core.strelka import (
    STATE_ACTIVE,
    STATE_BEFORE_ANCHOR,
    STATE_UNSTARTED,
    StrellaPeriodCalculator,
)
from student_planner.core.transport_repositories import RideRepository

from conftest import add_strelka_ride, weekday_dates


def build(rides, *, anchor=None, cnt0=0, period_days=30, first_limit=35):
    return StrellaPeriodCalculator(
        rides=[(ride.id, ride.ride_date) for ride in rides],
        anchor=anchor,
        initial_count=cnt0,
        period_days=period_days,
        first_limit=first_limit,
    )


# ---------------------------------------------------------------------------
# ACC-M-76 — период не определён при отсутствии поездок.
# ---------------------------------------------------------------------------
def test_acc_m_76_period_undefined_without_rides() -> None:
    calc = StrellaPeriodCalculator(rides=[], anchor=None, initial_count=0)
    state = calc.resolve(date(2026, 10, 20))

    assert state.state == STATE_UNSTARTED
    assert state.period_start is None, "В состоянии шага 1 границы не определены"
    assert state.period_end is None
    assert state.ride_number == 1, "Номер всё равно вычисляется: cnt0 + 1 (ALG-02 шаг 8)"
    assert state.stage == "strelka_stage1", "Ступень — первая"
    assert "начнётся с первой поездки" in state.bounds_caption, "REP-05: особый текст границ"


def test_acc_m_76_unstarted_number_includes_initial_count() -> None:
    calc = StrellaPeriodCalculator(rides=[], anchor=None, initial_count=7)
    state = calc.resolve(date(2026, 10, 20))
    assert state.state == STATE_UNSTARTED
    assert state.ride_number == 8


def test_acc_m_76_unstarted_with_anchor_only_is_not_step_1() -> None:
    """Если якорь задан, но поездок ещё нет — это не шаг 1, а период от якоря."""
    calc = StrellaPeriodCalculator(rides=[], anchor=date(2026, 9, 1), initial_count=0)
    state = calc.resolve(date(2026, 9, 10))
    assert state.state == STATE_ACTIVE
    assert state.period_start == date(2026, 9, 1)
    assert state.period_end == date(2026, 9, 30)


# ---------------------------------------------------------------------------
# ACC-M-76a — нет офф-бай-у-он при пересчёте.
# ---------------------------------------------------------------------------
def test_acc_m_76a_no_double_counting_on_recalculation() -> None:
    """Две поездки на одну дату: номера 1 и 2; повторный пересчёт их не увеличивает."""
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 7)), (2, date(2026, 9, 7))], anchor=None
    )
    numbers = {ride_id: state.ride_number for ride_id, state in calc.recalculate()}
    assert numbers == {1: 1, 2: 2}, "n_prev = 0, k = 1 и k = 2 (ALG-02 шаги 6–8)"

    repeated = {ride_id: state.ride_number for ride_id, state in calc.recalculate()}
    assert repeated == numbers, "Повторный пересчёт не увеличивает номер (ACC-M-76a)"


def test_acc_m_76a_three_rides_same_date_ordered_by_id() -> None:
    calc = StrellaPeriodCalculator(
        rides=[(10, date(2026, 9, 7)), (11, date(2026, 9, 7)), (12, date(2026, 9, 7))],
        anchor=None,
    )
    numbers = [state.ride_number for _, state in calc.recalculate()]
    assert numbers == [1, 2, 3], "Порядок внутри даты — по id (шаг 7)"


def test_acc_m_76a_ride_not_counted_in_own_counter() -> None:
    """Поездка на 10.09 при 3 поездках 07.09 получает номер 4, а не 5."""
    rides = [(1, date(2026, 9, 7)), (2, date(2026, 9, 7)), (3, date(2026, 9, 7)),
             (4, date(2026, 9, 10))]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    numbers = {ride_id: state.ride_number for ride_id, state in calc.recalculate()}
    assert numbers[4] == 4, "n_prev = 3 (строго раньше 10.09), k = 1"
    assert numbers[3] == 3


# ---------------------------------------------------------------------------
# ACC-M-77 — якорь по умолчанию = дата самой ранней поездки.
# ---------------------------------------------------------------------------
def test_acc_m_77_default_anchor_is_earliest_ride(db: object) -> None:
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 7)), (2, date(2026, 9, 8))], anchor=None
    )
    assert calc.anchor == date(2026, 9, 7), "ALG-02 шаг 2: anchor = дата самой ранней поездки"
    state = calc.resolve(date(2026, 9, 7))
    assert state.period_start == date(2026, 9, 7)
    assert state.period_end == date(2026, 10, 6), "30 дней включительно"


def test_acc_m_77_explicit_anchor_wins_over_earliest_ride() -> None:
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 7))], anchor=date(2026, 9, 1)
    )
    assert calc.anchor == date(2026, 9, 1)


# ---------------------------------------------------------------------------
# ACC-M-78 — границы периода: 30-й день входит, 31-й — нет.
# ---------------------------------------------------------------------------
def test_acc_m_78_thirtieth_day_is_last_of_period() -> None:
    calc = StrellaPeriodCalculator(rides=[(1, date(2026, 9, 7))], anchor=None)
    state = calc.resolve(date(2026, 10, 6))
    assert state.period_start == date(2026, 9, 7)
    assert state.period_end == date(2026, 10, 6), "07.09 + 29 дней = 06.10"


def test_acc_m_78_thirty_first_day_starts_new_period() -> None:
    rides = [(1, date(2026, 9, 7)), (2, date(2026, 10, 7))]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    state = calc.resolve(date(2026, 10, 7), ride_id=2)
    assert state.period_start == date(2026, 10, 7), "31-й день не входит в первый период"
    assert state.ride_number == 1, "Новый период начинается с 1"


def test_acc_m_78_period_length_is_configurable() -> None:
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 7))], anchor=None, period_days=10
    )
    state = calc.resolve(date(2026, 9, 16))
    assert state.period_end == date(2026, 9, 16), "07.09 + 9 = 16.09"
    assert state.period_start == date(2026, 9, 7)


# ---------------------------------------------------------------------------
# ACC-M-79 / ACC-M-79a — смена периода и объединение ветвей шага 4.
# ---------------------------------------------------------------------------
def test_acc_m_79_new_period_opened_by_first_ride_after_expiry() -> None:
    """Последняя поездка 06.10, следующая 12.10 → новый период с номера 1."""
    rides = [
        (1, date(2026, 9, 7)),
        (2, date(2026, 10, 6)),
        (3, date(2026, 10, 12)),
    ]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    state = calc.resolve(date(2026, 10, 12), ride_id=3)
    assert state.period_start == date(2026, 10, 12), "Ветвь next <= D: период открыла поездка"
    assert state.period_end == date(2026, 11, 10)
    assert state.ride_number == 1, "Не продолжение старого периода"


def test_acc_m_79a_all_three_branches_give_same_result() -> None:
    """«нет next», «next > D» и «next == D» дают start = D (ALG-02 шаг 4)."""
    base = [(1, date(2026, 9, 7)), (2, date(2026, 10, 6))]

    # Ветвь «нет next»: поездок после 06.10 нет, запрос на 20.10.
    no_next = StrellaPeriodCalculator(rides=base, anchor=None)
    state_no_next = no_next.resolve(date(2026, 10, 20))

    # Ветвь «next > D»: следующая поездка 25.10, запрос на 20.10.
    next_later = StrellaPeriodCalculator(
        rides=base + [(3, date(2026, 10, 25))], anchor=None
    )
    state_next_later = next_later.resolve(date(2026, 10, 20))

    # Ветвь «next == D»: поездка ровно на запрошенную дату.
    next_same = StrellaPeriodCalculator(
        rides=base + [(3, date(2026, 10, 20))], anchor=None
    )
    state_next_same = next_same.resolve(date(2026, 10, 20), ride_id=3)

    assert state_no_next.period_start == date(2026, 10, 20)
    assert state_next_later.period_start == date(2026, 10, 20)
    assert state_next_same.period_start == date(2026, 10, 20)
    assert state_no_next.period_end == state_next_later.period_end == state_next_same.period_end
    assert state_no_next.ride_number == state_next_later.ride_number == 1


def test_acc_m_79a_provisional_flag_only_when_no_ride_opens_period() -> None:
    """REP-05: границы предварительны, если период открыт запросом, а не поездкой."""
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 7)), (2, date(2026, 10, 6))], anchor=None
    )
    query = calc.resolve(date(2026, 10, 20))
    assert query.provisional is True, "Поездки после 06.10 нет — границы предварительные"

    with_next = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 7)), (2, date(2026, 10, 6)), (3, date(2026, 10, 20))], anchor=None
    )
    opened = with_next.resolve(date(2026, 10, 20), ride_id=3)
    assert opened.provisional is False, "Период открыт поездкой — границы окончательные"


# ---------------------------------------------------------------------------
# ACC-M-80 — разрыв длиннее периода открывает новый период с номера 1.
# ---------------------------------------------------------------------------
def test_acc_m_80_gap_longer_than_period() -> None:
    rides = [(1, date(2026, 1, 1)), (2, date(2026, 2, 2))]  # ровно 32 дня
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    state = calc.resolve(date(2026, 2, 2), ride_id=2)
    assert state.period_start == date(2026, 2, 2)
    assert state.ride_number == 1, "Без ручных действий: новая поездка открывает период"
    assert state.stage == "strelka_stage1", "Ступень первая"


def test_acc_m_80_gap_does_not_need_special_rule() -> None:
    """Разрыв проходит той же ветвью шага 4, отдельных правил нет."""
    rides = [(1, date(2026, 1, 1)), (2, date(2026, 6, 1))]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    state = calc.resolve(date(2026, 6, 1), ride_id=2)
    assert state.period_start == date(2026, 6, 1)
    assert state.ride_number == 1


# ---------------------------------------------------------------------------
# ACC-M-81 — дата раньше якоря: оба поля NULL, бейдж «До начала учёта».
# ---------------------------------------------------------------------------
def test_acc_m_81_ride_before_anchor() -> None:
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 8, 1)), (2, date(2026, 9, 10))], anchor=date(2026, 9, 1)
    )
    state = calc.resolve(date(2026, 8, 1), ride_id=1)
    assert state.state == STATE_BEFORE_ANCHOR
    assert state.period_start is None, "ALG-02 шаг 3: period_start_date = NULL"
    assert state.ride_number is None, "ALG-02 шаг 3: ride_number_in_period = NULL"
    assert state.badge == "До начала учёта", "Бейдж UI-13"


def test_acc_m_81_after_anchor_is_normal_case() -> None:
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 10))], anchor=date(2026, 9, 1)
    )
    state = calc.resolve(date(2026, 9, 10), ride_id=1)
    assert state.state == STATE_ACTIVE
    assert state.ride_number is not None


# ---------------------------------------------------------------------------
# ACC-M-82 — cnt0 применяется только к первому периоду цепочки.
# ---------------------------------------------------------------------------
def test_acc_m_82_initial_count_only_first_period() -> None:
    """При cnt0 = 10 первый период нумеруется 11, 12, …, 35 → 1-я ступень, 36 → 2-я."""
    rides = [(index, date(2026, 9, 7)) for index in range(1, 26)]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None, initial_count=10)
    numbers = [state.ride_number for _, state in calc.recalculate()]
    assert numbers == list(range(11, 36)), "Первый период продолжает счёт с cnt0"


def test_acc_m_82_threshold_with_initial_count() -> None:
    rides = [(index, date(2026, 9, 7)) for index in range(1, 27)]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None, initial_count=10)
    states = [state for _, state in calc.recalculate()]
    assert states[24].ride_number == 35 and states[24].stage == "strelka_stage1", (
        "25-я поездка: номер 10 + 25 = 35, ещё первая ступень"
    )
    assert states[25].ride_number == 36 and states[25].stage == "strelka_stage2", (
        "26-я поездка: номер 36 — вторая ступень"
    )


def test_acc_m_82_second_period_ignores_initial_count() -> None:
    rides = [(1, date(2026, 9, 7)), (2, date(2026, 10, 12))]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None, initial_count=10)
    second = calc.resolve(date(2026, 10, 12), ride_id=2)
    assert second.period_start == date(2026, 10, 12), "Второй период цепочки"
    assert second.ride_number == 1, "cnt0 не применяется вне первого периода (шаг 8)"


def test_acc_m_82_initial_count_with_explicit_anchor_applies_to_first_period() -> None:
    """Первый период цепочки = период от якоря."""
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 10))], anchor=date(2026, 9, 1), initial_count=5
    )
    state = calc.resolve(date(2026, 9, 10), ride_id=1)
    assert state.ride_number == 6, "n_prev = 0, k = 1, + cnt0 = 5 → 6"


# ---------------------------------------------------------------------------
# ACC-M-83 — прохождение порога 35; дебетовые поездки не считаются.
# ---------------------------------------------------------------------------
def test_acc_m_83_threshold_at_35_and_36() -> None:
    """Поездки с id 1…36 на одну дату: 35-я — первая ступень, 36-я — вторая."""
    rides = [(index, date(2026, 9, 7)) for index in range(1, 37)]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None, first_limit=35)
    states = {ride_id: state for ride_id, state in calc.recalculate()}
    assert states[35].ride_number == 35 and states[35].stage == "strelka_stage1"
    assert states[36].ride_number == 36 and states[36].stage == "strelka_stage2"
    assert states[36].period_start == date(2026, 9, 7), (
        "Переход ступени не открывает новый период"
    )


def test_acc_m_83_debit_card_rides_do_not_advance_counter(db, base_tariffs, ride_repo_factory) -> None:
    """DATA-14: в счётчик входят только ``strelka``."""
    rides = ride_repo_factory(db)
    first = add_strelka_ride(rides, date(2026, 9, 7))
    rides.create(
        study_date=date(2026, 9, 7),
        direction="home_to_college",
        transport_type="bus",
        vehicle="42",
        base_price="50.00",
        paid_price="50.00",
        discount_amount="0.00",
        payment_method="debit_card",
    )
    second = add_strelka_ride(rides, date(2026, 9, 7))

    strelka_only = rides.strelka_rides()
    assert len(strelka_only) == 2, "Дебетовая поездка не попадает в выборку ALG-02"
    calc = StrellaPeriodCalculator(
        rides=[(ride.id, ride.ride_date) for ride in strelka_only], anchor=None
    )
    numbers = {ride_id: state.ride_number for ride_id, state in calc.recalculate()}
    assert numbers[first.id] == 1
    assert numbers[second.id] == 2, "Номер второй strelka-поездки не «съеден» дебетовой"


def test_acc_m_83_custom_first_limit() -> None:
    rides = [(index, date(2026, 9, 7)) for index in range(1, 4)]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None, first_limit=2)
    states = [state.stage for _, state in calc.recalculate()]
    assert states == ["strelka_stage1", "strelka_stage1", "strelka_stage2"]


# ---------------------------------------------------------------------------
# ACC-M-86a — устаревший якорь самокорректируется.
# ---------------------------------------------------------------------------
def test_acc_m_86a_stale_anchor_self_corrects() -> None:
    """anchor на 3 месяца раньше первой поездки → период открывается её датой."""
    calc = StrellaPeriodCalculator(
        rides=[(1, date(2026, 9, 7)), (2, date(2026, 9, 8))],
        anchor=date(2026, 6, 1),
        initial_count=0,
    )
    first = calc.resolve(date(2026, 9, 7), ride_id=1)
    assert first.period_start == date(2026, 9, 7), (
        "Шаг 4: окно [01.06, 30.06] истекло, next == D → период открывает поездка"
    )
    assert first.ride_number == 1, "Номера последующих не искажены"


def test_acc_m_86a_numbers_not_distorted_by_stale_anchor() -> None:
    rides = [(index, date(2026, 9, 7)) for index in range(1, 4)]
    stale = StrellaPeriodCalculator(rides=rides, anchor=date(2026, 6, 1), initial_count=0)
    fresh = StrellaPeriodCalculator(rides=rides, anchor=None, initial_count=0)
    assert [s.ride_number for _, s in stale.recalculate()] == [
        s.ride_number for _, s in fresh.recalculate()
    ] == [1, 2, 3]


# ---------------------------------------------------------------------------
# ACC-M-93 — запрос внутри действующего периода не открывает новый.
# ---------------------------------------------------------------------------
def test_acc_m_93_query_inside_active_period() -> None:
    """Период [15.11, 14.12]; 2 поездки 15.11; запрос на 20.11 → номер 3."""
    rides = [
        (1, date(2026, 10, 12)),
        (2, date(2026, 11, 15)),
        (3, date(2026, 11, 15)),
    ]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    state = calc.resolve(date(2026, 11, 20))
    assert state.period_start == date(2026, 11, 15), "Цикл шага 4 не выполняется"
    assert state.period_end == date(2026, 12, 14)
    assert state.ride_number == 3, "n_prev = 2, k = 1"
    assert state.stage == "strelka_stage1"


def test_acc_m_93_query_after_expiry_opens_period() -> None:
    """Запрос на 18.12, поездок после 14.12 нет → [18.12, 16.01], номер 1."""
    rides = [
        (1, date(2026, 10, 12)),
        (2, date(2026, 11, 15)),
        (3, date(2026, 11, 15)),
    ]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    state = calc.resolve(date(2026, 12, 18))
    assert state.period_start == date(2026, 12, 18)
    assert state.period_end == date(2027, 1, 16)
    assert state.ride_number == 1
    assert state.provisional is True, "REP-05: границы предварительные"


def test_acc_m_93_chain_of_periods_matches_spec_table() -> None:
    """Полный сценарий таблицы ALG-02 на фикстуре Б (Пн–Сб, 2 поездки в день)."""
    period1_dates = weekday_dates(date(2026, 9, 7), date(2026, 10, 6), {1, 2, 3, 4, 5, 6})
    assert len(period1_dates) == 26, "В окне [07.09, 06.10] 26 учебных дней по Пн–Сб"

    rides: list[tuple[int, date]] = []
    ride_id = 1
    for day in period1_dates:
        rides.append((ride_id, day))
        ride_id += 1
        rides.append((ride_id, day))
        ride_id += 1
    assert len(rides) == 52, "Итого 52 поездки в первом периоде (фикстура Б)"

    boundary_first = rides[-2][0]
    boundary_second = rides[-1][0]
    # Далее — только названные в таблице даты: 12.10 (2), 15.11 (2).
    rides.extend([(ride_id, date(2026, 10, 12)), (ride_id + 1, date(2026, 10, 12))])
    oct_first = ride_id
    ride_id += 2
    rides.extend([(ride_id, date(2026, 11, 15)), (ride_id + 1, date(2026, 11, 15))])
    nov_first = ride_id

    calc = StrellaPeriodCalculator(rides=rides, anchor=None)

    first = calc.resolve(date(2026, 9, 7), ride_id=1)
    assert (first.period_start, first.period_end, first.ride_number) == (
        date(2026, 9, 7), date(2026, 10, 6), 1,
    )

    edge = calc.resolve(date(2026, 10, 6), ride_id=boundary_first)
    assert edge.ride_number == 51 and edge.stage == "strelka_stage2", (
        "По таблице ALG-02: n_prev = 50, k = 1 → номер 51"
    )
    edge2 = calc.resolve(date(2026, 10, 6), ride_id=boundary_second)
    assert edge2.ride_number == 52

    second = calc.resolve(date(2026, 10, 12), ride_id=oct_first)
    assert (second.period_start, second.period_end, second.ride_number) == (
        date(2026, 10, 12), date(2026, 11, 10), 1,
    )

    third = calc.resolve(date(2026, 11, 15), ride_id=nov_first)
    assert (third.period_start, third.period_end, third.ride_number) == (
        date(2026, 11, 15), date(2026, 12, 14), 1,
    )

    widget = calc.resolve(date(2026, 11, 20))
    assert (widget.period_start, widget.period_end, widget.ride_number) == (
        date(2026, 11, 15), date(2026, 12, 14), 3,
    )

    later = calc.resolve(date(2026, 12, 18))
    assert (later.period_start, later.period_end, later.ride_number) == (
        date(2026, 12, 18), date(2027, 1, 16), 1,
    )


def test_batch_matches_single_resolution() -> None:
    """Пакетный пересчёт обязан совпадать с поэлементным ``resolve``.

    ``recalculate`` переиспользует расчёт границ между поездками одной даты
    (NFR-10), а ``resolve`` каждый раз идёт от якоря. Инвариант эквивалентности
    фиксируется тестом: оптимизация не имеет права менять результат.
    """
    period1 = weekday_dates(date(2026, 9, 7), date(2026, 10, 6), {1, 2, 3, 4, 5, 6})
    rides: list[tuple[int, date]] = []
    ride_id = 1
    for day in period1:
        rides.append((ride_id, day))
        ride_id += 1
        rides.append((ride_id, day))
        ride_id += 1
    for day in (date(2026, 10, 12), date(2026, 10, 12), date(2026, 11, 15), date(2026, 11, 15)):
        rides.append((ride_id, day))
        ride_id += 1

    # Важно: свежий калькулятор для каждого способа, иначе кэш одного
    # повлияет на другой.
    batched = StrellaPeriodCalculator(rides=rides, anchor=None, initial_count=3)
    batch_states = batched.recalculate()

    single = StrellaPeriodCalculator(rides=rides, anchor=None, initial_count=3)
    single_states = [(item_id, single.resolve(day, ride_id=item_id)) for item_id, day in rides]

    assert batch_states == single_states, "Кэш границ не меняет результат (ALG-02)"

def test_shuffled_input_gives_same_result() -> None:
    """Порядок передачи поездок не влияет: калькулятор сортирует сам (шаг 6)."""
    ordered = [
        (1, date(2026, 9, 7)),
        (2, date(2026, 9, 7)),
        (3, date(2026, 9, 14)),
        (4, date(2026, 12, 1)),
    ]
    straight = dict(StrellaPeriodCalculator(rides=ordered, anchor=None).recalculate())
    shuffled = dict(
        StrellaPeriodCalculator(rides=list(reversed(ordered)), anchor=None).recalculate()
    )
    assert straight == shuffled


def test_cache_grows_monotonically_over_long_history() -> None:
    """Длинная история: границы остаются корректными при многократных периодах."""
    rides = [
        (index, date(2026, 9, 7) + timedelta(days=index * 31))
        for index in range(1, 13)
    ]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    states = dict(calc.recalculate())

    # Каждая поездка отстоит на 31 день — каждая открывает свой период с номера 1.
    for ride_id, _ in rides:
        assert states[ride_id].ride_number == 1, f"Поездка {ride_id} открывает период"
    # И её границы — ровно 30 дней от её даты.
    for ride_id, day in rides:
        assert states[ride_id].period_start == day
        assert states[ride_id].period_end == day + timedelta(days=29)
    """Альтернатива строке 15.11: первая поездка 16.11 → период [16.11, 15.12]."""
    rides = [(1, date(2026, 10, 12)), (2, date(2026, 11, 16))]
    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    state = calc.resolve(date(2026, 11, 16), ride_id=2)
    assert state.period_start == date(2026, 11, 16)
    assert state.period_end == date(2026, 12, 15), "Границы задаёт первая поездка, не календарь"
    assert state.ride_number == 1


# ---------------------------------------------------------------------------
# Фабрика репозитория поездок (нужна в тестах выше и ниже).
# ---------------------------------------------------------------------------
@pytest.fixture
def ride_repo_factory():
    def build(db):
        return RideRepository(db)

    return build
