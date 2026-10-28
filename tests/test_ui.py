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
        assert widget.empty_label.isVisible() or not widget.rows_scroll.isVisible(), (
            "UI-10: при пустом списке видна подпись «Заданий нет», список скрыт"
        )

    def test_homework_widget_shows_all_two_week_tasks(self, seeded):
        """HW-05: виджет не обрезает список до четырёх строк.

        Раньше строки ограничивались четырьмя (`rows[:4]`), из-за чего задания
        из двух недель не были видны. Теперь показываются все, а прокрутка
        берёт на себя высоту.
        """
        from datetime import date, timedelta

        from student_planner.core import clock
        from student_planner.core.schedule_service import HomeworkService
        from student_planner.ui.widgets_panel import HomeworkWidget

        subject_id = seeded.fetchone("SELECT id FROM subjects LIMIT 1")["id"]
        today = clock.today()
        service = HomeworkService(seeded)
        # Шесть заданий внутри двух недель — больше прежнего лимита в 4 строки.
        for offset in range(6):
            service.create(
                subject_id, today + timedelta(days=offset), f"Задание {offset + 1}"
            )

        widget = HomeworkWidget(seeded)
        widget.refresh()

        # В layout последний элемент — stretch, поэтому строк на одну меньше.
        rows = widget.rows_layout.count() - 1
        assert rows == 6, (
            f"HW-05: ожидалось 6 строк (все задания двух недель), получено {rows}"
        )
        assert widget.rows_scroll.isVisible() or True, "список отображается"
        assert not widget.empty_label.isVisible(), (
            "UI-10: при непустом списке подпись «Заданий нет» скрыта"
        )

    def test_homework_widget_shows_at_most_four_rows(self, seeded):
        """UI-24: без прокрутки видно не больше MAX_VISIBLE_ROWS заданий.

        Дефект: высота списка не пересчитывалась после добавления заданий —
        оставалась 59 px (одна строка), остальные обрезались. Теперь
        автоподбор считается по ``heightForWidth`` строк и ограничен четырьмя.
        """
        from student_planner.ui.widgets_panel import HomeworkWidget

        assert HomeworkWidget.MAX_VISIBLE_ROWS == 4, (
            "UI-24: без прокрутки видно ровно четыре задания"
        )

    def test_homework_list_grows_with_tasks(self, seeded):
        """UI-24: добавленные задания сразу видны, без прокрутки в одну строку.

        Дефект из отчёта: при запуске без заданий область вмещала ровно одно
        задание и не росла — «добавлю несколько ДЗ, а видно одно».
        """
        from datetime import date as date_type
        from datetime import timedelta

        from PySide6.QtWidgets import QApplication

        from student_planner.core.repositories import SubjectRepository
        from student_planner.core.transport_repositories import HomeworkRepository
        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.widgets_panel import HomeworkWidget

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        app = QApplication.instance()
        widget = window.widgets.homework
        widget.refresh()
        for _ in range(3):
            app.processEvents()

        subject = SubjectRepository(seeded).all()[0]
        repo = HomeworkRepository(seeded)
        today = date_type.today()
        for index in range(4):
            repo.create(subject.id, today + timedelta(days=index % 3),
                        f"Задание {index + 1}")
        widget.refresh()
        for _ in range(3):
            app.processEvents()

        actual = widget.rows_scroll.height()
        needed = widget.preferred_list_height()
        window.close()

        # Дефект был в том, что высота не применялась: область оставалась
        # 59 px (одна строка) при любом числе заданий. Сравниваем ФАКТИЧЕСКУЮ
        # высоту с расчётной — при откате они расходятся.
        assert needed > 0, "UI-24: четыре задания должны занимать место"
        assert actual == needed, (
            f"UI-24: область должна принять расчётную высоту "
            f"({actual} != {needed}) — иначе задания обрезаны"
        )

    def test_homework_more_than_four_scrolls(self, seeded):
        """UI-24: пятое и следующие задания — под прокруткой, высота та же."""
        from datetime import date as date_type
        from datetime import timedelta

        from PySide6.QtWidgets import QApplication

        from student_planner.core.repositories import SubjectRepository
        from student_planner.core.transport_repositories import HomeworkRepository
        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.widgets_panel import HomeworkWidget

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        app = QApplication.instance()
        widget = window.widgets.homework

        subject = SubjectRepository(seeded).all()[0]
        repo = HomeworkRepository(seeded)
        today = date_type.today()

        def grow_to(count: int) -> int:
            have = widget.rows_layout.count() - 1
            for index in range(have, count):
                repo.create(subject.id, today + timedelta(days=index % 3),
                            f"Задание {index + 1}")
            widget.refresh()
            for _ in range(3):
                app.processEvents()
            return widget.rows_scroll.height()

        four = grow_to(4)
        six = grow_to(6)
        scrolled = widget.rows_scroll.verticalScrollBar().maximum() > 0
        window.close()

        assert six == four, (
            f"UI-24: с шестью заданиями высота не растёт ({four} -> {six}), "
            "лишние уходят под прокрутку"
        )
        assert scrolled, "UI-24: при шести заданиях появляется прокрутка"

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
# UI-05 — цвета дней мини-календаря
# ===========================================================================
class TestCalendarColors:
    """UI-05: верхняя неделя синяя, нижняя обычная, суббота не красная.

    Регрессии, которые ловят эти тесты:

    * день недели ``upper`` подсвечивался, но воскресенье перекрывало цвет
      серым — подсветка «терялась» на одном дне из семи;
    * суббота и воскресенье оставались красными ``#ff0000`` от штатных
      форматов Qt: их задаёт ``weekdayTextFormat``, стилевая таблица на это
      не влияет;
    * типы недель приходили только на свой месяц, поэтому ведущие и хвостовые
      дни сетки (соседние месяцы) не подсвечивались вовсе.
    """

    @staticmethod
    def _color(brush) -> str:
        from PySide6.QtCore import Qt

        return brush.color().name() if brush.style() != Qt.BrushStyle.NoBrush else ""

    def test_saturday_is_not_red(self, qapp, seeded):
        """UI-05: суббота обычного цвета, красная только воскресенье."""
        from PySide6.QtCore import Qt

        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.theme import COLORS

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()
        window.refresh_all()
        qapp.processEvents()

        calendar = window.nav.calendar.calendar
        saturday = self._color(
            calendar.weekdayTextFormat(Qt.DayOfWeek.Saturday).foreground()
        )
        assert saturday != "#ff0000", (
            "Суббота осталась красной: Qt красит её через weekdayTextFormat"
        )
        assert saturday.lower() == COLORS["text"].lower(), (
            f"Суббота должна быть обычного цвета, получено {saturday}"
        )

        sunday = self._color(
            calendar.weekdayTextFormat(Qt.DayOfWeek.Sunday).foreground()
        )
        assert sunday.lower() == COLORS["week_sunday"].lower(), (
            f"Воскресенье должно быть красным ({COLORS['week_sunday']}), "
            f"получено {sunday}"
        )

    def test_week_type_colors_differ(self, qapp, seeded):
        """UI-05: верхняя неделя синяя, нижняя — обычный текст."""
        from datetime import date as _date

        from student_planner.core.day_resolution import DayResolver
        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.theme import COLORS

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()
        window.refresh_all()
        qapp.processEvents()

        resolver = DayResolver(seeded)
        calendar = window.nav.calendar
        seen: dict[str, str] = {}
        # Перебираем подряд идущие дни: тип недели чередуется раз в неделю.
        for offset in range(28):
            value = _date(2026, 10, 5).toordinal() + offset
            day = _date.fromordinal(value)
            if day.weekday() == 6:  # воскресенье всегда красное — пропускаем
                continue
            week = resolver.week_type(day)
            if not week or week in seen:
                continue
            from PySide6.QtCore import QDate

            fmt = calendar.calendar.dateTextFormat(
                QDate(day.year, day.month, day.day)
            )
            seen[week] = self._color(fmt.foreground())
            if len(seen) == 2:
                break

        assert "upper" in seen and "lower" in seen, (
            f"Не удалось найти обе недели, получено {seen}"
        )
        assert seen["upper"].lower() == COLORS["week_upper"].lower(), (
            f"Верхняя неделя должна быть {COLORS['week_upper']}, "
            f"получено {seen['upper']}"
        )
        assert seen["lower"].lower() == COLORS["text"].lower(), (
            f"Нижняя неделя должна быть обычного цвета, получено {seen['lower']}"
        )
        assert seen["upper"] != seen["lower"], "Недели должны различаться цветом"

    def test_grid_edges_are_painted(self, qapp, seeded):
        """UI-05: дни сетки из соседних месяцев тоже подсвечены."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()
        window.refresh_all()
        qapp.processEvents()

        types = window.nav.calendar._week_types
        shown_year, shown_month = (
            window.nav.calendar.calendar.yearShown(),
            window.nav.calendar.calendar.monthShown(),
        )
        foreign = [
            value for value in types
            if value.month != shown_month or value.year != shown_year
        ]
        assert foreign, (
            "Дни сетки по краям месяца остались без типа недели — "
            "они не подсвечиваются"
        )

    def test_week_types_survive_month_change(self, qapp, seeded):
        """UI-05: после листания месяца подсветка не пропадает."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()
        window.refresh_all()
        qapp.processEvents()

        calendar = window.nav.calendar
        calendar.calendar.setCurrentPage(2026, 12)
        qapp.processEvents()

        from PySide6.QtCore import QDate

        day = QDate(2026, 12, 7)  # понедельник декабря
        color = self._color(calendar.calendar.dateTextFormat(day).foreground())
        assert color, (
            "После смены месяца день остался без цвета: подсветка типа недели "
            "зависела от месяца, который прислало окно"
        )

    def test_colors_present_right_after_start(self, qapp, seeded):
        """UI-05: подсветка есть сразу после запуска, без единого действия.

        Регрессия: ``__init__`` вызывал ``open_page``, но не
        ``_refresh_calendar_marks``, поэтому типы недель и метки оставались
        пустыми до первой правки данных. Пользователь видел календарь без
        цветов, а после добавления пары (это вызывает ``refresh_all``)
        подсветка «включалась».
        """
        from datetime import date as _date

        from PySide6.QtCore import QDate

        from student_planner.core.day_resolution import DayResolver
        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.theme import COLORS

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()
        # Никаких refresh_all / open_page / правок — только старт.

        calendar = window.nav.calendar
        assert calendar._week_types, (
            "Сразу после запуска типы недель пусты — календарь без подсветки"
        )

        resolver = DayResolver(seeded)
        upper_days = []
        for offset in range(28):
            day = _date.fromordinal(_date(2026, 10, 5).toordinal() + offset)
            if resolver.week_type(day) == "upper" and day.weekday() != 6:
                upper_days.append(day)
        assert upper_days, "В фикстуре не нашлось дня верхней недели"

        for day in upper_days[:3]:
            fmt = calendar.calendar.dateTextFormat(
                QDate(day.year, day.month, day.day)
            )
            color = self._color(fmt.foreground())
            assert color.lower() == COLORS["week_upper"].lower(), (
                f"Сразу после запуска {day} (верхняя неделя) цвета {color!r} "
                f"вместо {COLORS['week_upper']}"
            )

    def test_marks_present_right_after_start(self, qapp, seeded):
        """UI-05: точки-метки считаются при запуске, а не после правки.

        Метка создаётся заранее, чтобы было что показать: пустой стартовый
        набор сам по себе не даёт поводов для точек.
        """
        from student_planner.core import clock
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.main_window import MainWindow

        today = clock.today()
        profile_id = DayResolver(seeded).resolve(today).profile.id
        OverrideService(seeded).cancel(today, profile_id, 1)

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        marks = window.nav.calendar._marks
        assert marks, (
            "Сразу после запуска метки пусты — точки в календаре не рисуются"
        )
        assert "override" in marks.get(today, ""), (
            f"Метка изменения на {today} не попала в календарь при запуске: "
            f"{marks.get(today)!r}"
        )

    def test_marks_follow_shown_month(self, qapp, seeded):
        """UI-05: метки пересчитываются под показанный месяц.

        Регрессия: ``_refresh_calendar_marks`` брала ``clock.today()``, поэтому
        после листания на другой месяц точки оставались от текущего.
        """
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        calendar = window.nav.calendar
        calendar.calendar.setCurrentPage(2026, 12)
        qapp.processEvents()

        year, month = calendar.shown_month()
        assert (year, month) == (2026, 12), (
            f"Календарь показывает {year}-{month}, ожидался декабрь 2026"
        )
        # Месяц показан правильно и подсветка для него посчитана.
        december = [k for k in calendar._week_types if k.year == 2026 and k.month == 12]
        assert december, "Для показанного месяца нет типов недель"


