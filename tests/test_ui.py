"""Модульные тесты интерфейса (UI-01…UI-14, ACC-U-01…ACC-U-32).

Тесты работают без экрана через ``QT_QPA_PLATFORM=offscreen``: проверяется
механика виджетов и страниц, а не внешний вид. Слой 1 — синтетические данные
(TEST-01); стартовый набор используется только там, где без него нельзя
построить сетку (GRID-01).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="PySide6 не установлен")

from datetime import date  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402


FIXED = date(2026, 10, 20)


@pytest.fixture(scope="session")
def qapp():
    """Один QApplication на сессию: второй создать нельзя."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def seeded(db, qapp):
    """База со стартовым набором Приложения А и готовым QApplication."""
    from student_planner.core.seeding import Seeder

    Seeder(db).seed_all()
    return db


# ===========================================================================
# UI-13 — тёмная тема и контраст
# ===========================================================================
class TestTheme:
    """UI-13: тёмная тема, контраст текста не ниже 4.5:1."""

    def test_stylesheet_is_dark_and_nonempty(self):
        """UI-13: стилевая таблица существует и задаёт тёмный фон."""
        from student_planner.ui.theme import COLORS, stylesheet

        css = stylesheet()
        assert css, "Стилевая таблица не должна быть пустой"
        assert COLORS["background"].lower() in css.lower(), (
            "Фон из палитры должен попадать в стилевую таблицу"
        )

    @pytest.mark.parametrize(
        ("foreground", "background"),
        [
            ("text", "background"),
            ("text_muted", "surface"),
            ("accent_text", "accent"),
        ],
    )
    def test_contrast_meets_wcag(self, foreground, background):
        """UI-13: контраст пары цветов не ниже 4.5:1."""
        from student_planner.ui.theme import COLORS, contrast_ratio

        ratio = contrast_ratio(COLORS[foreground], COLORS[background])
        assert ratio >= 4.5, (
            f"Контраст {foreground}/{background} = {ratio:.2f}:1, требуется ≥ 4.5:1"
        )


# ===========================================================================
# UI-01…UI-06 — каркас главного окна
# ===========================================================================
class TestMainWindow:
    """UI-01/UI-02/UI-06: три колонки, пять разделов, мини-календарь."""

    def test_has_three_columns(self, seeded):
        """UI-06: навигация, страница и виджеты — три колонки."""
        from PySide6.QtWidgets import QSplitter

        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        splitter = window.centralWidget().findChild(QSplitter)
        assert splitter is not None, "Ожидался QSplitter с тремя колонками"
        assert splitter.count() == 3, "Ожидались три колонки (UI-06)"

    def test_all_five_pages_exist(self, seeded):
        """UI-04: пять разделов меню, раздела «Экзамены» нет."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        for key in ("schedule", "trips", "expenses", "homework", "settings"):
            window.open_page(key)
        assert window.stack.count() == 5, "Ожидалось ровно пять страниц (UI-04)"

    def test_open_page_switches_stack(self, seeded):
        """UI-04: переход по разделу меняет видимую страницу."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.open_page("expenses")
        assert window.stack.currentIndex() == 2, "Страница «Расходы» — третья"
        window.open_page("settings")
        assert window.stack.currentIndex() == 4, "Страница «Настройки» — пятая"

    def test_refresh_all_does_not_raise(self, seeded):
        """UI-02: полное обновление виджетов проходит без ошибок."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.refresh_all()

    def test_selected_date_defaults_to_today(self, seeded):
        """UI-03: главное окно стартует на сегодняшней дате."""
        from student_planner.core import clock
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        assert window.selected_date == clock.today()

    def test_on_date_selected_updates_pages(self, seeded):
        """UI-03/SCH-10: выбор даты в календаре меняет дату страниц."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.on_date_selected(FIXED)
        assert window.selected_date == FIXED, "Выбранная дата должна сохраниться"


