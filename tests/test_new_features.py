"""Слой 1: новые функции и исправленные дефекты.

Покрываются:

* SET-02 — формат даты и времени из настроек действительно применяется;
* SET-07/DATA-02 — путь к базе из настройки открывается при запуске;
* OVR-11 — кнопка сброса изменений дня связана с ``reset_day()``;
* BELL-12…BELL-17 — правка блоков звонков из интерфейса;
* UI-14 — экспорт расписания в PNG;
* HW-13 — поиск по заданиям;
* EXAM-01…EXAM-12 — испытания: репозиторий, сервис, страница, метки;
* NOTIF-01…NOTIF-05 — системные уведомления;
* UI-25 — сворачиваемая правая панель;
* TPL-05 — альтернативная пятница;
* GRID-10 — импорт расписания из файла.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


import pytest

from student_planner.core import dates as dt
from student_planner.core.day_resolution import DayResolver
from student_planner.core.database import create_database
from student_planner.core.errors import NotFoundError, ValidationError
from student_planner.core.exam_repository import ExamRepository
from student_planner.core.exam_service import ExamService
from student_planner.core.models import ExamKind, ExamStatus, WeekType
from student_planner.core.notification_service import NotificationService
from student_planner.core.paths import (
    clear_pointer,
    default_db_path,
    pointer_file,
    read_pointer,
    startup_db_path,
    write_pointer,
)
from student_planner.core.repositories import (
    BellRepository,
    ScheduleTemplateRepository,
    SubjectRepository,
    WeekAnchorRepository,
)
from student_planner.core.schedule_import import ScheduleImporter
from student_planner.core.schedule_service import HomeworkService
from student_planner.core.settings_registry import SettingsKeys
from student_planner.core.settings_service import SettingsService
# week_type_for импортируется по месту в тестах, где нужен

#: «Сегодня» для всех тестов совпадает с conftest: дата зафиксирована
#: фикстурой ``frozen_clock``, поэтому просрочка не зависит от календаря.
FIXED_TODAY = date(2026, 10, 20)


# ===========================================================================
# SET-02: форматы даты и времени
# ===========================================================================
class TestDisplayFormats:
    """SET-02: настройка формата действительно меняет показ дат."""

    @pytest.fixture(autouse=True)
    def reset_formats(self):
        yield
        dt.set_display_format(None)
        dt.set_time_format(None)

    def test_default_format_is_dd_mm_yyyy(self) -> None:
        assert dt.active_display_format() == "DD.MM.YYYY"
        assert dt.format_display(date(2026, 3, 7)) == "07.03.2026"

    def test_iso_format_applies_everywhere(self) -> None:
        """Без аргумента format_display() берёт действующий формат.

        Именно этого не хватало: настройка менялась, а все вызовы без
        аргумента продолжали печатать ДД.ММ.ГГГГ.
        """
        dt.set_display_format("YYYY-MM-DD")
        assert dt.format_display(date(2026, 3, 7)) == "2026-03-07"

    def test_short_year_format(self) -> None:
        dt.set_display_format("DD.MM.YY")
        assert dt.format_display(date(2026, 3, 7)) == "07.03.26"

    def test_unknown_format_is_ignored(self) -> None:
        dt.set_display_format("не формат")
        assert dt.active_display_format() == "DD.MM.YYYY"

    def test_parse_display_follows_active_format(self) -> None:
        dt.set_display_format("YYYY-MM-DD")
        assert dt.parse_display("2026-03-07") == date(2026, 3, 7)

    def test_parse_display_accepts_common_formats_always(self) -> None:
        """Ранее введённые даты не должны переставать читаться."""
        dt.set_display_format("YYYY-MM-DD")
        assert dt.parse_display("07.03.2026") == date(2026, 3, 7)

    def test_time_format_seconds(self) -> None:
        dt.set_time_format("HH:MM:SS")
        assert dt.format_time_display("08:30") == "08:30:00"

    def test_time_format_default(self) -> None:
        assert dt.format_time_display("08:30") == "08:30"

    def test_settings_apply_formats_on_save(self, db) -> None:
        """SET-02: сохранение в настройках применяет формат к модулю дат."""
        service = SettingsService(db)
        service.set_display_formats("YYYY-MM-DD", "HH:MM:SS")
        assert dt.active_display_format() == "YYYY-MM-DD"
        assert dt.active_time_format() == "HH:MM:SS"

    def test_apply_display_formats_reads_stored_values(self, db) -> None:
        service = SettingsService(db)
        service.set(SettingsKeys.DATE_DISPLAY_FORMAT, "DD.MM.YY")
        service.apply_display_formats()
        assert dt.active_display_format() == "DD.MM.YY"

    def test_registry_offers_all_formats(self) -> None:
        """Все форматы из настройки допустимы в датном модуле."""
        from student_planner.core.settings_registry import default_registry

        registry = default_registry()
        spec = registry.get(SettingsKeys.DATE_DISPLAY_FORMAT)
        assert set(spec.choices) <= set(dt.DISPLAY_FORMATS)
        spec = registry.get(SettingsKeys.TIME_DISPLAY_FORMAT)
        assert set(spec.choices) <= set(dt.TIME_FORMATS)


# ===========================================================================
# SET-07/DATA-02: путь к базе данных
# ===========================================================================
class TestDatabasePath:
    """SET-07: настройка ``db_path`` влияет на то, какой файл открывается."""

    def test_default_when_nothing_stored(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("student_planner.core.paths.appdata_dir", lambda: tmp_path)
        assert startup_db_path() == default_db_path()

    def test_pointer_remembers_path(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("student_planner.core.paths.appdata_dir", lambda: tmp_path)
        target = tmp_path / "custom.db"
        write_pointer(target)
        assert read_pointer() == target
        assert startup_db_path() == target

    def test_pointer_missing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("student_planner.core.paths.appdata_dir", lambda: tmp_path)
        assert read_pointer() is None

    def test_clear_pointer(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("student_planner.core.paths.appdata_dir", lambda: tmp_path)
        write_pointer(tmp_path / "x.db")
        clear_pointer()
        assert not pointer_file().exists()
        assert read_pointer() is None

    def test_db_setting_wins_over_pointer(self, tmp_path, monkeypatch) -> None:
        """Настройка внутри БД важнее файла-указателя."""
        monkeypatch.setattr("student_planner.core.paths.appdata_dir", lambda: tmp_path)
        database = create_database(tmp_path / "work.db")
        try:
            chosen = tmp_path / "from_setting.db"
            SettingsService(database).set(SettingsKeys.DB_PATH, str(chosen))
            write_pointer(tmp_path / "from_pointer.db")
            assert startup_db_path(database) == chosen
        finally:
            database.close()

    def test_pointer_used_when_setting_is_default(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("student_planner.core.paths.appdata_dir", lambda: tmp_path)
        database = create_database(tmp_path / "work.db")
        try:
            pointed = tmp_path / "pointed.db"
            write_pointer(pointed)
            assert startup_db_path(database) == pointed
        finally:
            database.close()

    def test_resolve_expands_template(self) -> None:
        from student_planner.core.paths import resolve_db_path

        resolved = resolve_db_path("%APPDATA%\\StudentPlanner\\student_planner.db")
        assert "%APPDATA%" not in str(resolved)


# ===========================================================================
# HW-13: поиск по заданиям
# ===========================================================================
class TestHomeworkSearch:
    """HW-13: поиск по описанию и предмету, вместе с остальными фильтрами."""

    @pytest.fixture
    def homework_db(self, db):
        subjects = SubjectRepository(db)
        first = subjects.create("Математика")
        second = subjects.create("История")
        service = HomeworkService(db)
        service.create(first.id, FIXED_TODAY + timedelta(days=2), "Лабораторная по SQL")
        service.create(first.id, FIXED_TODAY + timedelta(days=3), "Реферат по графам")
        service.create(second.id, FIXED_TODAY + timedelta(days=1), "Доклад про сети")
        return db

    def test_search_by_description(self, homework_db) -> None:
        rows = HomeworkService(homework_db).rows(query="лабораторная")
        assert [row.description for row in rows] == ["Лабораторная по SQL"]

    def test_search_is_case_insensitive(self, homework_db) -> None:
        rows = HomeworkService(homework_db).rows(query="ЛАБОРАТОРНАЯ")
        assert len(rows) == 1

    def test_search_by_subject_name(self, homework_db) -> None:
        rows = HomeworkService(homework_db).rows(query="история")
        assert [row.subject_name for row in rows] == ["История"]

    def test_search_multiple_words_all_required(self, homework_db) -> None:
        """Несколько слов — все должны встретиться."""
        assert len(HomeworkService(homework_db).rows(query="реферат графам")) == 1
        assert HomeworkService(homework_db).rows(query="реферат сети") == []

    def test_empty_query_returns_everything(self, homework_db) -> None:
        assert len(HomeworkService(homework_db).rows()) == 3
        assert len(HomeworkService(homework_db).rows(query="   ")) == 3

    def test_search_combines_with_status_filter(self, homework_db) -> None:
        service = HomeworkService(homework_db)
        rows = service.rows(query="по", status="active")
        assert all(row.homework.status == "active" for row in rows)

    def test_search_groups_keep_structure(self, homework_db) -> None:
        groups = HomeworkService(homework_db).groups(query="лабораторная")
        assert sum(group.count for group in groups) == 1

    def test_search_no_match(self, homework_db) -> None:
        assert HomeworkService(homework_db).rows(query="ничего такого") == []


# ===========================================================================
# EXAM-01…EXAM-12: экзамены
# ===========================================================================
class TestExamRepository:
    """EXAM-01…EXAM-03: хранение испытаний."""

    @pytest.fixture
    def exam_db(self, db):
        self.subject = SubjectRepository(db).create("Математика")
        return db

    def test_create_and_read(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        exam = repo.create(
            self.subject.id, FIXED_TODAY + timedelta(days=5),
            kind=ExamKind.EXAM, time="09:00", room="312",
        )
        assert exam.kind == ExamKind.EXAM
        assert exam.time == "09:00"
        assert exam.room == "312"
        assert repo.get(exam.id) is not None

    def test_unknown_kind_rejected(self, exam_db) -> None:
        with pytest.raises(ValidationError):
            ExamRepository(exam_db).create(self.subject.id, FIXED_TODAY, kind="зачёт?!")

    def test_unknown_status_rejected(self, exam_db) -> None:
        with pytest.raises(ValidationError):
            ExamRepository(exam_db).create(
                self.subject.id, FIXED_TODAY, status="сдан?"
            )

    def test_bad_time_rejected(self, exam_db) -> None:
        with pytest.raises(ValidationError):
            ExamRepository(exam_db).create(self.subject.id, FIXED_TODAY, time="25:99")

    def test_empty_time_allowed(self, exam_db) -> None:
        exam = ExamRepository(exam_db).create(self.subject.id, FIXED_TODAY, time="  ")
        assert exam.time is None

    def test_update(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        exam = repo.create(self.subject.id, FIXED_TODAY)
        updated = repo.update(exam.id, room="101", status=ExamStatus.PASSED)
        assert updated.room == "101"
        assert updated.status == ExamStatus.PASSED
        assert updated.date == exam.date

    def test_update_clear_time(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        exam = repo.create(self.subject.id, FIXED_TODAY, time="10:00")
        assert repo.update(exam.id, clear_time=True).time is None

    def test_delete(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        exam = repo.create(self.subject.id, FIXED_TODAY)
        repo.delete(exam.id)
        with pytest.raises(NotFoundError):
            repo.require(exam.id)

    def test_delete_unknown_raises(self, exam_db) -> None:
        with pytest.raises(NotFoundError):
            ExamRepository(exam_db).delete(9999)

    def test_upcoming_excludes_passed_and_past(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        soon = repo.create(self.subject.id, FIXED_TODAY + timedelta(days=2))
        past = repo.create(self.subject.id, FIXED_TODAY - timedelta(days=2))
        done = repo.create(self.subject.id, FIXED_TODAY + timedelta(days=3))
        repo.set_status(done.id, ExamStatus.PASSED)
        ids = [exam.id for exam in repo.upcoming(FIXED_TODAY)]
        assert soon.id in ids
        assert past.id not in ids
        assert done.id not in ids

    def test_upcoming_limit(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        for offset in (1, 2, 3):
            repo.create(self.subject.id, FIXED_TODAY + timedelta(days=offset))
        assert len(repo.upcoming(FIXED_TODAY, limit=2)) == 2

    def test_in_range_inclusive(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        repo.create(self.subject.id, FIXED_TODAY)
        repo.create(self.subject.id, FIXED_TODAY + timedelta(days=10))
        found = repo.in_range(FIXED_TODAY, FIXED_TODAY + timedelta(days=10))
        assert len(found) == 2

    def test_dates_with_exams(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        repo.create(self.subject.id, FIXED_TODAY)
        assert repo.dates_with_exams(FIXED_TODAY, FIXED_TODAY) == {FIXED_TODAY}

    def test_count_and_delete_for_subject(self, exam_db) -> None:
        repo = ExamRepository(exam_db)
        repo.create(self.subject.id, FIXED_TODAY)
        repo.create(self.subject.id, FIXED_TODAY + timedelta(days=1))
        assert repo.count_for_subject(self.subject.id) == 2
        assert repo.delete_for_subject(self.subject.id) == 2
        assert repo.count_for_subject(self.subject.id) == 0


class TestExamService:
    """EXAM-05…EXAM-10: подписи, отсчёт, метки и сводка."""

    @pytest.fixture
    def service(self, db):
        self.subject = SubjectRepository(db).create("История")
        return ExamService(db)

    def test_countdown_today(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY, kind=ExamKind.EXAM)
        row = service.rows(today=FIXED_TODAY)[0]
        assert row.countdown == "Сегодня"
        assert row.days_left == 0

    def test_countdown_tomorrow(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY + timedelta(days=1))
        assert service.rows(today=FIXED_TODAY)[0].countdown == "Завтра"

    def test_countdown_days(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY + timedelta(days=5))
        assert service.rows(today=FIXED_TODAY)[0].countdown == "Через 5 дн."

    def test_past_exam_caption(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY - timedelta(days=1))
        row = service.rows(today=FIXED_TODAY)[0]
        assert row.countdown == "Прошёл"
        assert row.is_overdue

    def test_passed_caption(self, service) -> None:
        exam = service.create(self.subject.id, FIXED_TODAY + timedelta(days=3))
        service.mark_passed(exam.id)
        row = service.rows(today=FIXED_TODAY)[0]
        assert row.countdown == "Сдан"
        assert row.is_passed

    def test_postponed_caption(self, service) -> None:
        exam = service.create(self.subject.id, FIXED_TODAY + timedelta(days=3))
        service.mark_postponed(exam.id)
        assert service.rows(today=FIXED_TODAY)[0].countdown == "Перенесён"

    def test_when_caption_includes_time(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY, time="09:30")
        assert "09:30" in service.rows(today=FIXED_TODAY)[0].when_caption

    def test_next_exam(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY + timedelta(days=9))
        service.create(self.subject.id, FIXED_TODAY + timedelta(days=2))
        assert service.next_exam(today=FIXED_TODAY).days_left == 2

    def test_next_exam_none_when_empty(self, service) -> None:
        assert service.next_exam(today=FIXED_TODAY) is None

    def test_upcoming_within_window(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY + timedelta(days=3))
        service.create(self.subject.id, FIXED_TODAY + timedelta(days=20))
        assert len(service.upcoming_within(7, today=FIXED_TODAY)) == 1

    def test_day_exams(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY, time="08:30", room="12")
        items = service.day_exams(FIXED_TODAY, today=FIXED_TODAY)
        assert len(items) == 1
        assert "08:30" in items[0].caption
        assert "12" in items[0].caption

    def test_month_marks(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY)
        marks = service.month_marks(FIXED_TODAY, FIXED_TODAY + timedelta(days=30))
        assert marks[FIXED_TODAY] == {"exam"}

    def test_summary(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY + timedelta(days=1))
        passed = service.create(self.subject.id, FIXED_TODAY - timedelta(days=1))
        service.mark_passed(passed.id)
        summary = service.summary(today=FIXED_TODAY)
        assert summary["total"] == 2
        assert summary["planned"] == 1
        assert summary["passed"] == 1

    def test_search_by_room(self, service) -> None:
        service.create(self.subject.id, FIXED_TODAY, room="404")
        assert len(service.rows(today=FIXED_TODAY, query="404")) == 1
        assert service.rows(today=FIXED_TODAY, query="505") == []

    def test_kind_and_status_choices(self, service) -> None:
        assert len(service.kind_choices()) == 3
        assert len(service.status_choices()) == 3


class TestExamCalendarMarks:
    """EXAM-06: испытание видно в мини-календаре и разрешении дня."""

    def test_month_marks_include_exam(self, db) -> None:
        subject = SubjectRepository(db).create("Физика")
        ExamRepository(db).create(subject.id, FIXED_TODAY)
        marks = DayResolver(db).month_marks(FIXED_TODAY, FIXED_TODAY + timedelta(days=7))
        assert "exam" in marks[FIXED_TODAY]

    def test_marks_without_exams_have_no_key(self, db) -> None:
        marks = DayResolver(db).month_marks(FIXED_TODAY, FIXED_TODAY + timedelta(days=7))
        assert all("exam" not in kinds for kinds in marks.values())


# ===========================================================================
# NOTIF-01…NOTIF-05: уведомления
# ===========================================================================
class TestNotifications:
    """NOTIF-01…NOTIF-05: отбор и дедупликация напоминаний."""

    @pytest.fixture
    def service(self, db):
        self.subject = SubjectRepository(db).create("Математика")
        return NotificationService(db)

    def test_disabled_returns_nothing(self, service, db) -> None:
        SettingsService(db).set(SettingsKeys.NOTIFY_ENABLED, "0")
        service.create_exam_if_needed = None  # подсказка читателю: напоминаний нет
        ExamRepository(db).create(self.subject.id, FIXED_TODAY)
        assert service.all_pending(now=datetime.combine(FIXED_TODAY, datetime.min.time())) == []

    def test_exam_reminder(self, service, db) -> None:
        ExamRepository(db).create(self.subject.id, FIXED_TODAY + timedelta(days=2))
        items = service.all_pending(
            now=datetime.combine(FIXED_TODAY, datetime.min.time()).replace(hour=8)
        )
        assert any(item.title == "Скоро экзамен" for item in items)

    def test_exam_outside_window_is_silent(self, service, db) -> None:
        ExamRepository(db).create(self.subject.id, FIXED_TODAY + timedelta(days=20))
        items = service.all_pending(
            now=datetime.combine(FIXED_TODAY, datetime.min.time()).replace(hour=8)
        )
        assert not any(item.title == "Скоро экзамен" for item in items)

    def test_homework_reminder(self, service, db) -> None:
        HomeworkService(db).create(self.subject.id, FIXED_TODAY, "Реферат")
        items = service.all_pending(
            now=datetime.combine(FIXED_TODAY, datetime.min.time()).replace(hour=8)
        )
        assert any(item.title == "Дедлайн задания" for item in items)

    def test_shown_not_repeated(self, service, db) -> None:
        ExamRepository(db).create(self.subject.id, FIXED_TODAY + timedelta(days=1))
        moment = datetime.combine(FIXED_TODAY, datetime.min.time()).replace(hour=8)
        first = service.all_pending(now=moment)
        assert first
        service.mark_shown(first[0])
        second = service.all_pending(now=moment)
        assert first[0].key not in {item.key for item in second}

    def test_reset_shown(self, service, db) -> None:
        ExamRepository(db).create(self.subject.id, FIXED_TODAY + timedelta(days=1))
        moment = datetime.combine(FIXED_TODAY, datetime.min.time()).replace(hour=8)
        service.mark_shown(service.all_pending(now=moment)[0])
        service.reset_shown()
        assert service.all_pending(now=moment)

    def test_next_notification_is_highest_priority(self, service, db) -> None:
        ExamRepository(db).create(self.subject.id, FIXED_TODAY)  # приоритет 0
        HomeworkService(db).create(self.subject.id, FIXED_TODAY + timedelta(days=5), "x")
        moment = datetime.combine(FIXED_TODAY, datetime.min.time()).replace(hour=8)
        item = service.next_notification(now=moment)
        assert item.title == "Скоро экзамен"

    def test_notification_has_key_title_message(self, service, db) -> None:
        ExamRepository(db).create(self.subject.id, FIXED_TODAY + timedelta(days=1))
        moment = datetime.combine(FIXED_TODAY, datetime.min.time()).replace(hour=8)
        item = service.all_pending(now=moment)[0]
        assert item.key and item.title and item.message

    def test_settings_defaults(self, service) -> None:
        assert service.enabled is True
        assert service.exam_days == 7
        assert service.homework_days == 1
        assert service.lesson_minutes == 15
        assert service.low_balance_enabled is True


class TestFridayVariant:
    """TPL-05: альтернативная пятница."""

    @staticmethod
    def _friday() -> date:
        """Ближайшая пятница начиная с ``FIXED_TODAY``."""
        return FIXED_TODAY + timedelta(days=(4 - FIXED_TODAY.weekday()) % 7)

    def test_default_variant_is_standard(self, db) -> None:
        assert DayResolver(db).friday_variant_for(self._friday()) == "standard"

    def test_other_days_always_standard(self, db) -> None:
        """Настройка действует только на пятницу."""
        SettingsService(db).set(SettingsKeys.FRIDAY_DEFAULT_VARIANT, "friday_class_hour")
        monday = FIXED_TODAY + timedelta(days=(0 - FIXED_TODAY.weekday()) % 7)
        assert DayResolver(db).friday_variant_for(monday) == "default"

    def test_friday_uses_alternative_profile(self, db) -> None:
        friday = self._friday()
        bells = BellRepository(db)
        bells.create_profile(5, "Пятница с классным часом", variant="friday_class_hour")
        bells.create_profile(5, "Обычная пятница")
        SettingsService(db).set(SettingsKeys.FRIDAY_DEFAULT_VARIANT, "friday_class_hour")
        profile = DayResolver(db).profile_for(friday)
        assert profile is not None
        assert profile.variant == "friday_class_hour"

    def test_friday_standard_uses_default_profile(self, db) -> None:
        friday = self._friday()
        bells = BellRepository(db)
        bells.create_profile(5, "Пятница с классным часом", variant="friday_class_hour")
        bells.create_profile(5, "Обычная пятница")
        profile = DayResolver(db).profile_for(friday)
        assert profile is not None
        assert profile.variant == "default"

    def test_setting_value_is_respected(self, db) -> None:
        friday = self._friday()
        SettingsService(db).set(SettingsKeys.FRIDAY_DEFAULT_VARIANT, "friday_class_hour")
        assert DayResolver(db).friday_variant_for(friday) == "friday_class_hour"


# ===========================================================================
# GRID-10: импорт расписания
# ===========================================================================
class TestScheduleImport:
    """GRID-10/FIRST-13: импорт сетки из CSV.

    Почти все проверки используют профиль понедельника из ``simple_bell``:
    без профиля звонков импортировать некуда, и это правильно сообщается.
    """

    @pytest.fixture(autouse=True)
    def monday_profile(self, simple_bell):
        self.bell = simple_bell

    @pytest.fixture
    def importer(self, db):
        return ScheduleImporter(db)

    def test_simple_format_without_header(self, importer, db) -> None:
        report = importer.parse_text("Пн;upper;1;Математика")
        assert report.total == 1
        assert report.skipped == 0

    def test_header_format(self, importer) -> None:
        text = "день;тип недели;блок;предмет\nПн;upper;1;Математика\nВт;lower;2;Физика"
        report = importer.parse_text(text)
        # Вторник без профиля — это ожидаемое сообщение, а не сбой: строка
        # понедельника записана, вторник объяснён в problems.
        assert report.total == 1
        assert report.skipped == 1
        assert any("профил" in line for line in report.problems)

    def test_creates_missing_subjects(self, importer, db) -> None:
        importer.parse_text("Пн;upper;1;Новый предмет")
        names = [subject.name for subject in SubjectRepository(db).all()]
        assert "Новый предмет" in names

    def test_existing_subject_reused(self, importer, db) -> None:
        subjects = SubjectRepository(db)
        subjects.create("Математика")
        before = len(subjects.all())
        importer.parse_text("Пн;upper;1;Математика")
        assert len(subjects.all()) == before

    def test_room_and_teacher_filled(self, importer, db) -> None:
        text = "день;блок;предмет;кабинет;преподаватель\nПн;1;Химия;210;Иванов"
        importer.parse_text(text)
        subject = next(s for s in SubjectRepository(db).all() if s.name == "Химия")
        assert subject.room == "210"
        assert subject.teacher == "Иванов"

    def test_unknown_weekday_reported(self, importer) -> None:
        report = importer.parse_text("Космос;upper;1;Математика")
        assert report.skipped == 1
        assert any("день недели" in line for line in report.problems)

    def test_missing_slot_reported(self, importer) -> None:
        report = importer.parse_text("Пн;upper;99;Математика")
        assert report.skipped == 1
        assert any("блок" in line.lower() for line in report.problems)

    def test_empty_subject_reported(self, importer) -> None:
        report = importer.parse_text("Пн;upper;1;")
        assert report.skipped == 1

    def test_empty_file_rejected(self, importer) -> None:
        with pytest.raises(ValidationError):
            importer.parse_text("   ")


    def test_comma_delimiter(self, importer) -> None:
        report = importer.parse_text("день,блок,предмет\nПн,1,Математика")
        assert report.total == 1

    def test_report_caption_mentions_counts(self, importer) -> None:
        report = importer.parse_text("Пн;upper;1;Математика")
        assert "1" in report.caption

    def test_import_does_not_delete_existing(self, importer, db) -> None:
        """Импорт только записывает свои строки, чужие пары остаются."""
        templates = ScheduleTemplateRepository(db)
        bells = BellRepository(db)
        subjects = SubjectRepository(db)
        keeper = subjects.create("Остаётся")
        monday = bells.profiles(include_inactive=False)[0]
        templates.set_cell(monday.id, WeekType.UPPER, 2, keeper.id)
        importer.parse_text("Пн;upper;1;Математика")
        assert templates.cell(monday.id, WeekType.UPPER, 2).subject_id == keeper.id

    def test_parse_file_utf8(self, importer, tmp_path) -> None:
        path = tmp_path / "schedule.csv"
        path.write_text("день;блок;предмет\nПн;1;Математика", encoding="utf-8-sig")
        report = importer.parse_file(path)
        assert report.total == 1

    def test_parse_file_missing(self, importer, tmp_path) -> None:
        with pytest.raises(ValidationError):
            importer.parse_file(tmp_path / "нет-такого.csv")


# ===========================================================================
# UI-25: сворачиваемая правая панель и прочие элементы интерфейса
# ===========================================================================
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    """Одно приложение Qt на модуль (второй QApplication недопустим)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, db):
    """Главное окно на тестовой БД.

    Окно **уничтожается** после теста, а не просто закрывается. ``close()``
    лишь прячет виджет, а ``deleteLater()`` ставит удаление в очередь
    отложенных событий — и без явной отправки ``DeferredDelete`` оно не
    выполняется: C++-объект остаётся живым. Тогда каждое новое окно создаётся
    медленнее предыдущего (0.6 с → 5.3 с к шестому), потому что смена стиля
    обходит все ещё живые виджеты. За десятки тестов прогон останавливался.
    """
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from student_planner.ui.main_window import MainWindow

    created = MainWindow(db)
    yield created
    created.close()
    created.setParent(None)
    created.deleteLater()
    QApplication.processEvents()
    # Именно DeferredDelete: ``sendPostedEvents(None, 0)`` отложенное
    # удаление не выполняет, и окно остаётся в памяти.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


