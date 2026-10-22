"""Главное окно: три колонки (UI-02) и переключение страниц (UI-06).

Каркас §20–§23: навигация слева, рабочая зона в центре, виджеты справа. Сами
страницы живут в :mod:`student_planner.ui.pages` и не знают о раскладке.
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_TITLE, APP_VERSION
from ..core import clock
from ..core.dates import format_display
from ..core.day_resolution import DayResolver
from ..core.errors import AppError
from ..core.settings_service import SettingsService
from ..core.schedule_service import CalendarService, HomeworkService, OverrideService
from ..core.transport_service import TransportService
from ..core.trip_service import TripPlanService
from .dialogs import ConfirmTripsDialog, RecalculateDialog
from .nav_panel import NavPanel
from .theme import stylesheet
from .widgets_panel import WidgetsPanel

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """UI-02: три колонки — навигация, рабочая зона, виджеты."""

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = SettingsService(db)
        self._selected_date: date = clock.today()
        self._pages: dict[str, QWidget] = {}
        self._current_page = "schedule"

        self.setWindowTitle(f"{APP_TITLE} {APP_VERSION}")
        self.setStyleSheet(stylesheet())
        self.resize(1400, 880)
        self.setMinimumSize(1080, 680)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        # ---------------------------------------------------------- навигация
        self.nav = NavPanel(db)
        self.nav.page_requested.connect(self.open_page)
        self.nav.date_selected.connect(self.on_date_selected)
        # UI-05: при листании месяца пересчитываем точки-метки для нового
        # месяца, иначе они остаются от предыдущего.
        self.nav.month_changed.connect(self._refresh_calendar_marks)
        splitter.addWidget(self.nav)

        # ------------------------------------------------------- рабочая зона
        self.stack = QStackedWidget()
        # Страницы содержат длинные подписи и таблицы, поэтому их
        # minimumSizeHint (до 1000 px) распирал сплиттер: ручку нельзя было
        # сдвинуть влево, календарь оставался обрезанным. Сжимаемость важнее
        # «естественного» минимума — содержимое переносится и прокручивается.
        self.stack.setMinimumWidth(360)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        splitter.addWidget(self.stack)

        # ---------------------------------------------------------- виджеты
        self.widgets = WidgetsPanel(db)
        self.widgets.confirm_requested.connect(self.confirm_trips)
        self.widgets.recalculate_requested.connect(self.recalculate_counter)
        self.widgets.homework_requested.connect(lambda: self.open_page("homework"))
        splitter.addWidget(self.widgets)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        # Ширина колонок: левая вмещает мини-календарь целиком (258 px),
        # правая — виджеты; обе регулируются пользователем.
        splitter.setSizes([312, 808, 280])

        self.setStatusBar(QStatusBar())
        self.status_label = QLabel("Готово")
        self.statusBar().addWidget(self.status_label, 1)
        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setObjectName("Small")
        self.statusBar().addPermanentWidget(self.version_label)

        self._build_pages()
        self._install_shortcuts()
        # UI-05: метки и типы недель нужны сразу на старте. Без этого
        # календарь оставался без подсветки до первой правки данных —
        # любое действие вызывало refresh_all, и только тогда цвета
        # появлялись, что выглядело как «подсветка включается после
        # добавления пары».
        self._refresh_calendar_marks()
        self.open_page("schedule")

        # UI-07: часы в правой панели тикают раз в секунду; здесь только
        # ежедневное обновление даты, чтобы «сегодня» не отставало.
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(self._check_day_change)
        self._day_timer.start()
        self._last_today = clock.today()

    # ------------------------------------------------------------------ страницы
    def _build_pages(self) -> None:
        from .pages import (
            ExpensesPage,
            HomeworkPage,
            SchedulePage,
            SettingsPage,
            TripsPage,
        )

        self._pages = {
            "schedule": SchedulePage(self.db, self),
            "trips": TripsPage(self.db, self),
            "expenses": ExpensesPage(self.db, self),
            "homework": HomeworkPage(self.db, self),
            "settings": SettingsPage(self.db, self),
        }
        for page in self._pages.values():
            self.stack.addWidget(page)
            if hasattr(page, "changed"):
                page.changed.connect(self.refresh_all)
        # SCH-09: навигация внутри страницы расписания (стрелки, «Сегодня»,
        # смена режима) переводит дату всего окна — календарь и бейдж типа
        # недели слева обязаны следовать за ней.
        schedule_page = self._pages.get("schedule")
        if hasattr(schedule_page, "date_changed"):
            schedule_page.date_changed.connect(self.on_date_selected)

    def _install_shortcuts(self) -> None:
        for index, key in enumerate(("schedule", "trips", "expenses",
                                    "homework", "settings"), start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(
                lambda page=key: self.open_page(page)
            )
        today_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        today_shortcut.activated.connect(lambda: self.on_date_selected(clock.today()))

    def open_page(self, page: str) -> None:
        """UI-06: переключение раздела."""
        widget = self._pages.get(page)
        if widget is None:
            log.warning("Неизвестный раздел: %s", page)
            return
        self._current_page = page
        self.stack.setCurrentWidget(widget)
        self.nav.set_current_page(page)
        if hasattr(widget, "refresh"):
            widget.refresh()
        self.widgets.refresh(self._selected_date)
        self._update_week_badge()
        self.status_label.setText(self.nav.page_caption(page))

    # ------------------------------------------------------------------ дата
    @property
    def selected_date(self) -> date:
        return self._selected_date

    def on_date_selected(self, value: date) -> None:
        self._selected_date = value
        self.nav.set_selected_date(value)
        page = self._pages.get(self._current_page)
        if page is not None and hasattr(page, "set_date"):
            page.set_date(value)
        self.widgets.refresh(value)
        # UI-04/ALG-01: бейдж типа недели относится к выбранной дате, а не к
        # сегодняшней. Без этого при просмотре другой недели он показывал тип
        # предыдущей недели (или «—» до первого refresh_all).
        self._update_week_badge()
        self.status_label.setText(
            f"{self.nav.page_caption(self._current_page)} · {format_display(value)}"
        )

    def _update_week_badge(self) -> None:
        """UI-04: привести бейдж типа недели к выбранной дате (ALG-01)."""
        try:
            week_type = DayResolver(self.db).week_type(self._selected_date)
        except AppError as error:  # pragma: no cover - защита интерфейса
            log.warning("Не удалось определить тип недели: %s", error)
            week_type = None
        self.nav.set_week_type(week_type)

    def _check_day_change(self) -> None:
        today = clock.today()
        if today != self._last_today:
            self._last_today = today
            self.nav.refresh()
            self.on_date_selected(today)

    # ------------------------------------------------------------------ обновление
    def refresh_all(self) -> None:
        """Перечитать виджеты и текущую страницу после правки данных."""
        page = self._pages.get(self._current_page)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()
        self.widgets.refresh(self._selected_date)
        self.nav.refresh()
        self._refresh_calendar_marks()

    def _refresh_calendar_marks(self) -> None:
        """UI-05: точки-метки мини-календаря."""
        try:
            # Метки нужны для месяца, который календарь показывает сейчас,
            # а не для текущего: иначе после листания точки пропадали.
            shown_year, shown_month = self.nav.calendar.shown_month()
            overrides = OverrideService(self.db)
            transport = TransportService(self.db)
            calendar = CalendarService(self.db)
            homework = HomeworkService(self.db)

            marks: dict[date, list[str]] = {}
            for value in overrides.overrides.dates_with_overrides():
                marks.setdefault(value, []).append("override")
            for value in transport.rides.dates():
                marks.setdefault(value, []).append("rides")
            for entry in calendar.all():
                current = entry.start_date
                while current <= entry.end_date:
                    marks.setdefault(current, []).append("period")
                    current = date.fromordinal(current.toordinal() + 1)
            for value in homework.due_dates():
                marks.setdefault(value, []).append("homework")

            self.nav.set_marks({key: " ".join(value) for key, value in marks.items()})

            resolver = DayResolver(self.db)
            # Календарь получает разделитель и считает тип недели сам: при
            # листании месяца подсветка больше не пропадает, а дни сетки по
            # краям (соседние месяцы) тоже подсвечены.
            self.nav.set_type_resolver(resolver)
            types: dict[date, str] = {}
            for value in _grid_dates(shown_year, shown_month):
                types[value] = resolver.week_type(value) or ""
            self.nav.set_week_types(types)
            self.nav.set_week_type(resolver.week_type(self._selected_date))
        except AppError as error:  # pragma: no cover - защита интерфейса
            log.warning("Не удалось обновить метки календаря: %s", error)
            self.show_error(error)

    # ------------------------------------------------------------------ действия
    def confirm_trips(self, value: date) -> None:
        """UI-08: подтверждение поездок дня из правой панели."""
        dialog = ConfirmTripsDialog(self.db, value, self)
        if dialog.exec():
            self.refresh_all()

    def recalculate_counter(self) -> None:
        """REP-08: пересчёт счётчика «Стрелки» с подтверждением."""
        dialog = RecalculateDialog(self.db, self)
        if dialog.exec():
            self.refresh_all()

    # ------------------------------------------------------------------ ошибки
    def show_error(self, error: Exception) -> None:
        """ERR-*: сообщение об ошибке с кодом и подсказкой."""
        if isinstance(error, AppError):
            text = error.message
            details = f"\nКод: {error.code}" if error.code else ""
        else:  # pragma: no cover - непредвиденная ошибка
            text = str(error)
            details = ""
        QMessageBox.critical(self, "Ошибка", f"{text}{details}")
        self.status_label.setText(f"Ошибка: {text.splitlines()[0]}")


def _month_dates(value: date) -> list[date]:
    from calendar import monthrange

    last_day = monthrange(value.year, value.month)[1]
    return [
        date(value.year, value.month, day)
        for day in range(1, last_day + 1)
    ]


def _grid_dates(year: int, month: int) -> list[date]:
    """Даты, которые реально видны в сетке месяца, включая края.

    Сетка ``QCalendarWidget`` начинается с понедельника недели, содержащей
    первое число, и заканчивается воскресеньем недели с последним числом.
    Без этих дней подсветка типа недели обрывалась на границах месяца.
    """
    from calendar import monthrange

    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    start = first.toordinal() - first.weekday()
    end = last.toordinal() + (6 - last.weekday())
    return [date.fromordinal(value) for value in range(start, end + 1)]


__all__ = ["MainWindow"]
