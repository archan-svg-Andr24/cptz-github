"""Общие виджеты интерфейса (§20–§23).

Мелкие повторяющиеся элементы собраны здесь, чтобы страницы не дублировали
разметку и оформление: бейджи статусов (SCH-05, SCH-11), карточки занятий
(SCH-04), состояния «пусто» (SCH-07, HW-14, REP-07, TRIP-15) и предупреждения
(WAL-06, SCH-19).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.models import LessonStatus
from .theme import COLORS


def repolish(widget: QWidget) -> None:
    """Переприменить стиль после смены ``objectName``/свойств."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


# ===========================================================================
# Бейджи
# ===========================================================================
class Badge(QLabel):
    """Бейдж-подпись (статус, тип недели, предупреждение)."""

    KINDS = {
        "neutral": "Badge",
        "accent": "BadgeAccent",
        "warning": "BadgeWarning",
        "success": "BadgeSuccess",
        "error": "BadgeError",
    }

    def __init__(self, text: str = "", kind: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName(self.KINDS.get(kind, "Badge"))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_kind(self, kind: str) -> None:
        self.setObjectName(self.KINDS.get(kind, "Badge"))
        repolish(self)


def status_badge(status: str) -> Badge:
    """SCH-05/SCH-11: статус занятия бейджем."""
    kinds = {
        LessonStatus.PLANNED: "neutral",
        LessonStatus.CANCELLED: "error",
        LessonStatus.REPLACED: "warning",
        LessonStatus.ADDED: "success",
    }
    badge = Badge(LessonStatus.label(status), kinds.get(status, "neutral"))
    if status == LessonStatus.CANCELLED:
        badge.setStyleSheet(
            f"color: {COLORS['status_cancelled']}; "
            f"background-color: {COLORS['cancelled_bg']}; "
            f"border: 1px solid {COLORS['cancelled']}; "
            "border-radius: 6px; padding: 2px 8px; font-size: 9pt;"
        )
    return badge


def week_type_badge(caption: str) -> Badge:
    """UI-04: бейдж типа недели в левой панели."""
    return Badge(caption, "accent")


# ===========================================================================
# Карточки и заголовки
# ===========================================================================
class Card(QFrame):
    """Панель-карточка с заголовком и произвольным содержимым."""

    def __init__(
        self,
        title: str = "",
        *,
        accent: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CardAccent" if accent else "Card")
        # Карточка обнимает содержимое по высоте. С политикой Preferred она
        # делила свободное место со списком или пустым состоянием: три
        # карточки отчётов раздувались до 181 px каждая, а строка
        # «61.00 ₽ · 25 %» переносилась и разъезжалась.
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(6)

        self.header = QHBoxLayout()
        self.header.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("Subtitle")
        self.header.addWidget(self.title_label)
        self.header.addStretch(1)
        self._layout.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setSpacing(4)
        self._layout.addLayout(self.body)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget)


class SectionHeader(QWidget):
    """Заголовок страницы: название, подпись и место под кнопки."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Заголовок занимает одну строку и не должен забирать высоту у
        # содержимого. Без Maximum по вертикали он растягивался на всю
        # страницу, когда ниже показывалось пустое состояние: «Расписание»
        # разъезжалось на высоту 385 px вместо 32.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("Title")
        texts.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignTop)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("Muted")
        self.subtitle_label.setWordWrap(True)
        texts.addWidget(self.subtitle_label, 0, Qt.AlignmentFlag.AlignTop)
        # UI-27: видимость — после добавления в раскладку (см. EmptyState).
        self.subtitle_label.setVisible(bool(subtitle))
        layout.addLayout(texts, 0)
        layout.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        layout.addLayout(self.actions, 0)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


class Separator(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Separator")
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)


# ===========================================================================
# Пустые состояния
# ===========================================================================
class EmptyState(QWidget):
    """Состояние «пусто» с необязательной кнопкой действия.

    Используется для SCH-07 («Занятий нет»), HW-05/HW-14 («Заданий нет»),
    REP-07 («Поездок за период нет») и TRIP-15 («Шаблонов нет»).
    """

    action_clicked = Signal()

    def __init__(
        self,
        caption: str,
        *,
        hint: str = "",
        action_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Пустое состояние занимает свободное место целиком, но содержимое
        # держит по центру: без этого подпись и кнопка прилипали к верху, а
        # низ страницы оставался пустым.
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 24)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("Empty")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption_label.setWordWrap(True)
        layout.addWidget(self.caption_label, 0, Qt.AlignmentFlag.AlignCenter)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("Small")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label, 0, Qt.AlignmentFlag.AlignCenter)
        # UI-27: видимость — после добавления в раскладку. Кнопка без
        # родителя является самостоятельным окном, и setVisible(True) до
        # addWidget показывало её отдельным окном на один кадр.
        self.hint_label.setVisible(bool(hint))

        self.action_button = QPushButton(action_text)
        self.action_button.setObjectName("Primary")
        self.action_button.clicked.connect(self.action_clicked)
        holder = QHBoxLayout()
        holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        holder.addWidget(self.action_button)
        layout.addLayout(holder)
        self.action_button.setVisible(bool(action_text))

    def set_caption(self, text: str) -> None:
        self.caption_label.setText(text)

    def set_hint(self, text: str) -> None:
        self.hint_label.setText(text)
        self.hint_label.setVisible(bool(text))

    def set_action_text(self, text: str) -> None:
        self.action_button.setText(text)
        self.action_button.setVisible(bool(text))


# ===========================================================================
# Предупреждения
# ===========================================================================
class WarningBanner(QFrame):
    """Предупреждение с действиями (WAL-06, SCH-19, ALG-10)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"QFrame#Card {{ background-color: {COLORS['warning_bg']}; "
            f"border: 1px solid {COLORS['warning']}; border-radius: 6px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.icon = QLabel("!")
        self.icon.setStyleSheet(f"color: {COLORS['warning_text']}; font-weight: 700;")
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet(f"color: {COLORS['warning_text']};")
        layout.addWidget(self.message, 1)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        layout.addLayout(self.buttons)

        self.hide()

    def set_message(self, text: str) -> None:
        self.message.setText(text)

    def add_action(self, text: str, callback) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(callback)
        self.buttons.addWidget(button)
        return button

    def clear_actions(self) -> None:
        """Убрать кнопки действий.

        ``deleteLater`` выполняет удаление только на следующем проходе цикла
        событий, поэтому при нескольких обновлениях подряд старые кнопки
        оставались видимыми и копились. Убираем со слоя сразу, затем планируем
        удаление.
        """
        while self.buttons.count():
            item = self.buttons.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()


class MetricRow(QWidget):
    """Пара «подпись — значение» для виджетов правой панели и отчётов."""

    def __init__(
        self,
        caption: str,
        value: str = "—",
        *,
        strong: bool = False,
        wrap_value: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("Muted")
        layout.addWidget(self.caption_label, 0)
        layout.addStretch(1)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("Metric" if strong else "")
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        # Перенос включается только по запросу. В правой панели он нужен:
        # «21.10.2026 — 19.11.2026» не влезает в 240 px. В отчётах ширины
        # хватает, а включённый перенос ломал структуру: «61.00 ₽ · 25 %»
        # переносилось в узкую колонку и строки разъезжались по высоте.
        self.value_label.setWordWrap(wrap_value)
        layout.addWidget(self.value_label, 0)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)

    def set_kind(self, kind: str) -> None:
        """Подкрасить значение: ``warning``, ``success``, ``error``, ``muted``."""
        colors = {
            "warning": COLORS["warning_text"],
            "success": COLORS["success"],
            "error": COLORS["error"],
            "muted": COLORS["text_muted"],
            "": COLORS["text"],
        }
        self.value_label.setStyleSheet(f"color: {colors.get(kind, COLORS['text'])};")


__all__ = [
    "Badge",
    "status_badge",
    "week_type_badge",
    "Card",
    "SectionHeader",
    "Separator",
    "EmptyState",
    "WarningBanner",
    "MetricRow",
    "repolish",
]