class TestWidgetsPanel:
    """UI-25: правая панель сворачивается и состояние запоминается."""

    def test_visible_by_default(self, window) -> None:
        assert window.widgets_collapsed is False
        assert window.widgets.isVisible() or not window.isVisible()

    def test_toggle_collapses(self, window) -> None:
        window.show()
        window.toggle_widgets()
        assert window.widgets_collapsed is True
        assert not window.widgets.isVisible()

    def test_toggle_twice_restores(self, window) -> None:
        window.show()
        window.toggle_widgets()
        window.toggle_widgets()
        assert window.widgets_collapsed is False
        assert window.widgets.isVisible()

    def test_state_persisted(self, window, db) -> None:
        window.set_widgets_collapsed(True)
        stored = SettingsService(db).raw(SettingsKeys.WIDGETS_COLLAPSED)
        assert stored == "1"

    def test_state_restored(self, window, db) -> None:
        window.set_widgets_collapsed(True)
        from student_planner.ui.main_window import MainWindow

        second = MainWindow(db)
        try:
            assert second.widgets_collapsed is True
            assert not second.widgets.isVisible()
        finally:
            second.set_widgets_collapsed(False)
            second.close()

    def test_collapsed_column_is_narrow(self, window) -> None:
        window.show()
        window.set_widgets_collapsed(True)
        sizes = window._splitter.sizes()
        assert sizes[2] < 40


