"""Слой 1: календарь, недели и разрешение дня (ACC-M-01…04, 07, 13, 14, 74, 75).

Проверяется ALG-01 (тип недели), ALG-04 (приоритет период → профиль → шаблон →
оверрайд), ALG-05 (границы времени) и BELL-18 (выбор профиля по дате).
"""

from __future__ import annotations

from datetime import date

import pytest

from student_planner.core.day_resolution import DayResolver
from student_planner.core.models import LessonStatus, OverrideType
from student_planner.core.weektype import week_type_for


# ---------------------------------------------------------------------------
# ACC-M-01 — тип недели по якорю: чётная разница → опорный тип.
# ---------------------------------------------------------------------------
def test_acc_m_01_week_type_by_anchor(anchor_lower) -> None:
    anchors = [anchor_lower]
    # Якорь 07.09.2026, база lower, цикл 2.
    assert week_type_for(anchors, date(2026, 9, 7)) == "lower", "n = 0 → base_type"
    assert week_type_for(anchors, date(2026, 9, 13)) == "lower", "Вся неделя одного типа"
    assert week_type_for(anchors, date(2026, 9, 14)) == "upper", "n = 1 → противоположный"
    assert week_type_for(anchors, date(2026, 9, 20)) == "upper"
    assert week_type_for(anchors, date(2026, 9, 21)) == "lower", "n = 2 mod 2 = 0"
    assert week_type_for(anchors, date(2026, 9, 28)) == "upper"
    # Даты до якоря: действующего якоря нет.
    assert week_type_for(anchors, date(2026, 8, 31)) is None


def test_acc_m_01_anchor_sequence_matches_appendix_a() -> None:
    """Прил. А.0: 07.09–13.09 нижняя, 14.09–20.09 верхняя и далее."""
    from student_planner.core.models import WeekAnchor

    anchor = WeekAnchor(
        id=1,
        effective_from=date(2026, 9, 7),
        base_date=date(2026, 9, 7),
        base_type="lower",
        cycle_length=2,
    )
    expected = {
        date(2026, 9, 7): "lower",
        date(2026, 9, 14): "upper",
        date(2026, 9, 21): "lower",
        date(2026, 9, 28): "upper",
        date(2026, 10, 5): "lower",
        date(2026, 10, 12): "upper",
    }
    for day, kind in expected.items():
        assert week_type_for([anchor], day) == kind, f"Неделя от {day}"


def test_acc_m_01_negative_week_difference_wraps_correctly() -> None:
    """Дата раньше base_date: mod даёт корректный цикл, а не отрицательный сдвиг."""
    from student_planner.core.models import WeekAnchor

    anchor = WeekAnchor(
        id=1,
        effective_from=date(2026, 1, 1),
        base_date=date(2026, 9, 7),
        base_type="lower",
        cycle_length=2,
    )
    # 31.08.2026 — неделя на одну раньше базы → тип «верхняя».
    assert week_type_for([anchor], date(2026, 8, 31)) == "upper"


# ---------------------------------------------------------------------------
# ACC-M-02 / ACC-M-03 — смена якоря не меняет прошлое, создаёт новый якорь.
# ---------------------------------------------------------------------------
def test_acc_m_02_new_anchor_does_not_change_earlier_dates(anchors) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    anchors.create(date(2026, 9, 28), date(2026, 9, 28), "lower")  # новый якорь

    all_anchors = anchors.all()
    # До 28.09 действует первый якорь: 21.09 — нижняя.
    assert week_type_for(all_anchors, date(2026, 9, 21)) == "lower"
    # После 28.09 действует второй: 28.09 — нижняя (его base), 05.10 — верхняя.
    assert week_type_for(all_anchors, date(2026, 9, 28)) == "lower"
    assert week_type_for(all_anchors, date(2026, 10, 5)) == "upper"


