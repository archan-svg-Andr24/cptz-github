"""Слой 1: домашние задания, оверрайды, справочники (ACC-M-59…61, 65…67,
103, 104, 107…113).

Проверяются правила OVR-01…OVR-11 (включая запрет ``move`` в MVP), жизненный
цикл домашнего задания (HW-01…HW-11) и справочники предметов/звонков.

Номера 62, 63 и 64 в В.1 не присвоены — нумерация их пропускает.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from student_planner.core.errors import (
    InUseError,
    NotFoundError,
    RuleViolationError,
    ValidationError,
)
from student_planner.core.models import HomeworkStatus, LessonStatus, OverrideType


# ---------------------------------------------------------------------------
# ACC-M-103 — тип ``move`` запрещён в MVP.
# ---------------------------------------------------------------------------
def test_acc_m_103_move_override_rejected(db, anchors, simple_bell, simple_subjects,
                                          templates, overrides) -> None:
    """Перенос = отмена + добавление; отдельного ``move`` нет (OVR-03)."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)

    with pytest.raises(ValidationError) as excinfo:
        overrides.create(date(2026, 9, 7), simple_bell.id, 1, "move")
    assert "move" in str(excinfo.value)
    assert "отмен" in str(excinfo.value).lower()


def test_acc_m_103_mvp_override_types_are_three() -> None:
    assert OverrideType.MVP == ("cancel", "replace", "add")


def test_acc_m_103_relocation_via_cancel_and_add(db, anchors, simple_bell,
                                                simple_subjects, templates,
                                                overrides) -> None:
    """OVR-03: перенос занятия моделируется парой отмена + добавление."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)
    templates.set_cell(simple_bell.id, "lower", 2, simple_subjects[1].id)

    overrides.create(day, simple_bell.id, 1, "cancel")
    overrides.create(day, simple_bell.id, 3, "add", subject_id=subject.id)

    from student_planner.core.day_resolution import DayResolver

    lesson_map = {lesson.slot_no: lesson for lesson in DayResolver(db).resolve(day).lessons}
    assert lesson_map[1].status == LessonStatus.CANCELLED
    assert lesson_map[3].status == LessonStatus.ADDED
    assert lesson_map[3].subject is not None and lesson_map[3].subject.id == subject.id


# ---------------------------------------------------------------------------
# ACC-M-104 — уникальность тройки (дата, профиль, блок).
# ---------------------------------------------------------------------------
def test_acc_m_104_duplicate_override_rejected(db, anchors, simple_bell,
                                              simple_subjects, templates,
                                              overrides) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    overrides.create(day, simple_bell.id, 1, "cancel")
    with pytest.raises(RuleViolationError) as excinfo:
        overrides.create(day, simple_bell.id, 1, "replace",
                         subject_id=simple_subjects[0].id)
    assert "оверрайд" in str(excinfo.value).lower() or "изменение" in str(excinfo.value).lower()


def test_acc_m_104_same_slot_different_dates_allowed(db, anchors, simple_bell,
                                                    overrides) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    overrides.create(date(2026, 9, 7), simple_bell.id, 1, "cancel")
    overrides.create(date(2026, 9, 8), simple_bell.id, 1, "cancel")
    assert len(overrides.for_date(date(2026, 9, 7))) == 1
    assert len(overrides.for_date(date(2026, 9, 8))) == 1


# ---------------------------------------------------------------------------
# ACC-M-59…65 — правка и удаление оверрайдов, восстановление шаблона.
# ---------------------------------------------------------------------------
def test_acc_m_59_update_override_details(db, anchors, simple_bell, simple_subjects,
                                         templates, overrides) -> None:
    """OVR-05: у замены правятся предмет, преподаватель, кабинет и своё время."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)

    created = overrides.create(day, simple_bell.id, 1, "replace",
                               subject_id=simple_subjects[1].id)
    overrides.update(created.id, new_teacher="Петров П. П.", new_room="Каб. №7")

    refreshed = overrides.by_id(created.id)
    assert refreshed is not None
    assert refreshed.override_type == "replace", "Тип не меняется правкой деталей"
    assert refreshed.teacher == "Петров П. П."
    assert refreshed.room == "Каб. №7"
    assert refreshed.subject_id == simple_subjects[1].id


