"""Правая панель виджетов (§23: UI-07, UI-08, UI-09, UI-10).

Состав сверху вниз: текущее время, «Поездки на сегодня» с кнопкой
подтверждения, «Стрелка» (период, следующая поездка с ценой, остаток),
«Домашние задания» и «Экзамены».

Панель рассчитана на ширину 200–480 px: все подписи переносятся, а карточки
не тянут минимальную ширину по самой длинной строке (иначе контент требовал
462 px и обрезался на узкой панели).
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import clock
from ..core.subject_names import SubjectNameService
from ..core.dates import MONTH_NAMES_NOMINATIVE, WEEKDAY_NAMES, format_display
from ..core.schedule_service import HomeworkService
from ..core.transport_service import TransportService
from ..core.trip_service import TripPlanService
from .widgets import Badge, Card, MetricRow, Separator


class ClockWidget(QWidget):
    """UI-07: текущие дата и время.

    Дата возвращена: пользователь привык видеть её именно здесь, над списком
    карточек, вместе с часами. Подпись сжимается и переносится
    (``QSizePolicy.Ignored``), поэтому она больше не задаёт минимальную ширину
    панели — раньше из-за неё контент требовал 338 px и обрезался.
    """

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
        self.date_label.setWordWrap(True)
        self.date_label.setMinimumWidth(0)
        self.date_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.date_label.setToolTip("Сегодняшняя дата")
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

    def stop(self) -> None:
        """Остановить тиканье (вызывается при закрытии окна)."""
        self._timer.stop()


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
        # Кнопка должна сжиматься вместе с панелью: её обычная минимальная
        # ширина 277 px не влезала в 210 px и растягивала весь контент.
        self.confirm_button.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.confirm_button.setMinimumWidth(0)
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
        # UI-08: заголовок следует за выбранной датой. Раньше он всегда
        # назывался «на сегодня», даже когда календарь показывал 9 декабря, и
        # пользователь подтверждал поездки, думая, что это текущий день.
        if self._date == clock.today():
            self.set_title("Поездки на сегодня")
        else:
            self.set_title(f"Поездки на {format_display(self._date)}")
        service = TripPlanService(self.db)
        plan = service.plan(self._date)
        self.outbound_row.set_value(plan.outbound.name if plan.outbound else "не выбрано")
        self.return_row.set_value(
            plan.return_trip.name if plan.return_trip else "не выбрано"
        )

        if plan.is_confirmed:
            self.state_badge.setText("подтверждено")
            self.state_badge.set_kind("success")
            self.confirm_button.setText("Изменить")
            self.confirm_button.setToolTip("Изменить подтверждение поездок на этот день")
        else:
            self.state_badge.setText("не выбрано")
            self.state_badge.set_kind("neutral")
            # Короткая подпись: «Подтвердить поездки» требовала 277 px и не
            # влезала в панель шириной 200 px, растягивая весь контент.
            self.confirm_button.setText("Подтвердить")
            self.confirm_button.setToolTip("Подтвердить поездки на этот день")

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
                # Короткая подпись вместо «— после подтверждения»: длинный
                # текст задавал минимальную ширину 221 px и не давал панели
                # сжаться до 200 px. Пояснение — в подсказке.
                self.total_row.set_value("—")
                self.total_row.setToolTip("Стоимость станет известна после подтверждения")


class StrellaWidget(Card):
    """UI-09: период, следующая поездка с ценой и остаток.

    Карточка показывает только состояние счётчика. Действие «Пересчитать
    счётчик…» из неё убрано: это операция над данными, и её место — на
    странице «Расходы на транспорт», рядом с журналом и пополнениями.
    """

    recalculate_requested = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__("Стрелка", parent=parent)
        self.db = db

        self.period_row = MetricRow("Период", wrap_value=True)
        self.next_row = MetricRow("Поездка", wrap_value=True)
        self.balance_row = MetricRow("Остаток", strong=True, wrap_value=True)
        self.add_widget(self.period_row)
        self.add_widget(self.next_row)
        self.add_widget(Separator())
        self.add_widget(self.balance_row)

        self.warning_label = QLabel()
        self.warning_label.setObjectName("WarningBanner")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        self.add_widget(self.warning_label)

        self.note_label = QLabel()
        self.note_label.setObjectName("Small")
        self.note_label.setWordWrap(True)
        self.note_label.setVisible(False)
        self.add_widget(self.note_label)

    @property
    def recalculate_button(self) -> QWidget:
        """Совместимость: раньше это была кнопка в теле карточки.

        Сейчас пересчёт живёт на странице «Расходы», а карточка его не
        показывает — свойство осталось, чтобы не ломать внешний код.
        """
        return self

    def refresh(self) -> None:
        state = TransportService(self.db).strella_state()
        self.period_row.set_value(state.bounds_caption)
        # Номер и цена — одной строкой: две строки на одну поездку дорого.
        if state.next_ride_number is None:
            self.next_row.set_value("поездок ещё не было")
        else:
            self.next_row.set_value(
                f"№{state.next_ride_number} · {state.next_ride_price} ₽"
            )
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

    #: UI-14: предел длины подписи предмета в узкой панели (символов).
    SUBJECT_CAPTION_LIMIT = 50

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__("Домашние задания", parent=parent)
        self.db = db
        #: UI-14: сервис сокращённых названий; пересоздаётся в ``refresh``.
        self._names = SubjectNameService(db)

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
        self.open_button.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.open_button.setMinimumWidth(0)
        self.open_button.clicked.connect(self.open_requested)
        self.add_widget(self.open_button)

        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)

    def _visible_rows(self) -> list[QWidget]:
        """Строки, которые нужно показать в списке.

        Считаем по раскладке, а **не по** ``isVisibleTo``: сразу после
        ``refresh()`` последняя добавленная строка ещё не успевает стать
        «видимой» для Qt, и высота списка ошибочно рассчитывалась по трём
        строкам вместо четырёх — карточка «прыгала» при добавлении задания
        (UI-24). Скрытые строки всё равно удаляются в ``refresh()``, поэтому
        раскладка содержит ровно актуальные.
        """
        rows: list[QWidget] = []
        for index in range(self.rows_layout.count()):
            widget = self.rows_layout.itemAt(index).widget()
            if widget is not None and not widget.isHidden():
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

        Ширина считается **всегда с запасом на полосу прокрутки**, даже когда
        строк четыре и прокрутки ещё нет. Иначе высота зависела от числа
        заданий: при пятом задании полоса появлялась, строки становились уже,
        текст переносился на лишнюю строку — и карточка вырастала, хотя по
        правилу UI-24 она обязана остаться прежней.

        Запас применяется при **любом** числе строк, поэтому высота одинакова
        для четырёх и для шести заданий: она зависит только от ширины панели,
        а не от наличия полосы прокрутки.
        """
        width = self.rows_scroll.viewport().width()
        if width <= 0:
            width = self.rows_scroll.width() - 2 * self.rows_scroll.frameWidth()
        bar = self.rows_scroll.verticalScrollBar().sizeHint().width()
        if bar > 0 and width > bar:
            width -= bar
        heights = self._row_heights(width)
        if not heights:
            return 0
        return self._span_height(heights[: self.MAX_VISIBLE_ROWS])

    def refresh(self) -> None:
        # UI-14: настройки сокращений перечитываются на каждое обновление.
        self._names = SubjectNameService(self.db)
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
        # когда геометрия уже настоящая. Два прохода: после первого меняется
        # ширина (появляется или исчезает полоса прокрутки), и пересчёт по
        # новой ширине даёт окончательную высоту.
        QTimer.singleShot(0, self._fit_list_height)
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

    def _short(self, name: str) -> str:
        """UI-14: подпись предмета по настройкам, с пределом длины для панели."""
        return self._names.smart(name, limit=self.SUBJECT_CAPTION_LIMIT)

    def _row(self, row) -> QWidget:
        line = QWidget()
        layout = QVBoxLayout(line)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)

        # UI-14: подпись по настройкам сокращённых названий. Панель узкая
        # (от 220 px), поэтому здесь действует предел длины: полное название
        # занимало четыре строки и выдавливало остальные карточки.
        caption = QLabel(self._short(row.subject_name))
        caption.setObjectName("Subtitle")
        # Название предмета бывает длинным («Документирование программных
        # средств»), а панель узкой: без переноса текст уходил за край.
        caption.setWordWrap(True)
        if caption.text() != row.subject_name:
            caption.setToolTip(row.subject_name)
        layout.addWidget(caption)

        detail = QLabel(row.short_description or "без описания")
        detail.setObjectName("Small")
        detail.setToolTip(row.description)
        detail.setWordWrap(True)
        layout.addWidget(detail)

        due = QLabel(f"до {row.due_caption}")
        due.setObjectName("AccentText")
        layout.addWidget(due)
        return line