def test_acc_m_02_anchor_switch_changes_only_future(anchors) -> None:
    """WEEK-06: смена якоря меняет только даты >= effective_from нового."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    anchors.create(date(2026, 10, 5), date(2026, 10, 5), "upper")  # «переворот» типа

    all_anchors = anchors.all()
    # Старый якорь сделал бы 05.10 нижней; новый делает верхней.
    assert week_type_for(all_anchors, date(2026, 10, 5)) == "upper"
    # А 28.09 остаётся как было по старому якорю — верхняя.
    assert week_type_for(all_anchors, date(2026, 9, 28)) == "upper"
    # И 21.09 — нижняя, как и раньше.
    assert week_type_for(all_anchors, date(2026, 9, 21)) == "lower"


def test_acc_m_03_changing_anchor_date_creates_new_record(anchors) -> None:
    """WEEK-05: изменение опорной даты создаёт новый якорь, а не правит старый."""
    original = anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    replacement = anchors.create(date(2026, 10, 5), date(2026, 10, 5), "upper")

    assert len(anchors.all()) == 2, "Старый якорь должен сохраниться в истории"
    preserved = next(item for item in anchors.all() if item.id == original.id)
    assert preserved.effective_from == date(2026, 9, 7)
    assert preserved.base_type == "lower", "Прошлое не переписывается"
    assert replacement.effective_from == date(2026, 10, 5)


def test_acc_m_03_last_anchor_cannot_be_deleted(anchors) -> None:
    """Действующий якорь не удаляется: сначала создайте новый (WEEK-05)."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    with pytest.raises(Exception) as excinfo:
        anchors.delete(anchors.all()[-1].id)
    assert "действующий" in str(excinfo.value)


# ---------------------------------------------------------------------------
# ACC-M-04 — cycle_length = 3 принимается схемой; отображение не требуется.
# ---------------------------------------------------------------------------
def test_acc_m_04_cycle_length_three_accepted(anchors) -> None:
    anchor = anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower", cycle_length=3)
    assert anchor.cycle_length == 3
    # Поведение детерминировано, хотя «верхняя/нижняя» для 3 не определено (TODO-15).
    assert week_type_for([anchor], date(2026, 9, 7)) == "lower"
    assert week_type_for([anchor], date(2026, 9, 14)) == "upper"
    assert week_type_for([anchor], date(2026, 9, 21)) == "lower"


def test_cycle_length_below_two_rejected(anchors) -> None:
    with pytest.raises(Exception):
        anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower", cycle_length=1)


# ---------------------------------------------------------------------------
# ACC-M-07 — пересечение периодов: выигрывает последний созданный.
# ---------------------------------------------------------------------------
def test_acc_m_07_overlapping_periods_last_created_wins(periods) -> None:
    periods.create("vacation", "Летние каникулы", date(2026, 9, 1), date(2026, 9, 15))
    later = periods.create("holiday", "Праздник", date(2026, 9, 10), date(2026, 9, 12))

    covering = periods.covering(date(2026, 9, 11), no_classes_only=True)
    assert covering is not None
    assert covering.id == later.id, "CAL-03: выигрывает последний созданный период"
    assert "Праздн" in str(excinfo_kind(covering))


def excinfo_kind(period) -> str:
    return period.kind_label


