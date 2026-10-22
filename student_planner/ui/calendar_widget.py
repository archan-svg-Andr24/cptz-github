"""Мини-календарь левой панели (UI-05).

Показывает месяц, подсвечивает сегодня и выбранную дату, отмечает точки-метки:
оверрайд, подтверждённые поездки, учебный период и дедлайн домашнего задания.
Пометки практики, сессии и экзамена — v1.1.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import clock
from ..core.dates import MONTH_NAMES_NOMINATIVE
from .theme import COLORS


class MiniCalendar(QWidget):
    """UI-05: календарь с подсветкой и точками-метками."""

    date_selected = Signal(object)  # date
    month_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(4)
        self.month_label = QLabel()
        self.month_label.setObjectName("Subtitle")
        header.addWidget(self.month_label)
        header.addStretch(1)

        self.today_button = QPushButton("Сегодня")
        self.today_button.setObjectName("Flat")
        self.today_button.clicked.connect(self.go_today)
        header.addWidget(self.today_button)
        layout.addLayout(header)

        self.calendar = QCalendarWidget()
        self.calendar.setObjectName("MiniCalendar")
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.calendar.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.calendar.setMinimumHeight(190)
        # Кегль цифр подстраивается под ширину панели (см. _fit_font).
        self._font_size = 10.0
        self.calendar.setStyleSheet(self._style())
        self.calendar.selectionChanged.connect(self._on_selection)
        self.calendar.currentPageChanged.connect(self._on_page_changed)
        layout.addWidget(self.calendar)

        self.legend = QLabel()
        self.legend.setObjectName("Small")
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)

        self._marks: dict[date, str] = {}
        self._week_types: dict[date, str] = {}
        self._type_resolver = None
        self._base_font_size = 10.0
        self._selected = clock.today()
        self._refresh_header()

    # ------------------------------------------------------------------ метки
    def set_marks(self, marks: dict[date, str]) -> None:
        """Точки-метки: ``override``, ``rides``, ``period``, ``homework``."""
        self._marks = dict(marks)
        self._paint_marks()

    def set_week_types(self, types: dict[date, str]) -> None:
        """UI-05: тип недели в подсветке."""
        self._week_types.update(types)
        self._paint_marks()

    def set_type_resolver(self, resolver) -> None:
        """UI-05: досчитывать тип недели для любого показанного месяца.

        Без этого подсветка работала только в том месяце, для которого окно
        прислало словарь: после листания вперёд или назад все дни теряли цвет,
        хотя тип недели для них известен.
        """
        self._type_resolver = resolver
        self._paint_marks()

    def set_selected(self, value: date) -> None:
        self._selected = value
        self.calendar.setSelectedDate(QDate(value.year, value.month, value.day))
        self._refresh_header()

    @property
    def selected_date(self) -> date:
        selected = self.calendar.selectedDate()
        return date(selected.year(), selected.month(), selected.day())

    def shown_month(self) -> tuple[int, int]:
        """UI-05: месяц, который календарь показывает сейчас."""
        return self.calendar.yearShown(), self.calendar.monthShown()

    def resizeEvent(self, event) -> None:
        """UI-05: подстроить кегль календаря под ширину панели.

        ``QCalendarWidget`` не сжимается ниже ~250 px при базовом кегле:
        сетка из 7 колонок перестаёт помещаться. Когда пользователь сужает
        панель навигации, кегль уменьшается ступенями, чтобы все числа
        месяца остались видны, а не обрезались справа.
        """
        super().resizeEvent(event)
        self._fit_font()

    def _fit_font(self) -> None:
        """Подобрать наибольший кегль, при котором сетка помещается.

        Кегль задаётся через стилевую таблицу календаря: ``setFont`` на
        ``QCalendarWidget`` перебивается QSS, поэтому размер передаётся в
        ``_style``.
        """
        available = self.calendar.width()
        if available <= 0:
            return
        base = self._base_font_size
        # Ступени от базового кегля вниз: чем уже панель, тем мельче цифры.
        for size in (base, base - 0.5, base - 1.0, base - 1.5, base - 2.0):
            if size < 6.5:
                break
            self._font_size = size
            self.calendar.setStyleSheet(self._style())
            self.calendar.updateGeometry()
            if self.calendar.minimumSizeHint().width() <= available:
                return
        # Даже самый мелкий не помещается — оставляем последний.
        self._font_size = max(6.5, base - 2.0)
        self.calendar.setStyleSheet(self._style())

    def go_today(self) -> None:
        self.set_selected(clock.today())
        self.date_selected.emit(self.selected_date)

    # ------------------------------------------------------------------ отрисовка
    def _paint_marks(self) -> None:
        """UI-05: цвет дня по типу недели, фон по меткам.

        Три правила, которые чинят замеченные дефекты:

        1. Цвет задаётся **каждому** дню сетки, включая ведущие дни прошлого и
           хвостовые дни следующего месяца: иначе крайние числа оставались без
           подсветки, потому что типы недель приходили только на свой месяц.
        2. Верхняя неделя — синяя, нижняя — обычный текст. Раньше цвет
           считался, но воскресенье перекрывало его серым, а суббота и
           воскресенье оставались красными от штатных форматов Qt.
        3. Суббота — обычный цвет дня недели, воскресенье — красное всегда.
           Красный в Qt приходит из ``weekdayTextFormat`` для Сб и Вс; его
           нужно перебить явно, иначе суббота красная.
        """
        today = clock.today()
        grid = _month_dates(self.calendar.yearShown(), self.calendar.monthShown())
        resolved = self._resolve_types(grid)
        for value in grid:
            fmt = QTextCharFormat()
            kinds = self._marks.get(value, "")
            week_type = self._week_types.get(value) or resolved.get(value)

            # Цвет текста: сначала по типу недели, затем воскресенье.
            if week_type == "upper":
                fmt.setForeground(QColor(COLORS["week_upper"]))
            else:
                fmt.setForeground(QColor(COLORS["text"]))
            if value.weekday() == 6:
                fmt.setForeground(QColor(COLORS["week_sunday"]))

            # Фон: сегодня и учебный период важнее цвета текста.
            if value == today:
                fmt.setBackground(QColor(COLORS["surface_high"]))
                fmt.setFontWeight(700)
            if "period" in kinds:
                fmt.setBackground(QColor(COLORS["warning_bg"]))
                fmt.setForeground(QColor(COLORS["warning_text"]))
            if "override" in kinds:
                fmt.setFontUnderline(True)
            fmt.setToolTip(self._tooltip(value))
            self.calendar.setDateTextFormat(QDate(value.year, value.month, value.day), fmt)

        self._apply_weekday_formats()

    def _apply_weekday_formats(self) -> None:
        """UI-05: цвета заголовков и дней недели вместо красных по умолчанию.

        Qt красит субботу и воскресенье в ``#ff0000`` через
        ``weekdayTextFormat`` — стилевая таблица на это не влияет. Суббота
        должна быть обычной, воскресенье — красным (как и его числа).
        """
        for day_of_week in (
            Qt.DayOfWeek.Monday,
            Qt.DayOfWeek.Tuesday,
            Qt.DayOfWeek.Wednesday,
            Qt.DayOfWeek.Thursday,
            Qt.DayOfWeek.Friday,
            Qt.DayOfWeek.Saturday,
            Qt.DayOfWeek.Sunday,
        ):
            fmt = QTextCharFormat()
            if day_of_week == Qt.DayOfWeek.Sunday:
                fmt.setForeground(QColor(COLORS["week_sunday"]))
            else:
                fmt.setForeground(QColor(COLORS["text"]))
            self.calendar.setWeekdayTextFormat(day_of_week, fmt)

    def _resolve_types(self, values: list[date]) -> dict[date, str]:
        """UI-05: тип недели для любой показанной даты.

        Окно присылает типы только на текущий месяц, поэтому при листании
        календаря подсветка исчезала. Разделитель дат знает тип недели для
        любой даты — считаем на месте и не зависим от присланного словаря.
        """
        if self._type_resolver is None:
            return {}
        result: dict[date, str] = {}
        for value in values:
            try:
                result[value] = self._type_resolver.week_type(value) or ""
            except Exception:  # pragma: no cover - защита интерфейса
                result[value] = ""
        return result

    def _tooltip(self, value: date) -> str:
        from ..core.dates import WEEKDAY_NAMES

        parts = [f"{value.strftime('%d.%m.%Y')}, {WEEKDAY_NAMES[value.isoweekday()]}"]
        marks = self._marks.get(value, "")
        captions = {
            "override": "есть изменение",
            "rides": "поездки подтверждены",
            "period": "учебный период",
            "homework": "дедлайн задания",
        }
        for key, caption in captions.items():
            if key in marks:
                parts.append(caption)
        week_type = self._week_types.get(value)
        if week_type:
            parts.append("верхняя неделя" if week_type == "upper" else "нижняя неделя")
        return "\n".join(parts)

    def _refresh_header(self) -> None:
        self.month_label.setText(
            f"{MONTH_NAMES_NOMINATIVE[self.calendar.monthShown()]} {self.calendar.yearShown()}"
        )
        self.legend.setText("• изменение   • поездки   • период   • задание")

    # ------------------------------------------------------------------ события
    def _on_selection(self) -> None:
        self._selected = self.selected_date
        self._refresh_header()
        self.date_selected.emit(self._selected)

    def _on_page_changed(self, year: int, month: int) -> None:
        self._refresh_header()
        self._paint_marks()
        # Метки точек приходят из окна: при листании месяца их нужно
        # пересчитать, иначе точки остаются от прежнего месяца.
        self.month_changed.emit()

    # ------------------------------------------------------------------ стиль
    def _style(self) -> str:
        c = COLORS
        return f"""
        QCalendarWidget QWidget {{
            background-color: {c['surface']};
        }}
        QCalendarWidget QAbstractItemView {{
            background-color: {c['surface']};
            color: {c['text']};
            selection-background-color: {c['accent']};
            selection-color: {c['accent_text']};
            outline: none;
            border: none;
            /* Компактные ячейки: без этого календарь требовал 296 px и
               распирал панель навигации. Кегль подстраивается под ширину
               панели, чтобы сетка 7 колонок не обрезалась. */
            padding: 0px;
            margin: 0px;
            font-size: {self._font_size:.1f}pt;
        }}
        QCalendarWidget QAbstractItemView:disabled {{
            color: {c['text_disabled']};
        }}
        QCalendarWidget QToolButton {{
            background-color: transparent;
            color: {c['text']};
            border: none;
            padding: 1px 2px;
            margin: 0px;
            icon-size: 10px;
            /* min-width: 0 снимает «естественный» минимум кнопок месяца и
               года: их сумма (228 px) задавала нижний предел всей панели. */
            min-width: 0px;
            font-size: {self._font_size:.1f}pt;
        }}
        QCalendarWidget QToolButton:hover {{
            background-color: {c['surface_high']};
            border-radius: 4px;
        }}
        QCalendarWidget QMenu {{
            background-color: {c['surface_alt']};
            color: {c['text']};
        }}
        QCalendarWidget QSpinBox {{
            background-color: {c['surface']};
            color: {c['text']};
            border: 1px solid {c['border_strong']};
            border-radius: 4px;
            padding: 0px 2px;
            min-width: 44px;
            max-width: 58px;
        }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background-color: {c['surface_alt']};
            padding: 0px;
            margin: 0px;
        }}
        """


def _month_dates(year: int, month: int) -> list[date]:
    """Все даты месяца, включая ведущие и хвостовые дни сетки."""
    from calendar import monthrange

    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    start = first.toordinal() - (first.weekday())
    end = last.toordinal() + (6 - last.weekday())
    return [date.fromordinal(value) for value in range(start, end + 1)]


__all__ = ["MiniCalendar"]