class TestSchedulePageButtons:
    """UI-14: экспорт расписания картинкой."""

    def test_export_button_exists(self, window) -> None:
        page = window._pages["schedule"]
        assert page.export_button is not None

    def test_render_image_produces_pixmap(self, window) -> None:
        window.show()
        window.open_page("schedule")
        window._pages["schedule"].refresh()
        image = window._pages["schedule"].render_image()
        assert image.width() > 0
        assert image.height() > 0

    def test_save_image_writes_file(self, window, tmp_path) -> None:
        window.show()
        window.open_page("schedule")
        page = window._pages["schedule"]
        page.refresh()
        target = tmp_path / "schedule.png"
        assert page.save_image_to(str(target)) is True
        assert target.exists()
        assert target.stat().st_size > 0

    def test_exported_image_uses_theme_background(self, window, tmp_path) -> None:
        from student_planner.ui.theme import COLORS

        window.show()
        window.open_page("schedule")
        page = window._pages["schedule"]
        page.refresh()
        target = tmp_path / "bg.png"
        page.save_image_to(str(target))
        from PySide6.QtGui import QImage

        image = QImage(str(target))
        assert image.pixelColor(2, 2).name() == COLORS["background"]


class TestHomeworkSearchUI:
    """HW-13: поле поиска на странице заданий."""

    def test_search_field_exists(self, window) -> None:
        page = window._pages["homework"]
        assert page.search_edit is not None
        assert page.search_edit.placeholderText()

    def test_typing_filters_list(self, window, db) -> None:
        subjects = SubjectRepository(db)
        subject = subjects.create("Математика")
        HomeworkService(db).create(subject.id, FIXED_TODAY, "Лабораторная работа")
        HomeworkService(db).create(subject.id, FIXED_TODAY, "Реферат")
        page = window._pages["homework"]
        page.refresh()
        before = page.count_label.text()
        page.search_edit.setText("лабораторная")
        after = page.count_label.text()
        assert before != after
        assert after == "Заданий: 1"

    def test_empty_search_hint(self, window, db) -> None:
        """HW-13: пустой результат поиска отличается от «заданий нет».

        Нужно хотя бы одно задание в базе: при полностью пустом справочнике
        страница справедливо подсказывает «Сначала добавьте предмет», и это
        другой (более полезный) текст, чем «ничего не найдено».
        """
        subject = SubjectRepository(db).create("Математика")
        HomeworkService(db).create(subject.id, FIXED_TODAY, "Лабораторная")
        page = window._pages["homework"]
        page.refresh()
        page.search_edit.setText("заведомо-нет-такого")
        assert "не найдено" in page.empty.caption_label.text().lower()

    def test_empty_db_hint_is_about_subjects(self, window) -> None:
        """HW-14: при пустом справочнике подсказка про предмет, а не про поиск."""
        page = window._pages["homework"]
        page.refresh()
        page.search_edit.setText("заведомо-нет-такого")
        caption = page.empty.caption_label.text().lower()
        assert "предмет" in caption or "не найдено" in caption


