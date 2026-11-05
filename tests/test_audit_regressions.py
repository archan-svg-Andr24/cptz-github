"""Регрессионные тесты на дефекты, найденные при сквозном аудите.

Каждый тест воспроизводит конкретную поломку, которая была в приложении —
с указанием, что именно ломалось. Цель: не дать этим дефектам вернуться.

Разделы:

* SET-02/SET-05 — форматы даты и сохранение настроек;
* BELL-12…BELL-17 — правка блоков звонков;
* OVR-07/OVR-08 — занятость блока после очистки ячейки (TPL-08);
* CALC-04 — атомарность подтверждения дня;
* REP-09 — пополнения за период;
* ALG-02 — номер следующей поездки и границы периода;
* NOTIF-05 — предупреждение о низком остатке;
* BELL-19 — версионный профиль звонков в редакторе сетки;
* GRID-11 — замена недели;
* UI-03/UI-06 — выбранная дата доходит до всех страниц;
* SET-07 — резервные копии и сброс данных;
* DATA-19 — повреждённый файл базы.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from student_planner.core.database import create_database, is_initialized
from student_planner.core.exam_repository import ExamRepository
from student_planner.core.exam_service import ExamService
from student_planner.core.errors import AppError, RuleViolationError
from student_planner.core.models import ExamKind, WeekType
from student_planner.core.notification_service import NotificationService
from student_planner.core.recalculation import RecalculationService
from student_planner.core.repositories import (
    BellRepository,
    ScheduleTemplateRepository,
    SubjectRepository,
)
from student_planner.core.schedule_service import GridService, HomeworkService, OverrideService
from student_planner.core.day_resolution import DayResolver
from student_planner.core.settings_registry import SettingsKeys
from student_planner.core.settings_service import SettingsService
from student_planner.core.transport_repositories import RideRepository, TopUpRepository
from student_planner.core.transport_service import JournalFilter, TransportService
from student_planner.core.trip_service import TripPlanService
from student_planner.core import dates as dt

FIXED_TODAY = date(2026, 10, 20)


# ===========================================================================
# SET-02/SET-05 — настройки: форматы и сохранение
# ===========================================================================
class TestSettingsPersistence:
    """SET-02: правки не должны теряться или стирать чужие значения."""

    def test_college_and_home_survive_save(self, qapp, db) -> None:
        """Колледж и домашняя точка не стираются при сохранении «Общих».

        Раньше поля не заполнялись из БД, и «Сохранить» записывал пустоту —
        данные исчезали без предупреждения.
        """
        from student_planner.ui.pages.settings import GeneralTab

        settings = SettingsService(db)
        settings.set(SettingsKeys.COLLEGE_NAME, "Колледж №54")
        settings.set(SettingsKeys.HOME_POINT_NAME, "Тёплый Стан")
        tab = GeneralTab(db)
        try:
            assert tab.college_edit.text() == "Колледж №54"
            assert tab.home_edit.text() == "Тёплый Стан"
            tab.save()
            assert settings.raw(SettingsKeys.COLLEGE_NAME) == "Колледж №54"
            assert settings.raw(SettingsKeys.HOME_POINT_NAME) == "Тёплый Стан"
        finally:
            tab.close()

    def test_anchor_date_does_not_block_other_fields(self, qapp, db) -> None:
        """Дата начала учёта показана в формате UI, но сохраняется в ISO.

        Раньше в базу писался текст поля («01.09.2026»), проверка отклоняла
        сохранение, и вместе с ним отменялись все остальные поля формы.
        """
        from student_planner.ui.pages.settings import TransportTab
        from PySide6.QtWidgets import QSpinBox

        settings = SettingsService(db)
        settings.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "2026-09-01")
        tab = TransportTab(db)
        try:
            tab.refresh()
            assert tab.anchor_edit.text() == "01.09.2026"
            spins = tab.findChildren(QSpinBox)
            spins[2].setValue(7)  # порог предупреждения
            tab.save()
            assert settings.raw(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE) == "2026-09-01"
            assert settings.raw(SettingsKeys.STRELKA_LOW_BALANCE_WARN) == "7"
        finally:
            tab.close()


# ===========================================================================
# BELL-12…BELL-17 — блоки звонков
# ===========================================================================
class TestBellBlockEditing:
    """BELL-13: правка блока должна сохраняться."""

    def test_block_dialog_saves_name_and_parts(self, qapp, db, simple_bell) -> None:
        """«Сохранить» в диалоге блока действительно пишет в базу.

        ``BaseDialog`` вызывает ``apply``, а диалог определял ``save`` — правка
        закрывалась «успешно» и терялась целиком.
        """
        from student_planner.ui.pages.settings import BellBlockDialog

        bells = BellRepository(db)
        slot = simple_bell.slots[0]
        dialog = BellBlockDialog(db, slot)
        try:
            dialog.name_edit.setText("Новое имя")
            dialog.pair_spin.setValue(4)
            dialog.buttons.accepted.emit()
            updated = bells.require_profile(simple_bell.id).slots[0]
            assert updated.display_name == "Новое имя"
            assert updated.pair_no == 4
        finally:
            dialog.close()

    def test_add_slot_creates_block_with_parts(self, qapp, db, simple_bell) -> None:
        """«Добавить блок» создаёт блок с частями.

        Без частей репозиторий бросал ``ValidationError`` (BELL-02), и кнопка
        не работала вовсе.
        """
        from student_planner.ui.pages.settings import BellsTab

        bells = BellRepository(db)
        tab = BellsTab(db)
        try:
            tab.refresh()
            profile = tab._current_profile()
            start, end = tab._next_block_time(profile)
            created = bells.add_slot(
                profile.id, "pair", pair_no=len(profile.slots) + 1,
                parts=[("lesson", start, end)],
            )
            assert created.parts, "у нового блока должны быть части"
        finally:
            tab.close()

    def test_next_block_time_follows_last(self, db, simple_bell) -> None:
        """Новый блок ставится после последнего, без пересечений (BELL-17)."""
        from student_planner.ui.pages.settings import BellsTab

        start, end = BellsTab._next_block_time(simple_bell)
        last_end = max(slot.end_time for slot in simple_bell.slots if slot.end_time)
        assert dt.time_to_minutes(start) > dt.time_to_minutes(last_end)

    def test_next_block_time_first_block(self, db) -> None:
        """Для профиля без блоков берётся 08:30."""
        from student_planner.ui.pages.settings import BellsTab

        profile = BellRepository(db).create_profile(3, "Пустой профиль")
        assert BellsTab._next_block_time(profile) == ("08:30", "09:15")


# ===========================================================================
# TPL-08 / OVR-07 — занятость блока после очистки
# ===========================================================================
class TestClearedCellIsFree:
    """После «Очистить» в сетке блок должен стать свободным."""

    @pytest.fixture
    def setup(self, db):
        WeekAnchorRepository_setup(db)
        self.subjects = SubjectRepository(db)
        self.first = self.subjects.create("Первый")
        self.second = self.subjects.create("Второй")
        self.profile = BellRepository(db).create_profile(FIXED_TODAY.isoweekday(), "День")
        bells = BellRepository(db)
        bells.add_slot(self.profile.id, "pair", display_name="1", pair_no=1,
                       parts=[("lesson", "08:30", "09:15")])
        bells.add_slot(self.profile.id, "pair", display_name="2", pair_no=2,
                       parts=[("lesson", "09:25", "10:10")])
        self.profile = bells.require_profile(self.profile.id)
        self.templates = ScheduleTemplateRepository(db)
        return db

    def test_add_allowed_after_clear(self, setup) -> None:
        """Очищенная ячейка считается свободной (раньше — тупик OVR-08)."""
        when = FIXED_TODAY
        week = WeekType.UPPER
        self.templates.set_cell(self.profile.id, week, 1, self.first.id)
        self.templates.clear_cell(self.profile.id, week, 1, effective_from=FIXED_TODAY)
        assert self.templates.subject_at(self.profile.id, week, 1, on_date=when) is None
        service = OverrideService(setup)
        service.add(when, self.profile.id, 1, subject_id=self.second.id)
        resolved = DayResolver(setup).resolve(when)
        names = [lesson.subject.name for lesson in resolved.lessons if lesson.slot_no == 1]
        assert names == ["Второй"]

    def test_occupied_cell_still_protected(self, setup) -> None:
        """Занятый блок по-прежнему нельзя занять добавлением."""
        self.templates.set_cell(self.profile.id, WeekType.UPPER, 2, self.first.id)
        with pytest.raises(RuleViolationError):
            OverrideService(setup).add(
                FIXED_TODAY, self.profile.id, 2, subject_id=self.second.id
            )


def WeekAnchorRepository_setup(db) -> None:
    """Якорь верхней недели на дату теста (ALG-01)."""
    from student_planner.core.repositories import WeekAnchorRepository

    if not WeekAnchorRepository(db).all():
        WeekAnchorRepository(db).create(FIXED_TODAY, FIXED_TODAY, WeekType.UPPER)


# ===========================================================================
# CALC-04 — атомарность подтверждения дня
# ===========================================================================
class TestConfirmAtomicity:
    """CALC-04: сбой пересчёта не оставляет полуподтверждённый день."""

    def test_failed_recalculation_rolls_back(self, db, monkeypatch) -> None:
        """При сбое пересчёта не остаётся ни поездок, ни подтверждения.

        Раньше ``recalculate`` вызывался после ``commit``: пользователь видел
        ошибку, а в базе оставался день с поездками и одинаковыми номерами.
        """
        from student_planner.core.transport_repositories import TripConfirmationRepository

        db = _seeded(db)
        service = TripPlanService(db)
        day = FIXED_TODAY

        def boom(self, *args, **kwargs):
            raise RuntimeError("искусственный сбой пересчёта")

        monkeypatch.setattr(RecalculationService, "recalculate", boom)
        with pytest.raises(RuntimeError):
            service.confirm(day)
        assert RideRepository(db).for_date(day) == []
        assert TripConfirmationRepository(db).by_date(day) is None


# ===========================================================================
# REP-09 — пополнения за период
# ===========================================================================
class TestReportTopupsPeriod:
    """REP-09: «Пополнено» учитывается в границах периода."""

    @pytest.fixture
    def wallet(self, db):
        topups = TopUpRepository(db)
        topups.create(date(2026, 8, 1), "1000.00")
        topups.create(date(2026, 9, 10), "200.00")
        return TransportService(db)

    def test_single_day(self, wallet) -> None:
        """Отчёт за один день не включает прошлые пополнения."""
        report = wallet.report(JournalFilter(date_from=date(2026, 9, 10), date_to=date(2026, 9, 10)))
        assert report.topups == Decimal("200.00")

    def test_month(self, wallet) -> None:
        report = wallet.report(JournalFilter(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)))
        assert report.topups == Decimal("200.00")

    def test_all_time(self, wallet) -> None:
        assert wallet.report(JournalFilter()).topups == Decimal("1200.00")

    def test_only_upper_bound(self, wallet) -> None:
        report = wallet.report(JournalFilter(date_to=date(2026, 9, 10)))
        assert report.topups == Decimal("1200.00")


# ===========================================================================
# ALG-02 — номер поездки и границы периода
# ===========================================================================
class TestStrellaStateEdges:
    """ALG-02: номер следующей поездки и границы периода."""

    def test_initial_count_used_when_no_rides(self, db) -> None:
        """Без поездок номер = cnt0 + 1 (а не 1).

        Раньше стояла жёсткая единица, и после мастера первого запуска
        программа показывала неверный номер и неверную ступень скидки.
        """
        settings = SettingsService(db)
        settings.set(SettingsKeys.STRELKA_INITIAL_RIDE_COUNT, "34")
        settings.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "2026-09-01")
        state = TransportService(db).strella_state(today=date(2026, 9, 20))
        assert state.next_ride_number == 35

    def test_before_anchor_has_no_period(self, db) -> None:
        """До начала учёта границы периода не выдумываются.

        Раньше вместо отсутствующей границы подставлялся ``base``, и в
        интерфейсе появлялись «01.09 — 30.09» и «№None» для даты, которая
        ещё не входит ни в один период.
        """
        settings = SettingsService(db)
        settings.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, "2026-09-01")
        state = TransportService(db).strella_state(today=date(2026, 8, 15))
        assert state.period_start is None
        assert state.period_end is None
        # Период не начался — значит и «следующей поездки в периоде» нет.
        assert state.started is False


# ===========================================================================
# NOTIF-05 — низкий остаток «Стрелки»
# ===========================================================================
class TestLowBalanceNotification:
    """NOTIF-05: предупреждение о низком остатке должно работать."""

    def test_warns_when_balance_low(self, db) -> None:
        """При малом остатке напоминание появляется.

        Раньше вызывался несуществующий ``strelka_balance()``, исключение
        съедалось ``except``, и этот вид напоминаний молчал всегда.
        """
        _seeded(db)
        settings = SettingsService(db)
        settings.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, FIXED_TODAY.isoformat())
        settings.set(SettingsKeys.STRELKA_LOW_BALANCE_WARN, "5")
        TopUpRepository(db).create(FIXED_TODAY, "10.00")
        items = NotificationService(db)._balance_items(FIXED_TODAY)
        assert len(items) == 1
        assert "Стрелки" in items[0].title

    def test_silent_when_balance_enough(self, db) -> None:
        _seeded(db)
        settings = SettingsService(db)
        settings.set(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE, FIXED_TODAY.isoformat())
        settings.set(SettingsKeys.STRELKA_LOW_BALANCE_WARN, "5")
        TopUpRepository(db).create(FIXED_TODAY, "5000.00")
        assert NotificationService(db)._balance_items(FIXED_TODAY) == []


# ===========================================================================
# BELL-19 — версионный профиль звонков
# ===========================================================================
class TestVersionedBellProfile:
    """BELL-19: редактор сетки и день используют один профиль."""

    def test_grid_and_day_agree_before_and_after_change(self, db) -> None:
        """До смены профиля и после — редактор и день смотрят на один профиль."""
        bells = BellRepository(db)
        base = bells.create_profile(1, "Понедельник базовый")
        bells.add_slot(base.id, "pair", display_name="1", pair_no=1,
                       parts=[("lesson", "08:30", "09:15")])
        winter = bells.create_profile(1, "Понедельник зимний", effective_from=date(2026, 11, 1))
        bells.add_slot(winter.id, "pair", display_name="1", pair_no=1,
                       parts=[("lesson", "09:00", "09:45")])
        for when in (date(2026, 10, 19), date(2026, 11, 9)):
            grid_id = GridService(db).view("upper", weekdays=(1,), on_date=when).columns[0].profile_id
            day = DayResolver(db).profile_for(when)
            assert grid_id == (day.id if day else None), (
                f"{when}: редактор показывает профиль {grid_id}, а день — {day.id if day else None}"
            )


# ===========================================================================
# GRID-11 — замена недели
# ===========================================================================
class TestReplaceWeek:
    """GRID-11: замена недели очищает отсутствующие позиции."""

    def test_missing_positions_are_cleared(self, db) -> None:
        """Слоты, которых нет в новом наборе, исчезают из будущих недель.

        Раньше базовые версии переживали удаление и снова становились
        действующими — удалённые пары оставались в расписании.
        """
        WeekAnchorRepository_setup(db)
        subjects = SubjectRepository(db)
        profile = BellRepository(db).create_profile(FIXED_TODAY.isoweekday(), "День")
        bells = BellRepository(db)
        for number, (start, end) in enumerate(
            (("08:30", "09:15"), ("09:25", "10:10"), ("10:20", "11:05")), start=1
        ):
            bells.add_slot(profile.id, "pair", display_name=str(number), pair_no=number,
                           parts=[("lesson", start, end)])
        templates = ScheduleTemplateRepository(db)
        saved = [subjects.create(f"Предмет {n}") for n in range(1, 4)]
        for number, subject in zip((1, 2, 3), saved):
            templates.set_cell(profile.id, WeekType.UPPER, number, subject.id)
        # Замена действует с FIXED_TODAY, поэтому «прошлое» — на день раньше.
        past = FIXED_TODAY - timedelta(days=1)
        future = FIXED_TODAY + timedelta(days=7)
        templates.replace_week(
            WeekType.UPPER, [(profile.id, 1, saved[0].id)], effective_from=FIXED_TODAY
        )
        assert templates.subject_at(profile.id, WeekType.UPPER, 1, on_date=future) == saved[0].id
        assert templates.subject_at(profile.id, WeekType.UPPER, 2, on_date=future) is None
        assert templates.subject_at(profile.id, WeekType.UPPER, 3, on_date=future) is None
        # Прошлое не тронуто — там прежний набор целиком.
        assert templates.subject_at(profile.id, WeekType.UPPER, 2, on_date=past) == saved[1].id
        assert templates.subject_at(profile.id, WeekType.UPPER, 3, on_date=past) == saved[2].id


# ===========================================================================
# DATA-19 — повреждённый файл базы
# ===========================================================================
class TestCorruptedDatabase:
    """DATA-19: повреждённый файл не роняет запуск трейсбеком."""

    def test_is_initialized_returns_false(self, tmp_path: Path) -> None:
        """``is_initialized`` не бросает ``sqlite3.DatabaseError``.

        Раньше проверка падала с сырым исключением до обработки ошибок
        приложения, и вместо диалога пользователь видел трейсбек.
        """
        broken = tmp_path / "broken.db"
        broken.write_bytes(b"NOT A DATABASE" * 100)
        assert is_initialized(broken) is False

    def test_open_database_gives_app_error(self, tmp_path: Path) -> None:
        """``open_database`` сообщает о повреждении понятной ошибкой."""
        from student_planner.core.database import open_database

        broken = tmp_path / "broken2.db"
        broken.write_bytes(b"NOT A DATABASE" * 100)
        with pytest.raises(AppError):
            open_database(broken)


# ===========================================================================
# UI-03/UI-06 — выбранная дата доходит до страниц
# ===========================================================================
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def seeded(qapp, tmp_path):
    db = create_database(tmp_path / "seeded.db")
    from student_planner.core.seeding import Seeder

    Seeder(db).seed_all()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def window(qapp, seeded):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from student_planner.ui.main_window import MainWindow

    created = MainWindow(seeded)
    yield created
    created.close()
    created.setParent(None)
    created.deleteLater()
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


class TestWidgetsPanelLayout:
    """UI-23/UI-25: раскладка, ширина и состав правой панели."""

    def test_panel_has_no_horizontal_clipping(self, window) -> None:
        """Панель сужается до минимума без обрезки содержимого.

        Раньше контент требовал 462 px: дата в часах (338), кнопка
        подтверждения (277) и длинные значения не сжимались, и на узкой
        панели часть текста обрезалась без возможности прокрутки.
        """
        from PySide6.QtWidgets import QScrollArea

        from student_planner.ui.main_window import MIN_WIDGETS_WIDTH

        window.show()
        for width in (MIN_WIDGETS_WIDTH, 260, 320, 400, 480):
            window._splitter.setSizes([312, 1400 - 312 - width - 14, width + 14])
            window.refresh_all()
            scroll = window.widgets.findChild(QScrollArea)
            assert scroll.horizontalScrollBar().maximum() == 0, (
                f"при ширине {window.widgets.width()} px содержимое обрезано"
            )

    def test_width_persisted_and_restored(self, window, seeded) -> None:
        """UI-23: ширина панели запоминается и восстанавливается.

        Раньше ширина не сохранялась вовсе: растянув панель до 380 px,
        пользователь после перезапуска получал 280.
        """
        window.show()
        window._splitter.setSizes([312, 1400 - 312 - 394, 394])
        window._on_splitter_moved()
        window._persist_widgets_width()
        saved = SettingsService(seeded).raw(SettingsKeys.WIDGETS_WIDTH)
        assert saved == "380", f"сохранено {saved!r}"
        assert window.saved_widgets_width() == 380

    def test_double_click_resets_width(self, window) -> None:
        """UI-23: двойной щелчок по полосе возвращает ширину по умолчанию."""
        from student_planner.ui.main_window import DEFAULT_WIDGETS_WIDTH

        window.show()
        window._apply_widgets_width(400)
        window.reset_widgets_width()
        assert window.widgets.width() == DEFAULT_WIDGETS_WIDTH

    def test_edge_strip_replaces_top_button(self, window) -> None:
        """UI-25: кнопка сворачивания — вертикальная полоса, а не строка сверху."""
        window.show()
        assert window.edge_button is not None
        assert window.edge_button.height() > 200, "полоса идёт по всей высоте"
        assert window.edge_button.width() <= 20, "полоса узкая"
        # Прежней кнопки-строки больше нет.
        assert not hasattr(window, "collapse_button")

    def test_edge_strip_collapses_and_expands(self, window) -> None:
        window.show()
        width_before = window.widgets.width()
        window.edge_button.clicked.emit()
        assert window.widgets_collapsed
        assert not window.widgets.isVisible()
        assert window.edge_button.isVisible(), "полоса остаётся для разворота"
        window.edge_button.clicked.emit()
        assert not window.widgets_collapsed
        assert window.widgets.width() == width_before

    def test_strella_widget_has_three_rows(self, window) -> None:
        """UI-09: в «Стрелке» три строки, экономия убрана в отчёты."""
        strella = window.widgets.strella
        assert hasattr(strella, "period_row")
        assert hasattr(strella, "next_row")
        assert hasattr(strella, "balance_row")
        assert not hasattr(strella, "savings_row"), "экономия переехала в отчёты"
        assert not hasattr(strella, "price_row"), "цена в одной строке с номером"

    def test_strella_has_no_actions(self, window) -> None:
        """UI-09: в карточке «Стрелка» нет кнопки действий.

        Раньше там стояло меню «⋮» с пересчётом счётчика. По просьбе
        пользователя действие перенесено на страницу «Расходы на транспорт»,
        а карточка показывает только состояние счётчика.
        """
        strella = window.widgets.strella
        assert not hasattr(strella, "menu_button"), "меню в карточке не нужно"
        assert not hasattr(strella, "recalculate_action")

    def test_recalculate_button_lives_in_expenses(self, window) -> None:
        """REP-08: пересчёт счётчика — на странице «Расходы»."""
        window.show()
        window.open_page("expenses")
        page = window._pages["expenses"]
        assert "Пересчитать" in page.recalculate_button.text()
        # Кнопка в шапке страницы, поэтому видна сразу при открытии раздела.
        assert page.recalculate_button.isVisible()

    def test_trips_title_follows_selected_date(self, window) -> None:
        """UI-08: заголовок поездок показывает дату, если это не сегодня.

        Раньше всегда было «на сегодня», и при выбранном 9 декабря
        пользователь подтверждал поездки не того дня.
        """
        other = FIXED_TODAY + timedelta(days=20)
        window.widgets.trips.refresh(other)
        title = window.widgets.trips.title_label.text()
        assert "сегодня" not in title.lower()
        assert "Поездки на" in title
        # ``clock.today()`` в тестах заморожен на FIXED_TODAY.
        window.widgets.trips.refresh(FIXED_TODAY)
        assert window.widgets.trips.title_label.text() == "Поездки на сегодня"


class TestMetricRowLayout:
    """Регрессия: значения ``MetricRow`` были невидимы (ширина 0).

    В отчётах и на других страницах цифры присутствовали в тексте, но не
    отрисовывались: подпись занимала всю ширину строки, значению оставалось
    0 px. Пользователь видел пустые места вместо сумм. Причина — растяжение,
    отданное подписи, при сжимаемой политике.
    """

    def test_caption_and_value_both_have_width(self, qapp) -> None:
        """И подпись, и значение получают место в строке.

        Проверяется в реальном окне: раскладку применяет только показанное
        окно, отдельный ``show()`` без родителя её не запускает.
        """
        from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

        from student_planner.ui.widgets import MetricRow

        host = QMainWindow()
        central = QWidget()
        layout = QVBoxLayout(central)
        row = MetricRow("Остаток на конец периода", "1234.56 ₽", strong=True)
        layout.addWidget(row)
        layout.addStretch(1)
        host.setCentralWidget(central)
        host.resize(320, 80)
        host.show()
        qapp.processEvents()
        try:
            assert row.caption_label.width() > 0, "подпись не получила ширину"
            assert row.value_label.width() > 0, "значение не получило ширину"
            assert row.caption_label.text() == "Остаток на конец периода"
            assert row.value_label.text() == "1234.56 ₽"
        finally:
            host.close()

    def test_value_priority_over_caption(self, qapp) -> None:
        """При нехватке места значение не исчезает полностью."""
        from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

        from student_planner.ui.widgets import MetricRow

        host = QMainWindow()
        central = QWidget()
        layout = QVBoxLayout(central)
        row = MetricRow("Очень длинная подпись строки отчёта", "310.50 ₽")
        layout.addWidget(row)
        layout.addStretch(1)
        host.setCentralWidget(central)
        host.resize(220, 80)
        host.show()
        qapp.processEvents()
        try:
            assert row.value_label.width() > 0, "значение сжалось до нуля"
        finally:
            host.close()

    def test_value_tooltip_keeps_full_text(self, qapp) -> None:
        """Полный текст значения остаётся в подсказке при усечении."""
        from student_planner.ui.widgets import MetricRow

        row = MetricRow("Поездок")
        row.set_value("9 («Стрелка» 6, карта 0)")
        assert row.value_label.toolTip() == "9 («Стрелка» 6, карта 0)"

    def test_all_report_rows_visible(self, window, seeded) -> None:
        """На странице «Отчёты» у всех строк видны и подпись, и значение."""
        from student_planner.ui.widgets import MetricRow

        window.show()
        window.open_page("expenses")
        window.refresh_all()
        rows = [
            row for row in window._pages["expenses"].report_tab.findChildren(MetricRow)
            if row.isVisible()
        ]
        assert rows, "на странице отчётов должны быть строки показателей"
        broken = [
            f"{row.caption_label.text()!r} / {row.value_label.text()!r}"
            for row in rows
            if row.caption_label.width() <= 0 or row.value_label.width() <= 0
        ]
        assert not broken, f"невидимые значения: {broken}"


class TestSelectedDateReachesPages:
    """UI-03/UI-06: дата из календаря действует на всех страницах."""

    def test_date_passed_to_trips_expenses_homework(self, window) -> None:
        """Поездки, расходы и задания получают выбранную дату.

        Раньше ``open_page`` не передавал дату: выбрав 9 декабря и открыв
        «Поездки», пользователь видел 31 октября и подтверждал поездки не того
        дня.
        """
        target = date(2026, 12, 9)
        window.on_date_selected(target)
        for page_key in ("trips", "expenses", "homework"):
            window.open_page(page_key)
            assert getattr(window._pages[page_key], "_date", None) == target, page_key

    def test_today_button_emits_once(self, window) -> None:
        """«Сегодня» в календаре эмитит сигнал один раз.

        Раньше ``go_today`` делал и ``set_selected``, и явный ``emit``: сигнал
        шёл дважды, и окно дважды перерисовывало расписание, панель и метки.
        Если дата уже сегодняшняя, Qt не присылает ``selectionChanged`` и
        сигнала нет вовсе — поэтому сначала уходим на другую дату.
        """
        calendar = window.nav.calendar
        calendar.set_selected(FIXED_TODAY + timedelta(days=5))
        hits: list[date] = []
        calendar.date_selected.connect(hits.append)
        calendar.go_today()
        assert len(hits) == 1, f"ожидался один сигнал, получено {len(hits)}"


class TestBackupAndReset:
    """SET-07: резервная копия и сброс данных."""

    def test_backup_copies_working_database(self, window, seeded, tmp_path) -> None:
        """Копия берётся с рабочей базы, а не с пути по умолчанию.

        Раньше копировался файл по умолчанию: при выбранной другой базе копия
        делалась с чужого файла или падала.
        """
        from unittest.mock import patch

        tab = window._pages["settings"].data_tab
        target = tmp_path / "backup.db"
        with patch(
            "student_planner.ui.pages.settings.QFileDialog.getSaveFileName",
            return_value=(str(target), ""),
        ):
            tab.create_backup()
        assert target.exists()
        assert target.stat().st_size > 0

    def test_reset_removes_exams(self, window, seeded) -> None:
        """«Сброс данных» удаляет испытания.

        Раньше таблица ``exams`` не входила в список: экзамены оставались, хотя
        сообщение обещало, что данные удалены.
        """
        from unittest.mock import patch

        subject = SubjectRepository(seeded).all()[0]
        ExamRepository(seeded).create(subject.id, FIXED_TODAY, kind=ExamKind.EXAM)
        assert ExamService(seeded).rows()
        tab = window._pages["settings"].data_tab
        with patch(
            "student_planner.ui.pages.settings.QInputDialog.getText",
            return_value=("УДАЛИТЬ", True),
        ):
            tab.reset_data()
        assert ExamService(seeded).rows() == []


# ===========================================================================
# Прочие дефекты, найденные аудитом
# ===========================================================================
class TestMediumDefects:
    """Средние дефекты: импорт, бейдж ДЗ, формат даты, удаление блока."""

    def test_import_without_weekday_reports_problem(self, db) -> None:
        """Файл без колонки «день» сообщает о проблеме, а не молчит (GRID-10)."""
        from student_planner.core.schedule_import import ScheduleImporter

        report = ScheduleImporter(db).parse_text("блок;предмет\n1;Математика")
        assert report.skipped > 0
        assert report.problems, "должно быть объяснение, почему строка пропущена"

    def test_import_respects_slot_number_gaps(self, db, simple_bell) -> None:
        """Импорт проверяет номера блоков, а не их количество (GRID-10)."""
        from student_planner.core.schedule_import import ScheduleImporter

        # У simple_bell три блока подряд; добавим блок с номером 5.
        bells = BellRepository(db)
        bells.add_slot(simple_bell.id, "pair", display_name="5", pair_no=5,
                       parts=[("lesson", "11:15", "12:00")])
        profile = bells.require_profile(simple_bell.id)
        numbers = sorted(slot.slot_no for slot in profile.slots)
        report = ScheduleImporter(db).parse_text(f"Пн;upper;{numbers[-1]};Математика")
        assert report.total == 1, f"импорт в блок {numbers[-1]} должен пройти: {report.problems}"

    def test_homework_badge_matches_page(self, db) -> None:
        """Бейдж ДЗ и страница заданий считают активные одинаково (HW-06)."""
        subject = SubjectRepository(db).create("Математика")
        service = HomeworkService(db)
        service.create(subject.id, FIXED_TODAY, "активное")
        done = service.create(subject.id, FIXED_TODAY, "выполненное")
        service.toggle(done.id)
        assert service.badge(subject.id, FIXED_TODAY) == 1
        resolved = DayResolver(db).resolve(FIXED_TODAY)
        counts = [lesson.homework_count for lesson in resolved.lessons if lesson.subject]
        assert all(count <= 1 for count in counts)

    def test_exam_caption_follows_date_format(self, db) -> None:
        """Подпись даты испытания уважает настройку формата (SET-02)."""
        subject = SubjectRepository(db).create("Физика")
        ExamRepository(db).create(subject.id, date(2026, 11, 4), time="09:00")
        dt.set_display_format("YYYY-MM-DD")
        try:
            caption = ExamService(db).rows()[0].when_caption
            assert "2026-11-04" in caption
        finally:
            dt.set_display_format(None)

    def test_homework_caption_follows_date_format(self, db) -> None:
        subject = SubjectRepository(db).create("История")
        HomeworkService(db).create(subject.id, date(2026, 11, 4), "доклад")
        dt.set_display_format("YYYY-MM-DD")
        try:
            caption = HomeworkService(db).rows()[0].due_caption
            assert caption == "2026-11-04"
        finally:
            dt.set_display_format(None)

    def test_delete_slot_clears_template_cell(self, db) -> None:
        """Удаление блока убирает и ячейку шаблона (BELL-16).

        Иначе номер слота переиспользуется новым блоком, и он наследует
        предмет удалённого.
        """
        subject = SubjectRepository(db).create("Химия")
        bells = BellRepository(db)
        profile = bells.create_profile(7, "Воскресенье")
        bells.add_slot(profile.id, "pair", display_name="1", pair_no=1,
                       parts=[("lesson", "08:30", "09:15")])
        profile = bells.require_profile(profile.id)
        templates = ScheduleTemplateRepository(db)
        templates.set_cell(profile.id, WeekType.UPPER, 1, subject.id)
        bells.delete_slot(profile.slots[0].id)
        assert templates.cell(profile.id, WeekType.UPPER, 1) is None


# ===========================================================================
# Вспомогательное
# ===========================================================================
def _seeded(db):
    """Наполнить БД стартовым набором, если он пуст."""
    from student_planner.core.seeding import Seeder

    if not SubjectRepository(db).all():
        Seeder(db).seed_all()
    return db