class ExamWidget(Card):
    """EXAM-07: ближайшие испытания сессии с обратным отсчётом."""

    open_requested = Signal()

    #: Сколько испытаний видно без прокрутки. Четвёртое и далее — под
    #: прокруткой (по аналогии с ``HomeworkWidget.MAX_VISIBLE_ROWS``).
    MAX_VISIBLE_ROWS: int = 3

    #: Прежнее имя константы; оставлено для совместимости.
    MAX_ROWS: int = MAX_VISIBLE_ROWS

    #: UI-14: предел длины подписи предмета в узкой панели (символов).
    SUBJECT_CAPTION_LIMIT = 50

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__("Экзамены", parent=parent)
        self.db = db
        #: UI-14: сервис сокращённых названий; пересоздаётся в ``refresh``.
        self._names = SubjectNameService(db)

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
        # Высоту списка считает _fit_list_height по числу строк, поэтому
        # политика Expanding: карточка берёт ровно столько, сколько нужно.
        self.rows_scroll.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.rows_scroll.setWidget(self.rows_host)
        self.rows_scroll.setVisible(False)
        self.add_widget(self.rows_scroll)

        self.empty_label = QLabel("Испытаний нет")
        self.empty_label.setObjectName("Empty")
        self.empty_label.setWordWrap(True)
        self.empty_label.setMinimumWidth(0)
        self.empty_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.empty_label.setVisible(False)
        self.add_widget(self.empty_label)

        self.open_button = QPushButton("Все экзамены")
        self.open_button.setObjectName("Flat")
        # Политика Minimum не давала кнопке сжиматься, и она задавала
        # минимальную ширину всей панели (168 px у «Все экзамены»).
        self.open_button.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.open_button.setMinimumWidth(0)
        self.open_button.clicked.connect(self.open_requested)
        self.add_widget(self.open_button)

    def _visible_rows(self) -> list[QWidget]:
        """Строки, которые нужно показать в списке.

        Считаем по раскладке, а не по ``isVisibleTo``: сразу после
        ``refresh()`` последняя добавленная строка ещё не успевает стать
        «видимой» для Qt, и высота списка ошибочно рассчитывалась по двум
        строкам вместо трёх.
        """
        rows: list[QWidget] = []
        for index in range(self.rows_layout.count()):
            widget = self.rows_layout.itemAt(index).widget()
            if widget is not None and not widget.isHidden():
                rows.append(widget)
        return rows

    def _row_heights(self, width: int) -> list[int]:
        """Высоты строк при заданной ширине.

        ``sizeHint`` строки не учитывает перенос длинного названия предмета
        по ширине панели, поэтому считаем ``heightForWidth``.
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
        """Высота, при которой видно не больше MAX_VISIBLE_ROWS испытаний.

        Больше трёх строк не показываем даже при длинном списке: остальные
        уходят под прокрутку, и карточка не выдавливает верхние виджеты
        панели. Ширина считается всегда с запасом на полосу прокрутки, чтобы
        при четвёртом экзамене карточка не меняла высоту из-за переноса
        названий на лишнюю строку.
        """
        width = self.rows_scroll.viewport().width()
        if width <= 0:
            width = self.rows_scroll.width() - 2 * self.rows_scroll.frameWidth()
        bar = self.rows_scroll.verticalScrollBar().sizeHint().width()
        if bar > 0 and width > bar:
            width -= bar
        heights = self._row_heights(width)
        if not heights:
            return 0
        return self._span_height(heights[: self.MAX_VISIBLE_ROWS])

    def _fit_list_height(self) -> None:
        """Подогнать высоту области под видимые испытания.

        ``QScrollArea`` не выводит ``sizeHint`` из содержимого, поэтому
        высоту считаем явно после раскладки: иначе список оставался высотой
        в одну строку и добавленные экзамены обрезались.
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

    def refresh(self) -> None:
        from ..core.exam_service import ExamService

        # UI-14: настройки сокращений перечитываются на каждое обновление.
        self._names = SubjectNameService(self.db)
        while self.rows_layout.count() > 1:  # последний — stretch
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater() отложен: без hide()+setParent(None) старая
                # строка остаётся видимой до конца цикла событий.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        try:
            # limit не задаём: список может быть длиннее трёх, лишнее
            # прокручивается. Высоту карточки ограничивает MAX_VISIBLE_ROWS.
            rows = ExamService(self.db).upcoming()
        except Exception:  # pragma: no cover - защита панели
            rows = []

        self.empty_label.setVisible(not rows)
        self.rows_scroll.setVisible(bool(rows))
        if not rows:
            self._fit_list_height()
            return

        for row in rows:
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, self._make_row(row))
        self._fit_list_height()
        # Первый расчёт идёт до раскладки: у скрытой области ещё нет ширины,
        # поэтому heightForWidth строк врёт. Повторяем в конце цикла событий.
        QTimer.singleShot(0, self._fit_list_height)
        QTimer.singleShot(0, self._fit_list_height)
        self.open_button.setVisible(True)

    def _make_row(self, row) -> QWidget:
        """Строка карточки: предмет, вид и отсчёт."""
        host = QWidget()
        host.setMinimumWidth(0)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(1)

        title = QLabel(self._names.smart(row.subject_name, limit=self.SUBJECT_CAPTION_LIMIT))
        title.setObjectName("WidgetItem")
        title.setWordWrap(True)
        # Ширину не диктуем: длинное название предмета иначе задавало
        # минимальную ширину всей панели.
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.setMinimumWidth(0)
        title.setToolTip(row.subject_name)
        layout.addWidget(title)

        # Отсчёт: до трёх дней — предупреждающим цветом, иначе обычным.
        details = QLabel(f"{row.exam.kind_short} · {row.countdown}")
        details.setObjectName("WarningText" if row.days_left <= 3 else "Muted")
        details.setWordWrap(True)
        details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        details.setMinimumWidth(0)
        layout.addWidget(details)
        return host


