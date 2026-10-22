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

