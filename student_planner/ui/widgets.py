"""Общие виджеты интерфейса (§20–§23).

Мелкие повторяющиеся элементы собраны здесь, чтобы страницы не дублировали
разметку и оформление: бейджи статусов (SCH-05, SCH-11), карточки занятий
(SCH-04), состояния «пусто» (SCH-07, HW-14, REP-07, TRIP-15) и предупреждения
(WAL-06, SCH-19).
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from ..core.models import LessonStatus


def repolish(widget: QWidget) -> None:
    """Переприменить стиль после смены ``objectName``/свойств."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def show_message(label: QLabel, text: str, *, error: bool = False) -> None:
    """Показать сообщение под формой зелёным или красным цветом темы.

    Цвет задаётся именем объекта (``ErrorText``/``SuccessText``), а не строкой
    ``setStyleSheet``: строка с hex-значением пережила бы смену темы и осталась
    бы, например, тёмно-красной на светлом фоне.

    Пустой текст скрывает плашку: без этого после успешной операции оставалась
    висеть пустая цветная полоса (``setText('')`` + ``setVisible(True)``).
    """
    if not text:
        label.setText("")
        label.setVisible(False)
        return
    label.setObjectName("ErrorText" if error else "SuccessText")
    repolish(label)
    label.setText(text)
    label.setVisible(True)


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
        "cancelled": "BadgeCancelled",
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
    """SCH-05/SCH-11: статус занятия бейджем.

    Отменённое занятие — приглушённый бейдж ``cancelled``, а не «ошибка»:
    отмена бывает плановой, красный цвет для неё слишком громкий.
    """
    kinds = {
        LessonStatus.PLANNED: "neutral",
        LessonStatus.CANCELLED: "cancelled",
        LessonStatus.REPLACED: "warning",
        LessonStatus.ADDED: "success",
    }
    return Badge(LessonStatus.label(status), kinds.get(status, "neutral"))


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
        # Заголовок переносится и сжимается: «Поездки на 09.12.2026» длиннее
        # узкой панели, и без переноса карточка требовала лишние 60–80 px.
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.title_label.setMinimumWidth(0)
        self.header.addWidget(self.title_label, 1)
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