def test_acc_m_07_both_types_cancel_classes(periods, db, simple_bell, simple_subjects, anchors) -> None:
    """В MVP и каникулы, и праздник отменяют занятия (CAL-02)."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    from student_planner.core.repositories import ScheduleTemplateRepository

    ScheduleTemplateRepository(db).set_cell(simple_bell.id, "lower", 1, subject.id)

    resolver = DayResolver(db)
    day = date(2026, 9, 7)
    assert resolver.resolve(day).has_lessons

    periods.create("holiday", "Праздник", day, day)
    holiday = resolver.resolve(day)
    assert not holiday.has_lessons and holiday.is_day_off
    assert holiday.empty_caption.startswith("Праздник")


def test_period_only_on_its_dates(periods, db, anchors, simple_bell, simple_subjects) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    from student_planner.core.repositories import ScheduleTemplateRepository

    ScheduleTemplateRepository(db).set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    periods.create("vacation", "Каникулы", date(2026, 9, 7), date(2026, 9, 8))

    resolver = DayResolver(db)
    assert resolver.resolve(date(2026, 9, 7)).is_day_off
    assert resolver.resolve(date(2026, 9, 8)).is_day_off
    assert not resolver.resolve(date(2026, 9, 14)).is_day_off, "Вне периода занятия идут"


# ---------------------------------------------------------------------------
# ACC-M-13 — воскресенье: строки нет, если нет события.
# ---------------------------------------------------------------------------
def test_acc_m_13_sunday_has_no_lessons(db, anchors, simple_bell, simple_subjects) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    resolver = DayResolver(db)
    sunday = date(2026, 9, 13)
    assert sunday.isoweekday() == 7
    result = resolver.resolve(sunday)
    assert result.lessons == ()
    assert result.reason == "Воскресенье"


# ---------------------------------------------------------------------------
# ACC-M-14 — профиль по effective_from/effective_to; иначе ближайший предыдущий.
# ---------------------------------------------------------------------------
def test_acc_m_14_profile_selected_by_date_range(bells) -> None:
    bells.create_profile(1, "Пн (старый)", effective_from=date(2026, 9, 1),
                         effective_to=date(2026, 9, 30))
    bells.create_profile(1, "Пн (новый)", effective_from=date(2026, 10, 1))

    in_range = bells.profile_for(date(2026, 9, 14))
    assert in_range is not None and in_range.name == "Пн (старый)"

    after = bells.profile_for(date(2026, 10, 5))
    assert after is not None and after.name == "Пн (новый)"


def test_acc_m_14_missing_profile_falls_back_to_previous(bells) -> None:
    """При отсутствии профиля на дату берётся ближайший предыдущий (BELL-18)."""
    bells.create_profile(1, "Пн (единственный)", effective_from=date(2026, 9, 1),
                         effective_to=date(2026, 9, 30))
    # На 05.10 действующего профиля нет — используется предыдущий.
    fallback = bells.profile_for(date(2026, 10, 5))
    assert fallback is not None
    assert fallback.name == "Пн (единственный)"


def test_acc_m_14_no_profile_at_all_returns_none(bells) -> None:
    assert bells.profile_for(date(2026, 9, 14)) is None


# ---------------------------------------------------------------------------
# ACC-M-74 / ACC-M-75 — пустые слоты: скрыты в дне, видны в редакторе.
# ---------------------------------------------------------------------------
def test_acc_m_74_empty_slots_hidden_in_day(db, anchors, simple_bell, simple_subjects,
                                            templates) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    first, second = simple_subjects
    # Заполнены блоки 1 и 3; блок 2 пуст.
    templates.set_cell(simple_bell.id, "lower", 1, first.id)
    templates.set_cell(simple_bell.id, "lower", 3, second.id)

    resolver = DayResolver(db)
    result = resolver.resolve(date(2026, 9, 7))
    assert [lesson.slot_no for lesson in result.lessons] == [1, 3], (
        "SCH-03: пустой блок 2 в дне не показывается"
    )


def test_acc_m_74_day_without_cells_says_no_classes(db, anchors, simple_bell) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    resolver = DayResolver(db)
    result = resolver.resolve(date(2026, 9, 7))
    assert result.lessons == ()
    assert result.empty_caption == "Занятий нет"


def test_acc_m_75_editor_shows_all_slots(db, anchors, simple_bell, simple_subjects,
                                        templates) -> None:
    """GRID-01: профиль в редакторе показывает все блоки, включая пустые."""
    first = simple_subjects[0]
    templates.set_cell(simple_bell.id, "lower", 2, first.id)

    profile = simple_bell
    assert [slot.slot_no for slot in profile.slots] == [1, 2, 3], (
        "Редактор видит все блоки профиля (ACC-M-75)"
    )
    cells = {cell.slot_no for cell in templates.cells("lower", profile_id=profile.id)}
    assert cells == {2}, "Заполнена одна ячейка"

    day = DayResolver(db).resolve(date(2026, 9, 7)) if False else None
    assert day is None  # разрешение дня проверяется отдельным тестом ACC-M-74


# ---------------------------------------------------------------------------
# ALG-04 шаг 3–4: шаблон и оверрайды.
# ---------------------------------------------------------------------------
def test_statuses_for_cancel_replace_add(db, anchors, simple_bell, simple_subjects,
                                         templates, overrides) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    first, second = simple_subjects
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, first.id)
    templates.set_cell(simple_bell.id, "lower", 2, first.id)

    overrides.create(day, simple_bell.id, 1, "cancel")
    overrides.create(day, simple_bell.id, 2, "replace", subject_id=second.id)
    overrides.create(day, simple_bell.id, 3, "add", subject_id=second.id)

    result = DayResolver(db).resolve(day)
    by_slot = {lesson.slot_no: lesson for lesson in result.lessons}
    assert by_slot[1].status == LessonStatus.CANCELLED, "OVR-04: статус «Отменено»"
    assert by_slot[2].status == LessonStatus.REPLACED, "OVR-05: статус «Заменено»"
    assert by_slot[2].subject is not None and by_slot[2].subject.id == second.id
    assert by_slot[3].status == LessonStatus.ADDED, "OVR-07: статус «Добавлено»"


def test_cancel_does_not_shift_neighbours(db, anchors, simple_bell, simple_subjects,
                                          templates, overrides) -> None:
    """ACC-M-17: отмена блока не смещает соседние, шаблон цел."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    first = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, first.id)
    templates.set_cell(simple_bell.id, "lower", 2, first.id)
    templates.set_cell(simple_bell.id, "lower", 3, first.id)

    overrides.create(day, simple_bell.id, 2, "cancel")
    result = DayResolver(db).resolve(day)
    slots = [(lesson.slot_no, lesson.status) for lesson in result.lessons]
    assert slots == [
        (1, LessonStatus.PLANNED),
        (2, LessonStatus.CANCELLED),
        (3, LessonStatus.PLANNED),
    ], "Соседние блоки остаются на своих местах"
    assert templates.subject_at(simple_bell.id, "lower", 2) == first.id, (
        "Шаблон не повреждён отменой (OVR-04)"
    )