# ===========================================================================
# UI-07…UI-10 — виджеты правой панели
# ===========================================================================
class TestWidgets:
    """UI-07…UI-10: часы, поездки сегодня, «Стрелка», домашние задания."""

    def test_clock_widget_shows_time(self, qapp):
        """UI-07: часы показывают время в формате ЧЧ:ММ."""
        from student_planner.ui.widgets_panel import ClockWidget

        widget = ClockWidget()
        widget.refresh()
        text = widget.time_label.text()
        assert len(text) == 5 and text[2] == ":", f"Ожидалось ЧЧ:ММ, получено {text!r}"

    def test_clock_widget_shows_date(self, qapp):
        """UI-07: часы показывают дату по-русски."""
        from student_planner.ui.widgets_panel import ClockWidget

        widget = ClockWidget()
        widget.refresh()
        assert widget.date_label.text(), "Подпись даты не должна быть пустой"

    def test_strelka_widget_without_topup(self, seeded):
        """WAL-05: без пополнения — «Остаток не задан», предупреждения нет."""
        from student_planner.ui.widgets_panel import StrellaWidget

        widget = StrellaWidget(seeded)
        widget.refresh()
        assert "не задан" in widget.balance_row.value_label.text().lower(), (
            "Без пополнения остаток должен быть не задан (WAL-05)"
        )
        assert not widget.warning_label.isVisible(), (
            "WAL-05: предупреждения о низком остатке быть не должно"
        )

    def test_trips_widget_refresh(self, seeded):
        """UI-08: виджет поездок обновляется без подтверждённого дня."""
        from student_planner.ui.widgets_panel import TripsTodayWidget

        widget = TripsTodayWidget(seeded)
        widget.refresh()
        assert widget.state_badge.text(), "Бейдж состояния должен быть заполнен"

    def test_homework_widget_empty(self, seeded):
        """UI-10: без заданий виджет показывает подпись «Заданий нет»."""
        from student_planner.ui.widgets_panel import HomeworkWidget

        widget = HomeworkWidget(seeded)
        widget.refresh()
        assert widget.empty_label.isVisible() or widget.rows_layout.count() == 0


# ===========================================================================
# UI-05 — профиль в левой панели
# ===========================================================================
class TestProfile:
    """FIRST-15: пустые имя и группа отображаются как «Не указано»."""

    def test_empty_profile_shows_placeholder(self, seeded):
        """FIRST-15/UI-04: пустые значения — «Не указано», а не пустота."""
        from student_planner.ui.nav_panel import NavPanel

        panel = NavPanel(seeded)
        panel.refresh()
        assert "Не указано" in panel.name_label.text(), (
            "Пустое имя должно отображаться как «Не указано» (FIRST-15)"
        )

    def test_filled_profile_shows_values(self, seeded):
        """SET-02: заполненный профиль показывается в панели."""
        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.nav_panel import NavPanel

        SettingsService(seeded).set_student_profile("Иван Иванов", "ИС-21")
        panel = NavPanel(seeded)
        panel.refresh()
        assert "Иван Иванов" in panel.name_label.text()
        assert "ИС-21" in panel.group_label.text()


# ===========================================================================
# UI-03 — мини-календарь
# ===========================================================================
class TestMiniCalendar:
    """UI-03: мини-календарь с метками и переходом к сегодня."""

    def test_go_today_selects_today(self, qapp):
        """UI-03: кнопка «Сегодня» выделяет текущую дату."""
        from student_planner.core import clock
        from student_planner.ui.calendar_widget import MiniCalendar

        widget = MiniCalendar()
        widget.go_today()
        assert widget.selected_date == clock.today(), (
            "«Сегодня» должно выделять текущую дату"
        )

    def test_set_selected_updates_date(self, qapp):
        """UI-03: выбор даты меняет выделение."""
        from student_planner.ui.calendar_widget import MiniCalendar

        widget = MiniCalendar()
        widget.set_selected(FIXED)
        assert widget.selected_date == FIXED

    def test_marks_are_stored(self, qapp):
        """UI-03: метки дней сохраняются для отрисовки."""
        from student_planner.ui.calendar_widget import MiniCalendar

        widget = MiniCalendar()
        widget.set_marks({FIXED: "period homework"})
        widget.set_week_types({FIXED: "upper"})