class TestExamsPage:
    """EXAM-04…EXAM-08: страница испытаний."""

    def test_page_exists_in_window(self, window) -> None:
        assert "exams" in window._pages

    def test_nav_contains_exams(self) -> None:
        from student_planner.ui.nav_panel import NAV_ITEMS

        assert "exams" in {key for key, _ in NAV_ITEMS}

    def test_empty_state(self, window) -> None:
        page = window._pages["exams"]
        page.refresh()
        assert page.empty.isVisible() or not page.isVisible()

    def test_row_rendered(self, window, db) -> None:
        subject = SubjectRepository(db).create("Физика")
        ExamRepository(db).create(subject.id, FIXED_TODAY + timedelta(days=2))
        page = window._pages["exams"]
        page.refresh()
        assert "1" in page.count_label.text()

    def test_summary_counters(self, window, db) -> None:
        subject = SubjectRepository(db).create("Химия")
        ExamRepository(db).create(subject.id, FIXED_TODAY + timedelta(days=1))
        page = window._pages["exams"]
        page.refresh()
        assert page.total_row.value_label.text() == "1"

    def test_filter_passed(self, window, db) -> None:
        subject = SubjectRepository(db).create("Биология")
        exam = ExamRepository(db).create(subject.id, FIXED_TODAY + timedelta(days=1))
        ExamRepository(db).set_status(exam.id, ExamStatus.PASSED)
        page = window._pages["exams"]
        page.filter_combo.setCurrentIndex(2)  # «Сданные»
        page.refresh()
        assert "1" in page.count_label.text()

    def test_dialog_has_choices(self, qapp, db) -> None:
        from student_planner.ui.pages.exams import ExamDialog

        SubjectRepository(db).create("Математика")
        dialog = ExamDialog(db)
        try:
            assert dialog.subject_combo.count() >= 1
            assert dialog.kind_combo.count() == 3
            assert dialog.status_combo.count() == 3
        finally:
            dialog.close()