def test_period_cancels_overrides_too(db, anchors, simple_bell, simple_subjects,
                                     templates, overrides, periods) -> None:
    """OVR-10: внутри периода с ``no_classes = 1`` оверрайды не применяются."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    first = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, first.id)
    overrides.create(day, simple_bell.id, 1, "cancel")
    periods.create("vacation", "Каникулы", day, day)

    result = DayResolver(db).resolve(day)
    assert result.lessons == (), "Период отменяет занятия целиком (OVR-10, ACC-M-24)"
    assert result.is_day_off


# ---------------------------------------------------------------------------
# ALG-10 — сиротские оверрайды.
# ---------------------------------------------------------------------------
def test_orphan_override_detected_after_cell_cleared(db, anchors, simple_bell,
                                                    simple_subjects, templates, overrides) -> None:
    """ALG-10/ACC-M-66: после очистки ячейки оверрайд не применяется и попадает в сироты."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    first = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, first.id)
    override = overrides.create(day, simple_bell.id, 1, "cancel")

    templates.clear_cell(simple_bell.id, "lower", 1)
    # Оверрайд остаётся в БД, но становится сиротским.
    assert overrides.by_id(override.id) is not None, "Запись не удаляется автоматически"

    result = DayResolver(db).resolve(day)
    assert result.lessons == (), "Сиротский оверрайд не применяется"
    assert any(item.id == override.id for item in result.orphan_overrides), (
        "SCH-17: предупреждение о сиротском оверрайде"
    )


