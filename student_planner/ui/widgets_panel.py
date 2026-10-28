"""Правая панель виджетов (§23: UI-07, UI-08, UI-09, UI-10).

Три виджета: текущие дата и время, «Поездки на сегодня» с кнопкой подтверждения,
«Стрелка» с вычисленными границами периода и остатком, «Домашние задания» на
сегодня и завтра.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core import clock
from ..core.dates import MONTH_NAMES_NOMINATIVE, WEEKDAY_NAMES, format_display
from ..core.schedule_service import HomeworkService
from ..core.transport_service import TransportService
from ..core.trip_service import TripPlanService
from .theme import COLORS
from .widgets import Badge, Card, MetricRow, Separator


class ClockWidget(QWidget):
    """UI-07: текущие дата и время."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.time_label = QLabel()
        self.time_label.setObjectName("Clock")
        layout.addWidget(self.time_label)

        self.date_label = QLabel()
        self.date_label.setObjectName("Muted")
        layout.addWidget(self.date_label)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        now = clock.now()
        self.time_label.setText(now.strftime("%H:%M"))
        value = now.date()
        self.date_label.setText(
            f"{WEEKDAY_NAMES[value.isoweekday()]}, {value.day} "
            f"{MONTH_NAMES_NOMINATIVE[value.month].lower()} {value.year}"
        )


class TripsTodayWidget(Card):
    """UI-08: «Поездки на сегодня» — направления, стоимость, подтверждение."""

    confirm_requested = Signal(object)  # date

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__("Поездки на сегодня", parent=parent)
        self.db = db
        self._date: date = clock.today()

        self.outbound_row = MetricRow("Туда", wrap_value=True)
        self.return_row = MetricRow("Обратно", wrap_value=True)
        self.total_row = MetricRow("Стоимость", strong=True, wrap_value=True)
        for row in (self.outbound_row, self.return_row):
            self.add_widget(row)
        self.add_widget(Separator())
        self.add_widget(self.total_row)

        self.state_badge = Badge("не выбрано")
        self.add_action(self.state_badge)

        self.confirm_button = QPushButton("Подтвердить поездки")
        self.confirm_button.setObjectName("Primary")
        self.confirm_button.clicked.connect(
            lambda: self.confirm_requested.emit(self._date)
        )
        self.add_widget(self.confirm_button)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("Small")
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)
        self.add_widget(self.empty_label)

    def refresh(self, value: date | None = None) -> None:
        if value is not None:
            self._date = value
        service = TripPlanService(self.db)
        plan = service.plan(self._date)

        self.outbound_row.set_value(plan.outbound.name if plan.outbound else "не выбрано")
        self.return_row.set_value(
            plan.return_trip.name if plan.return_trip else "не выбрано"
        )

        if plan.is_confirmed:
            self.state_badge.setText("подтверждено")
            self.state_badge.set_kind("success")
            self.confirm_button.setText("Изменить подтверждение")
        else:
            self.state_badge.setText("не выбрано")
            self.state_badge.set_kind("neutral")
            self.confirm_button.setText("Подтвердить поездки")

        if not plan.has_lessons:
            self.empty_label.setText("Занятий нет — поездки не требуются")
            self.empty_label.setVisible(True)
            self.confirm_button.setEnabled(False)
            self.total_row.set_value("—")
        else:
            self.empty_label.setVisible(False)
            self.confirm_button.setEnabled(True)
            confirmation = plan.confirmation
            if confirmation is not None:
                rides = service.rides.for_confirmation(confirmation.id)
                total = sum((ride.paid_price for ride in rides), Decimal("0.00"))
                self.total_row.set_value(f"{total} ₽")
            else:
                self.total_row.set_value("— после подтверждения")