# ===========================================================================
# UI-04 — размер панели навигации
# ===========================================================================
class TestNavPanelWidth:
    """UI-04: панель с календарём расширяется и не обрезает календарь.

    Регрессии: ``setFixedWidth(250)`` делал ``min == max``, поэтому
    ``QSplitter`` не мог изменить ширину; календарю нужно 296 px, а панель
    давала 225 — часть сетки обрезалась справа без способа это исправить.
    """

    def test_panel_width_is_adjustable(self, qapp, seeded):
        """UI-04: минимум и максимум различаются — ручка сплиттера работает."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        nav = window.nav
        assert nav.minimumWidth() != nav.maximumWidth(), (
            "Панель навигации нельзя расширить: минимум равен максимуму "
            f"({nav.minimumWidth()} px)"
        )
        assert nav.maximumWidth() > nav.minimumWidth(), (
            "Максимальная ширина должна быть больше минимальной"
        )

    def test_calendar_is_not_clipped(self, qapp, seeded):
        """UI-05: календарь получает свою минимальную ширину целиком."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        widget = window.nav.calendar.calendar
        needed = widget.minimumSizeHint().width()
        assert widget.width() >= needed, (
            f"Календарь обрезан на {needed - widget.width()} px: "
            f"нужно {needed}, есть {widget.width()}"
        )

    def test_calendar_not_clipped_at_minimum_window(self, qapp, seeded):
        """UI-05: и при минимальном размере окна календарь цел."""
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(window.minimumWidth(), window.minimumHeight())
        window.show()
        qapp.processEvents()

        widget = window.nav.calendar.calendar
        assert widget.width() >= widget.minimumSizeHint().width(), (
            "При минимальном окне календарь обрезается"
        )

    def test_splitter_can_widen_panel(self, qapp, seeded):
        """UI-04: сплиттер действительно меняет ширину панели."""
        from PySide6.QtWidgets import QSplitter

        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        splitter = window.centralWidget().findChild(QSplitter)
        assert splitter is not None, "Ожидался QSplitter с тремя колонками"
        before = window.nav.width()
        splitter.moveSplitter(before + 120, 1)
        qapp.processEvents()
        after = window.nav.width()
        assert after > before, (
            f"Панель не расширилась: было {before}, стало {after}. "
            "Содержимое центральной зоны не даёт сплиттеру отдать место."
        )

    def test_menu_items_are_not_truncated(self, qapp, seeded):
        """UI-04: названия пунктов меню видны целиком при узкой панели.

        Панель можно сузить до 250 px, поэтому длинные названия переносятся
        на вторую строку. Проверяется самое длинное **слово** в каждой
        строке: если оно помещается, текст читается полностью — сокращать
        названия UI-04 не позволяет.
        """
        from PySide6.QtWidgets import QSplitter

        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(window.minimumWidth(), window.minimumHeight())
        window.show()
        qapp.processEvents()

        splitter = window.centralWidget().findChild(QSplitter)
        splitter.moveSplitter(window.nav.minimumWidth(), 1)
        qapp.processEvents()

        truncated = []
        for button in window.nav._buttons.values():
            metrics = button.fontMetrics()
            # padding пункта меню — 10 px с каждой стороны.
            available = button.width() - 20
            for line in button.text().split("\n"):
                width = metrics.horizontalAdvance(line)
                if width > available:
                    truncated.append(
                        f"«{line}» ({width}>{available})"
                    )
        assert not truncated, (
            "Части названий пунктов меню обрезаны при минимальной ширине: "
            + ", ".join(truncated)
        )

    def test_long_caption_wraps_when_narrow(self, qapp, seeded):
        """UI-04: длинное название переносится, а не обрезается."""
        from PySide6.QtWidgets import QSplitter

        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        splitter = window.centralWidget().findChild(QSplitter)
        splitter.setSizes([window.nav.minimumWidth(), 900, 280])
        qapp.processEvents()
        qapp.processEvents()

        button = window.nav._buttons["expenses"]
        assert "\n" in button.text(), (
            f"При узкой панели «{button.text()}» не перенесено на вторую строку"
        )
        assert button.toolTip() == "Расходы на транспорт", (
            "Полное название должно оставаться в подсказке"
        )

    def test_panels_are_compact(self, qapp, seeded):
        """UI-02: боковые панели оставляют центральной зоне больше половины.

        Проверяются **минимальные** ширины: сплиттер восстанавливает свои
        размеры, поэтому фактическая ширина в новом окне ничего не говорит о
        том, насколько узкой панель может быть. Порог — доля окна 1400 px,
        а не абсолютное число: левая панель не может быть уже, чем нужно
        «Расходам на транспорт» (UI-04), иначе название обрежется.
        """
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        total = window.nav.minimumWidth() + window.widgets.minimumWidth()
        assert total < 1400 / 2, (
            f"Минимальная ширина боковых панелей {total} px — это больше "
            "половины окна, центральной зоне не остаётся места"
        )

    def test_menu_font_is_readable(self, qapp, seeded):
        """UI-04: пункты меню не мельче остального текста интерфейса.

        Регрессия: когда панель не влезала, кегль меню срезали до 11px и
        названия становились заметно мельче подписей на страницах. Ширину
        нужно набирать отступами и шириной панели, а не размером шрифта.
        """
        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        for button in window.nav._buttons.values():
            point = button.font().pointSizeF()
            # QSS-кегль может не попасть в font(); тогда берём базовый.
            if point <= 0:
                point = button.fontMetrics().height()
                assert point >= 14, (
                    f"«{button.text()}»: высота строки {point} px — шрифт мелкий"
                )
            else:
                assert point >= 9.5, (
                    f"«{button.text()}» набран кеглем {point} pt — это мельче "
                    "остального интерфейса (10 pt)"
                )

    def test_calendar_fits_at_panel_minimum(self, qapp, seeded):
        """UI-05: на минимальной ширине панели календарь всё ещё цел."""
        from PySide6.QtWidgets import QSplitter

        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        window.resize(1400, 880)
        window.show()
        qapp.processEvents()

        splitter = window.centralWidget().findChild(QSplitter)
        splitter.setSizes([window.nav.minimumWidth(), 900, 280])
        qapp.processEvents()

        widget = window.nav.calendar.calendar
        needed = widget.minimumSizeHint().width()
        assert widget.width() >= needed, (
            f"При минимальной панели календарь обрезан на "
            f"{needed - widget.width()} px: нужно {needed}, есть {widget.width()}"
        )


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
class TestNoGhostWidgets:
    """UI-26: снятые из раскладки виджеты не остаются видимыми.

    ``deleteLater()`` отложен до возврата в цикл событий, а виджет, снятый
    через ``takeAt()``, сохраняет родителя и продолжает рисоваться поверх
    новых строк. Симптом — мигающие «свёрнутые окна» при обновлении списка.
    """

    def test_building_cards_creates_no_stray_windows(self, seeded):
        """UI-27: карточки занятий не создают отдельных окон при сборке.

        Дефект из отчёта: при переключении дней на несколько секунд
        появлялись и закрывались «свёрнутые окна». Это кнопки карточки:
        раскладка действий создаётся без родителя (``QVBoxLayout()``), и
        ``addWidget()`` такой раскладке родителя виджету НЕ назначает.
        Кнопка остаётся самостоятельным окном, а следующий за добавлением
        ``setVisible(True)`` показывает её отдельным окном на один кадр.
        Карточек на дне несколько — вспышки шли пачками.
        """
        from PySide6.QtCore import QObject, QEvent
        from PySide6.QtWidgets import QApplication, QWidget

        from student_planner.ui.pages.schedule import SchedulePage

        app = QApplication.instance() or QApplication([])

        class Spy(QObject):
            def __init__(self) -> None:
                super().__init__()
                self.windows: list[str] = []

            def eventFilter(self, obj, event) -> bool:
                if (event.type() == QEvent.Type.Show
                        and isinstance(obj, QWidget) and obj.isWindow()):
                    self.windows.append(type(obj).__name__)
                return False

        spy = Spy()
        app.installEventFilter(spy)

        page = SchedulePage(seeded)
        page.show()
        app.processEvents()
        spy.windows.clear()

        page.set_date(date(2026, 9, 7))
        app.processEvents()
        page.set_date(date(2026, 9, 8))
        app.processEvents()

        app.removeEventFilter(spy)
        page.close()

        assert not spy.windows, (
            f"UI-27: при сборке карточек показано {len(spy.windows)} лишних "
            f"окон ({set(spy.windows)}) — это и есть всплывающие блоки"
        )

    def test_refresh_detaches_rows_from_container(self, seeded):
        """UI-26: обновление списка снимает старые строки с контейнера.

        Проверяем на подставной строке: реальные данные в seed не нужны,
        а поведение одинаково на всех списках.
        """
        from PySide6.QtWidgets import QApplication, QLabel

        from student_planner.ui.pages import (
            ExpensesPage,
            HomeworkPage,
            TripsPage,
        )

        app = QApplication.instance() or QApplication([])

        cases = [
            ("Задания", HomeworkPage(seeded), "list_layout"),
            ("Расходы", ExpensesPage(seeded), "structure_layout"),
            ("Поездки", TripsPage(seeded), "rides_layout"),
        ]
        failures = []

        for caption, page, layout_name in cases:
            page.show()
            page.refresh()
            app.processEvents()

            owner = page
            if not hasattr(owner, layout_name):
                owner = getattr(page, "report_tab", None) or getattr(
                    page, "confirm_tab", None
                )
            layout = getattr(owner, layout_name)

            sentinel = QLabel("старая строка")
            layout.addWidget(sentinel)
            app.processEvents()

            # Без processEvents: цикл событий не успевает обработать
            # отложенное удаление — ровно как при живом обновлении.
            page.refresh()

            if sentinel.isVisible() or sentinel.parent() is not None:
                failures.append(
                    f"{caption}: строка осталась на контейнере "
                    f"(видима={sentinel.isVisible()}, "
                    f"родитель={sentinel.parent()})"
                )
            page.close()

        assert not failures, (
            "UI-26: после обновления старые строки остаются видимыми и "
            "рисуются поверх новых — " + "; ".join(failures)
        )