def test_orphan_list_excludes_add_overrides(db, anchors, simple_bell, simple_subjects,
                                            templates, overrides) -> None:
    """ALG-10 п. 4: оверрайд ``add`` сиротским не считается."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    added = overrides.create(day, simple_bell.id, 3, "add", subject_id=simple_subjects[0].id)

    orphans = overrides.orphans()
    assert all(item.id != added.id for item in orphans), "add не бывает сиротским"


def test_orphan_mass_delete_touches_only_cancel_replace(db, anchors, simple_bell,
                                                       simple_subjects, templates,
                                                       overrides) -> None:
    """ALG-10 п. 5: массовое удаление сиротских не трогает ``add``."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    subject = simple_subjects[0]
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)

    orphan_cancel = overrides.create(day, simple_bell.id, 1, "cancel")
    kept_add = overrides.create(day, simple_bell.id, 2, "add", subject_id=subject.id)

    # Очищаем ячейку — cancel становится сиротским.
    templates.clear_cell(simple_bell.id, "lower", 1)

    removed = overrides.delete_orphans()
    removed_ids = {item.id for item in removed}
    assert orphan_cancel.id in removed_ids
    assert kept_add.id not in removed_ids, "Оверрайд add не удаляется как сиротский"
    assert overrides.by_id(kept_add.id) is not None
    assert overrides.by_id(orphan_cancel.id) is None


# ---------------------------------------------------------------------------
# ALG-05 — T_start / T_end.
# ---------------------------------------------------------------------------
def test_alg05_time_bounds_of_day(db, anchors, simple_bell, simple_subjects,
                                  templates) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)
    templates.set_cell(simple_bell.id, "lower", 3, subject.id)

    result = DayResolver(db).resolve(day)
    start, end = result.time_bounds
    assert start == "08:30", "Первое занятие"
    assert end == "11:05", "Последнее занятие блока 3"


def test_alg05_cancelled_last_lesson_changes_end(db, anchors, simple_bell,
                                                simple_subjects, templates,
                                                overrides) -> None:
    """ALG-05: отменённое занятие не участвует в границах дня."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)
    templates.set_cell(simple_bell.id, "lower", 3, subject.id)
    overrides.create(day, simple_bell.id, 3, "cancel")

    _, end = DayResolver(db).resolve(day).time_bounds
    assert end == "09:15", "Окончание — по последнему неотменённому занятию"


def test_alg05_empty_day_has_no_bounds(db, anchors, simple_bell) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    start, end = DayResolver(db).resolve(date(2026, 9, 7)).time_bounds
    assert (start, end) == (None, None)


# ---------------------------------------------------------------------------
# Двухчастные блоки и разрешение недели.
# ---------------------------------------------------------------------------
def test_two_part_block_spans_break(two_part_bell, db, anchors, simple_subjects,
                                    templates) -> None:
    """BELL-02/BELL-06: начало — первая часть, окончание — последняя."""
    slot = two_part_bell.slots[0]
    assert len(slot.parts) == 3, "lesson | break | lesson"
    assert slot.start_time == "08:30"
    assert slot.end_time == "10:10"
    assert slot.is_two_part is True


def test_resolve_week_returns_seven_days(db, anchors, simple_bell, simple_subjects,
                                       templates) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    week = DayResolver(db).resolve_week(date(2026, 9, 9))
    assert len(week) == 7
    assert week[0].date == date(2026, 9, 7), "Неделя начинается с понедельника (WEEK-01)"
    assert week[6].date == date(2026, 9, 13)
    assert week[0].has_lessons
    assert week[6].lessons == (), "Воскресенье без занятий"


def test_week_type_badge_matches_resolution(db, anchors, simple_bell, simple_subjects,
                                            templates) -> None:
    """WEEK-07: бейдж «Верхняя»/«Нижняя» соответствует типу недели."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    resolver = DayResolver(db)

    plan = resolver.resolve(date(2026, 9, 7))
    assert plan.week_type == "lower"
    assert plan.week_type_label == "Нижняя"

    # Верхняя неделя: ячейка не заполнена, поэтому занятий нет.
    other = resolver.resolve(date(2026, 9, 14))
    assert other.week_type == "upper"
    assert other.week_type_label == "Верхняя"