class StrellaWidget(Card):
    """UI-09: границы периода, следующая поездка, стоимость, экономия, остаток."""

    recalculate_requested = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__("Стрелка", parent=parent)
        self.db = db

        self.period_row = MetricRow("Период", wrap_value=True)
        self.next_row = MetricRow("Следующая поездка", wrap_value=True)
        self.price_row = MetricRow("Стоимость", wrap_value=True)
        self.savings_row = MetricRow("Экономия за период", wrap_value=True)
        self.balance_row = MetricRow("Остаток", strong=True, wrap_value=True)
        for row in (self.period_row, self.next_row, self.price_row,
                    self.savings_row):
            self.add_widget(row)
        self.add_widget(Separator())
        self.add_widget(self.balance_row)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        self.warning_label.setStyleSheet(
            f"color: {COLORS['warning_text']}; "
            f"background-color: {COLORS['warning_bg']}; "
            f"border: 1px solid {COLORS['warning']}; "
            "border-radius: 6px; padding: 6px;"
        )
        self.add_widget(self.warning_label)

        self.note_label = QLabel()
        self.note_label.setObjectName("Small")
        self.note_label.setWordWrap(True)
        self.note_label.setVisible(False)
        self.add_widget(self.note_label)

        self.recalculate_button = QPushButton("Пересчитать счётчик…")
        self.recalculate_button.setObjectName("Flat")
        self.recalculate_button.clicked.connect(self.recalculate_requested)
        self.add_widget(self.recalculate_button)

    def refresh(self) -> None:
        state = TransportService(self.db).strella_state()
        self.period_row.set_value(state.bounds_caption)
        self.next_row.set_value(f"№{state.next_ride_number}")
        self.price_row.set_value(f"{state.next_ride_price} ₽")
        self.savings_row.set_value(f"{state.savings_in_period} ₽")
        self.balance_row.set_value(state.balance_caption)

        if state.balance < 0:
            self.balance_row.set_kind("error")
        elif state.low_balance:
            self.balance_row.set_kind("warning")
        else:
            self.balance_row.set_kind("")

        self.warning_label.setText(state.warning_caption)
        self.warning_label.setVisible(bool(state.warning_caption))

        self.note_label.setText(state.initial_count_note)
        self.note_label.setVisible(bool(state.initial_count_note))


class HomeworkWidget(Card):
    """UI-10/HW-05: задания на текущую и следующую недели.

    Высота списка **подбирается автоматически** по числу заданий: от 0 до
    ``MAX_VISIBLE_ROWS`` (четырёх) строк видны целиком. Если заданий больше,
    показываются первые четыре, а остальные доступны вертикальной прокруткой.
    Ручной регулировки у карточки нет: граница списка всегда снизу, и список
    не должен «уезжать» при обновлениях.
    """

    open_requested = Signal()

    #: Сколько строк видно без прокрутки. Пятая и далее — под прокруткой.
    MAX_VISIBLE_ROWS = 4

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__("Домашние задания", parent=parent)
        self.db = db

        self.rows_host = QWidget()
        self.rows_host.setMinimumWidth(0)
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(4)
        self.rows_layout.addStretch(1)

        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # Height зависит от числа строк и считается в _fit_list_height, поэтому
        # политика Expanding: карточка забирает ровно столько, сколько нужно.
        self.rows_scroll.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.rows_scroll.setWidget(self.rows_host)
        self.rows_scroll.setVisible(False)
        self.add_widget(self.rows_scroll)

        self.empty_label = QLabel("Заданий нет")
        self.empty_label.setObjectName("Empty")
        self.empty_label.setVisible(False)
        self.add_widget(self.empty_label)

        self.open_button = QPushButton("Все задания")
        self.open_button.setObjectName("Flat")
        self.open_button.clicked.connect(self.open_requested)
        self.add_widget(self.open_button)

        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)

    def _visible_rows(self) -> list[QWidget]:
        rows: list[QWidget] = []
        for index in range(self.rows_layout.count()):
            widget = self.rows_layout.itemAt(index).widget()
            if widget is not None and widget.isVisibleTo(self.rows_host):
                rows.append(widget)
        return rows

    def _row_heights(self, width: int) -> list[int]:
        """Высоты строк при заданной ширине.

        ``sizeHint`` строки не учитывает перенос длинных названий по ширине
        панели (отдавал 76 px вместо 96), поэтому считаем ``heightForWidth``.
        """
        if width <= 0:
            width = self.rows_scroll.width() - 2 * self.rows_scroll.frameWidth()
        heights: list[int] = []
        for widget in self._visible_rows():
            height = widget.heightForWidth(width) if width > 0 else -1
            heights.append(height if height > 0 else widget.sizeHint().height())
        return heights

    def _span_height(self, heights: list[int]) -> int:
        """Высота области под указанные строки, включая отступы и рамку."""
        if not heights:
            return 0
        margins = self.rows_layout.contentsMargins()
        total = sum(heights)
        total += self.rows_layout.spacing() * (len(heights) - 1)
        total += margins.top() + margins.bottom()
        total += 2 * self.rows_scroll.frameWidth()
        return total

    def preferred_list_height(self) -> int:
        """Высота, при которой видно не больше MAX_VISIBLE_ROWS заданий.

        Больше четырёх строк не показываем даже при большом списке: остальные
        уходят под прокрутку, и карточка не выдавливает верхние виджеты панели.
        """
        width = self.rows_scroll.viewport().width()
        heights = self._row_heights(width)
        if not heights:
            return 0
        limit = self.MAX_VISIBLE_ROWS
        if len(heights) > limit:
            # Прокрутка отнимает ширину у строк: пересчитываем по ней, иначе
            # последняя видимая строка окажется обрезанной по высоте.
            bar = self.rows_scroll.verticalScrollBar().sizeHint().width()
            if bar > 0 and width > bar:
                heights = self._row_heights(width - bar)
        return self._span_height(heights[:limit])

    def refresh(self) -> None:
        while self.rows_layout.count() > 1:  # последний — stretch
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater() отложен: без hide()+setParent(None) старая
                # строка остаётся видимой до конца цикла событий.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        rows = HomeworkService(self.db).upcoming()
        self.empty_label.setVisible(not rows)
        self.rows_scroll.setVisible(bool(rows))
        if not rows:
            self._fit_list_height()
            return

        for row in rows:
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, self._row(row))
        self._fit_list_height()
        # Первый расчёт идёт до раскладки: у скрытой области ещё нет ширины,
        # поэтому heightForWidth строк врёт. Повторяем в конце цикла событий,
        # когда геометрия уже настоящая.
        QTimer.singleShot(0, self._fit_list_height)

    def _fit_list_height(self) -> None:
        """Подогнать высоту области под видимые задания (дефект: стояла 59 px).

        ``QScrollArea`` не выводит ``sizeHint`` из содержимого, а карточка с
        политикой Maximum брала её один раз при первом показе — список
        навсегда оставался высотой в одну строку, и добавленные задания
        обрезались. Считаем нужную высоту явно после раскладки.
        """
        height = self.preferred_list_height()
        if height <= 0:
            return
        if (self.rows_scroll.minimumHeight() != height
                or self.rows_scroll.maximumHeight() != height):
            # min = max: ровно по содержимому, без пустого поля снизу.
            self.rows_scroll.setMinimumHeight(height)
            self.rows_scroll.setMaximumHeight(height)
            self.rows_scroll.updateGeometry()
            self.updateGeometry()

    def _row(self, row) -> QWidget:
        line = QWidget()
        layout = QVBoxLayout(line)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)

        caption = QLabel(row.subject_name)
        caption.setObjectName("Subtitle")
        # Название предмета бывает длинным («Документирование программных
        # средств»), а панель узкой: без переноса текст уходил за край.
        caption.setWordWrap(True)
        layout.addWidget(caption)

        detail = QLabel(row.short_description or "без описания")
        detail.setObjectName("Small")
        detail.setToolTip(row.description)
        detail.setWordWrap(True)
        layout.addWidget(detail)

        due = QLabel(f"до {row.due_caption}")
        due.setObjectName("Small")
        due.setStyleSheet(f"color: {COLORS['accent_hover']};")
        layout.addWidget(due)
        return line