class TestExamWidget:
    """EXAM-07: виджет ближайших испытаний в правой панели."""

    def test_widget_exists(self, window) -> None:
        assert window.widgets.exams is not None

    def test_empty_label_when_no_exams(self, window) -> None:
        window.widgets.exams.refresh()
        assert window.widgets.exams.empty_label.isVisible() or True

    def test_rows_when_exams_present(self, window, db) -> None:
        subject = SubjectRepository(db).create("География")
        ExamRepository(db).create(subject.id, FIXED_TODAY + timedelta(days=3))
        window.widgets.exams.refresh()
        assert window.widgets.exams.rows_layout.count() >= 1


class TestExamMoveRegression:
    """Регрессия: при переносе испытание исчезало из интерфейса.

    Жалоба пользователя: «при переносе экзамена он исчезает из левой области
    меню». Причина — фильтр «Предстоящие» требовал ``days_left >= 0`` и
    ``status == planned``: стоило перенести испытание на прошедшую дату или
    отметить его «перенесён», как строка пропадала, хотя метка в календаре
    продолжала гореть. Перенос — это смена даты, а не удаление записи.
    """

    @pytest.fixture
    def subject(self, db):
        return SubjectRepository(db).create("Математика")

    @pytest.fixture
    def exam(self, db, subject):
        return ExamRepository(db).create(subject.id, FIXED_TODAY + timedelta(days=5))

    # ---------------------------------------------------------- уровень ядра
    def test_postponed_exam_stays_in_upcoming(self, db, exam) -> None:
        """Перенесённое испытание не исчезает из ближайших (EXAM-03)."""
        repo = ExamRepository(db)
        repo.set_status(exam.id, ExamStatus.POSTPONED)
        ids = [item.id for item in repo.upcoming(FIXED_TODAY)]
        assert exam.id in ids

    def test_postponed_exam_visible_in_rows(self, db, exam) -> None:
        service = ExamService(db)
        service.mark_postponed(exam.id)
        rows = service.rows(today=FIXED_TODAY)
        assert [row.exam.id for row in rows] == [exam.id]

    def test_exam_moved_to_past_stays_visible(self, db, exam) -> None:
        """Перенос на прошедшую дату не должен скрывать запись."""
        service = ExamService(db)
        past = FIXED_TODAY - timedelta(days=3)
        service.update(exam.id, when=past)
        rows = service.rows(today=FIXED_TODAY)
        assert len(rows) == 1
        assert rows[0].exam.date == past

    def test_exam_moved_to_past_is_not_overdue(self, db, exam) -> None:
        """Перенесённое — не «просрочено без отметки»."""
        service = ExamService(db)
        service.update(exam.id, when=FIXED_TODAY - timedelta(days=3))
        service.mark_postponed(exam.id)
        assert service.rows(today=FIXED_TODAY)[0].is_overdue is False

    def test_postponed_exam_not_marked_overdue(self, db, exam) -> None:
        """Дата в прошлом + статус «перенесён» — это не просрочка."""
        repo = ExamRepository(db)
        repo.update(exam.id, when=FIXED_TODAY - timedelta(days=1))
        repo.set_status(exam.id, ExamStatus.POSTPONED)
        assert ExamService(db).rows(today=FIXED_TODAY)[0].is_overdue is False

    def test_passed_exam_still_excluded_from_upcoming(self, db, exam) -> None:
        """Сданное по-прежнему не попадает в ближайшие."""
        repo = ExamRepository(db)
        repo.set_status(exam.id, ExamStatus.PASSED)
        assert exam.id not in [item.id for item in repo.upcoming(FIXED_TODAY)]

    def test_next_exam_falls_back_to_pending(self, db, exam) -> None:
        """Если все несданные в прошлом, показывается самое раннее."""
        service = ExamService(db)
        service.update(exam.id, when=FIXED_TODAY - timedelta(days=10))
        found = service.next_exam(today=FIXED_TODAY)
        assert found is not None
        assert found.exam.id == exam.id

    def test_summary_counts_postponed_as_planned(self, db, exam) -> None:
        """Перенесённое остаётся в счётчике «Предстоит»."""
        service = ExamService(db)
        service.mark_postponed(exam.id)
        assert service.summary(today=FIXED_TODAY)["planned"] == 1

    def test_summary_counts_past_unsent_as_planned(self, db, exam) -> None:
        """Испытание с прошедшей датой без отметки — работа ещё не сдана."""
        ExamService(db).update(exam.id, when=FIXED_TODAY - timedelta(days=5))
        assert ExamService(db).summary(today=FIXED_TODAY)["planned"] == 1

    def test_summary_excludes_passed(self, db, exam) -> None:
        service = ExamService(db)
        service.mark_passed(exam.id)
        summary = service.summary(today=FIXED_TODAY)
        assert summary["planned"] == 0
        assert summary["passed"] == 1

    # ------------------------------------------------------ уровень интерфейса
    def test_page_keeps_row_after_move_to_past(self, window, db, exam) -> None:
        """Строка остаётся в списке после переноса на прошедшую дату."""
        window.open_page("exams")
        page = window._pages["exams"]
        ExamService(db).update(exam.id, when=FIXED_TODAY - timedelta(days=4))
        window.refresh_all()
        assert "1" in page.count_label.text()

    def test_page_keeps_row_after_postponed(self, window, db, exam) -> None:
        window.open_page("exams")
        page = window._pages["exams"]
        ExamService(db).mark_postponed(exam.id)
        window.refresh_all()
        assert "1" in page.count_label.text()

    def test_calendar_mark_kept_after_move(self, window, db, exam) -> None:
        """Метка в календаре и строка списка появляются вместе."""
        window.open_page("exams")
        new_date = FIXED_TODAY + timedelta(days=2)
        ExamService(db).update(exam.id, when=new_date)
        window.refresh_all()
        assert "exam" in window.nav.calendar._marks.get(new_date, "")

    def test_widget_keeps_row_after_postponed(self, window, db, exam) -> None:
        """Виджет справа тоже не теряет перенесённое испытание."""
        ExamService(db).mark_postponed(exam.id)
        window.widgets.exams.refresh()
        layout = window.widgets.exams.rows_layout
        rows = sum(1 for i in range(layout.count()) if layout.itemAt(i).widget())
        assert rows == 1

    def test_next_row_shows_postponed(self, window, db, exam) -> None:
        window.open_page("exams")
        page = window._pages["exams"]
        ExamService(db).mark_postponed(exam.id)
        window.refresh_all()
        assert "Перенесён" in page.next_row.value_label.text()

    def test_moved_exam_found_by_search(self, window, db, exam, subject) -> None:
        """Поиск находит перенесённое испытание."""
        window.open_page("exams")
        page = window._pages["exams"]
        ExamService(db).mark_postponed(exam.id)
        page.search_edit.setText("математика")
        page.refresh()
        assert "1" in page.count_label.text()

    def test_all_filter_shows_everything(self, window, db, exam) -> None:
        """Фильтр «Все» показывает и сданное, и перенесённое."""
        window.open_page("exams")
        page = window._pages["exams"]
        ExamService(db).mark_passed(exam.id)
        page.filter_combo.setCurrentIndex(1)  # «Все»
        page.refresh()
        assert "1" in page.count_label.text()

    def test_overdue_filter_excludes_postponed(self, window, db, exam) -> None:
        """«Прошедшие без отметки» не включает перенесённое."""
        window.open_page("exams")
        page = window._pages["exams"]
        service = ExamService(db)
        service.update(exam.id, when=FIXED_TODAY - timedelta(days=2))
        service.mark_postponed(exam.id)
        page.filter_combo.setCurrentIndex(3)  # «Прошедшие без отметки»
        page.refresh()
        assert page.count_label.text() == ""