def test_acc_m_59_change_override_type_via_recreate(db, anchors, simple_bell,
                                                   simple_subjects, templates,
                                                   overrides) -> None:
    """Смена типа оверрайда — удаление + создание (OVR-08 держит уникальность)."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)

    created = overrides.create(day, simple_bell.id, 1, "cancel")
    overrides.delete(created.id)
    replacement = overrides.create(day, simple_bell.id, 1, "replace",
                                    subject_id=simple_subjects[1].id)
    assert replacement.override_type == "replace"
    assert replacement.subject_id == simple_subjects[1].id
    assert len(overrides.for_date(day)) == 1, "Осталась ровно одна запись"


def test_acc_m_60_delete_override_restores_template(db, anchors, simple_bell,
                                                   simple_subjects, templates,
                                                   overrides) -> None:
    """OVR-11: удаление оверрайда возвращает занятие из шаблона."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)

    created = overrides.create(day, simple_bell.id, 1, "cancel")
    from student_planner.core.day_resolution import DayResolver

    assert DayResolver(db).resolve(day).lessons[0].status == LessonStatus.CANCELLED

    overrides.delete(created.id)
    restored = DayResolver(db).resolve(day).lessons[0]
    assert restored.status == LessonStatus.PLANNED, "Занятие снова из шаблона"
    assert restored.subject is not None and restored.subject.id == subject.id


def test_acc_m_61_delete_all_overrides_for_date(db, anchors, simple_bell,
                                               simple_subjects, templates,
                                               overrides) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    for slot in (1, 2, 3):
        templates.set_cell(simple_bell.id, "lower", slot, simple_subjects[0].id)
    overrides.create(day, simple_bell.id, 1, "cancel")
    overrides.create(day, simple_bell.id, 2, "cancel")

    removed = overrides.delete_for_date(day)
    assert removed == 2
    assert overrides.for_date(day) == []

    from student_planner.core.day_resolution import DayResolver

    assert len(DayResolver(db).resolve(day).lessons) == 3, "Все занятия вернулись"


def test_ovr_03_cancel_and_add_different_slots_allowed(db, anchors, simple_bell,
                                                       simple_subjects, overrides) -> None:
    """OVR-03: перенос — это отмена на одном слоте и добавление на другом.

    Отдельной проверки В.1 для этого требования нет (ACC-M-62 не присвоен):
    перенос в MVP выражается двумя записями, и обе сосуществуют по ключу
    ``(date, profile_id, slot_no)``.
    """
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    day = date(2026, 9, 7)
    overrides.create(day, simple_bell.id, 1, "cancel")
    added = overrides.create(day, simple_bell.id, 3, "add",
                             subject_id=simple_subjects[0].id)
    assert added.override_type == "add"
    assert len(overrides.for_date(day)) == 2, "Обе записи сосуществуют"


def test_ovr_07_add_requires_subject(db, anchors, simple_bell, overrides) -> None:
    """OVR-07: добавление обязано указывать предмет (ACC-M-63 не присвоен)."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    with pytest.raises(ValidationError):
        overrides.create(date(2026, 9, 7), simple_bell.id, 3, "add")


def test_ovr_05_replace_requires_subject(db, anchors, simple_bell, overrides) -> None:
    """OVR-05: замена обязана указывать предмет (ACC-M-64 не присвоен)."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    with pytest.raises(ValidationError):
        overrides.create(date(2026, 9, 7), simple_bell.id, 1, "replace")