# ===========================================================================
# UI-04/ALG-01 — бейдж типа недели следует за выбранной датой
# ===========================================================================
class TestWeekTypeBadge:
    """Бейдж «Верхняя»/«Нижняя» относится к выбранной дате, а не к сегодняшней.

    Регрессия: ``on_date_selected`` не пересчитывал бейдж, поэтому при
    просмотре другой недели он показывал тип предыдущей, а до первого
    ``refresh_all`` — прочерк.
    """

    def test_badge_matches_selected_date(self, qapp, seeded):
        """ALG-01: тип недели пересчитывается при каждом выборе даты."""
        from datetime import date as _date

        from student_planner.core.day_resolution import DayResolver
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        resolver = DayResolver(seeded)
        expected = {"upper": "Верхняя", "lower": "Нижняя"}
        # Даты подобраны через одну неделю, чтобы тип недели чередовался.
        for value in (_date(2026, 10, 19), _date(2026, 10, 26),
                      _date(2026, 11, 2), _date(2026, 11, 9)):
            window.on_date_selected(value)
            qapp.processEvents()
            real = resolver.week_type(value)
            assert window.nav.week_badge.text() == expected[real], (
                f"UI-04: для {value} в БД тип недели {real}, "
                f"а бейдж показывает «{window.nav.week_badge.text()}»"
            )
        window.close()

    def test_badge_not_empty_on_start(self, qapp, seeded):
        """UI-04: бейдж заполнен сразу после открытия окна, без прочерка."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.show()
        qapp.processEvents()

        assert window.nav.week_badge.text() in ("Верхняя", "Нижняя"), (
            f"UI-04: при старте бейдж недели показывает "
            f"«{window.nav.week_badge.text()}»"
        )
        window.close()

    def test_calendar_click_updates_badge(self, qapp, seeded):
        """UI-05: клик по дню в мини-календаре меняет бейдж недели."""
        from datetime import date as _date

        from PySide6.QtCore import QDate

        from student_planner.core.day_resolution import DayResolver
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        resolver = DayResolver(seeded)
        target = _date(2026, 10, 26)  # тип недели отличается от 19.10
        window.nav.calendar.calendar.setSelectedDate(
            QDate(target.year, target.month, target.day)
        )
        qapp.processEvents()

        expected = {"upper": "Верхняя", "lower": "Нижняя"}[resolver.week_type(target)]
        assert window.nav.week_badge.text() == expected, (
            f"UI-05: после выбора {target} бейдж показывает "
            f"«{window.nav.week_badge.text()}», ожидалось «{expected}»"
        )
        window.close()


# ===========================================================================
# SCH-09/UI-05 — навигация в расписании двигает дату всего окна
# ===========================================================================
class TestScheduleCalendarSync:
    """Расписание не должно жить отдельной датой от календаря.

    Регрессия: ``SchedulePage`` хранила собственную дату и меняла её стрелками
    молча — мини-календарь и бейдж типа недели слева оставались на прежней
    дате, а бейдж внутри расписания показывал правильный тип. Два указателя
    одной недели расходились.
    """

    def test_shift_date_moves_window_date(self, qapp, seeded):
        """SCH-09: стрелка «›» переводит дату окна и календаря."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        page = window._pages["schedule"]
        page.mode_combo.setCurrentIndex(page.mode_combo.findData("date"))
        window.on_date_selected(date(2026, 10, 21))
        qapp.processEvents()

        for _ in range(7):
            page.shift_date(1)
            qapp.processEvents()
            assert page.date == window.selected_date, (
                f"SCH-09: страница на {page.date}, окно на {window.selected_date}"
            )
            assert window.nav.calendar.selected_date == page.date, (
                f"UI-05: календарь на {window.nav.calendar.selected_date}, "
                f"страница на {page.date}"
            )
        window.close()

    def test_badges_agree_after_week_jump(self, qapp, seeded):
        """UI-04: бейдж расписания и левый бейдж показывают один тип недели."""
        from student_planner.core.day_resolution import DayResolver
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        page = window._pages["schedule"]
        page.mode_combo.setCurrentIndex(page.mode_combo.findData("date"))
        # 21.10 — нижняя неделя, 26.10 — уже верхняя: переход через границу.
        window.on_date_selected(date(2026, 10, 21))
        qapp.processEvents()
        for _ in range(5):
            page.shift_date(1)
            qapp.processEvents()

        resolver = DayResolver(seeded)
        expected = {"upper": "Верхняя", "lower": "Нижняя"}[resolver.week_type(page.date)]
        assert window.nav.week_badge.text() == expected, (
            f"UI-04: на {page.date} тип недели {resolver.week_type(page.date)}, "
            f"левый бейдж показывает «{window.nav.week_badge.text()}»"
        )
        window.close()

    def test_today_button_returns_window(self, qapp, seeded):
        """SCH-09: «Сегодня» в расписании возвращает дату окна к сегодня."""
        from student_planner.core import clock
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        page = window._pages["schedule"]
        page.mode_combo.setCurrentIndex(page.mode_combo.findData("date"))
        window.on_date_selected(date(2026, 12, 25))
        qapp.processEvents()

        page.go_today()
        qapp.processEvents()

        assert page.date == clock.today(), "SCH-09: страница не вернулась к сегодня"
        assert window.selected_date == clock.today(), (
            "SCH-09: окно осталось на прежней дате после «Сегодня»"
        )
        assert window.nav.calendar.selected_date == clock.today(), (
            "UI-05: календарь не вернулся к сегодня"
        )
        window.close()

    def test_mode_change_moves_window_date(self, qapp, seeded):
        """SCH-02: смена режима переводит дату окна вместе со страницей."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        page = window._pages["schedule"]
        for index in range(page.mode_combo.count()):
            page.mode_combo.setCurrentIndex(index)
            qapp.processEvents()
            assert page.date == window.selected_date, (
                f"SCH-02: режим «{page.mode_combo.itemText(index)}»: "
                f"страница {page.date}, окно {window.selected_date}"
            )
        window.close()


# ===========================================================================
# §24 — страница «Расписание»
# ===========================================================================
class TestSchedulePage:
    """SCH-02/SCH-09/SCH-10: три режима и карточки занятий."""

    def test_three_modes_only(self, seeded):
        """SCH-02: ровно три режима отображения, без режима «шаблон недели»."""
        from student_planner.ui.pages.schedule import MODES

        assert len(MODES) == 3, "SCH-02 допускает три режима"
        keys = {key for key, _ in MODES}
        assert keys == {"selected", "current", "next"}

    def test_page_builds_and_refreshes(self, seeded):
        """SCH-09: страница строится и обновляется на стартовом наборе."""
        from student_planner.ui.pages.schedule import SchedulePage

        page = SchedulePage(seeded)
        page.refresh()

    def test_selected_date_mode_shows_one_day(self, seeded):
        """SCH-02: режим «выбранная дата» показывает одну колонку."""
        from student_planner.ui.pages.schedule import SchedulePage

        page = SchedulePage(seeded)
        page.set_date(FIXED)
        assert len(page._visible_days()) == 1

    def test_current_week_mode_shows_seven_days(self, seeded):
        """SCH-02: режим «текущая неделя» показывает семь дней."""
        from student_planner.ui.pages.schedule import SchedulePage

        page = SchedulePage(seeded)
        page.mode_combo.setCurrentIndex(1)
        page.refresh()
        assert len(page._visible_days()) == 7, "Неделя — семь дней"

    def test_shift_date_moves_one_day(self, seeded):
        """SCH-10: стрелки переключают дату на день."""
        from student_planner.ui.pages.schedule import SchedulePage

        page = SchedulePage(seeded)
        page.set_date(FIXED)
        page.shift_date(1)
        assert page.date == date(2026, 10, 21)


# ===========================================================================
# §9.2 — редактор сетки
# ===========================================================================
class TestGridEditor:
    """GRID-01…GRID-05: сетка на одном экране, сохранение по ячейке."""

    def test_editor_shows_week_rows(self, seeded):
        """GRID-01: вся неделя на одном экране."""
        from student_planner.ui.grid_editor import GridEditorDialog

        dialog = GridEditorDialog(seeded, FIXED)
        assert dialog.table.columnCount() == 6, (
            "GRID-01: Пн–Сб, то есть шесть колонок"
        )
        assert dialog.table.rowCount() > 0, "GRID-01: строки блоков должны быть"

    def test_save_cell_writes_to_template(self, seeded):
        """GRID-02: выбор предмета сохраняет ячейку сразу."""
        from student_planner.core.repositories import SubjectRepository
        from student_planner.core.schedule_service import GridService
        from student_planner.ui.grid_editor import GridEditorDialog

        dialog = GridEditorDialog(seeded, FIXED)
        view = GridService(seeded).view(dialog._week_type)
        column = view.columns[0]
        slot = column.slots[0]
        subject = SubjectRepository(seeded).all(include_inactive=False)[0]

        dialog.save_cell(column.profile_id, slot.slot_no, subject.id)
        saved = GridService(seeded).view(dialog._week_type).columns[0].slots[0]
        assert saved.subject_id == subject.id, "GRID-02: ячейка должна сохраниться"

    def test_clear_cell_keeps_slot(self, seeded):
        """GRID-05: очистка удаляет строку шаблона, но не блок."""
        from student_planner.core.schedule_service import GridService
        from student_planner.ui.grid_editor import GridEditorDialog

        dialog = GridEditorDialog(seeded, FIXED)
        view = GridService(seeded).view(dialog._week_type)
        column = view.columns[0]
        slot = column.slots[0]

        dialog.clear_cell(column.profile_id, slot.slot_no, 0, 0)
        after = GridService(seeded).view(dialog._week_type).columns[0].slots[0]
        assert after.subject_id is None, "GRID-05: ячейка должна быть пуста"
        assert after.slot_no == slot.slot_no, "GRID-05: блок остаётся на месте"


# ===========================================================================
# §27 — страница «Поездки»
# ===========================================================================
class TestTripsPage:
    """TRIP-20: три вкладки и подтверждение на дату."""

    def test_has_three_tabs(self, seeded):
        """TRIP-20: шаблоны, подтверждение дня, журнал."""
        from student_planner.ui.pages.trips import TripsPage

        page = TripsPage(seeded)
        assert page.tabs.count() == 3

    def test_templates_listed(self, seeded):
        """TRIP-13: шаблоны стартового набора видны в таблице."""
        from student_planner.ui.pages.trips import TripsPage

        page = TripsPage(seeded)
        page.refresh()
        assert page.templates_tab.table.rowCount() == 7, (
            "Прил. А.4: семь шаблонов поездок"
        )

    def test_confirm_tab_set_date(self, seeded):
        """TRIP-08: вкладка подтверждения принимает дату."""
        from student_planner.ui.pages.trips import TripsPage

        page = TripsPage(seeded)
        page.set_date(FIXED)
        page.refresh()


# ===========================================================================
# §28 — страница «Расходы»
# ===========================================================================
class TestExpensesPage:
    """REP-10/WAL-04: отчёты, журнал, пополнения."""

    def test_has_three_tabs(self, seeded):
        """REP-10: отчёты, журнал поездок, пополнения."""
        from student_planner.ui.pages.expenses import ExpensesPage

        page = ExpensesPage(seeded)
        assert page.tabs.count() == 3

    def test_report_shows_separate_columns(self, seeded):
        """WAL-04: «пополнено» и «потрачено» — отдельные строки, не сумма."""
        from student_planner.ui.pages.expenses import ExpensesPage

        page = ExpensesPage(seeded)
        page.refresh()
        spent = page.report_tab.spent_row
        topups = page.report_tab.topups_row
        assert spent.value_label.text() != "", "Строка «Потрачено» должна заполняться"
        assert topups.value_label.text() != "", "Строка «Пополнено» должна заполняться"

    def test_empty_journal_hidden_table(self, seeded):
        """REP-10: без поездок таблица скрыта, показано пустое состояние."""
        from student_planner.ui.pages.expenses import ExpensesPage

        page = ExpensesPage(seeded)
        page.refresh()
        assert page.journal_tab.empty.isVisible() or not page.journal_tab.table.isVisible()


# ===========================================================================
# §25 — страница «Домашние задания»
# ===========================================================================
class TestHomeworkPage:
    """HW-13/HW-15: фильтры и отметка выполнения."""

    def test_four_filters(self, seeded):
        """HW-13: четыре фильтра — все, активные, выполненные, просроченные."""
        from student_planner.ui.pages.homework import FILTERS

        assert len(FILTERS) == 4
        assert {key for key, _ in FILTERS} == {"all", "active", "done", "overdue"}

    def test_empty_page_shows_hint(self, seeded):
        """HW-13: без заданий список скрыт, показано пустое состояние."""
        from student_planner.ui.pages.homework import HomeworkPage

        page = HomeworkPage(seeded)
        page.refresh()
        assert page.empty.isHidden() != page.scroll.isHidden(), (
            "HW-13: при отсутствии заданий виден ровно один блок — пустое состояние"
        )

    def test_create_and_toggle(self, seeded):
        """HW-15: задание создаётся и отмечается выполненным одним действием."""
        from student_planner.core.models import HomeworkStatus
        from student_planner.core.schedule_service import HomeworkService
        from student_planner.ui.pages.homework import HomeworkPage

        service = HomeworkService(seeded)
        subject = service.subject_choices()[0]
        created = service.create(subject.id, date(2026, 10, 25), "Параграф 5")

        page = HomeworkPage(seeded)
        page.refresh()
        page.toggle_homework(created.id)

        updated = service.repo.require(created.id)
        assert updated.status == HomeworkStatus.DONE, "HW-15: отметка должна сохраниться"

    def test_filter_done_shows_only_done(self, seeded):
        """HW-13: фильтр «Выполненные» не показывает активные задания."""
        from student_planner.core.schedule_service import HomeworkService
        from student_planner.ui.pages.homework import HomeworkPage

        service = HomeworkService(seeded)
        subject = service.subject_choices()[0]
        active = service.create(subject.id, date(2026, 10, 25), "Активное")
        done = service.create(subject.id, date(2026, 10, 26), "Выполненное")
        service.toggle(done.id)

        page = HomeworkPage(seeded)
        page.filter_combo.setCurrentIndex(2)
        page.refresh()

        rows = service.rows(status="done", today=date(2026, 10, 20))
        ids = {row.homework.id for row in rows}
        assert done.id in ids, "Выполненное задание должно попасть в фильтр"
        assert active.id not in ids, "Активное задание не должно попасть в фильтр"


# ===========================================================================
# §29 — страница «Настройки»
# ===========================================================================
class TestSettingsPage:
    """SET-01/SET-08: разделы строятся из реестра §30."""

    def test_six_sections(self, seeded):
        """SET-01: Общие, Недели, Звонки, Транспорт, Календарь, Данные."""
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        assert page.tabs.count() == 6

    def test_general_saves_profile(self, seeded):
        """SET-02: имя и группа сохраняются из раздела «Общие»."""
        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        page.refresh()
        page.general_tab.name_edit.setText("Пётр Петров")
        page.general_tab.group_edit.setText("ИС-22")
        page.general_tab.save()

        settings = SettingsService(seeded)
        assert settings.student_name() == "Пётр Петров"
        assert settings.group_title() == "ИС-22"

    def test_transport_rejects_future_anchor(self, seeded):
        """DATA-21: дата начала периода позже сегодняшней отклоняется."""
        from student_planner.core import clock
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        page.refresh()
        future = clock.today().replace(year=clock.today().year + 1)
        page.transport_tab.anchor_edit.setText(future.isoformat())
        page.transport_tab.recalc_check.setChecked(False)
        page.transport_tab.save()
        message = page.transport_tab.message
        assert message.text(), "DATA-21: должно появиться сообщение об ошибке"
        assert "позже" in message.text() or "дата" in message.text().lower(), (
            f"DATA-21: ожидалось объяснение про дату, получено {message.text()!r}"
        )

    def test_data_tab_has_paths(self, seeded):
        """SET-07: раздел «Данные» показывает путь к базе."""
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        page.refresh()
        assert "Файл:" in page.data_tab.path_label.text()


# ===========================================================================
# §2.5 — мастер первого запуска
# ===========================================================================
class TestFirstRunWizard:
    """FIRST-15/FIRST-16/FIRST-14: четыре шага и право отказа."""

    def test_four_steps_in_order(self, seeded, qapp):
        """§36.15: имя и группа → расписание → остаток → начало учёта."""
        from student_planner.ui.first_run import STEPS, FirstRunWizard

        assert STEPS[0] == "Имя и группа", "FIRST-15 идёт первым"
        assert STEPS[1] == "Расписание", "FIRST-16 идёт вторым"
        wizard = FirstRunWizard(seeded)
        assert wizard.stack.count() == 4

    def test_profile_saved_on_next(self, seeded, qapp):
        """FIRST-15: «Далее» сохраняет имя и группу."""
        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.first_run import FirstRunWizard

        wizard = FirstRunWizard(seeded)
        wizard.name_edit.setText("Иван Иванов")
        wizard.group_edit.setText("ИС-21")
        wizard.go_next()

        settings = SettingsService(seeded)
        assert settings.student_name() == "Иван Иванов"
        assert settings.group_title() == "ИС-21"

    def test_refusal_keeps_empty_profile(self, seeded, qapp):
        """FIRST-15/ACC-M-102: отказ оставляет пустые строки, профиль работает."""
        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.first_run import FirstRunWizard

        wizard = FirstRunWizard(seeded)
        wizard.go_next()
        settings = SettingsService(seeded)
        assert settings.student_name() == ""
        assert settings.group_title() == ""
        assert settings.profile_caption() == ("Не указано", "Не указано")

    def test_default_schedule_does_not_touch_templates(self, seeded, qapp):
        """FIRST-16/ACC-M-105: путь «По умолчанию» не меняет ни одной строки."""
        from student_planner.core.schedule_service import GridService
        from student_planner.ui.first_run import FirstRunWizard

        before = GridService(seeded).view("upper").filled_count
        wizard = FirstRunWizard(seeded)
        wizard.keep_default_schedule()
        after = GridService(seeded).view("upper").filled_count
        assert after == before, (
            "FIRST-16: «По умолчанию» не должна менять строки schedule_templates"
        )

    def test_wallet_step_creates_topup(self, seeded, qapp):
        """FIRST-06/WAL-09: начальный остаток становится записью пополнения."""
        from student_planner.core.transport_service import WalletService
        from student_planner.ui.first_run import FirstRunWizard

        wizard = FirstRunWizard(seeded)
        wizard.amount_edit.setText("150.00")
        wizard._step = 2
        wizard.go_next()

        wallet = WalletService(seeded)
        assert wallet.started, "WAL-09: пополнение должно появиться"
        assert wallet.balance_caption == "150.00 ₽"

    def test_anchor_refusal_gives_zero_and_empty(self, seeded, qapp):
        """FIRST-14/ACC-M-91: отказ даёт cnt0 = 0 и пустой якорь."""
        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.first_run import FirstRunWizard

        wizard = FirstRunWizard(seeded)
        wizard.count_spin.setValue(0)
        wizard.no_anchor_check.setChecked(True)
        # Отказ = пропуск шага: ничего не записывается, значения остаются
        # пустыми по умолчанию реестра (FARE-12).
        wizard._step = 3
        wizard.skip_step()

        settings = SettingsService(seeded)
        assert settings.strelka_initial_ride_count() == 0, (
            "FIRST-14: отказ даёт cnt0 = 0"
        )
        assert settings.strelka_period_anchor_date() is None, (
            "FARE-12: отказ оставляет якорь «не задано»"
        )


# ===========================================================================
# §6 — быстрый ввод (UI-14)
# ===========================================================================
class TestQuickInput:
    """UI-14: не более трёх полей, Enter сохраняет."""

    @pytest.mark.parametrize(
        "factory",
        ["cancel_lesson", "confirm_trips", "top_up", "manual_ride", "homework"],
    )
    def test_quick_input_has_at_most_three_fields(self, seeded, qapp, factory):
        """UI-14: у быстрых диалогов не больше трёх полей ввода."""
        from PySide6.QtWidgets import (
            QComboBox,
            QDateEdit,
            QDoubleSpinBox,
            QLineEdit,
            QPlainTextEdit,
            QSpinBox,
            QWidget,
        )

        from student_planner.ui import dialogs

        if factory == "cancel_lesson":
            dialog = dialogs.CancelLessonDialog(seeded, FIXED, 1, 1, "Алгебра")
        elif factory == "confirm_trips":
            dialog = dialogs.ConfirmTripsDialog(seeded, FIXED)
        elif factory == "top_up":
            dialog = dialogs.TopUpDialog(seeded)
        elif factory == "manual_ride":
            dialog = dialogs.ManualRideDialog(seeded, FIXED)
        else:
            dialog = dialogs.HomeworkDialog(seeded)

        # QDateEdit и QComboBox содержат внутренний QLineEdit, поэтому считаем
        # только поля верхнего уровня: у такого поля нет предка-поля.
        counts = {}
        for kind in (QLineEdit, QComboBox, QDateEdit, QSpinBox,
                     QDoubleSpinBox, QPlainTextEdit):
            counts[kind] = dialog.findChildren(kind)

        def is_nested(widget: QWidget) -> bool:
            parent = widget.parentWidget()
            while parent is not None:
                if isinstance(
                    parent,
                    (QLineEdit, QComboBox, QDateEdit, QSpinBox,
                     QDoubleSpinBox, QPlainTextEdit),
                ):
                    return True
                parent = parent.parentWidget()
            return False

        total = sum(
            1
            for found in counts.values()
            for widget in found
            if not is_nested(widget)
        )

        assert total <= 3, (
            f"UI-14: у диалога {factory} полей ввода {total}, допустимо не более трёх"
        )


# ===========================================================================
# UI-02/§20 — геометрия пустых состояний
# ===========================================================================
class TestEmptyStateLayout:
    """Пустое состояние не должно разъезжаться по странице.

    Регрессия: ``SectionHeader`` без вертикальной политики ``Maximum``
    растягивался на всю высоту, когда ниже показывалось пустое состояние
    (воскресенье без пар, пустой список заданий, пустой календарь). Заголовок
    «Расписание» занимал 385 px вместо 32, и элементы выглядели разбросанными.
    """

    def test_section_header_does_not_stretch(self, qapp):
        """Заголовок держит высоту одной строки независимо от соседей."""
        from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

        from student_planner.ui.widgets import EmptyState, SectionHeader

        host = QWidget()
        layout = QVBoxLayout(host)
        header = SectionHeader("Расписание")
        layout.addWidget(header)
        layout.addWidget(EmptyState("Занятий нет"), 1)
        host.resize(900, 700)
        host.show()
        qapp.processEvents()

        assert header.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum, (
            "UI-02: заголовок обязан иметь вертикальную политику Maximum"
        )
        assert header.height() < 120, (
            f"UI-02: заголовок раздулся до {header.height()} px вместо одной строки"
        )

    def test_empty_state_fills_free_space(self, qapp):
        """Пустое состояние занимает освободившееся место и не липнет к краю."""
        from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

        from student_planner.ui.widgets import EmptyState, SectionHeader

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.addWidget(SectionHeader("Расписание"))
        empty = EmptyState("Занятий нет")
        layout.addWidget(empty, 1)
        host.resize(900, 700)
        host.show()
        qapp.processEvents()

        assert empty.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding, (
            "UI-02: пустое состояние обязано растягиваться по вертикали"
        )
        assert empty.height() > 300, (
            f"UI-02: пустое состояние сжалось до {empty.height()} px"
        )

    def test_empty_state_caption_centred(self, qapp):
        """Подпись держится по центру блока, а не у верхней границы."""
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        from student_planner.ui.widgets import EmptyState

        host = QWidget()
        layout = QVBoxLayout(host)
        empty = EmptyState("Заданий нет", action_text="Добавить задание")
        layout.addWidget(empty, 1)
        host.resize(900, 700)
        host.show()
        qapp.processEvents()

        block_centre = empty.height() / 2
        # Подпись — верхняя часть группы «подпись + кнопка», поэтому её центр
        # выше центра блока примерно на половину высоты группы.
        caption_centre = empty.caption_label.y() + empty.caption_label.height() / 2
        assert 0 < block_centre - caption_centre < 200, (
            f"UI-02: подпись смещена от центра на {block_centre - caption_centre:.0f} px"
        )
        assert empty.caption_label.y() > 20, (
            "UI-02: подпись прилипла к верхней границе блока"
        )

    def test_report_cards_keep_their_height(self, qapp, seeded):
        """Карточки отчётов обнимают содержимое, а не делят свободное место.

        Регрессия: с политикой ``Preferred`` три карточки отчётов раздувались
        до 181 px каждая, значение «61.00 ₽ · 25 %» в структуре расходов
        переносилось, и строки разъезжались по высоте.
        """
        from PySide6.QtWidgets import QSizePolicy

        from student_planner.ui.pages.expenses import ExpensesPage
        from student_planner.ui.widgets import Card

        page = ExpensesPage(seeded)
        page.resize(1100, 780)
        page.show()
        page.refresh()
        qapp.processEvents()

        cards = [c for c in page.report_tab.findChildren(Card) if c.isVisible()]
        assert cards, "REP-01: на вкладке отчётов обязаны быть карточки"
        for card in cards:
            assert card.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum, (
                "REP-01: карточка отчёта обязана иметь вертикальную политику Maximum"
            )
            assert card.height() <= card.sizeHint().height() + 8, (
                f"REP-01: карточка раздулась до {card.height()} px "
                f"при содержимом {card.sizeHint().height()} px"
            )

    def test_report_values_do_not_wrap(self, qapp, seeded):
        """Значения отчёта помещаются в строку: переноса быть не должно."""
        from student_planner.ui.pages.expenses import ExpensesPage
        from student_planner.ui.widgets import MetricRow

        page = ExpensesPage(seeded)
        page.resize(1100, 780)
        page.show()
        page.refresh()
        qapp.processEvents()

        rows = [r for r in page.report_tab.findChildren(MetricRow) if r.isVisible()]
        assert rows, "REP-01: строк отчёта нет"
        for row in rows:
            value = row.value_label
            assert value.height() <= value.sizeHint().height() + 1, (
                f"REP-01: значение «{value.text()}» перенеслось на вторую строку "
                f"(h={value.height()}, нужно {value.sizeHint().height()})"
            )

    def test_report_filters_row_is_compact(self, qapp, seeded):
        """Строка фильтров периода занимает одну строку.

        Регрессия: вложенный ``QHBoxLayout`` забирал вес, оставшийся от скрытого
        ``EmptyState``, и раздувался до 344 px вместо 28 — между фильтром
        периода и первой карточкой появлялся отступ в треть экрана.
        Проверка идёт на ``ReportTab`` внутри ``MainWindow``: в отрыве от окна
        вес перераспределяется иначе и дефект не виден.
        """
        from student_planner.core import clock
        from student_planner.core.trip_service import TripPlanService
        from student_planner.ui.main_window import MainWindow

        # Поездка нужна, чтобы отчёт перестал быть пустым и скрытый EmptyState
        # сохранял вес — именно в этом состоянии дефект и проявлялся.
        TripPlanService(seeded).add_manual_ride(
            clock.today(), direction="home_to_college", transport_type="bus",
            vehicle="22", payment_method="strelka",
        )

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        window.open_page("expenses")
        qapp.processEvents()

        tab = window._pages["expenses"].report_tab
        tab.refresh()
        qapp.processEvents()

        layout = tab.layout()
        assert not tab.empty.isVisible(), (
            "REP-09: при наличии поездок пустое состояние обязано быть скрыто"
        )
        filters = layout.itemAt(0).widget()
        assert filters is not None, "REP-03: строки фильтров нет"
        assert filters.height() <= 60, (
            f"REP-03: строка фильтров раздулась до {filters.height()} px "
            f"вместо одной строки"
        )

        # Скрытый блок не должен удерживать вес: иначе место раздают карточки.
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is not None and not widget.isVisible():
                assert layout.stretch(index) == 0, (
                    f"REP-01: скрытый {type(widget).__name__} удерживает "
                    f"вес {layout.stretch(index)} — отступы разъедутся"
                )
        window.close()