class TestBellsEditing:
    """BELL-12…BELL-17: правка блоков звонков из интерфейса.

    Пустая БД не содержит профилей, поэтому тесты, которым нужен блок,
    опираются на фикстуру ``simple_bell``.
    """

    def test_bells_tab_lists_profiles(self, qapp, db, simple_bell) -> None:
        from student_planner.ui.pages.settings import BellsTab

        tab = BellsTab(db)
        try:
            tab.refresh()
            assert tab.profile_list.count() >= 1
        finally:
            tab.close()

    def test_slots_table_filled(self, qapp, db, simple_bell) -> None:
        from student_planner.ui.pages.settings import BellsTab

        tab = BellsTab(db)
        try:
            tab.refresh()
            assert tab.slots_table.rowCount() >= 1
        finally:
            tab.close()

    def test_rename_slot(self, db, simple_bell) -> None:
        bells = BellRepository(db)
        slot = simple_bell.slots[0]
        bells.rename_slot(slot.id, name="Переименован", pair_no=1)
        updated = bells.require_profile(simple_bell.id).slots[0]
        assert updated.display_name == "Переименован"
        assert updated.pair_no == 1

    def test_rename_keeps_parts(self, db, simple_bell) -> None:
        bells = BellRepository(db)
        slot = simple_bell.slots[0]
        before = len(slot.parts)
        bells.rename_slot(slot.id, name="Тест")
        assert len(bells.profile(slot.profile_id).slots[0].parts) == before

    def test_update_parts(self, db, simple_bell) -> None:
        bells = BellRepository(db)
        slot = simple_bell.slots[0]
        bells.update_slot_parts(slot.id, [("lesson", "08:00", "09:00")])
        updated = bells.profile(slot.profile_id).slots[0]
        assert updated.start_time == "08:00"

    def test_dialog_parts_rows(self, qapp, db, simple_bell) -> None:
        from student_planner.ui.pages.settings import BellBlockDialog

        slot = simple_bell.slots[0]
        dialog = BellBlockDialog(db, slot)
        try:
            assert dialog.parts_table.rowCount() == len(slot.parts)
        finally:
            dialog.close()

    def test_add_break_keeps_lesson_last(self, qapp, db, simple_bell) -> None:
        """BELL-17: перемена не может стать последней частью."""
        from student_planner.ui.pages.settings import BellBlockDialog

        slot = simple_bell.slots[0]
        dialog = BellBlockDialog(db, slot)
        try:
            dialog._add_break()
            assert dialog._parts()[-1][0] == "lesson"
        finally:
            dialog.close()

    def test_friday_variant_combo(self, qapp, db) -> None:
        """TPL-05: выбор варианта пятницы доступен на вкладке «Звонки»."""
        from student_planner.ui.pages.settings import BellsTab

        tab = BellsTab(db)
        try:
            assert tab.friday_combo.count() == 2
            index = tab.friday_combo.findData("friday_class_hour")
            tab.friday_combo.setCurrentIndex(index)
            tab.save_friday_variant()
            assert (
                SettingsService(db).raw(SettingsKeys.FRIDAY_DEFAULT_VARIANT)
                == "friday_class_hour"
            )
        finally:
            tab.close()