class WidgetsPanel(QFrame):
    """§23: правая панель виджетов."""

    confirm_requested = Signal(object)
    recalculate_requested = Signal()
    homework_requested = Signal()
    exams_requested = Signal()
    #: UI-25: панель просит окно свернуть её (кнопка в шапке).
    collapse_requested = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WidgetsPanel")
        # UI-02/UI-23: ширину панели задаёт пользователь, потянув разделитель.
        # Жёсткий setFixedWidth запрещал это: сплиттер не мог изменить размер,
        # и длинные подписи уходили за край без возможности что-либо сделать.
        #
        # Нижняя граница 220 px: контент (карточка с отступами 12+12 и самая
        # широкая кнопка) требует 215 px, поэтому при 200 px появлялась
        # горизонтальная обрезка. Верхняя граница 480 px — выше контент уже
        # не используется, оставалась пустая полоса.
        self.setMinimumWidth(220)
        self.setMaximumWidth(480)
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
        layout.setSpacing(10)

        # UI-24: высоту списка заданий задаёт автоподбор (до четырёх строк,
        # дальше прокрутка), поэтому вертикальный сплиттер не нужен: тянуть
        # границу сверху было неудобно и не давало доступа к нижней.
        #
        # UI-25: шапка — время слева, кнопка сворачивания справа. Кнопка
        # стоит «сбоку» от часов, а не отдельной строкой над ними, поэтому
        # не отнимает вертикального места у карточек.
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.clock = ClockWidget()
        head.addWidget(self.clock, 1)
        self.collapse_button = QToolButton()
        self.collapse_button.setText("»")
        self.collapse_button.setObjectName("CardMenu")
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Размер не меньше minimumSizeHint: у «CardMenu» из темы отступы
        # 6 px по горизонтали и 4 px по вертикали, поэтому минимум — 25x26.
        # При setFixedSize(22, 22) кнопка была меньше минимума, и Qt рисовала
        # её содержимое в обрез. 26 px держит квадрат и оставляет поле.
        self.collapse_button.setFixedSize(26, 26)
        self.collapse_button.setToolTip("Свернуть правую панель (Ctrl+Shift+W)")
        self.collapse_button.clicked.connect(self.collapse_requested)
        head.addWidget(self.collapse_button, 0)
        layout.addLayout(head)

        layout.addWidget(Separator())

        # Порядок как в прежней версии: сначала действия на день («Поездки»),
        # затем состояние счётчика («Стрелка»). Пользователь привык к нему, и
        # подтверждение поездок — более частое действие, чем просмотр остатка.
        self.trips = TripsTodayWidget(db)
        self.trips.confirm_requested.connect(self.confirm_requested)
        layout.addWidget(self.trips)

        self.strella = StrellaWidget(db)
        self.strella.recalculate_requested.connect(self.recalculate_requested)
        layout.addWidget(self.strella)

        self.homework = HomeworkWidget(db)
        self.homework.open_requested.connect(self.homework_requested)
        layout.addWidget(self.homework)

        self.exams = ExamWidget(db)
        self.exams.open_requested.connect(self.exams_requested)
        layout.addWidget(self.exams)

        layout.addStretch(1)
        scroll.setWidget(content)

    def refresh(self, value: date | None = None) -> None:
        self.clock.refresh()
        self.trips.refresh(value)
        self.strella.refresh()
        self.homework.refresh()
        self.exams.refresh()

    def set_collapsed_hint(self, collapsed: bool) -> None:
        """UI-25: показать на кнопке в шапке, что она сделает."""
        self.collapse_button.setText("⟨" if collapsed else "⟩")
        self.collapse_button.setToolTip(
            "Развернуть правую панель (Ctrl+Shift+W)" if collapsed
            else "Свернуть правую панель (Ctrl+Shift+W)"
        )

    def stop_timers(self) -> None:
        """Остановить таймеры панели при закрытии окна."""
        self.clock.stop()


__all__ = ["WidgetsPanel", "ClockWidget", "TripsTodayWidget", "StrellaWidget",
           "HomeworkWidget", "ExamWidget"]
