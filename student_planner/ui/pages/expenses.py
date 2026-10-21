"""Страница «Расходы на транспорт» (§28: REP-10, REP-11).

Журнал поездок с фильтрами, отчёты по периодам, состояние «Стрелки» и остаток,
журнал пополнений.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from ...core.models import PaymentMethod, TransportType
from ...core.transport_service import (
    JournalFilter,
    TariffService,
    TransportService,
    WalletService,
)
from ..dialogs import ManualRideDialog, TopUpDialog
from ..theme import COLORS
from ..widgets import Card, EmptyState, MetricRow, SectionHeader, Separator


class ReportTab(QWidget):
    """REP-03/REP-04/REP-09: показатели за период."""

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._date = clock.today()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        # Строку фильтров держит отдельный виджет с политикой Maximum. Без него
        # вложенный layout забирал вес, оставшийся от скрытого EmptyState, и
        # раздувался до 344 px вместо 28 — между фильтром периода и первой
        # карточкой появлялся отступ в треть экрана.
        top_host = QWidget()
        top_host.setSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Maximum)
        top = QHBoxLayout(top_host)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.period_combo = QComboBox()
        self.period_combo.addItem("Месяц", "month")
        self.period_combo.addItem("Неделя", "week")
        self.period_combo.addItem("День", "day")
        self.period_combo.addItem("Все время", "all")
        self.period_combo.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.period_combo)
        self.period_label = QLabel()
        self.period_label.setObjectName("Muted")
        top.addWidget(self.period_label)
        top.addStretch(1)
        layout.addWidget(top_host)

        # ------------------------------------------------------- «потрачено»
        spent_card = Card("Потрачено", accent=True)
        self.spent_row = MetricRow("Всего", strong=True)
        self.train_row = MetricRow("Электричка")
        self.bus_row = MetricRow("Автобусы")
        self.strelka_row = MetricRow("По «Стрелке»")
        self.card_row = MetricRow("Дебетовой картой")
        self.savings_row = MetricRow("Экономия")
        self.count_row = MetricRow("Поездок")
        for row in (self.spent_row, self.train_row, self.bus_row, self.strelka_row,
                    self.card_row):
            spent_card.add_widget(row)
        spent_card.add_widget(Separator())
        for row in (self.savings_row, self.count_row):
            spent_card.add_widget(row)
        layout.addWidget(spent_card)

        # -------------------------------------------------------- кошелёк
        wallet_card = Card("Кошелёк «Стрелки»")
        self.topups_row = MetricRow("Пополнено")
        self.fees_row = MetricRow("Комиссии")
        self.balance_row = MetricRow("Остаток на конец периода", strong=True)
        for row in (self.topups_row, self.fees_row):
            wallet_card.add_widget(row)
        wallet_card.add_widget(Separator())
        wallet_card.add_widget(self.balance_row)
        note = QLabel(
            "Пополнение не является расходом: величины в блоках не суммируются "
            "(WAL-04)."
        )
        note.setObjectName("Small")
        note.setWordWrap(True)
        wallet_card.add_widget(note)
        layout.addWidget(wallet_card)

        # ------------------------------------------------------- структура
        self.structure_card = Card("Структура расходов")
        self.structure_layout = QVBoxLayout()
        self.structure_layout.setSpacing(2)
        self.structure_card.add_layout(self.structure_layout)
        layout.addWidget(self.structure_card)

        self.empty = EmptyState("Поездок за период нет")
        # Вес распределяется явно в refresh(). Скрытый EmptyState с весом 1
        # раздавал освободившееся место видимым карточкам, и зазор между ними
        # вырастал с 10 до 73 px — «слишком большие отступы между элементами».
        layout.addWidget(self.empty, 1)
        self._empty_stretch_index = layout.count() - 1
        self._tail_spacer_index = layout.count()
        layout.addStretch(1)

    def set_date(self, value: date) -> None:
        self._date = value
        self.refresh()

    def refresh(self) -> None:
        service = TransportService(self.db)
        mode = self.period_combo.currentData()
        if mode == "day":
            criteria = JournalFilter.for_day(self._date)
        elif mode == "week":
            criteria = JournalFilter.for_week(self._date)
        elif mode == "month":
            criteria = JournalFilter.for_month(self._date)
        else:
            criteria = JournalFilter()

        totals = service.report(criteria)
        self.period_label.setText(totals.period_caption)
        self.spent_row.set_value(f"{totals.spent} ₽")
        self.train_row.set_value(f"{totals.spent_train} ₽")
        self.bus_row.set_value(f"{totals.spent_bus} ₽")
        self.strelka_row.set_value(f"{totals.spent_strelka} ₽")
        self.card_row.set_value(f"{totals.spent_debit_card} ₽")
        self.savings_row.set_value(f"{totals.savings} ₽")
        self.savings_row.set_kind("success")
        self.count_row.set_value(
            f"{totals.rides_total} "
            f"(«Стрелка» {totals.rides_strelka}, карта {totals.rides_debit_card})"
        )

        self.topups_row.set_value(f"{totals.topups} ₽")
        self.fees_row.set_value(f"{totals.fees} ₽")
        wallet = WalletService(self.db)
        self.balance_row.set_value(
            f"{totals.balance_end} ₽" if wallet.started else "Остаток не задан"
        )
        if totals.balance_end < 0:
            self.balance_row.set_kind("error")

        while self.structure_layout.count():
            item = self.structure_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        structure = totals.structure()
        for label, amount, percent in structure:
            row = MetricRow(label)
            row.set_value(f"{amount} ₽ · {percent:.0f} %")
            self.structure_layout.addWidget(row)
        self.structure_card.setVisible(bool(structure))
        has_rides = totals.has_rides
        # Вес переключается вместе с видимостью: пустое состояние тянется,
        # когда оно одно, и не тянется, когда выше есть карточки. Иначе
        # освободившееся место раздавалось карточкам, и зазор между ними
        # вырастал с 10 до 73 px.
        layout = self.layout()
        layout.setStretch(self._empty_stretch_index, 0 if has_rides else 1)
        layout.setStretch(self._tail_spacer_index, 1 if has_rides else 0)
        self.empty.setVisible(not has_rides)


class JournalTab(QWidget):
    """REP-10: журнал поездок с фильтрами."""

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
        self.add_button.clicked.connect(self.add_ride)
        filters.addWidget(self.add_button)

        self.delete_button = QPushButton("Удалить")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_ride)
        filters.addWidget(self.delete_button)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Дата", "Направление", "Транспорт", "Оплата", "Оплачено",
             "Экономия", "Период"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Поездок за период нет", action_text="Добавить поездку"
        )
        self.empty.action_clicked.connect(self.add_ride)
        # Вес 1: пустое состояние занимает место скрытого списка и держит
        # содержимое по центру, а не прижимает его к низу.
        layout.addWidget(self.empty, 1)

    def set_date(self, value: date) -> None:
        self._date = value
        self.refresh()

    def _criteria(self) -> JournalFilter:
        mode = self.period_combo.currentData()
        if mode == "day":
            base = JournalFilter.for_day(self._date)
        elif mode == "week":
            base = JournalFilter.for_week(self._date)
        elif mode == "month":
            base = JournalFilter.for_month(self._date)
        else:
            base = JournalFilter()
        return JournalFilter(
            date_from=base.date_from,
            date_to=base.date_to,
            transport_type=self.transport_combo.currentData(),
            payment_method=self.payment_combo.currentData(),
        )

    def refresh(self) -> None:
        rows = TransportService(self.db).journal(self._criteria())
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
            self.table.setItem(index, 5, QTableWidgetItem(f"{row.discount} ₽"))
            self.table.setItem(index, 6, QTableWidgetItem(row.period_caption))
            self.table.item(index, 0).setData(Qt.ItemDataRole.UserRole, row.ride_id)

    def add_ride(self) -> None:
        dialog = ManualRideDialog(self.db, self._date, self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def delete_ride(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Журнал", "Выберите поездку.")
            return
        ride_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self, "Удаление поездки",
            "Удалить поездку? Счётчик будет пересчитан (CALC-04).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            TransportService(self.db).delete_ride(ride_id)
        except Exception as error:  # noqa: BLE001 - показываем пользователю
            QMessageBox.warning(self, "Ошибка", getattr(error, "message", str(error)))
            return
        self.changed.emit()
        self.refresh()


class TopUpsTab(QWidget):
    """REP-11: журнал пополнений с добавлением и удалением."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.wallet = WalletService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.balance_label = QLabel()
        self.balance_label.setObjectName("Metric")
        top.addWidget(self.balance_label)
        top.addStretch(1)

        self.add_button = QPushButton("Пополнить…")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self.add_topup)
        top.addWidget(self.add_button)

        self.delete_button = QPushButton("Удалить")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_topup)
        top.addWidget(self.delete_button)
        layout.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Дата", "Сумма", "Комиссия", "Комментарий"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Пополнений нет",
            hint="Внесите фактический остаток на карте — это начальное пополнение "
                 "(WAL-09).",
            action_text="Пополнить",
        )
        self.empty.action_clicked.connect(self.add_topup)
        # Вес 1: пустое состояние занимает место скрытого списка и держит
        # содержимое по центру, а не прижимает его к низу.
        layout.addWidget(self.empty, 1)

    def refresh(self) -> None:
        rows = self.wallet.rows()
        self.balance_label.setText(f"Остаток: {self.wallet.balance_caption}")
        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)
        self.table.setRowCount(len(rows))

        for index, row in enumerate(rows):
            self.table.setItem(index, 0, QTableWidgetItem(row.date_caption))
            self.table.setItem(index, 1, QTableWidgetItem(f"{row.amount} ₽"))
            self.table.setItem(index, 2, QTableWidgetItem(f"{row.fee} ₽"))
            self.table.setItem(index, 3, QTableWidgetItem(row.comment))
            self.table.item(index, 0).setData(Qt.ItemDataRole.UserRole, row.topup_id)

    def add_topup(self) -> None:
        initial = not self.wallet.started
        dialog = TopUpDialog(self.db, self, initial=initial)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def delete_topup(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Пополнения", "Выберите запись.")
            return
        topup_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self, "Удаление пополнения",
            "Удалить пополнение? Остаток будет пересчитан (WAL-07).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.wallet.delete(topup_id)
        self.changed.emit()
        self.refresh()


class ExpensesPage(QWidget):
    """REP-10: отчёты, журнал и пополнения."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._date = clock.today()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = SectionHeader("Расходы на транспорт")
        layout.addWidget(header)

        self.tabs = QTabWidget()
        self.report_tab = ReportTab(db)
        self.journal_tab = JournalTab(db)
        self.topups_tab = TopUpsTab(db)
        for tab in (self.journal_tab, self.topups_tab):
            tab.changed.connect(self._on_changed)
        self.tabs.addTab(self.report_tab, "Отчёты")
        self.tabs.addTab(self.journal_tab, "Журнал поездок")
        self.tabs.addTab(self.topups_tab, "Пополнения")
        layout.addWidget(self.tabs, 1)

    def set_date(self, value: date) -> None:
        self._date = value
        self.report_tab.set_date(value)
        self.journal_tab.set_date(value)

    def refresh(self) -> None:
        self.report_tab.refresh()
        self.journal_tab.refresh()
        self.topups_tab.refresh()

    def _on_changed(self) -> None:
        self.report_tab.refresh()
        self.changed.emit()


__all__ = ["ExpensesPage"]