class FlowLayout(QLayout):
    """Раскладка «в строку с переносом»: элементы переходят на новую строку.

    Нужна для панелей управления, где рядом стоят поле выбора, флажок и
    кнопки. В обычном ``QHBoxLayout`` при нехватке места Qt не переносит
    элементы, а сжимает их ниже ``minimumSizeHint`` — текст обрезается по
    краю без многоточия и без подсказки. Так обрезались флажок «Показывать
    отменённые» (154 px при минимуме 172), бейдж «Нижняя неделя» (73 px при
    103) и кнопка «Добавить поездку…» (123 px при 155) — на обычном окне
    1400x880 и на минимальном 1080x680.

    Перенос вместо сжатия сохраняет каждый элемент целым: это и есть
    требование UI-02/UI-04 — содержимое не обрезается, а занимает больше
    строк. Минимальная ширина раскладки — ширина самого широкого элемента,
    поэтому она не распирает центральную зону.
    """

    def __init__(self, parent: QWidget | None = None, *, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)
        # Раскладка сама задаёт высоту по числу строк, поэтому тянется
        # только по горизонтали.
        self.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)

    # ---------------------------------------------------------- QLayout API
    def addWidget(self, widget: QWidget) -> None:  # noqa: N802 - имя из Qt
        """Добавить виджет (как у ``QBoxLayout``)."""
        self.addChildWidget(widget)
        self._items.append(QWidgetItem(widget))

    def addLayout(self, layout: QLayout) -> None:  # noqa: N802 - имя из Qt
        """Добавить вложенную раскладку — как один неделимый элемент.

        Вложенная раскладка оборачивается в отдельный ``QWidget``: перенос
        целой группы элементов (например, бейджа типа недели) на другую
        строку выглядит аккуратнее, чем перенос её частей по одной.
        """
        host = QWidget()
        host.setLayout(layout)
        host.setSizePolicy(QSizePolicy.Policy.Maximum,
                           QSizePolicy.Policy.Fixed)
        self.addWidget(host)

    def addItem(self, item) -> None:  # noqa: N802 - имя из Qt
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - имя из Qt
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802 - имя из Qt
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802 - имя из Qt
        # Растягивать нечего: лишнее место уходит вправо от последнего
        # элемента, а высота определяется числом строк.
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - имя из Qt
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - имя из Qt
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - имя из Qt
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - имя из Qt
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - имя из Qt
        """Ширина — самый широкий элемент, высота — все элементы в столбик.

        Так раскладка не требует больше, чем помещается в центральную зону:
        в худшем случае каждый элемент встанет на свою строку.
        """
        size = QSize()
        margins = self.contentsMargins()
        for item in self._items:
            widget = item.widget()
            if widget is None or widget.isHidden():
                continue
            hint = widget.minimumSizeHint()
            size = size.expandedTo(hint)
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    # ------------------------------------------------------------- раскладка
    def _do_layout(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0
        spacing = self._spacing
        for item in self._items:
            widget = item.widget()
            if widget is None or widget.isHidden():
                continue
            hint = widget.sizeHint()
            width = min(hint.width(), max(effective.width(), 1))
            next_x = x + width + spacing
            if next_x - spacing > effective.right() + 1 and line_height > 0:
                # Не помещается — начинаем новую строку.
                x = effective.x()
                y = y + line_height + spacing
                next_x = x + width + spacing
            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, hint.height())))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


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
        # Центрируем **отступами-распорками**, а не выравниванием раскладки.
        # ``setAlignment(AlignCenter)`` заставляет раскладку ужимать каждый
        # элемент до его минимального размера: подпись «Пополнений нет»
        # получала 100x28 вместо 117x20, а подсказка на две строки — те же
        # 100x28 при нужных 96 px высоты, и обе обрезались. Распорки дают
        # элементам их нормальную ширину и держат группу по центру.
        layout.addStretch(1)

        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("Empty")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption_label.setWordWrap(True)
        self.caption_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.caption_label.setMinimumWidth(0)
        layout.addWidget(self.caption_label)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("Small")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.hint_label.setMinimumWidth(0)
        layout.addWidget(self.hint_label)
        # UI-27: видимость — после добавления в раскладку. Кнопка без
        # родителя является самостоятельным окном, и setVisible(True) до
        # addWidget показывало её отдельным окном на один кадр.
        self.hint_label.setVisible(bool(hint))

        self.action_button = QPushButton(action_text)
        self.action_button.setObjectName("Primary")
        # Кнопка сжимается: «Добавить испытание» требовала 230 px и задавала
        # минимальную ширину всей правой панели — она не могла сузиться до
        # 220 px, и контент обрезался.
        self.action_button.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self.action_button.setMinimumWidth(0)
        self.action_button.clicked.connect(self.action_clicked)
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self.action_button)
        holder.addStretch(1)
        layout.addLayout(holder)
        layout.addStretch(1)
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
    """Предупреждение с действиями (WAL-06, SCH-19, ALG-10).

    Цвета берутся из темы по имени объекта (``CardWarning``/``WarningText``), а
    не из ``setStyleSheet`` с конкретными hex-значениями: иначе при смене темы
    баннер оставался бы оформленным по прежней палитре.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardWarning")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.icon = QLabel("!")
        self.icon.setObjectName("WarningText")
        self.icon.setStyleSheet("font-weight: 700;")
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)

        self.message = QLabel()
        self.message.setObjectName("WarningText")
        self.message.setWordWrap(True)
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


class WrappingLabel(QLabel):
    """Метка с переносом строк, у которой ``sizeHint`` честно просит ширину.

    У ``QLabel`` с ``setWordWrap(True)`` ``sizeHint`` возвращает не полную
    ширину текста, а заниженную: «Дебетовой картой» просит 59 px вместо 111,
    «Остаток на конец периода» — 46 вместо 159. Раскладка верит подсказке и
    выделяет метке мало места, после чего текст переносится на две-три
    строки, строка разъезжается по высоте, а часть текста всё равно
    упирается в край.

    Здесь ``sizeHint`` считается по тексту (полная ширина одной строки), а
    ``minimumSizeHint`` — по самому длинному слову: переносить текст можно,
    но не до бесконечности, и ширина панели по-прежнему ограничена словом.
    """

    def sizeHint(self) -> QSize:  # noqa: N802 - имя из Qt
        metrics = self.fontMetrics()
        text = self.text()
        if not text:
            return super().sizeHint()
        width = max(
            (metrics.horizontalAdvance(line) for line in text.split("\n")),
            default=0,
        )
        margins = self.contentsMargins()
        width += margins.left() + margins.right() + 2 * self.margin()
        return QSize(
            width,
            metrics.height() + margins.top() + margins.bottom()
            + 2 * self.margin(),
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - имя из Qt
        metrics = self.fontMetrics()
        text = self.text()
        if not text:
            return super().minimumSizeHint()
        widest = max(
            (metrics.horizontalAdvance(word) for line in text.split("\n")
             for word in line.split(" ")),
            default=0,
        )
        margins = self.contentsMargins()
        widest += margins.left() + margins.right() + 2 * self.margin()
        return QSize(
            widest,
            metrics.height() + margins.top() + margins.bottom()
            + 2 * self.margin(),
        )


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

        self.caption_label = WrappingLabel(caption)
        self.caption_label.setObjectName("Muted")
        # Подпись получает столько места, сколько нужно её тексту, и
        # переносится, если строка уже. Раньше стояли Ignored + минимум 40 px:
        # политика запрещала подписи занимать больше минимума, и Qt сжимал её
        # ровно до 40 px — «Стоимость» (63 px), «Обратно» (53 px), «Остаток на
        # конец периода» (159 px) рисовались обрезанными по правому краю, а
        # подсказки у подписи нет, так что прочитать их было нельзя. Перенос
        # не даёт подписи диктовать минимальную ширину: у неё минимум — самое
        # длинное слово, и панель по-прежнему сжимается до 220 px.
        self.caption_label.setWordWrap(True)
        self.caption_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.caption_label.setMinimumWidth(40)
        layout.addWidget(self.caption_label, 0)

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
        # Значение забирает свободное место (растяжение 1) и сжимается на
        # узкой панели; полный текст — в подсказке.
        self.value_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.value_label.setMinimumWidth(30)
        self.value_label.setToolTip(value)
        layout.addWidget(self.value_label, 1)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)
        # Полное значение — в подсказке: на узкой панели текст усекается
        # многоточием, и без подсказки его нельзя прочитать целиком.
        self.value_label.setToolTip(text)

    def set_kind(self, kind: str) -> None:
        """Подкрасить значение: ``warning``, ``success``, ``error``, ``muted``.

        Цвет задаётся свойством ``kind`` и живёт в таблице стилей темы. Строка
        стиля с сегодняшним hex-значением пережила бы смену темы и осталась
        бы, например, жёлтой на светлом фоне.
        """
        allowed = {"warning", "success", "error", "muted", ""}
        value = kind if kind in allowed else ""
        self.value_label.setProperty("kind", value)
        repolish(self.value_label)


__all__ = [
    "Badge",
    "status_badge",
    "week_type_badge",
    "Card",
    "FlowLayout",
    "WrappingLabel",
    "SectionHeader",
    "Separator",
    "EmptyState",
    "WarningBanner",
    "MetricRow",
    "repolish",
    "show_message",
]
