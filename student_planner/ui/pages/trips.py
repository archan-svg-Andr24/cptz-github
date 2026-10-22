"""Страница «Поездки» (§27: TRIP-20, TRIP-13, TRIP-14, TRIP-15).

Три части: список шаблонов, подтверждение на дату, журнал поездок.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import clock
from ...core.dates import format_display
from ...core.errors import AppError
from ...core.models import Direction, PaymentMethod, TransportType
from ...core.transport_service import TransportService
from ...core.trip_service import TripPlanService
from ..dialogs import BaseDialog, ConfirmTripsDialog, ManualRideDialog
from ..theme import COLORS
from ..widgets import Badge, Card, EmptyState, MetricRow, SectionHeader, Separator


def _make_compact(combo: QComboBox) -> None:
    """Не дать длинной подписи распирать комбобокс (и всю раскладку).

    ``QComboBox`` по умолчанию просит ширину самой длинной строки: шаблон с
    четырьмя рейсами занимал 820 px и через ``minimumSizeHint`` страницы
    блокировал ``QSplitter`` — панель с календарём нельзя было расширить.
    """
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(12)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def _apply_combo_tooltip(combo: QComboBox) -> None:
    """Полное название шаблона — в подсказке, чтобы его не терять."""
    text = combo.currentText()
    combo.setToolTip(text if text and text != "— не выбрано —" else "")


class TemplatesTab(QWidget):
    """TRIP-13: список шаблонов — название, направление, рейсы, оплата, активность."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Название", "Направление", "Рейсы", "Оплата", "Активен"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Двойной клик по строке — самый ожидаемый способ начать правку.
        self.table.doubleClicked.connect(lambda _index: self.edit_template())
        layout.addWidget(self.table, 1)

        # Действия разбиты на две строки: в одну они требуют 1180 px и
        # распирают центральную область (UI-02).
        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self.add_button = QPushButton("Создать")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self.create_template)
        buttons.addWidget(self.add_button)

        self.edit_button = QPushButton("Изменить")
        self.edit_button.setToolTip("Изменить название, направление и рейсы шаблона")
        self.edit_button.clicked.connect(self.edit_template)
        buttons.addWidget(self.edit_button)

        buttons.addStretch(1)
        layout.addLayout(buttons)

        buttons2 = QHBoxLayout()
        buttons2.setSpacing(8)

        self.toggle_button = QPushButton("Включить / отключить")
        self.toggle_button.clicked.connect(self.toggle_active)
        buttons2.addWidget(self.toggle_button)

        self.delete_button = QPushButton("Удалить")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_template)
        buttons2.addWidget(self.delete_button)

        buttons2.addStretch(1)
        layout.addLayout(buttons2)

        restore_row = QHBoxLayout()
        restore_row.setSpacing(8)
        restore_row.addStretch(1)
        self.restore_button = QPushButton("Восстановить стартовый набор")
        self.restore_button.clicked.connect(self.restore_seed)
        restore_row.addWidget(self.restore_button)
        layout.addLayout(restore_row)

        self.empty = EmptyState(
            "Шаблонов нет",
            hint="Создайте шаблон или восстановите стартовый набор (TRIP-15).",
            action_text="Создать",
        )
        self.empty.action_clicked.connect(self.create_template)
        # Вес 1: пустое состояние занимает место скрытого списка и держит
        # содержимое по центру, а не прижимает его к низу.
        layout.addWidget(self.empty, 1)

        self.refresh()

    def refresh(self) -> None:
        templates = TripPlanService(self.db).templates.all()
        self.empty.setVisible(not templates)
        self.table.setVisible(bool(templates))
        self.table.setRowCount(len(templates))

        for row, template in enumerate(templates):
            self.table.setItem(row, 0, QTableWidgetItem(template.name))
            self.table.setItem(
                row, 1, QTableWidgetItem(Direction.label(template.direction))
            )
            legs = " → ".join(
                f"{TransportType.label(leg.mode)} {leg.vehicle}" for leg in template.legs
            )
            self.table.setItem(row, 2, QTableWidgetItem(legs))
            payments = {
                PaymentMethod.label(leg.payment_method) for leg in template.legs
            }
            self.table.setItem(row, 3, QTableWidgetItem(", ".join(sorted(payments))))
            self.table.setItem(
                row, 4, QTableWidgetItem("да" if template.is_active else "нет")
            )
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, template.id)

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def create_template(self) -> None:
        dialog = TemplateDialog(self.db, self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def edit_template(self) -> None:
        """RT-13: правка уже созданного шаблона."""
        template_id = self._selected_id()
        if template_id is None:
            self._message("Выберите шаблон для изменения.")
            return
        dialog = TemplateDialog(self.db, self, template_id=template_id)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def toggle_active(self) -> None:
        template_id = self._selected_id()
        if template_id is None:
            self._message("Выберите шаблон.")
            return
        service = TripPlanService(self.db)
        template = service.templates.require(template_id)
        try:
            service.templates.set_active(template_id, not template.is_active)
        except AppError as error:
            self._message(error.message)
            return
        self.changed.emit()
        self.refresh()

    def delete_template(self) -> None:
        template_id = self._selected_id()
        if template_id is None:
            self._message("Выберите шаблон.")
            return
        service = TripPlanService(self.db)
        used = service.templates.references(template_id) > 0
        text = (
            "Шаблон использовался в поездках. Удалить его?\n"
            "Поездки и их стоимость сохранятся (RT-14)."
            if used else "Удалить шаблон?"
        )
        answer = QMessageBox.question(
            self, "Удаление шаблона", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            service.templates.delete(template_id, confirm_used=True)
        except AppError as error:
            self._message(error.message)
            return
        self.changed.emit()
        self.refresh()

    def restore_seed(self) -> None:
        from ...core.seeding import Seeder

        Seeder(self.db).seed_missing()
        self.changed.emit()
        self.refresh()

    def _message(self, text: str) -> None:
        QMessageBox.information(self, "Поездки", text)


class TripLegRow(QWidget):
    """Один рейс шаблона: тип транспорта, номер, способ оплаты (RT-02, RT-03).

    Смешанный маршрут «Электричка + №22» — штатный случай (TRIP-01, RT-01,
    Прил. А.4), поэтому рейс задаётся отдельной строкой, а не одним типом на
    весь шаблон.
    """

    changed = Signal()

    def __init__(self, seq: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.seq_label = QLabel(str(seq))
        self.seq_label.setObjectName("Muted")
        self.seq_label.setFixedWidth(16)
        layout.addWidget(self.seq_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Автобус", TransportType.BUS)
        self.mode_combo.addItem("Электричка", TransportType.TRAIN)
        self.mode_combo.setMinimumWidth(120)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        self.vehicle_edit = QLineEdit()
        self.vehicle_edit.setPlaceholderText("номер или название")
        self.vehicle_edit.setMinimumWidth(120)
        self.vehicle_edit.textChanged.connect(self.changed)
        layout.addWidget(self.vehicle_edit, 1)

        self.payment_combo = QComboBox()
        self.payment_combo.setMinimumWidth(150)
        layout.addWidget(self.payment_combo)

        self.remove_button = QPushButton("✕")
        self.remove_button.setObjectName("Flat")
        self.remove_button.setFixedWidth(30)
        self.remove_button.setToolTip("Убрать рейс")
        layout.addWidget(self.remove_button)

        self._fill_payments()

    def set_seq(self, seq: int) -> None:
        self.seq_label.setText(str(seq))

    def set_values(
        self,
        *,
        mode: str,
        vehicle: str,
        payment_method: str,
    ) -> None:
        """Заполнить рейс готовыми значениями (режим правки шаблона)."""
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        # Режим мог смениться — список оплат перестроится, и способ оплаты
        # нужно выставить уже после этого.
        self._fill_payments()
        pay_index = self.payment_combo.findData(payment_method)
        if pay_index >= 0:
            self.payment_combo.setCurrentIndex(pay_index)
        self.vehicle_edit.setText(vehicle)

    def _fill_payments(self) -> None:
        """RT-17: электричка оплачивается только студенческим билетом."""
        is_train = self.mode_combo.currentData() == TransportType.TRAIN
        previous = self.payment_combo.currentData()
        self.payment_combo.clear()
        if is_train:
            self.payment_combo.addItem("Студенческий билет",
                                       PaymentMethod.TRAIN_STUDENT)
            self.payment_combo.setEnabled(False)
        else:
            self.payment_combo.addItem("Стрелка", PaymentMethod.STRELKA)
            self.payment_combo.addItem("Дебетовая карта", PaymentMethod.DEBIT_CARD)
            self.payment_combo.setEnabled(True)
            if previous in (PaymentMethod.STRELKA, PaymentMethod.DEBIT_CARD):
                index = self.payment_combo.findData(previous)
                if index >= 0:
                    self.payment_combo.setCurrentIndex(index)

    def _on_mode_changed(self) -> None:
        self._fill_payments()
        self.changed.emit()

    # ------------------------------------------------------------------ данные
    @property
    def mode(self) -> str:
        return self.mode_combo.currentData()

    @property
    def vehicle(self) -> str:
        return self.vehicle_edit.text().strip()

    @property
    def payment_method(self) -> str:
        return self.payment_combo.currentData()

    def as_dict(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "vehicle": self.vehicle,
            "payment_method": self.payment_method,
        }


class TemplateDialog(BaseDialog):
    """Создание и редактирование шаблона поездки (TRIP-01, TRIP-02, RT-01…RT-04).

    ``template_id`` переводит диалог в режим правки: поля заполняются текущими
    значениями шаблона, кнопка называется «Сохранить», а ``apply`` вызывает
    ``templates.update`` вместо ``create`` (RT-13).
    """

    MAX_LEGS = 4

    def __init__(
        self,
        db,
        parent: QWidget | None = None,
        *,
        template_id: int | None = None,
    ) -> None:
        self._template_id = template_id
        self._existing = (
            TripPlanService(db).templates.require(template_id)
            if template_id is not None
            else None
        )
        caption = (
            f"Шаблон поездки «{self._existing.name}»"
            if self._existing is not None
            else "Новый шаблон поездки"
        )
        super().__init__(parent, caption)
        self.db = db
        self._error_label = self.error_label()
        self._legs: list[TripLegRow] = []

        form = QFormLayout()
        form.setSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Например, Электричка + №22")
        form.addRow("Название:", self.name_edit)

        self.direction_combo = QComboBox()
        for value in Direction.ALL:
            self.direction_combo.addItem(Direction.label(value), value)
        form.addRow("Направление:", self.direction_combo)
        self.add_form(form)

        # ------------------------------------------------------------ рейсы
        legs_caption = QLabel("Рейсы маршрута:")
        legs_caption.setObjectName("Small")
        self.add_widget(legs_caption)

        self.legs_host = QWidget()
        self.legs_layout = QVBoxLayout(self.legs_host)
        self.legs_layout.setContentsMargins(0, 0, 0, 0)
        self.legs_layout.setSpacing(6)
        self.add_widget(self.legs_host)

        self.add_button = QPushButton("Добавить рейс")
        self.add_button.setObjectName("Flat")
        self.add_button.clicked.connect(self.add_leg)
        self.add_widget(self.add_button)

        hint = QLabel(
            "Рейсы выполняются по порядку: 1 — первый, 2 — пересадка. "
            "Справочные времена рейсов необязательны и на стоимость не влияют (RT-12)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.finish("Сохранить" if self._existing is not None else "Создать")

        # Заполняем поля: при правке — текущими значениями, при создании —
        # одним автобусным рейсом со «Стрелкой».
        if self._existing is not None:
            self._fill_from_template(self._existing)
        else:
            self.add_leg()

    # ---------------------------------------------------------------- заполнение
    def _fill_from_template(self, template) -> None:
        """RT-13: показать текущие значения шаблона для правки."""
        self.name_edit.setText(template.name)
        index = self.direction_combo.findData(template.direction)
        if index >= 0:
            self.direction_combo.setCurrentIndex(index)
        for leg in template.legs:
            row = self.add_leg()
            if row is None:
                break
            row.set_values(
                mode=leg.mode,
                vehicle=leg.vehicle,
                payment_method=leg.payment_method,
            )

    # ------------------------------------------------------------------ рейсы
    def add_leg(self) -> TripLegRow | None:
        """Добавить строку рейса (не больше ``MAX_LEGS``)."""
        if len(self._legs) >= self.MAX_LEGS:
            return None
        row = TripLegRow(len(self._legs) + 1)
        row.remove_button.clicked.connect(lambda: self.remove_leg(row))
        row.changed.connect(self._on_leg_changed)
        self._legs.append(row)
        self.legs_layout.addWidget(row)
        self._renumber()
        return row

    def remove_leg(self, row: TripLegRow) -> None:
        """Убрать рейс; последний рейс удалить нельзя (RT-16)."""
        if len(self._legs) <= 1 or row not in self._legs:
            return
        self._legs.remove(row)
        self.legs_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._renumber()

    def _renumber(self) -> None:
        for index, row in enumerate(self._legs, start=1):
            row.set_seq(index)
            # Удалять можно любой, кроме единственного.
            row.remove_button.setEnabled(len(self._legs) > 1)
        self.add_button.setEnabled(len(self._legs) < self.MAX_LEGS)

    def _on_leg_changed(self) -> None:
        self._error_label.clear()

    def legs(self) -> list[dict[str, str]]:
        return [row.as_dict() for row in self._legs]

    # ------------------------------------------------------------------ запись
    def apply(self) -> bool:
        name = self.name_edit.text().strip()
        if not name:
            raise AppError("Укажите название шаблона (TRIP-02).")
        legs = self.legs()
        for index, leg in enumerate(legs, start=1):
            if not leg["vehicle"]:
                raise AppError(f"Укажите номер или название рейса №{index} (RT-16).")

        service = TripPlanService(self.db)
        if self._template_id is not None:
            # RT-13: правка существующего шаблона. Способ оплаты по умолчанию
            # репозиторий выводит из новых рейсов сам (Б.13).
            service.templates.update(
                self._template_id,
                name=name,
                direction=self.direction_combo.currentData(),
                legs=legs,
            )
            return True
        service.templates.create(
            self.direction_combo.currentData(), name, legs,
        )
        return True


class ConfirmTab(QWidget):
    """TRIP-02/TRIP-08/TRIP-14: подтверждение на дату и «Проверить стоимость».

    Шаблоны направления выбираются прямо на вкладке: пользователь видит и
    меняет набор до подтверждения, а не только внутри диалога. Новый шаблон
    сразу появляется в списке (TRIP-03).
    """

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._date = clock.today()
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.date_label = QLabel()
        self.date_label.setObjectName("Subtitle")
        top.addWidget(self.date_label)
        top.addStretch(1)

        self.check_button = QPushButton("Проверить стоимость")
        self.check_button.clicked.connect(self.check_price)
        top.addWidget(self.check_button)

        self.confirm_button = QPushButton("Подтвердить поездки")
        self.confirm_button.setObjectName("Primary")
        self.confirm_button.clicked.connect(self.confirm_day)
        top.addWidget(self.confirm_button)
        layout.addLayout(top)

        # TRIP-02: выбор шаблона прямо на вкладке, до подтверждения.
        selectors = QHBoxLayout()
        selectors.setSpacing(8)

        outbound_box = QVBoxLayout()
        outbound_box.setSpacing(2)
        outbound_caption = QLabel("Туда")
        outbound_caption.setObjectName("Small")
        outbound_box.addWidget(outbound_caption)
        self.outbound_combo = QComboBox()
        # Длинные названия шаблонов распирали комбобокс до 820 px и через
        # раскладку блокировали сплиттер: панель с календарём нельзя было
        # расширить. Подсказка при наведении сохраняет полное имя.
        _make_compact(self.outbound_combo)
        self.outbound_combo.currentIndexChanged.connect(self._on_template_changed)
        outbound_box.addWidget(self.outbound_combo)
        selectors.addLayout(outbound_box, 1)

        return_box = QVBoxLayout()
        return_box.setSpacing(2)
        return_caption = QLabel("Обратно")
        return_caption.setObjectName("Small")
        return_box.addWidget(return_caption)
        self.return_combo = QComboBox()
        _make_compact(self.return_combo)
        self.return_combo.currentIndexChanged.connect(self._on_template_changed)
        return_box.addWidget(self.return_combo)
        selectors.addLayout(return_box, 1)

        layout.addLayout(selectors)

        self.card = Card("Расчёт")
        self.outbound_row = MetricRow("Туда")
        self.return_row = MetricRow("Обратно")
        self.counter_row = MetricRow("Влияние на счётчик")
        self.total_row = MetricRow("Стоимость", strong=True)
        self.balance_row = MetricRow("Остаток после")
        for row in (self.outbound_row, self.return_row, self.counter_row):
            self.card.add_widget(row)
        self.card.add_widget(Separator())
        self.card.add_widget(self.total_row)
        self.card.add_widget(self.balance_row)
        self.state_badge = Badge("не подтверждено")
        self.card.add_action(self.state_badge)
        layout.addWidget(self.card)

        self.rides_card = Card("Поездки дня")
        self.rides_layout = QVBoxLayout()
        self.rides_layout.setSpacing(2)
        self.rides_card.add_layout(self.rides_layout)
        layout.addWidget(self.rides_card)

        self.empty = EmptyState(
            "Поездок за период нет",
            action_text="Добавить поездку",
        )
        self.empty.action_clicked.connect(self.add_manual_ride)
        # Вес 1: пустое состояние занимает место скрытого списка и держит
        # содержимое по центру, а не прижимает его к низу.
        layout.addWidget(self.empty, 1)

        layout.addStretch(1)
        self.refresh()

    def set_date(self, value: date) -> None:
        self._date = value
        self.refresh()

    def _fill_combo(self, combo: QComboBox, direction: str, selected_id) -> None:
        """Заполнить список шаблонами направления (TRIP-03)."""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— не выбрано —", None)
        for template in TripPlanService(self.db).available_templates(direction):
            legs = " → ".join(
                f"{TransportType.label(leg.mode)} {leg.vehicle}"
                for leg in template.legs
            )
            combo.addItem(f"{template.name} ({legs})", template.id)
        if selected_id is not None:
            index = combo.findData(selected_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        _apply_combo_tooltip(combo)
        combo.blockSignals(False)

    def _on_template_changed(self) -> None:
        """Пересчитать карточку при смене шаблона (TRIP-14)."""
        if self._updating:
            return
        for combo in (self.outbound_combo, self.return_combo):
            _apply_combo_tooltip(combo)
        self._update_card()

    def refresh(self) -> None:
        service = TripPlanService(self.db)
        plan = service.plan(self._date)
        self.date_label.setText(f"Дата: {format_display(self._date)}")

        self._updating = True
        self._fill_combo(
            self.outbound_combo, Direction.HOME_TO_COLLEGE,
            plan.outbound.id if plan.outbound else None,
        )
        self._fill_combo(
            self.return_combo, Direction.COLLEGE_TO_HOME,
            plan.return_trip.id if plan.return_trip else None,
        )
        self._updating = False

        self._update_card()

    def _update_card(self) -> None:
        """Карточка «Расчёт» по выбранным шаблонам (TRIP-14)."""
        service = TripPlanService(self.db)
        plan = service.plan(
            self._date,
            outbound_template_id=self.outbound_combo.currentData(),
            return_template_id=self.return_combo.currentData(),
        )

        self.outbound_row.set_value(plan.outbound.name if plan.outbound else "не выбрано")
        self.return_row.set_value(
            plan.return_trip.name if plan.return_trip else "не выбрано"
        )
        self.counter_row.set_value(f"{plan.legs_count} поездок")

        if plan.is_confirmed:
            self.state_badge.setText("подтверждено")
            self.state_badge.set_kind("success")
        else:
            self.state_badge.setText("не подтверждено")
            self.state_badge.set_kind("neutral")

        rides = service.rides.for_date(self._date)
        while self.rides_layout.count():
            item = self.rides_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if rides:
            total = sum((ride.paid_price for ride in rides), Decimal("0.00"))
            for ride in rides:
                line = QLabel(
                    f"{ride.vehicle} · {TransportType.label(ride.transport_type)} · "
                    f"{PaymentMethod.label(ride.payment_method)} · {ride.paid_price} ₽"
                    + ("  (вручную)" if ride.is_manual else "")
                )
                line.setObjectName("Small")
                self.rides_layout.addWidget(line)
            self.total_row.set_value(f"{total} ₽")
            self.balance_row.set_value(
                f"{TransportService(self.db).strella_state().balance} ₽"
            )
            self.rides_card.setVisible(True)
            self.empty.setVisible(False)
        else:
            self.total_row.set_value("—")
            self.balance_row.set_value("—")
            self.rides_card.setVisible(False)
            self.empty.setVisible(True)

    def confirm_day(self) -> None:
        """TRIP-08: подтвердить день с выбранными на вкладке шаблонами."""
        dialog = ConfirmTripsDialog(
            self.db, self._date, self,
            outbound_template_id=self.outbound_combo.currentData(),
            return_template_id=self.return_combo.currentData(),
        )
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def check_price(self) -> None:
        """TRIP-14: расчёт по рейсам с ALG-09 и ALG-02."""
        service = TripPlanService(self.db)
        plan = service.plan(self._date)
        state = TransportService(self.db).strella_state()
        lines = [
            f"Шаблонов выбрано: {plan.legs_count}",
            f"Следующая поездка «Стрелки»: №{state.next_ride_number} "
            f"по {state.next_ride_price} ₽",
            f"Остаток до: {state.balance_caption}",
        ]
        QMessageBox.information(self, "Проверить стоимость", "\n".join(lines))

    def add_manual_ride(self) -> None:
        dialog = ManualRideDialog(self.db, self._date, self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()


class JournalTab(QWidget):
    """REP-10/TRIP-20: журнал поездок с фильтрами и ручной поездкой."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._date = clock.today()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(8)

        self.period_combo = QComboBox()
        self.period_combo.addItem("Месяц", "month")
        self.period_combo.addItem("Неделя", "week")
        self.period_combo.addItem("День", "day")
        self.period_combo.addItem("Все", "all")
        self.period_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.period_combo)

        self.payment_combo = QComboBox()
        self.payment_combo.addItem("Любая оплата", None)
        for value in PaymentMethod.ALL:
            self.payment_combo.addItem(PaymentMethod.label(value), value)
        self.payment_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.payment_combo)

        self.transport_combo = QComboBox()
        self.transport_combo.addItem("Любой транспорт", None)
        for value in TransportType.ALL:
            self.transport_combo.addItem(TransportType.label(value), value)
        self.transport_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.transport_combo)

        filters.addStretch(1)

        self.add_button = QPushButton("Добавить поездку…")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self.add_manual_ride)
        filters.addWidget(self.add_button)

        self.delete_button = QPushButton("Удалить")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_ride)
        filters.addWidget(self.delete_button)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Дата", "Направление", "Транспорт", "Оплата", "Оплачено", "Период", ""]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Поездок за период нет",
            action_text="Добавить поездку",
        )
        self.empty.action_clicked.connect(self.add_manual_ride)
        # Вес 1: пустое состояние занимает место скрытого списка и держит
        # содержимое по центру, а не прижимает его к низу.
        layout.addWidget(self.empty, 1)

    def set_date(self, value: date) -> None:
        self._date = value
        self.refresh()

    def refresh(self) -> None:
        from ...core.transport_service import JournalFilter

        service = TransportService(self.db)
        mode = self.period_combo.currentData()
        criteria = JournalFilter()
        if mode == "day":
            criteria = JournalFilter.for_day(self._date)
        elif mode == "week":
            criteria = JournalFilter.for_week(self._date)
        elif mode == "month":
            criteria = JournalFilter.for_month(self._date)
        criteria = JournalFilter(
            date_from=criteria.date_from,
            date_to=criteria.date_to,
            transport_type=self.transport_combo.currentData(),
            payment_method=self.payment_combo.currentData(),
        )

        rows = service.journal(criteria)
        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)
        self.table.setRowCount(len(rows))

        for index, row in enumerate(rows):
            self.table.setItem(index, 0, QTableWidgetItem(row.ride_date_caption))
            self.table.setItem(index, 1, QTableWidgetItem(row.direction_caption))
            self.table.setItem(
                index, 2, QTableWidgetItem(f"{row.transport_caption} {row.vehicle}")
            )
            self.table.setItem(index, 3, QTableWidgetItem(row.payment_caption))
            self.table.setItem(index, 4, QTableWidgetItem(f"{row.paid_price} ₽"))
            self.table.setItem(index, 5, QTableWidgetItem(row.period_caption))
            self.table.setItem(index, 6, QTableWidgetItem(row.manual_caption))
            self.table.item(index, 0).setData(Qt.ItemDataRole.UserRole, row.ride_id)

    def add_manual_ride(self) -> None:
        dialog = ManualRideDialog(self.db, self._date, self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def delete_ride(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Журнал", "Выберите поездку.")
            return
        item = self.table.item(row, 0)
        ride_id = item.data(Qt.ItemDataRole.UserRole)
        if not self._confirm("Удалить поездку? Счётчик будет пересчитан (CALC-04)."):
            return
        try:
            TransportService(self.db).delete_ride(ride_id)
        except AppError as error:
            QMessageBox.warning(self, "Ошибка", error.message)
            return
        self.changed.emit()
        self.refresh()

    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.question(
            self, "Подтверждение", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


class TripsPage(QWidget):
    """TRIP-20: шаблоны, подтверждение на дату, журнал."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._date = clock.today()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = SectionHeader("Поездки")
        layout.addWidget(header)

        self.tabs = QTabWidget()
        self.templates_tab = TemplatesTab(db)
        self.confirm_tab = ConfirmTab(db)
        self.journal_tab = JournalTab(db)
        for tab in (self.templates_tab, self.confirm_tab, self.journal_tab):
            tab.changed.connect(self._on_changed)
        self.tabs.addTab(self.templates_tab, "Шаблоны")
        self.tabs.addTab(self.confirm_tab, "Подтверждение дня")
        self.tabs.addTab(self.journal_tab, "Журнал поездок")
        layout.addWidget(self.tabs, 1)

    def set_date(self, value: date) -> None:
        self._date = value
        self.confirm_tab.set_date(value)
        self.journal_tab.set_date(value)

    def refresh(self) -> None:
        self.templates_tab.refresh()
        self.confirm_tab.refresh()
        self.journal_tab.refresh()

    def _on_changed(self) -> None:
        self.changed.emit()


__all__ = ["TripsPage"]