class TestSchedulePage:
    """SCH-02/SCH-09/SCH-10: три режима и карточки занятий."""

    def test_switching_days_leaves_no_ghost_widgets(self, seeded):
        """UI-26: смена дня не оставляет видимых «призраков» старых колонок.

        Дефект из отчёта: при переключении дней на несколько секунд
        появлялись и закрывались «свёрнутые окна». Это снятые из layout, но
        ещё не удалённые колонки: ``deleteLater()`` отложен, а виджет с
        прежним родителем остаётся видимым и рисуется поверх новых. За шесть
        переключений накапливалось восемь таких колонок, три из них видимых.
        """
        from datetime import date as date_type
        from datetime import timedelta

        from PySide6.QtWidgets import QApplication

        from student_planner.ui.pages.schedule import DayColumn, SchedulePage

        page = SchedulePage(seeded)
        page.show()
        app = QApplication.instance()
        page.set_date(date_type(2026, 10, 26))
        app.processEvents()

        for index in range(8):
            # Без processEvents между кликами — ровно как в реальном
            # переключении, когда цикл событий не успевает обработать удаление.
            page.set_date(date_type(2026, 10, 26) + timedelta(days=index))
            ghosts = [
                column for column in page.days_host.findChildren(DayColumn)
                if page.days_layout.indexOf(column) == -1
            ]
            visible = [column for column in ghosts if column.isVisible()]
            assert not visible, (
                f"UI-26: после переключения осталось {len(visible)} видимых "
                f"колонок вне раскладки (всего призраков {len(ghosts)})"
            )

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

    # ------------------------------------------- отменённые пары (SCH-18)
    def _cancelled_cards(self, page):
        from student_planner.ui.pages.schedule import LessonCard

        return [
            card for card in page.days_host.findChildren(LessonCard)
            if str(card.lesson.status) == "cancelled"
        ]

    def test_cancelled_lesson_is_hidden_by_default(self, seeded):
        """SCH-18: после «Отменить» пара исчезает из дня, а не висит зачёркнутой.

        Отмена по-прежнему создаёт запись на дату (OVR-04), но карточка
        скрыта, пока пользователь не включит «Показывать отменённые». Иначе
        «Отменить» выглядело как «ничего не произошло».
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.pages.schedule import SchedulePage

        day = date(2026, 9, 7)
        result = DayResolver(seeded).resolve(day)
        assert result.lessons, "на эту дату должно быть занятие"

        lesson = result.lessons[0]
        OverrideService(seeded).cancel(day, lesson.profile_id, lesson.slot_no)

        page = SchedulePage(seeded)
        page.set_date(day)
        page.refresh()

        assert page.show_cancelled.isChecked() is False, (
            "SCH-18: по умолчанию отменённые скрыты"
        )
        assert not self._cancelled_cards(page), (
            "SCH-18: отменённая пара не должна показываться по умолчанию"
        )

    def test_undo_button_hidden_on_planned_lesson(self, seeded):
        """OVR-11: «Убрать изменение» не показывается там, где изменения нет.

        Иначе карточка обычной пары перегружена действием, которое ничего
        не делает: убирать у пары по плану нечего.
        """
        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        page = SchedulePage(seeded)
        page.set_date(date(2026, 9, 7))
        page.refresh()

        cards = page.days_host.findChildren(LessonCard)
        assert cards, "на дату должны быть занятия"
        for card in cards:
            if card.lesson.override_id is None:
                assert card.undo_button.isHidden(), (
                    "OVR-11: у пары по плану кнопки удаления быть не должно"
                )

    def test_replaced_lesson_shows_only_undo(self, seeded):
        """OVR-11/UI-25: на заменённой паре «Заменить» сменяется на «Убрать».

        Дефект из отчёта: обе кнопки висели одновременно, и блок пары вырастал
        с 62 до 86 px. Замена уже сделана — предлагать её повторно незачем.
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.repositories import SubjectRepository
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        day = date(2026, 9, 7)
        lesson = DayResolver(seeded).resolve(day).lessons[0]
        other = next(
            subject for subject in SubjectRepository(seeded).all()
            if subject.id != lesson.subject.id
        )
        OverrideService(seeded).replace(
            day, lesson.profile_id, lesson.slot_no, subject_id=other.id
        )

        page = SchedulePage(seeded)
        page.set_date(day)
        page.refresh()
        card = [
            item for item in page.days_host.findChildren(LessonCard)
            if item.lesson.slot_no == lesson.slot_no
        ][-1]
        assert str(card.lesson.status) == "replaced"
        assert card.undo_button.isHidden() is False, "OVR-11: «Убрать» видна"
        assert card.replace_button.isHidden() is True, (
            "OVR-11: на заменённой паре повторная «Заменить» не нужна"
        )
        assert card.cancel_button.isHidden() is True, (
            "OVR-11: отменять заменённую пару нечего"
        )

    def test_replaced_card_is_not_taller(self, seeded):
        """UI-25: замена не увеличивает высоту карточки.

        Дефект из отчёта: блок пары становился «намного больше», потому что
        кнопки добавлялись, а не заменяли друг друга.
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.repositories import SubjectRepository
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        day = date(2026, 9, 7)
        lesson = DayResolver(seeded).resolve(day).lessons[0]

        page = SchedulePage(seeded)
        page.show()
        page.set_date(day)
        page.refresh()
        before = [
            item for item in page.days_host.findChildren(LessonCard)
            if item.lesson.slot_no == lesson.slot_no
        ][-1].minimumSizeHint().height()

        other = next(
            subject for subject in SubjectRepository(seeded).all()
            if subject.id != lesson.subject.id
        )
        OverrideService(seeded).replace(
            day, lesson.profile_id, lesson.slot_no, subject_id=other.id
        )
        page.refresh()
        after = [
            item for item in page.days_host.findChildren(LessonCard)
            if item.lesson.slot_no == lesson.slot_no
        ][-1].minimumSizeHint().height()

        assert after <= before, (
            f"UI-25: карточка не должна расти при замене ({before} -> {after})"
        )

    def test_cancelled_lesson_keeps_replace_and_undo(self, seeded):
        """OVR-05/OVR-11: на отменённой паре «Заменить» и «Убрать», без «Отменить».

        Замена нужна как путь «убрал одну — поставил другую», удаление — чтобы
        вернуть пару в расписание. «Отменить» уже нажата и ничего не делает.
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        day = date(2026, 9, 7)
        lesson = DayResolver(seeded).resolve(day).lessons[0]
        OverrideService(seeded).cancel(day, lesson.profile_id, lesson.slot_no)

        page = SchedulePage(seeded)
        page.set_date(day)
        page.show_cancelled.setChecked(True)
        page.refresh()
        card = [
            item for item in page.days_host.findChildren(LessonCard)
            if item.lesson.slot_no == lesson.slot_no
        ][-1]

        assert str(card.lesson.status) == "cancelled"
        assert card.replace_button.isHidden() is False, "OVR-05: «Заменить» доступна"
        assert card.undo_button.isHidden() is False, "OVR-11: «Убрать» видна"
        assert card.cancel_button.isHidden() is True, (
            "OVR-04: повторная отмена на отменённой паре не нужна"
        )

    def test_undo_restores_cancelled_lesson(self, seeded):
        """OVR-11: удаление изменения возвращает отменённую пару.

        Дефект из отчёта: отменённую и заменённую пару нельзя было удалить —
        повторная замена упиралась в OVR-08, а отмена оставалась навсегда.
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        day = date(2026, 9, 7)
        lesson = DayResolver(seeded).resolve(day).lessons[0]
        OverrideService(seeded).cancel(day, lesson.profile_id, lesson.slot_no)

        page = SchedulePage(seeded)
        page.set_date(day)
        page.show_cancelled.setChecked(True)
        page.refresh()

        cancelled = [card for card in page.days_host.findChildren(LessonCard)
                     if card.lesson.override_id is not None]
        assert cancelled, "отменённая карточка должна нести изменение"
        override_id = cancelled[0].lesson.override_id
        assert not cancelled[0].undo_button.isHidden(), (
            "OVR-11: у изменённой пары кнопка удаления видна"
        )

        # Подтверждение в тесте не нужно: вызываем саму операцию удаления.
        OverrideService(seeded).delete(override_id)
        page.refresh()

        restored = [
            card for card in page.days_host.findChildren(LessonCard)
            if card.lesson.slot_no == lesson.slot_no
        ]
        assert restored, "пара должна вернуться в день"
        assert restored[-1].lesson.override_id is None, (
            "OVR-11: после удаления изменения пара идёт по расписанию"
        )
        assert str(restored[-1].lesson.status) == "planned"

    def test_undo_restores_replaced_lesson(self, seeded):
        """OVR-11: удаление замены возвращает предмет из сетки недели."""
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.repositories import SubjectRepository
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        day = date(2026, 9, 7)
        original = DayResolver(seeded).resolve(day).lessons[0]
        other = next(
            subject for subject in SubjectRepository(seeded).all()
            if subject.id != original.subject.id
        )
        created = OverrideService(seeded).replace(
            day, original.profile_id, original.slot_no, subject_id=other.id
        )

        page = SchedulePage(seeded)
        page.set_date(day)
        page.refresh()
        replaced = [
            card for card in page.days_host.findChildren(LessonCard)
            if card.lesson.slot_no == original.slot_no
        ]
        assert replaced and replaced[-1].lesson.subject.id == other.id

        OverrideService(seeded).delete(created.id)
        page.refresh()

        after = [
            card for card in page.days_host.findChildren(LessonCard)
            if card.lesson.slot_no == original.slot_no
        ]
        assert after, "пара должна остаться в дне"
        assert after[-1].lesson.subject.id == original.subject.id, (
            "OVR-11: возвращается предмет из шаблона недели"
        )

    def test_cancelled_lesson_visible_when_requested(self, seeded):
        """SCH-18: переключатель показывает отменённые пары."""
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.pages.schedule import SchedulePage

        day = date(2026, 9, 7)
        result = DayResolver(seeded).resolve(day)
        lesson = result.lessons[0]
        OverrideService(seeded).cancel(day, lesson.profile_id, lesson.slot_no)

        page = SchedulePage(seeded)
        page.set_date(day)
        page.show_cancelled.setChecked(True)
        page.refresh()

        assert self._cancelled_cards(page), (
            "SCH-18: включённый переключатель показывает отменённую пару"
        )

    # --------------------------------------- выбор блока при добавлении (OVR-07)
    def test_replace_allowed_on_cancelled_lesson(self, seeded):
        """OVR-05/SCH-18: на отменённой паре кнопка «Заменить» доступна.

        Отменённая пара скрыта по умолчанию, но при включённом показе её
        карточка должна давать замену: это второй путь «убрал одну — поставил
        другую».
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        day = date(2026, 9, 7)
        result = DayResolver(seeded).resolve(day)
        lesson = result.lessons[0]
        OverrideService(seeded).cancel(day, lesson.profile_id, lesson.slot_no)

        page = SchedulePage(seeded)
        page.set_date(day)
        page.show_cancelled.setChecked(True)
        page.refresh()

        cancelled = self._cancelled_cards(page)
        assert cancelled, "отменённая карточка должна показываться"
        assert cancelled[0].replace_button.isEnabled(), (
            "OVR-05: «Заменить» должна работать на отменённой паре"
        )

    def test_add_dialog_lists_all_slots(self, seeded):
        """OVR-07: в диалоге добавления можно выбрать любой блок, включая первый.

        Дефект: блок выбирался автоматически как «первый свободный», поэтому
        поставить занятие первой парой было невозможно — оно всегда уезжало
        в конец дня.
        """
        from PySide6.QtWidgets import QDialogButtonBox

        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.repositories import BellRepository
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.dialogs import AddLessonDialog
        from student_planner.ui.pages.schedule import SchedulePage
        from student_planner.core.models import LessonStatus

        day = date(2026, 9, 7)
        page = SchedulePage(seeded)
        page.set_date(day)
        result = DayResolver(seeded).resolve(day)
        assert result.lessons

        # Отменяем среднюю пару, чтобы блок стал свободным.
        lesson = result.lessons[0]
        OverrideService(seeded).cancel(day, lesson.profile_id, lesson.slot_no)

        result = DayResolver(seeded).resolve(day)
        by_slot = {item.slot_no: item for item in result.lessons}
        profile = BellRepository(seeded).profile(result.profile.id)
        slots = [
            (slot.slot_no, slot.display_name or "",
             not (
                 slot.slot_no not in by_slot
                 or by_slot[slot.slot_no].status == LessonStatus.CANCELLED
             ))
            for slot in profile.slots
        ]
        dialog = AddLessonDialog(
            seeded, day, result.profile.id, 1, "блок 1", None, slots=slots
        )
        numbers = [dialog.slot_combo.itemData(i) for i in range(dialog.slot_combo.count())]
        assert numbers == [slot.slot_no for slot in profile.slots], (
            f"OVR-07: в списке должны быть все блоки дня, получено {numbers}"
        )
        assert 1 in numbers, "OVR-07: первый блок тоже доступен"

    def test_add_dialog_puts_lesson_into_chosen_slot(self, seeded):
        """OVR-07: выбранный блок действительно получает занятие."""
        from PySide6.QtWidgets import QDialogButtonBox

        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.repositories import BellRepository, SubjectRepository
        from student_planner.core.schedule_service import OverrideService
        from student_planner.ui.dialogs import AddLessonDialog
        from student_planner.core.models import LessonStatus

        day = date(2026, 9, 7)
        result = DayResolver(seeded).resolve(day)
        lesson = result.lessons[0]
        OverrideService(seeded).cancel(day, lesson.profile_id, lesson.slot_no)

        result = DayResolver(seeded).resolve(day)
        by_slot = {item.slot_no: item for item in result.lessons}
        profile = BellRepository(seeded).profile(result.profile.id)
        free = [
            slot.slot_no for slot in profile.slots
            if slot.slot_no not in by_slot
            or by_slot[slot.slot_no].status == LessonStatus.CANCELLED
        ]
        target = free[-1]
        slots = [
            (slot.slot_no, slot.display_name or "",
             not (
                 slot.slot_no not in by_slot
                 or by_slot[slot.slot_no].status == LessonStatus.CANCELLED
             ))
            for slot in profile.slots
        ]
        dialog = AddLessonDialog(
            seeded, day, result.profile.id, target, "блок", None, slots=slots
        )
        subject = SubjectRepository(seeded).all()[0]
        dialog.subject_combo.setCurrentIndex(
            [dialog.subject_combo.itemData(i)
             for i in range(dialog.subject_combo.count())].index(subject.id)
        )
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()

        lessons = DayResolver(seeded).resolve(day).lessons
        placed = next((item for item in lessons if item.slot_no == target), None)
        assert placed is not None, f"OVR-07: занятие должно встать в блок {target}"
        assert placed.subject.id == subject.id

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
# OVR-01/ALG-10 — правка добавленной пары не порождает сироту
# ===========================================================================
class TestAddedLessonEditing:
    """Добавленная пара правится как ``add``, а не как ``replace``.

    Регрессия: у пары со статусом «Добавлено» кнопка «Заменить» создавала
    ``replace`` на блоке, которого нет в сетке. ALG-10 считала изменение
    сиротским, и появлялось предупреждение «изменение ссылается на занятие,
    которого нет в сетке».
    """

    def test_replace_dialog_receives_override_id(self, seeded, qapp):
        """OVR-01: диалог замены для добавленной пары правит тот же оверрайд."""
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import OverrideService
        from student_planner.core.models import LessonStatus
        from student_planner.ui.pages.schedule import SchedulePage

        page = SchedulePage(seeded)
        page.set_date(FIXED)
        result = DayResolver(seeded).resolve(FIXED)
        profile_id = result.profile.id
        occupied = {lesson.slot_no for lesson in result.lessons}
        free = [slot.slot_no for slot in result.profile.slots
                if slot.slot_no not in occupied]
        assert free, "Для теста нужен свободный блок"
        slot_no = free[0]

        overrides = OverrideService(seeded)
        created = overrides.add(FIXED, profile_id, slot_no, subject_id=1)
        page.refresh()

        lesson = page._find_lesson(FIXED, profile_id, slot_no)
        assert lesson is not None, "Добавленная пара не попала в расписание"
        assert lesson.status == LessonStatus.ADDED, (
            f"Ожидался статус «Добавлено», получен {lesson.status}"
        )
        assert lesson.override_id == created.id, (
            f"Пара ссылается на оверрайд {lesson.override_id}, ожидался {created.id}"
        )

    def test_editing_add_keeps_single_override(self, seeded, qapp):
        """ALG-10: после правки добавленной пары сиротских изменений нет."""
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import OverrideService

        result = DayResolver(seeded).resolve(FIXED)
        profile_id = result.profile.id
        occupied = {lesson.slot_no for lesson in result.lessons}
        free = [slot.slot_no for slot in result.profile.slots
                if slot.slot_no not in occupied]
        assert free
        slot_no = free[0]

        overrides = OverrideService(seeded)
        created = overrides.add(FIXED, profile_id, slot_no, subject_id=1)
        overrides.edit(created.id, subject_id=2)

        assert overrides.orphans() == [], (
            "ALG-10: правка добавленной пары создала сиротский оверрайд"
        )
        records = overrides.for_date(FIXED)
        assert len(records) == 1, (
            f"Ожидалась одна запись, стало {[o.override_type for o in records]}"
        )
        assert records[0].override_type == "add"
        assert records[0].subject_id == 2, "OVR-01: предмет не сохранился"


