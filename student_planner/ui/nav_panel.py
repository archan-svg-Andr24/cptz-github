"""Левая панель навигации (UI-04, UI-05).

Состав: профиль (имя и группа, при пустом значении — «Не указано», FIRST-15),
меню из пяти разделов, мини-календарь и бейдж типа недели. Раздел «Экзамены»
добавится в v1.1.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core import clock
from ..core.dates import MONTH_NAMES_NOMINATIVE, WEEKDAY_NAMES
from ..core.settings_service import SettingsService
from .calendar_widget import MiniCalendar
from .widgets import Badge, Separator, repolish

#: UI-04/UI-06: разделы меню. «Экзамены» — v1.1.
NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("schedule", "Расписание"),
    ("trips", "Поездки"),
    ("expenses", "Расходы на транспорт"),
    ("homework", "Домашние задания"),
    ("settings", "Настройки"),
)


class NavPanel(QFrame):
    """UI-04: профиль, меню, мини-календарь, бейдж типа недели."""

    page_requested = Signal(str)
    date_selected = Signal(object)

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavPanel")
        self.setFixedWidth(250)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.db = db
        self.settings = SettingsService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        # ---------------------------------------------------------- профиль
        profile = QFrame()
        profile_layout = QVBoxLayout(profile)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(2)

        self.app_title = QLabel("Студенческий органайзер")
        self.app_title.setObjectName("Small")
        profile_layout.addWidget(self.app_title)

        self.name_label = QLabel("Не указано")
        self.name_label.setObjectName("ProfileName")
        self.name_label.setWordWrap(True)
        profile_layout.addWidget(self.name_label)

        self.group_label = QLabel("Не указано")
        self.group_label.setObjectName("Muted")
        self.group_label.setWordWrap(True)
        profile_layout.addWidget(self.group_label)
        layout.addWidget(profile)
        layout.addWidget(Separator())

        # ------------------------------------------------------------ меню
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, caption in NAV_ITEMS:
            button = QPushButton(caption)
            button.setObjectName("NavItem")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, page=key: self._on_nav(page))
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)
        self._buttons["schedule"].setChecked(True)

        layout.addStretch(1)
        layout.addWidget(Separator())

        # -------------------------------------------------- мини-календарь
        self.calendar = MiniCalendar()
        self.calendar.date_selected.connect(self.date_selected)
        layout.addWidget(self.calendar)

        # ------------------------------------------------------- тип недели
        week_row = QHBoxLayout()
        week_row.setSpacing(6)
        week_caption = QLabel("Неделя:")
        week_caption.setObjectName("Small")
        week_row.addWidget(week_caption)
        self.week_badge = Badge("—", "accent")
        week_row.addWidget(self.week_badge)
        week_row.addStretch(1)
        layout.addLayout(week_row)

        self.today_label = QLabel()
        self.today_label.setObjectName("Small")
        self.today_label.setWordWrap(True)
        layout.addWidget(self.today_label)

        self.refresh()

    # ------------------------------------------------------------------ данные
    def refresh(self) -> None:
        """Перечитать профиль и текущую дату (§30: значения только из реестра)."""
        name, group = self.settings.profile_caption()
        self.name_label.setText(name)
        self.group_label.setText(group)
        self.set_today(clock.today())

    def set_today(self, value: date) -> None:
        self.today_label.setText(
            f"{WEEKDAY_NAMES[value.isoweekday()]}, "
            f"{value.day} {MONTH_NAMES_NOMINATIVE[value.month].lower()} {value.year}"
        )

    def set_week_type(self, week_type: str | None) -> None:
        """UI-04: бейдж типа недели."""
        if week_type == "upper":
            self.week_badge.setText("Верхняя")
        elif week_type == "lower":
            self.week_badge.setText("Нижняя")
        else:
            self.week_badge.setText("—")

    def set_marks(self, marks: dict[date, str]) -> None:
        self.calendar.set_marks(marks)

    def set_week_types(self, types: dict[date, str]) -> None:
        self.calendar.set_week_types(types)

    def set_selected_date(self, value: date) -> None:
        self.calendar.set_selected(value)

    def set_current_page(self, page: str) -> None:
        button = self._buttons.get(page)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    # ------------------------------------------------------------------ события
    def _on_nav(self, page: str) -> None:
        self.page_requested.emit(page)

    def page_caption(self, page: str) -> str:
        return dict(NAV_ITEMS).get(page, page)


__all__ = ["NavPanel", "NAV_ITEMS"]
