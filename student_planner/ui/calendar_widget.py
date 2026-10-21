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
        self._selected = clock.today()
        self._refresh_header()

    # ------------------------------------------------------------------ метки
    def set_marks(self, marks: dict[date, str]) -> None:
        """Точки-метки: ``override``, ``rides``, ``period``, ``homework``."""
        self._marks = dict(marks)
        self._paint_marks()

    def set_week_types(self, types: dict[date, str]) -> None:
        """UI-05: тип недели в подсветке."""
        self._week_types = dict(types)
        self._paint_marks()

    def set_selected(self, value: date) -> None:
        self._selected = value
        self.calendar.setSelectedDate(QDate(value.year, value.month, value.day))
        self._refresh_header()

    @property
    def selected_date(self) -> date:
        selected = self.calendar.selectedDate()
        return date(selected.year(), selected.month(), selected.day())

    def go_today(self) -> None:
        self.set_selected(clock.today())
        self.date_selected.emit(self.selected_date)

    # ------------------------------------------------------------------ отрисовка
    def _paint_marks(self) -> None:
        weekdays = [
            Qt.DayOfWeek.Monday, Qt.DayOfWeek.Tuesday, Qt.DayOfWeek.Wednesday,
            Qt.DayOfWeek.Thursday, Qt.DayOfWeek.Friday, Qt.DayOfWeek.Saturday,
            Qt.DayOfWeek.Sunday,
        ]
        today = clock.today()
        for value in _month_dates(self.calendar.yearShown(), self.calendar.monthShown()):
            fmt = QTextCharFormat()
            kinds = [self._marks.get(value, "")]
            base_color = COLORS["text"]

            if value == today:
                fmt.setBackground(QColor(COLORS["surface_high"]))
                fmt.setFontWeight(700)
            week_type = self._week_types.get(value)
            if week_type == "upper":
                fmt.setForeground(QColor(COLORS["accent_hover"]))
            elif week_type == "lower":
                fmt.setForeground(QColor(base_color))
            if value.weekday() == 6:
                fmt.setForeground(QColor(COLORS["text_muted"]))
            if "period" in kinds:
                fmt.setBackground(QColor(COLORS["warning_bg"]))
                fmt.setForeground(QColor(COLORS["warning_text"]))
            if "override" in kinds:
                fmt.setFontUnderline(True)
            fmt.setToolTip(self._tooltip(value))
            self.calendar.setDateTextFormat(QDate(value.year, value.month, value.day), fmt)

        del weekdays  # список дней недели нужен только для читаемости выше

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

    # ------------------------------------------------------------------ стиль
    @staticmethod
    def _style() -> str:
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
        }}
        QCalendarWidget QAbstractItemView:disabled {{
            color: {c['text_disabled']};
        }}
        QCalendarWidget QToolButton {{
            background-color: transparent;
            color: {c['text']};
            border: none;
            padding: 2px 6px;
            icon-size: 14px;
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
        }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background-color: {c['surface_alt']};
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