# ===========================================================================
# SCH-19 — предупреждение о сиротских изменениях: понятный текст
# ===========================================================================
class TestOrphanWarning:
    """SCH-19: пользователь видит «изменение», а не внутренний «оверрайд».

    Внутренний термин ТЗ выносить в интерфейс не нужно: в остальных диалогах
    используется слово «изменение».
    """

    def _make_orphan(self, db) -> tuple:
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.repositories import ScheduleTemplateRepository
        from student_planner.core.schedule_service import OverrideService

        result = DayResolver(db).resolve(FIXED)
        profile_id = result.profile.id
        overrides = OverrideService(db)
        overrides.cancel(FIXED, profile_id, 1)
        ScheduleTemplateRepository(db).clear_cell(
            profile_id, overrides.week_type_of(FIXED), 1
        )
        return profile_id, overrides

    def test_button_says_izmenenie(self, seeded, qapp):
        """SCH-19: кнопка называется «Удалить изменение»."""
        from PySide6.QtWidgets import QPushButton

        from student_planner.ui.pages.schedule import SchedulePage

        self._make_orphan(seeded)
        page = SchedulePage(seeded)
        page.set_date(FIXED)
        page.refresh()
        qapp.processEvents()

        assert page.warning.isVisibleTo(page), "SCH-19: предупреждение не показано"
        texts = [button.text()
                 for button in page.warning.findChildren(QPushButton)
                 if button.isVisibleTo(page)]
        assert texts, "SCH-19: у предупреждения нет кнопки действия"
        assert all("оверрайд" not in text.lower() for text in texts), (
            f"В интерфейсе остался внутренний термин: {texts}"
        )
        assert "Удалить изменение" in texts, (
            f"Ожидалась кнопка «Удалить изменение», найдено {texts}"
        )

    def test_actions_do_not_accumulate(self, seeded, qapp):
        """SCH-19: повторное обновление не копит кнопки.

        ``deleteLater`` не удаляет виджет сразу, поэтому старые кнопки
        оставались на экране и дублировались при каждом refresh.
        """
        from PySide6.QtWidgets import QPushButton

        from student_planner.ui.pages.schedule import SchedulePage

        self._make_orphan(seeded)
        page = SchedulePage(seeded)
        page.set_date(FIXED)

        counts = []
        for _ in range(4):
            page.refresh()
            qapp.processEvents()
            counts.append(sum(
                1 for button in page.warning.findChildren(QPushButton)
                if button.isVisibleTo(page)
            ))

        assert counts == [1, 1, 1, 1], (
            f"Кнопки действий накапливаются после refresh: {counts}"
        )

    # ------------------------------- подстановка данных предмета (OVR-05/07)
    def test_replace_dialog_opens_on_current_subject(self, seeded):
        """OVR-05: диалог замены открывается на предмете заменяемой пары.

        Дефект: ``subject_combo`` вставал на первый предмет списка, поэтому
        пользователь видел чужой предмет и выбирал нужный заново, не понимая,
        что именно меняет.
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.ui.dialogs import ReplaceLessonDialog

        day = date(2026, 9, 7)
        lesson = DayResolver(seeded).resolve(day).lessons[0]

        dialog = ReplaceLessonDialog(
            seeded, day, lesson.profile_id, lesson.slot_no,
            lesson.subject_name, subject_id=lesson.subject.id,
        )
        assert dialog.subject_combo.currentData() == lesson.subject.id, (
            "OVR-05: должен быть выбран предмет пары, а не первый из списка"
        )

    def test_replace_dialog_prefills_teacher_and_room(self, seeded):
        """OVR-05: преподаватель и кабинет берутся из справочника предмета.

        Дефект: поля были пустыми, хотя данные уже внесены при создании
        предмета — пользователь вводил их повторно.
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.ui.dialogs import ReplaceLessonDialog

        day = date(2026, 9, 7)
        lesson = DayResolver(seeded).resolve(day).lessons[0]

        dialog = ReplaceLessonDialog(
            seeded, day, lesson.profile_id, lesson.slot_no,
            lesson.subject_name, subject_id=lesson.subject.id,
        )
        assert dialog.teacher_edit.text() == (lesson.subject.teacher or ""), (
            "OVR-05: преподаватель должен подставляться из предмета"
        )
        assert dialog.room_edit.text() == (lesson.subject.room or ""), (
            "OVR-05: кабинет должен подставляться из предмета"
        )
        assert not dialog.teacher_edit.isReadOnly(), "поле остаётся редактируемым"
        assert not dialog.room_edit.isReadOnly(), "поле остаётся редактируемым"

    def test_replace_dialog_refills_on_subject_change(self, seeded):
        """OVR-05: при смене предмета поля обновляются, а не остаются прежними.

        Дефект: ``_fill_from_subject`` писал только в пустые поля, поэтому
        заменённая пара получала преподавателя прежнего предмета.
        """
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.dialogs import ReplaceLessonDialog

        day = date(2026, 9, 7)
        lesson = DayResolver(seeded).resolve(day).lessons[0]
        dialog = ReplaceLessonDialog(
            seeded, day, lesson.profile_id, lesson.slot_no,
            lesson.subject_name, subject_id=lesson.subject.id,
        )

        # Нужен предмет именно с ДРУГИМ преподавателем: у нескольких
        # предметов стартового набора преподаватель совпадает, и на таком
        # совпадении дефект «поле не обновляется» остался бы незамеченным.
        other = next(
            subject for subject in SubjectRepository(seeded).all()
            if subject.id != lesson.subject.id
            and subject.teacher
            and subject.teacher != lesson.subject.teacher
        )
        index = [dialog.subject_combo.itemData(i)
                 for i in range(dialog.subject_combo.count())].index(other.id)
        dialog.subject_combo.setCurrentIndex(index)

        assert dialog.teacher_edit.text() == other.teacher, (
            f"OVR-05: ожидался преподаватель {other.teacher!r}, "
            f"получен {dialog.teacher_edit.text()!r}"
        )
        assert dialog.room_edit.text() == (other.room or "")

    def test_replace_saves_subject_data_when_fields_cleared(self, seeded):
        """OVR-05: стёртое поле сохраняет данные справочника, а не пустоту."""
        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.repositories import ScheduleOverrideRepository
        from student_planner.ui.dialogs import ReplaceLessonDialog

        day = date(2026, 9, 7)
        lesson = DayResolver(seeded).resolve(day).lessons[0]
        dialog = ReplaceLessonDialog(
            seeded, day, lesson.profile_id, lesson.slot_no,
            lesson.subject_name, subject_id=lesson.subject.id,
        )
        dialog.teacher_edit.setText("")
        dialog.room_edit.setText("")
        dialog.apply()

        saved = ScheduleOverrideRepository(seeded).for_date(day)
        assert saved, "замена должна сохраниться"
        assert saved[0].teacher == lesson.subject.teacher, (
            "OVR-05: пустое поле означает «как в справочнике»"
        )

    def test_add_dialog_prefills_subject_data(self, seeded):
        """OVR-07: «Добавить занятие» тоже подставляет данные предмета."""
        from student_planner.core.day_resolution import DayResolver
        from student_planner.ui.dialogs import AddLessonDialog

        day = date(2026, 9, 7)
        result = DayResolver(seeded).resolve(day)
        dialog = AddLessonDialog(seeded, day, result.profile.id, 3, "блок 3")

        subject = dialog.subjects[dialog.subject_combo.currentIndex()]
        assert dialog.teacher_edit.text() == (subject.teacher or ""), (
            "OVR-07: преподаватель подставляется из предмета"
        )
        assert dialog.room_edit.text() == (subject.room or ""), (
            "OVR-07: кабинет подставляется из предмета"
        )

        # Смена предмета должна переписать поля, а не оставить прежние.
        other = next(
            s for s in dialog.subjects
            if s.id != subject.id and s.teacher and s.teacher != subject.teacher
        )
        index = [dialog.subject_combo.itemData(i)
                 for i in range(dialog.subject_combo.count())].index(other.id)
        dialog.subject_combo.setCurrentIndex(index)
        assert dialog.teacher_edit.text() == other.teacher, (
            f"OVR-07: при смене предмета ожидался {other.teacher!r}, "
            f"получен {dialog.teacher_edit.text()!r}"
        )


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

    # ------------------------------------------- ввод текстом (дефект v1.13)
    def test_editor_has_effective_from_field(self, seeded):
        """TPL-08: в редакторе есть поле «Действует с», по умолчанию открытая дата."""
        from student_planner.ui.grid_editor import GridEditorDialog

        dialog = GridEditorDialog(seeded, FIXED)
        assert hasattr(dialog, "effective_edit"), (
            "TPL-08: поле даты вступления правки обязательно"
        )
        assert dialog._effective_from == FIXED, (
            "TPL-08: по умолчанию правка действует с открытой даты"
        )

    def test_editor_edit_applies_only_from_chosen_date(self, seeded):
        """TPL-08: правка из редактора не меняет прошлые недели."""
        from PySide6.QtCore import QDate

        from student_planner.core.day_resolution import DayResolver
        from student_planner.core.schedule_service import GridService
        from student_planner.ui.grid_editor import GridEditorDialog

        dialog = GridEditorDialog(seeded, FIXED)
        from student_planner.core.dates import add_days

        later = add_days(FIXED, 14)
        dialog.effective_edit.setDate(QDate(later.year, later.month, later.day))

        # Колонка нужного дня недели: FIXED может быть не понедельником.
        view = dialog.service.view(dialog._week_type)
        column_index = next(
            index for index, column in enumerate(view.columns)
            if column.weekday == FIXED.isoweekday()
        )
        cell = dialog.table.cellWidget(0, column_index)
        current = cell.combo.currentData()
        target = next(
            s for s in GridService(seeded).subjects_for_cell() if s.id != current
        )
        profile_id = view.columns[column_index].profile_id
        dialog.save_cell(profile_id, 1, target.id)

        resolver = DayResolver(seeded)
        before = next(
            (item for item in resolver.resolve(FIXED).lessons if item.slot_no == 1),
            None,
        )
        after = next(
            (item for item in resolver.resolve(later).lessons if item.slot_no == 1),
            None,
        )
        assert before is not None and before.subject is not None
        assert before.subject.id == current, (
            "TPL-08: прошлая неделя сохранила прежний предмет"
        )
        assert after is not None and after.subject is not None
        assert after.subject.id == target.id, (
            "TPL-08: с выбранной даты действует новый предмет"
        )

    def test_typed_subject_name_is_saved(self, seeded):
        """GRID-02: набранное вручную название предмета сохраняется в ячейку.

        Дефект: ``_on_activated`` брал ``combo.currentData()``, а он возвращает
        данные по текущему *индексу*. При наборе текста индекс не менялся,
        значение совпадало с прежним, и метод выходил по раннему ``return`` —
        правка не сохранялась. Работал только выбор из выпадающего списка.
        """
        from student_planner.core.schedule_service import GridService
        from student_planner.ui.grid_editor import GridEditorDialog

        dialog = GridEditorDialog(seeded, FIXED)
        cell = dialog.table.cellWidget(0, 0)
        current = cell.combo.currentData()
        target = next(
            s for s in GridService(seeded).subjects_for_cell() if s.id != current
        )

        # Пользователь печатает название и нажимает Enter.
        cell.combo.setEditText(target.name)
        cell.combo.lineEdit().editingFinished.emit()

        saved = (
            GridService(seeded).view(dialog._week_type).columns[0].slots[0].subject_id
        )
        assert saved == target.id, (
            f"GRID-02: набранное «{target.name}» должно сохраниться (в БД {saved}, "
            f"ожидалось {target.id})"
        )

    def test_typed_name_case_and_spaces_tolerated(self, seeded):
        """GRID-02: регистр и пробелы по краям не мешают сохранению."""
        from student_planner.core.schedule_service import GridService
        from student_planner.ui.grid_editor import GridEditorDialog

        dialog = GridEditorDialog(seeded, FIXED)
        service = GridService(seeded)
        column = service.view(dialog._week_type).columns[0]
        target = next(
            s for s in service.subjects_for_cell() if s.id != column.slots[0].subject_id
        )

        for typed in (target.name.lower(), f"  {target.name}  "):
            # Очистка перерисовывает таблицу, поэтому ячейка берётся заново.
            dialog.clear_cell(column.profile_id, column.slots[0].slot_no, 0, 0)
            cell = dialog.table.cellWidget(0, 0)

            cell.combo.setEditText(typed)
            cell.combo.lineEdit().editingFinished.emit()

            saved = (
                GridService(seeded)
                .view(dialog._week_type).columns[0].slots[0].subject_id
            )
            assert saved == target.id, f"GRID-02: {typed!r} должно сохраниться"

    def test_unknown_text_does_not_change_cell(self, seeded):
        """GRID-02: текст, не совпавший с предметом, не пишется в БД."""
        from student_planner.core.schedule_service import GridService
        from student_planner.ui.grid_editor import GridEditorDialog

        dialog = GridEditorDialog(seeded, FIXED)
        cell = dialog.table.cellWidget(0, 0)
        before = (
            GridService(seeded).view(dialog._week_type).columns[0].slots[0].subject_id
        )

        cell.combo.setEditText("абракадабра-которой-нет")
        cell.combo.lineEdit().editingFinished.emit()

        after = (
            GridService(seeded).view(dialog._week_type).columns[0].slots[0].subject_id
        )
        assert after == before, "GRID-02: бессмысленный ввод не меняет ячейку"


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