def test_acc_m_65_cancel_ignores_subject(db, anchors, simple_bell, simple_subjects,
                                         templates, overrides) -> None:
    """OVR-04: отмена не ссылается на предмет."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    day = date(2026, 9, 7)
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)
    created = overrides.create(day, simple_bell.id, 1, "cancel")
    assert created.subject_id is None, "У отмены предмет не сохраняется"


def test_dates_with_overrides_lists_days(db, anchors, simple_bell, overrides) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    overrides.create(date(2026, 9, 7), simple_bell.id, 1, "cancel")
    overrides.create(date(2026, 9, 9), simple_bell.id, 2, "cancel")
    dates = overrides.dates_with_overrides()
    assert date(2026, 9, 7) in dates and date(2026, 9, 9) in dates


# ---------------------------------------------------------------------------
# ACC-M-107…113 — домашние задания.
# ---------------------------------------------------------------------------
def test_acc_m_107_homework_created_and_listed(homework_repo_factory, db, simple_subjects) -> None:
    repo = homework_repo_factory(db)
    subject = simple_subjects[0]
    item = repo.create(subject.id, date(2026, 9, 14), "Упражнение 12")
    assert item.id > 0
    assert item.status == HomeworkStatus.ACTIVE
    assert item.description == "Упражнение 12"
    assert len(repo.all()) == 1


def test_acc_m_108_multiple_homework_per_subject_date(homework_repo_factory, db,
                                                     simple_subjects) -> None:
    """HW-06: несколько заданий на один предмет и дату — норма."""
    repo = homework_repo_factory(db)
    subject = simple_subjects[0]
    repo.create(subject.id, date(2026, 9, 14), "Задача 1")
    repo.create(subject.id, date(2026, 9, 14), "Задача 2")
    items = repo.for_subject_date(subject.id, date(2026, 9, 14))
    assert len(items) == 2, "Ограничения уникальности нет"


def test_acc_m_109_homework_description_optional(homework_repo_factory, db,
                                                simple_subjects) -> None:
    """HW-07: описание может отсутствовать, срок обязателен."""
    repo = homework_repo_factory(db)
    item = repo.create(simple_subjects[0].id, date(2026, 9, 14))
    assert item.description is None


def test_acc_m_110_toggle_status(homework_repo_factory, db, simple_subjects) -> None:
    """HW-15: переключение «выполнено» ↔ «активное»."""
    repo = homework_repo_factory(db)
    item = repo.create(simple_subjects[0].id, date(2026, 9, 14), "Реферат")
    done = repo.toggle(item.id)
    assert done.status == HomeworkStatus.DONE
    assert done.completed_at, "Дата выполнения заполняется"

    undone = repo.toggle(item.id)
    assert undone.status == HomeworkStatus.ACTIVE
    assert not undone.completed_at, "При снятии отметки дата очищается"


def test_acc_m_111_set_status_explicitly(homework_repo_factory, db, simple_subjects) -> None:
    repo = homework_repo_factory(db)
    item = repo.create(simple_subjects[0].id, date(2026, 9, 14), "Доклад")
    assert repo.set_status(item.id, HomeworkStatus.DONE).status == HomeworkStatus.DONE
    assert repo.set_status(item.id, HomeworkStatus.ACTIVE).status == HomeworkStatus.ACTIVE


def test_acc_m_112_overdue_is_computed_not_stored(homework_repo_factory, db,
                                                 simple_subjects) -> None:
    """HW-08: «просрочено» — производное состояние (сегодня 20.10.2026)."""
    repo = homework_repo_factory(db)
    item = repo.create(simple_subjects[0].id, date(2026, 10, 1), "Старое задание")
    today = date(2026, 10, 20)
    assert item.is_overdue(today) is True, "Активное с прошедшим сроком — просрочено"

    overdue = repo.filtered(only_overdue=True, overdue_before=today)
    assert [entry.id for entry in overdue] == [item.id]

    repo.set_status(item.id, HomeworkStatus.DONE)
    assert repo.require(item.id).is_overdue(today) is False, "Выполненное не просрочено"


def test_acc_m_113_homework_deleted_with_subject_blocked(homework_repo_factory, db,
                                                        simple_subjects, subjects) -> None:
    """HW-09: предмет с домашними заданиями не удаляется."""
    repo = homework_repo_factory(db)
    subject = simple_subjects[0]
    repo.create(subject.id, date(2026, 9, 14), "Задание")
    with pytest.raises(InUseError):
        subjects.delete(subject.id)


def test_acc_m_113_homework_deleted_removes_task(homework_repo_factory, db,
                                                simple_subjects) -> None:
    repo = homework_repo_factory(db)
    item = repo.create(simple_subjects[0].id, date(2026, 9, 14), "Удалить меня")
    repo.delete(item.id)
    assert repo.all() == []


def test_homework_filter_by_status(homework_repo_factory, db, simple_subjects) -> None:
    repo = homework_repo_factory(db)
    subject = simple_subjects[0]
    first = repo.create(subject.id, date(2026, 10, 25), "Сделано")
    repo.create(subject.id, date(2026, 10, 26), "Не сделано")
    repo.set_status(first.id, HomeworkStatus.DONE)

    active = repo.filtered(status=HomeworkStatus.ACTIVE)
    assert [item.description for item in active] == ["Не сделано"]
    done = repo.filtered(status=HomeworkStatus.DONE)
    assert [item.description for item in done] == ["Сделано"]


def test_homework_upcoming_window(homework_repo_factory, db, simple_subjects) -> None:
    """HW-05: виджет показывает задания на сегодня и завтра."""
    repo = homework_repo_factory(db)
    subject = simple_subjects[0]
    today = date(2026, 10, 20)
    repo.create(subject.id, today, "Сегодня")
    repo.create(subject.id, date(2026, 10, 21), "Завтра")
    repo.create(subject.id, date(2026, 10, 25), "Позже")

    items = repo.upcoming(today=today)
    assert {item.description for item in items} == {"Сегодня", "Завтра"}


def test_homework_missing_record_raises(homework_repo_factory, db) -> None:
    repo = homework_repo_factory(db)
    with pytest.raises(NotFoundError):
        repo.delete(9999)


def test_homework_due_dates_listed(homework_repo_factory, db, simple_subjects) -> None:
    repo = homework_repo_factory(db)
    subject = simple_subjects[0]
    repo.create(subject.id, date(2026, 10, 25), "A")
    repo.create(subject.id, date(2026, 10, 25), "B")
    repo.create(subject.id, date(2026, 10, 28), "C")
    assert repo.due_dates() == {date(2026, 10, 25), date(2026, 10, 28)}


# ---------------------------------------------------------------------------
# Справочник предметов (SUBJ-01…SUBJ-06).
# ---------------------------------------------------------------------------
def test_subject_name_required(subjects) -> None:
    with pytest.raises(Exception):
        subjects.create("   ")


def test_subject_deactivate_keeps_history(subjects, db, simple_subjects) -> None:
    """SUBJ-04: отключённый предмет остаётся в истории, но не в выборе."""
    subject = subjects.create("История", code="HIST")
    subjects.set_active(subject.id, False)
    all_subjects = subjects.all(include_inactive=True)
    assert any(item.id == subject.id for item in all_subjects)
    active = subjects.all(include_inactive=False)
    assert all(item.id != subject.id for item in active)


def test_subject_update_name_and_teacher(subjects) -> None:
    subject = subjects.create("Алгебра", code="ALG")
    updated = subjects.update(subject.id, name="Алгебра и начала анализа",
                              teacher="Иванов И. И.", room="Каб. №12")
    assert updated.name == "Алгебра и начала анализа"
    assert updated.teacher == "Иванов И. И."


def test_subject_delete_when_unused(subjects) -> None:
    subject = subjects.create("Временный", code="TMP")
    subjects.delete(subject.id)
    assert subjects.all() == []


def test_subject_delete_blocked_by_template(db, anchors, simple_bell, simple_subjects,
                                            templates, subjects) -> None:
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    subject = simple_subjects[0]
    templates.set_cell(simple_bell.id, "lower", 1, subject.id)
    with pytest.raises(InUseError) as excinfo:
        subjects.delete(subject.id)
    assert "шаблон" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Справочник звонков (BELL-01…BELL-20).
# ---------------------------------------------------------------------------
def test_bell_profile_has_weekday(bells) -> None:
    profile = bells.create_profile(1, "Понедельник")
    assert profile.weekday == 1
    assert profile.name == "Понедельник"
    assert profile.slots == ()


def test_bell_weekday_out_of_range_rejected(bells) -> None:
    with pytest.raises(ValidationError):
        bells.create_profile(0, "Ноль")
    with pytest.raises(ValidationError):
        bells.create_profile(8, "Восемь")


def test_bell_slot_times_ordered(bells) -> None:
    """BELL-17: начало раньше окончания."""
    profile = bells.create_profile(1, "Пн")
    with pytest.raises(ValidationError):
        bells.add_slot(profile.id, "lesson", parts=[("lesson", "09:15", "08:30")])


def test_bell_overlapping_slots_rejected(bells) -> None:
    """BELL-17: блоки внутри профиля не пересекаются."""
    profile = bells.create_profile(1, "Пн")
    bells.add_slot(profile.id, "pair", parts=[("lesson", "08:30", "09:15")])
    with pytest.raises(ValidationError):
        bells.add_slot(profile.id, "pair", parts=[("lesson", "09:00", "09:45")])


def test_bell_adjacent_slots_allowed(bells) -> None:
    profile = bells.create_profile(1, "Пн")
    bells.add_slot(profile.id, "pair", parts=[("lesson", "08:30", "09:15")])
    second = bells.add_slot(profile.id, "pair", parts=[("lesson", "09:15", "10:00")])
    assert second.slot_no == 2


def test_bell_slots_append_only(bells) -> None:
    """BELL-13: блоки добавляются только в конец профиля."""
    profile = bells.create_profile(1, "Пн")
    first = bells.add_slot(profile.id, "pair", parts=[("lesson", "08:30", "09:15")])
    second = bells.add_slot(profile.id, "pair", parts=[("lesson", "10:00", "10:45")])
    assert (first.slot_no, second.slot_no) == (1, 2), "Номер назначается последовательно"


def test_bell_delete_slot_blocked_if_referenced(db, anchors, simple_bell,
                                               simple_subjects, templates, bells) -> None:
    """BELL-14: блок с занятиями в шаблоне не удаляется."""
    anchors.create(date(2026, 9, 7), date(2026, 9, 7), "lower")
    templates.set_cell(simple_bell.id, "lower", 1, simple_subjects[0].id)
    slot = simple_bell.slots[0]
    with pytest.raises(InUseError):
        bells.delete_slot(slot.id)


def test_bell_two_part_parts_validated(bells) -> None:
    """BELL-17: части двухчастного блока чередуются «занятие | перемена»."""
    profile = bells.create_profile(1, "Пн")
    # Первая и последняя части обязаны быть занятием.
    with pytest.raises(ValidationError):
        bells.add_slot(profile.id, "pair", parts=[("break", "08:30", "08:40"),
                                                 ("lesson", "08:40", "09:25")])


def test_bell_two_part_block_accepted(bells) -> None:
    """BELL-02/BELL-06: пара из двух занятий с переменой внутри."""
    profile = bells.create_profile(1, "Пн")
    slot = bells.add_slot(
        profile.id, "pair",
        parts=[("lesson", "08:30", "09:15"), ("break", "09:15", "09:25"),
               ("lesson", "09:25", "10:10")],
    )
    assert slot.is_two_part is True
    assert slot.start_time == "08:30"
    assert slot.end_time == "10:10", "Окончание — по последней части"


def test_bell_profile_dates_ordering(bells) -> None:
    with pytest.raises(ValidationError):
        bells.create_profile(1, "Пн", effective_from=date(2026, 10, 1),
                             effective_to=date(2026, 9, 1))