class WidgetsPanel(QFrame):
    """§23: правая панель виджетов."""

    confirm_requested = Signal(object)
    recalculate_requested = Signal()
    homework_requested = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WidgetsPanel")
        # UI-02/UI-23: ширину панели задаёт пользователь, потянув разделитель.
        # Жёсткий setFixedWidth запрещал это: сплиттер не мог изменить размер,
        # и длинные подписи («Документирование программных средств») уходили
        # за край без возможности что-либо сделать.
        self.setMinimumWidth(210)
        self.setMaximumWidth(560)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.db = db

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Перенос строк включён у всех подписей, поэтому горизонтальная
        # прокрутка не нужна даже на минимальной ширине.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(12)

        # UI-24: высоту списка заданий задаёт автоподбор (до четырёх строк,
        # дальше прокрутка), поэтому вертикальный сплиттер не нужен: тянуть
        # границу сверху было неудобно и не давало доступа к нижней.
        self.clock = ClockWidget()
        layout.addWidget(self.clock)
        layout.addWidget(Separator())

        self.trips = TripsTodayWidget(db)
        self.trips.confirm_requested.connect(self.confirm_requested)
        layout.addWidget(self.trips)

        self.strella = StrellaWidget(db)
        self.strella.recalculate_requested.connect(self.recalculate_requested)
        layout.addWidget(self.strella)

        self.homework = HomeworkWidget(db)
        self.homework.open_requested.connect(self.homework_requested)
        layout.addWidget(self.homework)

        layout.addStretch(1)
        scroll.setWidget(content)

    def refresh(self, value: date | None = None) -> None:
        self.clock.refresh()
        self.trips.refresh(value)
        self.strella.refresh()
        self.homework.refresh()


__all__ = ["WidgetsPanel", "ClockWidget", "TripsTodayWidget", "StrellaWidget",
           "HomeworkWidget"]