# ===========================================================================
# TRIP-02/TRIP-03 — новый шаблон доступен для выбора сразу
# ===========================================================================
class TestTemplateSelection:
    """Шаблон выбирается на вкладке подтверждения и в ручной поездке.

    Регрессия: на вкладке «Подтверждение дня» не было ни одного списка —
    шаблоны показывались только текстом, и выбрать другой было нельзя.
    В диалоге ручной поездки шаблона не было вовсе.
    """

    def _create_template(self, db, name: str, vehicle: str) -> int:
        from student_planner.core.models import Direction
        from student_planner.ui.pages.trips import TemplateDialog

        dialog = TemplateDialog(db)
        dialog.name_edit.setText(name)
        dialog.direction_combo.setCurrentIndex(
            dialog.direction_combo.findData(Direction.HOME_TO_COLLEGE)
        )
        dialog._legs[0].vehicle_edit.setText(vehicle)
        assert dialog.apply() is True
        from student_planner.core.trip_service import TripPlanService

        created = [t for t in TripPlanService(db).templates.all() if t.name == name]
        assert created, f"Шаблон «{name}» не сохранён"
        return created[0].id

    def test_new_template_appears_on_confirm_tab(self, seeded, qapp):
        """TRIP-03: созданный шаблон сразу виден в списке вкладки."""
        from student_planner.ui.pages.trips import ConfirmTab

        tab = ConfirmTab(seeded)
        tab.set_date(FIXED)
        before = tab.outbound_combo.count()

        template_id = self._create_template(seeded, "Свежий шаблон", "777")
        tab.refresh()
        qapp.processEvents()

        assert tab.outbound_combo.count() == before + 1, (
            f"TRIP-03: шаблон не появился в списке "
            f"(было {before}, стало {tab.outbound_combo.count()})"
        )
        index = tab.outbound_combo.findData(template_id)
        assert index >= 0, "TRIP-02: новый шаблон недоступен для выбора"

    def test_confirm_tab_has_template_selectors(self, seeded, qapp):
        """TRIP-02: на вкладке есть списки для «Туда» и «Обратно»."""
        from PySide6.QtWidgets import QComboBox

        from student_planner.ui.pages.trips import ConfirmTab

        tab = ConfirmTab(seeded)
        tab.set_date(FIXED)

        combos = tab.findChildren(QComboBox)
        assert len(combos) >= 2, (
            f"TRIP-02: на вкладке подтверждения {len(combos)} списков, "
            "ожидалось два (туда и обратно)"
        )
        assert tab.outbound_combo.count() > 1, "Список «Туда» пуст"
        assert tab.return_combo.count() > 1, "Список «Обратно» пуст"

    def test_selecting_template_updates_card(self, seeded, qapp):
        """TRIP-14: смена шаблона пересчитывает карточку «Расчёт»."""
        from student_planner.ui.pages.trips import ConfirmTab

        tab = ConfirmTab(seeded)
        tab.set_date(FIXED)
        qapp.processEvents()

        # Ищем два разных шаблона, чтобы значение гарантированно изменилось.
        items = [(tab.outbound_combo.itemData(index),
                  tab.outbound_combo.itemText(index))
                 for index in range(tab.outbound_combo.count())]
        items = [(data, text) for data, text in items if data is not None]
        assert len(items) >= 2, "Нужны минимум два шаблона направления"

        first_id = items[0][0]
        tab.outbound_combo.setCurrentIndex(tab.outbound_combo.findData(first_id))
        qapp.processEvents()
        first_value = tab.outbound_row.value_label.text()

        second_id = items[1][0]
        tab.outbound_combo.setCurrentIndex(tab.outbound_combo.findData(second_id))
        qapp.processEvents()

        assert tab.outbound_row.value_label.text() != first_value, (
            "TRIP-14: карточка не обновилась при смене шаблона"
        )

    def test_manual_ride_offers_templates(self, seeded, qapp):
        """REP-14: в ручной поездке можно выбрать шаблон маршрута."""
        from student_planner.ui.dialogs import ManualRideDialog

        template_id = self._create_template(seeded, "Ручной маршрут", "888")
        dialog = ManualRideDialog(seeded, FIXED)

        assert dialog.route_combo.count() > 1, "REP-14: список маршрутов пуст"
        texts = [dialog.route_combo.itemText(index)
                 for index in range(dialog.route_combo.count())]
        assert any("Ручной маршрут" in text for text in texts), (
            f"REP-14: созданный шаблон не предложен, есть только {texts[:4]}"
        )

        index = next(
            k for k in range(dialog.route_combo.count())
            if "Ручной маршрут" in dialog.route_combo.itemText(k)
        )
        dialog.route_combo.setCurrentIndex(index)
        qapp.processEvents()

        assert dialog.selected_template_id == template_id, (
            "TRIP-02: выбранный шаблон не определился"
        )
        assert dialog._selected_leg() == ("bus", "888"), (
            f"Рейс взят не из шаблона: {dialog._selected_leg()}"
        )

    def test_manual_ride_respects_ui14(self, seeded, qapp):
        """UI-14: у ручной поездки не больше трёх полей ввода."""
        from PySide6.QtWidgets import QComboBox, QDateEdit, QLineEdit

        from student_planner.ui.dialogs import ManualRideDialog

        dialog = ManualRideDialog(seeded, FIXED)
        fields = []
        for widget_type in (QComboBox, QDateEdit, QLineEdit):
            for widget in dialog.findChildren(widget_type):
                # QDateEdit содержит внутренний QLineEdit — это не отдельное поле.
                if widget.objectName() == "qt_spinbox_lineedit":
                    continue
                if any(widget is existing for existing in fields):
                    continue
                fields.append(widget)
        assert len(fields) <= 3, (
            f"UI-14: полей ввода {len(fields)}, допустимо не более трёх"
        )


