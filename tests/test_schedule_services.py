"""Этап 2: сервисы расписания (сетка, оверрайды, календарь, домашние задания).

Проверяются правила, которым нужно несколько репозиториев сразу: GRID-01…GRID-11,
OVR-01…OVR-12, CAL-01…CAL-09, HW-01…HW-16. Механика слоя 1 на синтетических
фикстурах (TEST-01); интерфейса здесь нет (PLAN-05).
"""

from __future__ import annotations

from datetime import date

import pytest

from student_planner.core.errors import NotFoundError, RuleViolationError, ValidationError
from student_planner.core.models import HomeworkStatus, OverrideType
from student_planner.core.schedule_service import (
    CalendarService,
    GridService,
    HomeworkService,
    OverrideService,
)


@pytest.fixture
def grid(db):
    return GridService(db)


@pytest.fixture
def override_service(db):
    return OverrideService(db)


@pytest.fixture
def calendar(db):
    return CalendarService(db)


@pytest.fixture
def homework(db):
    return HomeworkService(db)


@pytest.fixture
def monday_lower(db, anchors, simple_bell, simple_subjects, templates):
    """Понедельник 07.09.2026 — нижняя неделя, три блока, заполнен блок 1."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    return date(2026, 9, 7)


# ===========================================================================
# GRID-01 / GRID-03 / GRID-07 — состав сетки
# ===========================================================================
def test_grid_shows_all_slots_including_empty(grid, simple_bell) -> None:
    """GRID-01: видны все слоты профиля, включая пустые."""
    view = grid.view("lower")
    monday = next(column for column in view.columns if column.weekday == 1)
    assert monday.has_profile
    assert len(monday.slots) == 3, "simple_bell содержит три блока"
    assert all(slot.is_empty for slot in monday.slots), "Ни одна ячейка не заполнена"


def test_grid_shows_six_weekday_columns(grid, simple_bell) -> None:
    """GRID-01: Пн–Сб — шесть колонок."""
    view = grid.view("lower")
    assert [column.weekday for column in view.columns] == [1, 2, 3, 4, 5, 6]


def test_grid_week_type_switch_changes_content(grid, simple_bell, simple_subjects,
                                               templates) -> None:
    """GRID-03: переключатель типа недели показывает другой набор ячеек."""
    templates.set_cell(simple_bell.id, "upper", 1, simple_subjects[0].id)
    upper = grid.view("upper")
    lower = grid.view("lower")

    assert upper.filled_count == 1
    assert lower.filled_count == 0, "Типы недель независимы"


def test_grid_rejects_unknown_week_type(grid) -> None:
    with pytest.raises(ValidationError):
        grid.view("middle")


def test_grid_slot_shows_subject_teacher_room(grid, simple_bell, simple_subjects,
                                              templates) -> None:
    """GRID-07: в ячейке название, преподаватель и кабинет."""
    subject = simple_subjects[0]
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)

    view = grid.view("lower")
    slot = view.columns[0].slots[0]
    assert slot.subject_name == "Алгебра"
    assert slot.teacher == "Иванова"
    assert slot.room == "101"
    assert "Алгебра" in slot.caption and "Иванова" in slot.caption


def test_grid_empty_cell_has_no_caption(grid, simple_bell) -> None:
    """GRID-07: при отсутствии предмета ячейка пуста."""
    view = grid.view("lower")
    slot = view.columns[0].slots[0]
    assert slot.caption == ""
    assert slot.is_empty


def test_grid_total_filled_count(grid, simple_bell, simple_subjects, templates) -> None:
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    templates.set_cell(simple_bell.id, "lower", 2, simple_subjects[1].id)
    assert grid.view("lower").filled_count == 2


# ===========================================================================
# GRID-02 — сохранение ячейки
# ===========================================================================
def test_grid_set_cell_saves_immediately(grid, simple_bell, simple_subjects) -> None:
    """GRID-02: выбор предмета сохраняет ячейку без общего «Сохранить»."""
    grid.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    view = grid.view("lower")
    assert view.columns[0].slots[0].subject_id == simple_subjects[0].id


def test_grid_set_cell_updates_in_place(db, grid, simple_bell, simple_subjects) -> None:
    """ACC-M-60: повторный выбор обновляет ту же строку, дубля нет."""
    grid.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    grid.set_cell(simple_bell.id, "lower", 1, simple_subjects[1].id)

    rows = db.fetchall(
        "SELECT * FROM schedule_templates WHERE profile_id = ? AND week_type = 'lower' "
        "AND slot_no = 1",
        (simple_bell.id,),
    )
    assert len(rows) == 1
    assert int(rows[0]["subject_id"]) == simple_subjects[1].id


def test_grid_set_cell_to_none_clears(grid, simple_bell, simple_subjects) -> None:
    """GRID-02: пустое значение очищает ячейку."""
    grid.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    grid.set_cell(simple_bell.id, "lower", 1, None)
    assert grid.view("lower").columns[0].slots[0].is_empty


def test_grid_set_cell_rejects_inactive_subject(grid, simple_bell, simple_subjects,
                                                subjects) -> None:
    """SUBJ-03: отключённый предмет не выбирается в сетке."""
    subject = simple_subjects[0]
    subjects.set_active(subject.id, False)
    with pytest.raises(ValidationError) as excinfo:
        grid.set_cell(simple_bell.id, "lower", 1, subject.id)
    assert "отключ" in str(excinfo.value).lower()


def test_grid_set_cell_rejects_unknown_subject(grid, simple_bell) -> None:
    with pytest.raises(NotFoundError):
        grid.set_cell(simple_bell.id, "lower", 1, 9999)


def test_grid_set_cell_rejects_unknown_slot(grid, simple_bell, simple_subjects) -> None:
    """GRID-05: слоты не создаются редактором."""
    with pytest.raises(NotFoundError) as excinfo:
        grid.set_cell(simple_bell.id, "lower", 99, simple_subjects[0].id)
    assert "слот" in str(excinfo.value).lower()


# ===========================================================================
# GRID-05 / DATA-20 — очистка ячейки
# ===========================================================================
def test_grid_clear_cell_keeps_slot_and_overrides(db, grid, monday_lower,
                                                 simple_bell, simple_subjects,
                                                 overrides) -> None:
    """GRID-05/DATA-20: удаляется только строка шаблона."""
    override = overrides.create(monday_lower, simple_bell.id, 1, "cancel")
    grid.clear_cell(simple_bell.id, "lower", 1)

    assert db.fetchone(
        "SELECT 1 FROM schedule_templates WHERE profile_id = ? AND week_type = 'lower' "
        "AND slot_no = 1",
        (simple_bell.id,),
    ) is None
    assert overrides.by_id(override.id) is not None, "Оверрайд остался сиротским"


def test_grid_clear_cell_keeps_bell_parts(db, grid, simple_bell, simple_subjects) -> None:
    parts_before = db.scalar("SELECT COUNT(*) FROM bell_slot_parts")
    grid.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    grid.clear_cell(simple_bell.id, "lower", 1)
    assert db.scalar("SELECT COUNT(*) FROM bell_slot_parts") == parts_before


# ===========================================================================
# SUBJ-05 / GRID-02 — новый предмет из ячейки
# ===========================================================================
def test_grid_create_subject_from_cell(grid, simple_bell, subjects) -> None:
    """SUBJ-05: предмет создаётся и сразу подставляется в клетку."""
    created = grid.create_subject_for_cell(
        simple_bell.id, "lower", 1, name="Новый предмет", code="NEW", teacher="Сидоров",
    )
    assert created.id in [item.id for item in subjects.all()]
    assert grid.view("lower").columns[0].slots[0].subject_id == created.id


def test_grid_autocomplete_by_name_teacher_code(grid, simple_subjects) -> None:
    """GRID-02: автодополнение по названию, преподавателю и коду."""
    subject = simple_subjects[0]
    for query in ("Алг", "Иван", "ALG"):
        found = grid.search_subjects(query)
        assert subject.id in [item.id for item in found], f"Поиск по «{query}»"


def test_grid_autocomplete_empty_query_returns_all(grid, simple_subjects) -> None:
    assert len(grid.search_subjects("")) == len(grid.subjects_for_cell())


def test_grid_subject_list_excludes_inactive(grid, simple_subjects, subjects) -> None:
    subjects.set_active(simple_subjects[1].id, False)
    active_ids = [item.id for item in grid.subjects_for_cell()]
    assert simple_subjects[1].id not in active_ids


# ===========================================================================
# GRID-06 / ALG-10 — сиротские оверрайды
# ===========================================================================
def test_grid_reports_orphans_after_clear(db, grid, monday_lower, simple_bell) -> None:
    """GRID-06: после очистки ячейки сиротский оверрайд виден предупреждением."""
    OverrideService(db).cancel(monday_lower, simple_bell.id, 1)
    grid.clear_cell(simple_bell.id, "lower", 1)

    view = grid.view("lower")
    assert view.orphan_warnings, "Предупреждение о сиротском изменении"
    assert "блок 1" in view.orphan_warnings[0]


def test_grid_no_orphan_warnings_on_clean_grid(grid, simple_bell) -> None:
    assert grid.view("lower").orphan_warnings == []


# ===========================================================================
# GRID-11 / ACC-M-104 — вернуть стартовый набор недели
# ===========================================================================
def test_grid_restore_seed_week(db) -> None:
    """GRID-11: восстанавливает 16 строк выбранного типа недели."""
    from student_planner.core.seeding import Seeder

    Seeder(db).seed_all()
    service = GridService(db)

    restored = service.restore_seed_week("upper")
    assert restored == 16, "А.3: 16 ячеек верхней недели"
    assert service.view("upper").filled_count == 16


def test_grid_restore_seed_week_is_idempotent(db) -> None:
    """ACC-M-104: повторный вызов ничего не меняет."""
    from student_planner.core.seeding import Seeder

    Seeder(db).seed_all()
    service = GridService(db)
    service.restore_seed_week("lower")
    before = db.scalar("SELECT COUNT(*) FROM schedule_templates WHERE week_type = 'lower'")
    service.restore_seed_week("lower")
    after = db.scalar("SELECT COUNT(*) FROM schedule_templates WHERE week_type = 'lower'")
    assert before == after == 16


def test_grid_restore_seed_week_keeps_other_week_and_overrides(db) -> None:
    """GRID-11: второй тип недели и оверрайды не затрагиваются."""
    from student_planner.core.seeding import Seeder

    Seeder(db).seed_all()
    service = GridService(db)

    upper_before = db.scalar("SELECT COUNT(*) FROM schedule_templates WHERE week_type = 'upper'")
    bells_before = db.scalar("SELECT COUNT(*) FROM bell_slots")

    # Заменяем нижнюю неделю и добавляем оверрайд.
    db.execute("DELETE FROM schedule_templates WHERE week_type = 'lower'")
    profile = db.fetchone("SELECT id FROM bell_profiles WHERE weekday = 1")
    subjects = db.fetchall("SELECT id FROM subjects LIMIT 1")
    override = OverrideService(db).cancel(
        date(2026, 9, 7), int(profile["id"]), 1
    )

    service.restore_seed_week("lower")

    assert db.scalar("SELECT COUNT(*) FROM schedule_templates WHERE week_type = 'upper'") == upper_before
    assert db.scalar("SELECT COUNT(*) FROM bell_slots") == bells_before
    assert db.fetchone("SELECT id FROM schedule_overrides WHERE id = ?", (override.id,)) is not None


# ===========================================================================
# OVR-01 / OVR-04 — отмена
# ===========================================================================
def test_override_cancel_marks_block(db, override_service, monday_lower,
                                     simple_bell) -> None:
    """OVR-04: блок помечается отменённым, шаблон не меняется."""
    created = override_service.cancel(monday_lower, simple_bell.id, 1)
    assert created.override_type == OverrideType.CANCEL
    assert created.subject_id is not None, "Предмет берётся из шаблона"

    template_cell = db.fetchone(
        "SELECT subject_id FROM schedule_templates WHERE profile_id = ? AND week_type = 'lower' "
        "AND slot_no = 1",
        (simple_bell.id,),
    )
    assert template_cell is not None, "Шаблон не изменён (OVR-01)"


def test_override_cancel_does_not_shift_other_slots(override_service, monday_lower,
                                                    simple_bell, simple_subjects,
                                                    templates) -> None:
    """OVR-04: остальные блоки не смещаются."""
    templates.set_cell(simple_bell.id, "lower", 2, simple_subjects[1].id)
    override_service.cancel(monday_lower, simple_bell.id, 1)
    assert templates.subject_at(simple_bell.id, "lower", 2) == simple_subjects[1].id


def test_override_cancel_unknown_slot_allowed(db, override_service, monday_lower,
                                              simple_bell) -> None:
    """Cancel на пустом слоте допустим: предмет просто не подставляется."""
    created = override_service.cancel(monday_lower, simple_bell.id, 3)
    assert created.subject_id is None


# ===========================================================================
# OVR-05 — замена
# ===========================================================================
def test_override_replace_stores_details(override_service, monday_lower, simple_bell,
                                         simple_subjects) -> None:
    """OVR-05: предмет, преподаватель, кабинет, комментарий."""
    created = override_service.replace(
        monday_lower, simple_bell.id, 1,
        subject_id=simple_subjects[1].id,
        teacher="Петров П. П.", room="Каб. 202", comment="Болезнь преподавателя",
    )
    assert created.override_type == OverrideType.REPLACE
    assert created.subject_id == simple_subjects[1].id
    assert created.teacher == "Петров П. П."
    assert created.room == "Каб. 202"
    assert created.comment == "Болезнь преподавателя"


def test_override_replace_custom_time(override_service, monday_lower, simple_bell,
                                      simple_subjects) -> None:
    """OVR-05: время по умолчанию сохраняется, может быть задано своё."""
    created = override_service.replace(
        monday_lower, simple_bell.id, 1, subject_id=simple_subjects[1].id,
        custom_start="09:00", custom_end="10:30",
    )
    assert created.custom_start == "09:00"
    assert created.custom_end == "10:30"


def test_override_replace_requires_subject(override_service, monday_lower,
                                           simple_bell) -> None:
    """OVR-05: замена без предмета невозможна."""
    with pytest.raises((ValidationError, TypeError)):
        override_service.replace(monday_lower, simple_bell.id, 1, subject_id=None)


# ===========================================================================
# OVR-07 / OVR-08 — добавление и конфликты
# ===========================================================================
def test_override_add_into_free_slot(override_service, monday_lower, simple_bell,
                                     simple_subjects) -> None:
    """OVR-07: добавление в свободный слот."""
    created = override_service.add(
        monday_lower, simple_bell.id, 3, subject_id=simple_subjects[1].id,
        teacher="Петров", room="202",
    )
    assert created.override_type == OverrideType.ADD
    assert created.subject_id == simple_subjects[1].id


def test_override_add_into_occupied_slot_rejected(override_service, monday_lower,
                                                  simple_bell, simple_subjects) -> None:
    """OVR-08: ``add`` в занятый слот запрещён."""
    with pytest.raises(RuleViolationError):
        override_service.add(monday_lower, simple_bell.id, 1, subject_id=simple_subjects[1].id)


def test_override_second_cancel_same_slot_rejected(override_service, monday_lower,
                                                   simple_bell, simple_subjects) -> None:
    """OVR-08: не более одного ``cancel``/``replace`` на слот."""
    override_service.cancel(monday_lower, simple_bell.id, 1)
    with pytest.raises(RuleViolationError):
        override_service.replace(
            monday_lower, simple_bell.id, 1, subject_id=simple_subjects[1].id
        )


def test_override_cancel_after_replace_rejected(override_service, monday_lower,
                                                simple_bell, simple_subjects) -> None:
    override_service.replace(
        monday_lower, simple_bell.id, 1, subject_id=simple_subjects[1].id
    )
    with pytest.raises(RuleViolationError):
        override_service.cancel(monday_lower, simple_bell.id, 1)


# ===========================================================================
# OVR-10 — период отменяет оверрайды
# ===========================================================================
def test_override_not_applied_inside_no_classes_period(db, override_service,
                                                       monday_lower, simple_bell,
                                                       periods) -> None:
    """OVR-10: внутри периода ``no_classes = 1`` оверрайды не применяются."""
    override_service.cancel(monday_lower, simple_bell.id, 1)
    periods.create("vacation", "Каникулы", monday_lower, monday_lower)

    assert override_service.applied_for_date(monday_lower) == []
    assert len(override_service.for_date(monday_lower)) == 1, "Запись сохранена в БД"


def test_override_applied_without_period(override_service, monday_lower,
                                         simple_bell) -> None:
    override_service.cancel(monday_lower, simple_bell.id, 1)
    assert len(override_service.applied_for_date(monday_lower)) == 1


# ===========================================================================
# OVR-12 / ALG-10 — оверрайды переживают правку шаблона
# ===========================================================================
def test_override_survives_template_edit(override_service, monday_lower,
                                         simple_bell, simple_subjects,
                                         templates) -> None:
    """OVR-12: изменение ячейки сетки не удаляет оверрайды."""
    created = override_service.cancel(monday_lower, simple_bell.id, 1)
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[1].id)
    assert override_service.for_date(monday_lower)[0].id == created.id


def test_override_orphan_detected_after_clear(override_service, monday_lower,
                                              simple_bell, templates) -> None:
    """ALG-10: после очистки ячейки ``cancel`` становится сиротским."""
    override_service.cancel(monday_lower, simple_bell.id, 1)
    templates.clear_cell(simple_bell.id, "lower", 1)

    found = override_service.orphans()
    assert len(found) == 1
    assert override_service.warnings_for_date(monday_lower)


def test_override_add_never_orphan(override_service, monday_lower, simple_bell,
                                   simple_subjects) -> None:
    """ALG-10 п. 2: ``add`` не бывает сиротским."""
    override_service.add(monday_lower, simple_bell.id, 3, subject_id=simple_subjects[0].id)
    assert override_service.orphans() == []


def test_override_delete_orphans(override_service, monday_lower, simple_bell,
                                 templates) -> None:
    """ALG-10 п. 5: массовое удаление сиротских одной кнопкой."""
    override_service.cancel(monday_lower, simple_bell.id, 1)
    templates.clear_cell(simple_bell.id, "lower", 1)

    removed = override_service.delete_orphans()
    assert len(removed) == 1
    assert override_service.for_date(monday_lower) == []


# ===========================================================================
# SCH-09 — сброс изменений даты
# ===========================================================================
def test_override_reset_day(override_service, monday_lower, simple_bell,
                            simple_subjects) -> None:
    override_service.cancel(monday_lower, simple_bell.id, 1)
    override_service.add(monday_lower, simple_bell.id, 3, subject_id=simple_subjects[0].id)

    result = override_service.reset_day(monday_lower)
    assert result.removed == 2
    assert override_service.for_date(monday_lower) == []


def test_override_reset_day_dry_run(override_service, monday_lower, simple_bell) -> None:
    override_service.cancel(monday_lower, simple_bell.id, 1)
    result = override_service.reset_day(monday_lower, dry_run=True)
    assert result.removed == 1
    assert len(override_service.for_date(monday_lower)) == 1, "Ничего не удалено"


def test_override_reset_only_that_date(override_service, anchors, simple_bell,
                                       simple_subjects) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    first, second = date(2026, 9, 7), date(2026, 9, 14)
    override_service.cancel(first, simple_bell.id, 1)
    override_service.cancel(second, simple_bell.id, 2)

    override_service.reset_day(first)
    assert override_service.for_date(first) == []
    assert len(override_service.for_date(second)) == 1, "Другая дата не тронута"


def test_override_can_cancel_requires_template(override_service, monday_lower,
                                               simple_bell) -> None:
    assert override_service.can_cancel(monday_lower, simple_bell.id, 1) is True
    assert override_service.can_cancel(monday_lower, simple_bell.id, 3) is False


# ===========================================================================
# CAL-01 / CAL-02 / CAL-04 — календарь
# ===========================================================================
def test_calendar_create_vacation(calendar) -> None:
    entry = calendar.create(
        "vacation", "Осенние каникулы", date(2026, 10, 26), date(2026, 11, 1),
        comment="По приказу колледжа",
    )
    assert entry.kind == "vacation"
    assert entry.kind_caption == "Каникулы"
    assert entry.no_classes is True
    assert entry.days == 7
    assert entry.bounds_caption == "26.10.2026 — 01.11.2026"


def test_calendar_create_holiday(calendar) -> None:
    entry = calendar.create("holiday", "День народного единства", date(2026, 11, 4),
                            date(2026, 11, 4))
    assert entry.kind_caption == "Праздник"
    assert entry.days == 1


def test_calendar_rejects_v11_kind(calendar) -> None:
    """CAL-02: практика и сессия — v1.1, в MVP отклоняются."""
    with pytest.raises(ValidationError) as excinfo:
        calendar.create("exam_session", "Сессия", date(2027, 1, 10), date(2027, 1, 25))
    assert "MVP" in str(excinfo.value)


def test_calendar_edit_period(calendar) -> None:
    entry = calendar.create("vacation", "Каникулы", date(2026, 10, 26), date(2026, 11, 1))
    updated = calendar.update(entry.period_id, end_date=date(2026, 11, 3))
    assert updated.end_date == date(2026, 11, 3)
    assert updated.days == 9


def test_calendar_delete_period(calendar) -> None:
    entry = calendar.create("holiday", "Праздник", date(2026, 11, 4), date(2026, 11, 4))
    calendar.delete(entry.period_id)
    with pytest.raises(NotFoundError):
        calendar.entry(entry.period_id)


def test_calendar_period_at_date(calendar) -> None:
    """CAL-09: страница расписания показывает название периода вместо сетки."""
    calendar.create("vacation", "Осенние каникулы", date(2026, 10, 26), date(2026, 11, 1))
    found = calendar.period_at(date(2026, 10, 28))
    assert found is not None and found.title == "Осенние каникулы"
    assert calendar.is_day_off(date(2026, 10, 28)) is True
    assert calendar.is_day_off(date(2026, 10, 20)) is False


def test_calendar_periods_may_overlap(db, calendar) -> None:
    """CAL-03: периоды могут перекрываться."""
    calendar.create("vacation", "Каникулы", date(2026, 10, 26), date(2026, 11, 1))
    calendar.create("holiday", "Праздник", date(2026, 10, 30), date(2026, 10, 30))
    assert len(calendar.all()) == 2


def test_calendar_month_listing(calendar) -> None:
    calendar.create("holiday", "Ноябрь", date(2026, 11, 4), date(2026, 11, 4))
    calendar.create("vacation", "Декабрь", date(2026, 12, 28), date(2026, 12, 31))

    november = calendar.for_month(2026, 11)
    assert [entry.title for entry in november] == ["Ноябрь"]


# ===========================================================================
# HW-01…HW-16 — домашние задания
# ===========================================================================
def test_homework_create_three_fields(homework, simple_subjects) -> None:
    """HW-07: быстрый ввод — предмет, дата, описание."""
    created = homework.create(simple_subjects[0].id, date(2026, 9, 14), "Упражнение 5")
    assert created.status == HomeworkStatus.ACTIVE
    assert created.description == "Упражнение 5"
    assert created.completed_at is None


def test_homework_statuses_are_two(homework, simple_subjects) -> None:
    """HW-03: только ``active`` и ``done``."""
    assert HomeworkStatus.ALL == ("active", "done")


def test_homework_relevant_until_end_of_day(homework, simple_subjects) -> None:
    """HW-02: задание актуально до конца даты сдачи включительно."""
    created = homework.create(simple_subjects[0].id, date(2026, 10, 20))
    assert created.is_overdue(date(2026, 10, 20)) is False, "В день сдачи не просрочено"
    assert created.is_overdue(date(2026, 10, 21)) is True


def test_homework_toggle_done_and_back(homework, simple_subjects) -> None:
    """HW-15: отметка одним действием, обратная возвращает ``active``."""
    created = homework.create(simple_subjects[0].id, date(2026, 9, 14), "Задание")
    done = homework.toggle(created.id)
    assert done.status == HomeworkStatus.DONE
    assert done.completed_at is not None

    back = homework.toggle(created.id)
    assert back.status == HomeworkStatus.ACTIVE
    assert back.completed_at is None


def test_homework_overdue_does_not_change_status(homework, simple_subjects) -> None:
    """HW-08: просрочка вычисляемая, статус не меняется."""
    created = homework.create(simple_subjects[0].id, date(2026, 10, 1))
    rows = homework.rows(only_overdue=True, today=date(2026, 10, 20))
    assert len(rows) == 1
    assert rows[0].is_overdue is True
    assert created.is_active


def test_homework_done_is_not_overdue(homework, simple_subjects) -> None:
    """HW-08: просроченным считается только активное задание."""
    created = homework.create(simple_subjects[0].id, date(2026, 10, 1))
    homework.set_done(created.id)
    assert homework.rows(only_overdue=True, today=date(2026, 10, 20)) == []


def test_homework_widget_today_and_tomorrow(homework, simple_subjects) -> None:
    """HW-05: виджет показывает задания на сегодня и завтра."""
    today = date(2026, 10, 20)
    homework.create(simple_subjects[0].id, today, "Сегодня")
    homework.create(simple_subjects[0].id, date(2026, 10, 21), "Завтра")
    homework.create(simple_subjects[0].id, date(2026, 10, 25), "Позже")

    items = homework.upcoming(today=today)
    assert [item.homework.description for item in items] == ["Сегодня", "Завтра"]


def test_homework_widget_empty_caption(homework, simple_subjects) -> None:
    """HW-05/HW-14: пустой список — «Заданий нет»."""
    assert homework.upcoming(today=date(2026, 10, 20)) == []
    assert homework.upcoming_empty_caption == "Заданий нет"


def test_homework_badge_by_subject_and_date(homework, simple_subjects) -> None:
    """HW-06: правило сопоставления — по ``subject_id`` и дате."""
    first, second = simple_subjects
    day = date(2026, 9, 14)
    homework.create(first.id, day, "Задание 1")
    homework.create(first.id, day, "Задание 2")
    homework.create(second.id, day, "Другое")

    assert homework.badge(first.id, day) == 2, "При нескольких заданиях — счётчик"
    assert homework.badge(second.id, day) == 1
    assert homework.badge(first.id, date(2026, 9, 15)) == 0


def test_homework_badge_ignores_done(homework, simple_subjects) -> None:
    first = simple_subjects[0]
    day = date(2026, 9, 14)
    created = homework.create(first.id, day, "Задание")
    assert homework.badge(first.id, day) == 1
    homework.set_done(created.id)
    assert homework.badge(first.id, day) == 0, "Выполненное задание бейджа не даёт"


def test_homework_groups_by_due_date(homework, simple_subjects) -> None:
    """HW-12: группировка по дате сдачи, ближайшие сверху."""
    today = date(2026, 10, 20)
    subject = simple_subjects[0]
    homework.create(subject.id, date(2026, 10, 22), "Послезавтра")
    homework.create(subject.id, today, "Сегодня")
    homework.create(subject.id, date(2026, 10, 21), "Завтра")

    groups = homework.groups(today=today)
    assert [group.caption for group in groups] == ["Сегодня", "Завтра", "22.10.2026, Четверг"]


def test_homework_groups_overdue_separately(homework, simple_subjects) -> None:
    """HW-12: просроченные активные задания выделены отдельной группой."""
    today = date(2026, 10, 20)
    subject = simple_subjects[0]
    homework.create(subject.id, date(2026, 10, 1), "Просрочено")
    homework.create(subject.id, today, "Сегодня")

    groups = homework.groups(today=today)
    assert groups[0].caption == "Просроченные"
    assert groups[0].is_overdue is True
    assert groups[0].count == 1


def test_homework_filters(homework, simple_subjects) -> None:
    """HW-13: фильтры «Активные», «Выполненные», «Все», по предмету."""
    first, second = simple_subjects
    active = homework.create(first.id, date(2026, 9, 14), "Активное")
    done = homework.create(second.id, date(2026, 9, 15), "Выполненное")
    homework.set_done(done.id)

    assert len(homework.rows(status=HomeworkStatus.ACTIVE)) == 1
    assert len(homework.rows(status=HomeworkStatus.DONE)) == 1
    assert len(homework.rows()) == 2
    assert [row.homework.id for row in homework.rows(subject_id=first.id)] == [active.id]


def test_homework_delete_active_without_confirmation(homework, simple_subjects) -> None:
    """HW-16: активное задание удаляется без подтверждения."""
    created = homework.create(simple_subjects[0].id, date(2026, 9, 14))
    assert homework.needs_confirmation(created.id) is False
    homework.delete(created.id)
    assert homework.rows() == []


def test_homework_delete_done_requires_confirmation(homework, simple_subjects) -> None:
    """HW-16: выполненное — только с подтверждением."""
    created = homework.create(simple_subjects[0].id, date(2026, 9, 14))
    homework.set_done(created.id)
    assert homework.needs_confirmation(created.id) is True

    with pytest.raises(ValidationError):
        homework.delete(created.id)
    assert len(homework.rows()) == 1, "Задание не удалено"

    homework.delete(created.id, confirmed=True)
    assert homework.rows() == []


def test_homework_empty_hint_without_subjects(db, subjects) -> None:
    """HW-14: при пустом справочнике — подсказка «Сначала добавьте предмет»."""
    service = HomeworkService(db)
    assert service.has_subjects is False
    assert service.empty_hint == "Сначала добавьте предмет"


def test_homework_empty_hint_with_subjects(homework, simple_subjects) -> None:
    assert homework.has_subjects is True
    assert homework.empty_hint == "Заданий нет"


def test_homework_survives_lesson_cancellation(db, homework, monday_lower,
                                               simple_bell, simple_subjects) -> None:
    """HW-10: отмена пары не удаляет и не переносит задание."""
    created = homework.create(simple_subjects[0].id, monday_lower, "Задание")
    OverrideService(db).cancel(monday_lower, simple_bell.id, 1)

    assert homework.rows()[0].homework.id == created.id
    assert homework.repo.by_id(created.id).due_date == monday_lower


def test_homework_short_description_truncated(homework, simple_subjects) -> None:
    """HW-12: обрезка длинного описания с полным текстом в подсказке."""
    long_text = ("Очень длинное описание задания, " * 10).strip()
    created = homework.create(simple_subjects[0].id, date(2026, 9, 14), long_text)
    row = homework.rows()[0]
    assert len(row.short_description) <= 80
    assert row.description == long_text, "Полный текст доступен во всплывающей подсказке"


def test_homework_update_subject_and_date(homework, simple_subjects) -> None:
    """HW-04: редактирование задания."""
    first, second = simple_subjects
    created = homework.create(first.id, date(2026, 9, 14), "Черновик")
    updated = homework.update(
        created.id, subject_id=second.id, due_date=date(2026, 9, 20),
        description="Итог",
    )
    assert updated.subject_id == second.id
    assert updated.due_date == date(2026, 9, 20)
    assert updated.description == "Итог"


def test_homework_due_dates_for_calendar(homework, simple_subjects) -> None:
    """UI-05: дедлайны — точки-метки мини-календаря."""
    subject = simple_subjects[0]
    homework.create(subject.id, date(2026, 9, 14))
    homework.create(subject.id, date(2026, 9, 14))
    homework.create(subject.id, date(2026, 9, 20))

    dates = homework.due_dates()
    assert dates == {date(2026, 9, 14), date(2026, 9, 20)}