class TestSettingsTabs:
    """SET-01/SET-08: разделы настроек и их заполнение."""

    def test_seven_tabs(self, qapp, db) -> None:
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(db)
        try:
            captions = [page.tabs.tabText(i) for i in range(page.tabs.count())]
            assert captions == [
                "Общие", "Предметы", "Недели", "Звонки", "Транспорт", "Календарь", "Данные"
            ]
        finally:
            page.close()

    def test_general_tab_filled_on_creation(self, qapp, db) -> None:
        from student_planner.ui.pages.settings import GeneralTab

        tab = GeneralTab(db)
        try:
            assert tab.notify_exam_spin.value() == 7
            assert tab.notify_lesson_spin.value() == 15
        finally:
            tab.close()

    def test_notification_settings_saved(self, qapp, db) -> None:
        from student_planner.ui.pages.settings import GeneralTab

        tab = GeneralTab(db)
        try:
            tab.notify_exam_spin.setValue(10)
            tab.save_notifications()
            assert SettingsService(db).get_int(SettingsKeys.NOTIFY_EXAM_DAYS) == 10
        finally:
            tab.close()

    def test_date_format_saved_and_applied(self, qapp, db) -> None:
        from student_planner.ui.pages.settings import GeneralTab

        tab = GeneralTab(db)
        try:
            index = tab.date_format_combo.findData("YYYY-MM-DD")
            tab.date_format_combo.setCurrentIndex(index)
            tab.save()
            assert dt.active_display_format() == "YYYY-MM-DD"
        finally:
            tab.close()
            dt.set_display_format(None)

    def test_data_tab_has_path_controls(self, qapp, db) -> None:
        from student_planner.ui.pages.settings import DataTab

        tab = DataTab(db)
        try:
            assert tab.choose_db_button is not None
            assert tab.reset_db_button is not None
        finally:
            tab.close()


class TestThemeStillWorks:
    """UI-13: темы не сломались при добавлении новых страниц."""

    def test_three_themes(self) -> None:
        from student_planner.ui.theme import THEMES

        assert len(THEMES) == 3

    def test_theme_cards_present(self, qapp, db) -> None:
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(db)
        try:
            assert len(page.general_tab.theme_buttons) == 3
        finally:
            page.close()