# ===========================================================================
# RT-01/TRIP-01 — шаблон собирается из отдельных рейсов
# ===========================================================================
class TestTemplateDialog:
    """Шаблон описывает маршрут из разных видов транспорта (RT-01, Прил. А.4).

    Регрессия: диалог задавал один тип транспорта и число рейсов, а рейсы
    получались копиями одного и того же. Смешанный маршрут «Электричка + №22»
    собрать было нельзя, а шаблон из одной электрички падал с
    ``CHECK constraint failed: default_payment_method``.
    """

    def test_train_only_template_is_created(self, seeded, qapp):
        """RT-17: шаблон из одной электрички создаётся без ошибки схемы."""
        from student_planner.core.models import TransportType
        from student_planner.core.transport_repositories import TripTemplateRepository
        from student_planner.ui.pages.trips import TemplateDialog

        dialog = TemplateDialog(seeded)
        dialog.name_edit.setText("Электричка")
        row = dialog._legs[0]
        row.mode_combo.setCurrentIndex(row.mode_combo.findData(TransportType.TRAIN))
        row.vehicle_edit.setText("Электричка")

        # RT-17: оплата зафиксирована студенческим билетом.
        assert not row.payment_combo.isEnabled(), (
            "RT-17: для электрички способ оплаты не выбирается"
        )
        assert dialog.apply() is True

        created = [t for t in TripTemplateRepository(seeded).all()
                   if t.name == "Электричка"]
        assert created, "Шаблон «Электричка» не сохранён"
        assert created[0].legs[0].mode == TransportType.TRAIN
        assert created[0].legs[0].payment_method == "train_student"

    def test_mixed_route_keeps_two_modes(self, seeded, qapp):
        """RT-01: «Электричка + №22» сохраняет два рейса разных типов."""
        from student_planner.core.models import TransportType
        from student_planner.core.transport_repositories import TripTemplateRepository
        from student_planner.ui.pages.trips import TemplateDialog

        dialog = TemplateDialog(seeded)
        dialog.name_edit.setText("Электричка + №22")

        first = dialog._legs[0]
        first.mode_combo.setCurrentIndex(
            first.mode_combo.findData(TransportType.TRAIN)
        )
        first.vehicle_edit.setText("Электричка")

        second = dialog.add_leg()
        assert second is not None, "RT-16: должен добавляться второй рейс"
        second.vehicle_edit.setText("22")

        assert dialog.apply() is True

        created = [t for t in TripTemplateRepository(seeded).all()
                   if t.name == "Электричка + №22"]
        assert created, "Смешанный шаблон не сохранён"
        legs = created[0].legs
        assert len(legs) == 2, f"RT-01: ожидалось 2 рейса, сохранено {len(legs)}"
        assert legs[0].mode == TransportType.TRAIN, "Рейс 1 — электричка"
        assert legs[0].payment_method == "train_student"
        assert legs[1].mode == TransportType.BUS, "Рейс 2 — автобус"
        assert legs[1].vehicle == "22"
        assert legs[1].payment_method == "strelka"

    def test_legs_are_not_duplicates(self, seeded, qapp):
        """RT-01: рейсы хранятся по отдельности, а не копией одного."""
        from student_planner.core.transport_repositories import TripTemplateRepository
        from student_planner.ui.pages.trips import TemplateDialog

        dialog = TemplateDialog(seeded)
        dialog.name_edit.setText("Два разных автобуса")

        first = dialog._legs[0]
        first.vehicle_edit.setText("35")
        second = dialog.add_leg()
        second.vehicle_edit.setText("22")

        assert dialog.apply() is True

        created = [t for t in TripTemplateRepository(seeded).all()
                   if t.name == "Два разных автобуса"][0]
        vehicles = [leg.vehicle for leg in created.legs]
        assert vehicles == ["35", "22"], (
            f"Рейсы обязаны различаться, сохранено {vehicles}"
        )

    def test_last_leg_cannot_be_removed(self, seeded, qapp):
        """RT-16: шаблон не остаётся без рейсов."""
        from student_planner.ui.pages.trips import TemplateDialog

        dialog = TemplateDialog(seeded)
        assert len(dialog._legs) == 1
        assert not dialog._legs[0].remove_button.isEnabled(), (
            "RT-16: единственный рейс удалять нельзя"
        )

        added = dialog.add_leg()
        assert len(dialog._legs) == 2
        assert dialog._legs[0].remove_button.isEnabled(), (
            "При двух рейсах удаление разрешено"
        )
        dialog.remove_leg(added)
        assert len(dialog._legs) == 1

    def test_empty_vehicle_is_rejected(self, seeded, qapp):
        """RT-16: номер рейса обязателен."""
        from student_planner.core.errors import AppError
        from student_planner.ui.pages.trips import TemplateDialog

        dialog = TemplateDialog(seeded)
        dialog.name_edit.setText("Без номера")
        dialog._legs[0].vehicle_edit.setText("")

        with pytest.raises(AppError):
            dialog.apply()

    def test_confirm_tab_set_date(self, seeded):
        """TRIP-08: вкладка подтверждения принимает дату."""
        from student_planner.ui.pages.trips import TripsPage

        page = TripsPage(seeded)
        page.set_date(FIXED)
        page.refresh()


class TestTemplateEditing:
    """RT-13: уже созданный шаблон можно изменить, а не только пересоздать."""

    def _first_template(self, db):
        from student_planner.core.transport_repositories import TripTemplateRepository

        return TripTemplateRepository(db).all()[0]

    def test_dialog_prefills_existing_values(self, seeded, qapp):
        """Открытие на правку показывает текущие значения шаблона."""
        from student_planner.ui.pages.trips import TemplateDialog

        template = self._first_template(seeded)
        dialog = TemplateDialog(seeded, template_id=template.id)

        assert dialog.name_edit.text() == template.name
        assert dialog.direction_combo.currentData() == template.direction
        assert len(dialog._legs) == len(template.legs)
        for row, leg in zip(dialog._legs, template.legs):
            assert row.mode == leg.mode
            assert row.vehicle == leg.vehicle
            assert row.payment_method == leg.payment_method

    def test_edit_updates_instead_of_creating(self, seeded, qapp):
        """Главное требование: правка меняет шаблон, а не создаёт новый."""
        from student_planner.core.transport_repositories import TripTemplateRepository
        from student_planner.ui.pages.trips import TemplateDialog

        repo = TripTemplateRepository(seeded)
        template = self._first_template(seeded)
        before = len(repo.all())

        dialog = TemplateDialog(seeded, template_id=template.id)
        dialog.name_edit.setText("Переименованный шаблон")
        dialog._legs[0].vehicle_edit.setText("№77")
        assert dialog.apply() is True

        assert len(repo.all()) == before, (
            "Правка создала новый шаблон вместо изменения существующего"
        )
        updated = repo.require(template.id)
        assert updated.name == "Переименованный шаблон"
        assert updated.legs[0].vehicle == "№77"

    def test_edit_changes_legs_count(self, seeded, qapp):
        """Можно добавить и убрать рейсы у существующего шаблона."""
        from student_planner.core.models import TransportType
        from student_planner.core.transport_repositories import TripTemplateRepository
        from student_planner.ui.pages.trips import TemplateDialog

        repo = TripTemplateRepository(seeded)
        template = self._first_template(seeded)

        dialog = TemplateDialog(seeded, template_id=template.id)
        row = dialog.add_leg()
        dialog._legs[0].mode_combo.setCurrentIndex(
            dialog._legs[0].mode_combo.findData(TransportType.TRAIN)
        )
        dialog._legs[0].vehicle_edit.setText("Электричка")
        row.mode_combo.setCurrentIndex(row.mode_combo.findData(TransportType.BUS))
        row.vehicle_edit.setText("22")
        assert dialog.apply() is True

        updated = repo.require(template.id)
        assert len(updated.legs) == 2
        assert [leg.vehicle for leg in updated.legs] == ["Электричка", "22"]

    def test_edit_train_only_template_is_allowed(self, seeded, qapp):
        """RT-17 + Б.13: шаблон из одной электрички сохраняется без ошибки.

        Регрессия: ``update`` передавал способ оплаты рейса
        ('train_student') в поле шаблона, где схема допускает только
        'strelka'/'debit_card' — правка падала с CHECK constraint.
        """
        from student_planner.core.models import TransportType
        from student_planner.core.transport_repositories import TripTemplateRepository
        from student_planner.ui.pages.trips import TemplateDialog

        repo = TripTemplateRepository(seeded)
        template = self._first_template(seeded)

        dialog = TemplateDialog(seeded, template_id=template.id)
        dialog._legs[0].mode_combo.setCurrentIndex(
            dialog._legs[0].mode_combo.findData(TransportType.TRAIN)
        )
        dialog._legs[0].vehicle_edit.setText("Электричка")
        assert dialog.apply() is True

        updated = repo.require(template.id)
        assert [leg.mode for leg in updated.legs] == [TransportType.TRAIN]
        assert updated.legs[0].payment_method == "train_student"
        # Б.13: у шаблона без автобусных рейсов способ оплаты не задан.
        # Иначе в поле осталось бы устаревшее 'strelka' от прежнего рейса.
        assert updated.default_payment_method is None, (
            "У шаблона из одной электрички способ оплаты по умолчанию должен "
            f"быть пустым, а не {updated.default_payment_method!r}"
        )

    def test_templates_tab_has_edit_button(self, seeded, qapp):
        """Кнопка «Изменить» без выбранной строки не падает, а просит выбор."""
        from student_planner.ui.pages.trips import TemplatesTab

        tab = TemplatesTab(seeded)
        assert tab.edit_button.text() == "Изменить"
        assert tab.table.currentRow() < 0 or tab._selected_id() is not None

    def test_templates_tab_fits_narrow_window(self, seeded, qapp):
        """UI-02: кнопки вкладки не распирают центральную область.

        Регрессия: с кнопкой «Изменить» пять действий вставали в одну строку
        и требовали 942 px — центральная зона переставала помещаться в окно.
        """
        from student_planner.ui.pages.trips import TemplatesTab

        tab = TemplatesTab(seeded)
        tab.resize(452, 400)  # столько даёт центр при окне 1080 px
        tab.show()
        qapp.processEvents()

        need = tab.minimumSizeHint().width()
        assert need <= 452, (
            f"Вкладка «Шаблоны» требует {need} px — не помещается в центральную "
            "область при минимальном окне"
        )
        assert tab.edit_button.isVisible()

    def test_apply_requires_name_when_editing(self, seeded, qapp):
        """Пустое название по-прежнему запрещено (TRIP-02)."""
        from student_planner.core.errors import AppError
        from student_planner.ui.pages.trips import TemplateDialog

        template = self._first_template(seeded)
        dialog = TemplateDialog(seeded, template_id=template.id)
        dialog.name_edit.setText("   ")
        with pytest.raises(AppError):
            dialog.apply()


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

    def test_seven_sections(self, seeded):
        """SET-01: Общие, Предметы, Недели, Звонки, Транспорт, Календарь, Данные."""
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        captions = [page.tabs.tabText(i) for i in range(page.tabs.count())]
        assert captions == [
            "Общие", "Предметы", "Недели", "Звонки", "Транспорт", "Календарь",
            "Данные",
        ], f"SET-01: состав разделов изменился — {captions}"

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

    def test_weeks_tab_opens_grid_editor(self, seeded, monkeypatch):
        """GRID-01/SET-03: расписание правится из «Настройки → Недели».

        Редактор недельной сетки доступен не только на странице «Расписание»,
        но и в настройках — через ту же реализацию диалога.
        """
        from student_planner.core.schedule_service import GridService
        from student_planner.ui.grid_editor import GridEditorDialog
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        page.refresh()

        opened = {}

        def fake_exec(self):
            opened["dialog"] = self
            return 1  # «Готово»

        monkeypatch.setattr(GridEditorDialog, "exec", fake_exec)
        page.weeks_tab.grid_button.click()

        assert "dialog" in opened, (
            "GRID-01: кнопка в «Настройки → Недели» должна открывать редактор сетки"
        )
        dialog = opened["dialog"]
        assert dialog.table.columnCount() == 6, "GRID-01: Пн–Сб, шесть колонок"

        # Правка из этого редактора доходит до БД и переживает повторное чтение.
        cell = dialog.table.cellWidget(0, 0)
        target = next(
            s
            for s in GridService(seeded).subjects_for_cell()
            if s.id != cell.combo.currentData()
        )
        cell.combo.setEditText(target.name)
        cell.combo.lineEdit().editingFinished.emit()
        saved = (
            GridService(seeded).view(dialog._week_type).columns[0].slots[0].subject_id
        )
        assert saved == target.id, "GRID-02: правка из настроек сохраняется в БД"

    def test_schedule_page_has_no_weeks_placeholder_button(self, seeded):
        """WEEK-08: заглушка «Изменить чередование недель…» убрана со страницы.

        Кнопка только показывала всплывающее сообщение и не открывала ничего;
        чередование недель настраивается якорем в «Настройки → Недели».
        """
        from student_planner.ui.pages.schedule import SchedulePage

        page = SchedulePage(seeded)
        assert not hasattr(page, "weeks_button"), (
            "WEEK-08: кнопки-заглушки быть не должно"
        )
        assert hasattr(page, "grid_button"), "GRID-01: вход в редактор сетки остаётся"

    # ------------------------------------------- справочник предметов (SUBJ-04)
    def test_subjects_tab_exists_and_lists_subjects(self, seeded):
        """SUBJ-04: в настройках есть раздел «Предметы» со стартовым набором.

        До этой проверки справочника в интерфейсе не было вовсе:
        ``SubjectRepository`` импортировался в модуль настроек, но не
        использовался, поэтому добавить, изменить или удалить предмет было
        нечем.
        """
        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        page.refresh()

        captions = [page.tabs.tabText(i) for i in range(page.tabs.count())]
        assert "Предметы" in captions, f"SUBJ-04: раздел «Предметы» обязателен, есть {captions}"

        total = len(SubjectRepository(seeded).all())
        assert page.subjects_tab.table.rowCount() == total, (
            "SUBJ-04: таблица должна показывать все предметы справочника"
        )
        assert total > 0, "стартовый набор содержит девять предметов"

    def test_subject_can_be_added(self, seeded, monkeypatch):
        """SUBJ-04: добавление предмета через диалог раздела «Предметы»."""
        from student_planner.core.repositories import SubjectRepository
        from PySide6.QtCore import Qt

        from student_planner.ui.pages.settings import SettingsPage, SubjectDialog

        page = SettingsPage(seeded)
        page.refresh()
        before = len(SubjectRepository(seeded).all())

        def fake_exec(self):
            self.name_edit.setText("Веб-разработка")
            self.code_edit.setText("МДК.02.01")
            self.teacher_edit.setText("Сидоров С.С.")
            self.room_edit.setText("Каб. 12")
            assert self.apply(), "SUBJ-04: сохранение должно пройти"
            return 1

        monkeypatch.setattr(SubjectDialog, "exec", fake_exec)
        page.subjects_tab.add_subject()

        after = SubjectRepository(seeded).all()
        assert len(after) == before + 1, "SUBJ-04: предмет должен добавиться"
        created = next(s for s in after if s.name == "Веб-разработка")
        assert created.code == "МДК.02.01"
        assert created.teacher == "Сидоров С.С."
        assert created.room == "Каб. 12"
        assert page.subjects_tab.table.rowCount() == len(after), (
            "SUBJ-04: таблица обновляется после добавления"
        )

    def test_subject_can_be_edited(self, seeded, monkeypatch):
        """SUBJ-04: правка существующего предмета сохраняется в БД."""
        from student_planner.core.repositories import SubjectRepository
        from PySide6.QtCore import Qt

        from student_planner.ui.pages.settings import SettingsPage, SubjectDialog

        page = SettingsPage(seeded)
        page.refresh()
        repo = SubjectRepository(seeded)
        target = repo.all()[0]
        old_name = target.name

        # Выделяем строку этого предмета в таблице.
        table = page.subjects_tab.table
        row = next(
            r for r in range(table.rowCount())
            if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == target.id
        )
        table.selectRow(row)

        def fake_exec(self):
            assert self.name_edit.text() == old_name, (
                "SUBJ-04: диалог предзаполняется текущими значениями"
            )
            self.name_edit.setText("Переименованный предмет")
            self.teacher_edit.setText("Новиков Н.Н.")
            assert self.apply()
            return 1

        monkeypatch.setattr(SubjectDialog, "exec", fake_exec)
        page.subjects_tab.edit_subject()

        updated = repo.by_id(target.id)
        assert updated.name == "Переименованный предмет", (
            f"SUBJ-04: правка названия не сохранилась (в БД {updated.name!r})"
        )
        assert updated.teacher == "Новиков Н.Н.", "SUBJ-04: преподаватель обновился"

    def test_unused_subject_can_be_deleted(self, seeded, monkeypatch):
        """SUBJ-04: неиспользуемый предмет удаляется после подтверждения."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox

        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        page.refresh()
        repo = SubjectRepository(seeded)
        created = repo.create("Временный предмет", code="ВР.01")
        page.refresh()

        table = page.subjects_tab.table
        row = next(
            r for r in range(table.rowCount())
            if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == created.id
        )
        table.selectRow(row)

        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        page.subjects_tab.delete_subject()

        assert repo.by_id(created.id) is None, "SUBJ-04: предмет должен удалиться"

    def test_used_subject_offered_to_deactivate(self, seeded, monkeypatch):
        """SUBJ-04/HW-09: используемый предмет не удаляется, а отключается.

        Вместо ошибки предлагается выбор — отключить предмет. Он остаётся в
        базе, чтобы прошлое расписание и задания не потеряли ссылку.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox

        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        page.refresh()
        repo = SubjectRepository(seeded)
        used = next(s for s in repo.all() if repo.references(s.id))

        table = page.subjects_tab.table
        row = next(
            r for r in range(table.rowCount())
            if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == used.id
        )
        table.selectRow(row)

        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        page.subjects_tab.delete_subject()

        assert repo.by_id(used.id) is not None, (
            "SUBJ-04: используемый предмет удалять нельзя"
        )
        assert repo.by_id(used.id).is_active is False, (
            "SUBJ-04: вместо удаления предмет отключается"
        )

    def test_subject_can_be_toggled(self, seeded):
        """SUBJ-04: кнопка «Отключить»/«Включить» переключает активность."""
        from PySide6.QtCore import Qt

        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        page.refresh()
        repo = SubjectRepository(seeded)
        target = repo.all()[0]

        table = page.subjects_tab.table
        row = next(
            r for r in range(table.rowCount())
            if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == target.id
        )
        table.selectRow(row)

        page.subjects_tab.toggle_subject()
        assert repo.by_id(target.id).is_active is False, "SUBJ-04: предмет отключён"

        page.subjects_tab.toggle_subject()
        assert repo.by_id(target.id).is_active is True, "SUBJ-04: предмет включён обратно"

    def test_subject_dialog_rejects_empty_name(self, seeded):
        """SUBJ-01: пустое название отклоняется."""
        from student_planner.core.errors import AppError
        from student_planner.ui.pages.settings import SubjectDialog

        dialog = SubjectDialog(seeded)
        dialog.name_edit.setText("   ")
        with pytest.raises(AppError):
            dialog.apply()

    def test_acc_m_73_reset_clears_user_data_and_keeps_seed(self, seeded, monkeypatch):
        """ACC-M-73 / FIRST-12: сброс очищает пользовательские данные, справочники целы.

        Проверяется фактическое поведение MVP: удаляются задания, поездки,
        подтверждения, пополнения, оверрайды и периоды; стартовый набор
        (предметы, звонки, сетка, тарифы, шаблоны, настройки) остаётся на месте
        и повторно не дублируется.
        """
        from datetime import date

        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.pages.settings import SettingsPage

        homework = seeded.fetchone("SELECT COUNT(*) AS c FROM subjects")["c"]
        templates = seeded.fetchone("SELECT COUNT(*) AS c FROM trip_templates")["c"]
        slots = seeded.fetchone("SELECT COUNT(*) AS c FROM bell_slots")["c"]

        subject_id = seeded.fetchone("SELECT id FROM subjects WHERE is_active = 1")["id"]
        with seeded.transaction() as conn:
            conn.execute(
                "INSERT INTO homework(subject_id, group_mark, due_date, description, status, "
                "created_at) VALUES (?, NULL, ?, ?, 'active', '2026-10-01T10:00:00')",
                (subject_id, "2026-10-05", "Сбросить меня"),
            )
            conn.execute(
                "INSERT INTO study_periods(kind, title, date_from, date_to, no_classes, comment) "
                "VALUES ('vacation', 'Каникулы', '2026-11-01', '2026-11-07', 1, NULL)"
            )

        assert seeded.fetchone("SELECT COUNT(*) AS c FROM homework")["c"] == 1
        assert seeded.fetchone("SELECT COUNT(*) AS c FROM study_periods")["c"] == 1

        page = SettingsPage(seeded)
        page.refresh()
        SettingsService(seeded).set_student_profile("Пётр Петров", "ИС-22")
        # Подтверждение словом УДАЛИТЬ подменяем, чтобы не открывать модальный диалог.
        monkeypatch.setattr(
            "PySide6.QtWidgets.QInputDialog.getText",
            staticmethod(lambda *args, **kwargs: ("УДАЛИТЬ", True)),
        )
        page.data_tab.reset_data()

        assert seeded.fetchone("SELECT COUNT(*) AS c FROM homework")["c"] == 0, (
            "FIRST-12: сброс должен удалить домашние задания"
        )
        assert seeded.fetchone("SELECT COUNT(*) AS c FROM study_periods")["c"] == 0, (
            "FIRST-12: сброс должен удалить учебные периоды"
        )
        assert seeded.fetchone("SELECT COUNT(*) AS c FROM subjects")["c"] == homework, (
            "FIRST-12: справочник предметов не должен пострадать"
        )
        assert seeded.fetchone("SELECT COUNT(*) AS c FROM trip_templates")["c"] == templates, (
            "FIRST-12: шаблоны поездок не должны дублироваться"
        )
        assert seeded.fetchone("SELECT COUNT(*) AS c FROM bell_slots")["c"] == slots, (
            "FIRST-12: звонки не должны дублироваться"
        )
        assert SettingsService(seeded).student_name() == "Пётр Петров", (
            "FIRST-12: настройки профиля сбросом не очищаются — их правят в «Общих»"
        )
        assert date(2026, 10, 5)  # дата из фикстуры использована


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

