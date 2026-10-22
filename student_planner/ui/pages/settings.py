"""Страница «Настройки» (§29: SET-01…SET-08).

Экран строится из реестра §30 (SET-08): настройка с флагом «видима в UI» не
может отсутствовать. Разделы: Общие, Недели, Звонки, Транспорт, Календарь, Данные.
"""

from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from ...core import clock
from ...core.dates import format_display
from ...core.errors import AppError
from ...core.paths import appdata_dir, default_db_path, resolve_db_path
from ...core.repositories import (
    BellRepository,
    SubjectRepository,
    TariffRepository,
    WeekAnchorRepository,
)
from ...core.schedule_service import CalendarService
from ...core.seeding import Seeder
from ...core.settings_registry import RECALC_TRIGGER_KEYS, SettingsKeys
from ...core.settings_service import SettingsService
from ...core.transport_service import TariffService, WalletService
from ..dialogs import BaseDialog, PeriodDialog
from ..theme import COLORS
from ..widgets import Card, EmptyState, MetricRow, SectionHeader, Separator


class GeneralTab(QWidget):
    """SET-02: имя студента, группа, колледж, домашняя точка, форматы."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = SettingsService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        card = Card("Профиль студента")
        form = QFormLayout()
        form.setSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Не указано")
        form.addRow("Имя студента:", self.name_edit)

        self.group_edit = QLineEdit()
        self.group_edit.setPlaceholderText("Не указано")
        form.addRow("Группа:", self.group_edit)

        self.college_edit = QLineEdit()
        form.addRow("Название колледжа:", self.college_edit)

        self.home_edit = QLineEdit()
        form.addRow("Домашняя точка:", self.home_edit)

        self.date_format_combo = QComboBox()
        self.date_format_combo.addItem("ДД.ММ.ГГГГ", "DD.MM.YYYY")
        self.date_format_combo.addItem("ГГГГ-ММ-ДД", "YYYY-MM-DD")
        form.addRow("Формат даты:", self.date_format_combo)

        self.time_format_combo = QComboBox()
        self.time_format_combo.addItem("ЧЧ:ММ", "HH:MM")
        self.time_format_combo.addItem("ЧЧ:ММ:СС", "HH:MM:SS")
        form.addRow("Формат времени:", self.time_format_combo)
        card.add_layout(form)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_button = QPushButton("Сохранить")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.save)
        save_row.addWidget(self.save_button)
        card.add_layout(save_row)
        layout.addWidget(card)

        self.message = QLabel()
        self.message.setObjectName("Small")
        self.message.setVisible(False)
        layout.addWidget(self.message)
        layout.addStretch(1)

    def refresh(self) -> None:
        self.name_edit.setText(self.settings.student_name())
        self.group_edit.setText(self.settings.group_title())
        self.group_edit.setPlaceholderText("Не указано")
        self.name_edit.setPlaceholderText("Не указано")
        self._set_combo(self.date_format_combo, self.settings.display_format())
        self._set_combo(self.time_format_combo, self.settings.time_format())

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def save(self) -> None:
        try:
            self.settings.set_student_profile(
                self.name_edit.text(), self.group_edit.text()
            )
            self.settings.set_many(
                {
                    SettingsKeys.COLLEGE_NAME: self.college_edit.text(),
                    SettingsKeys.HOME_POINT_NAME: self.home_edit.text(),
                    SettingsKeys.DATE_DISPLAY_FORMAT: self.date_format_combo.currentData(),
                    SettingsKeys.TIME_DISPLAY_FORMAT: self.time_format_combo.currentData(),
                }
            )
        except AppError as error:
            self._show(error.message, error=True)
            return
        self._show("Сохранено")
        self.changed.emit()

    def _show(self, text: str, *, error: bool = False) -> None:
        self.message.setText(text)
        self.message.setStyleSheet(
            f"color: {COLORS['error'] if error else COLORS['success']};"
        )
        self.message.setVisible(True)


class WeeksTab(QWidget):
    """SET-03: действующий якорь и исторические якоря (WEEK-08)."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.anchors = WeekAnchorRepository(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        card = Card("Действующий якорь")
        form = QFormLayout()
        form.setSpacing(8)

        self.effective_edit = QDateEdit()
        self.effective_edit.setCalendarPopup(True)
        self.effective_edit.setDisplayFormat("dd.MM.yyyy")
        form.addRow("Дата действия:", self.effective_edit)

        self.base_edit = QDateEdit()
        self.base_edit.setCalendarPopup(True)
        self.base_edit.setDisplayFormat("dd.MM.yyyy")
        form.addRow("Опорная дата:", self.base_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Нижняя неделя", "lower")
        self.type_combo.addItem("Верхняя неделя", "upper")
        form.addRow("Тип недели:", self.type_combo)

        self.cycle_label = QLabel("2")
        self.cycle_label.setObjectName("Muted")
        self.cycle_label.setToolTip("Длина цикла в MVP только для чтения (SET-03)")
        form.addRow("Длина цикла:", self.cycle_label)
        card.add_layout(form)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_button = QPushButton("Создать якорь")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.create_anchor)
        save_row.addWidget(self.save_button)
        card.add_layout(save_row)
        layout.addWidget(card)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Дата действия", "Опорная дата", "Тип", "Комментарий"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        self.message = QLabel()
        self.message.setObjectName("Small")
        self.message.setVisible(False)
        layout.addWidget(self.message)

    def refresh(self) -> None:
        anchors = sorted(self.anchors.all(), key=lambda item: item.effective_from)
        self.table.setRowCount(len(anchors))
        for row, anchor in enumerate(anchors):
            self.table.setItem(
                row, 0, QTableWidgetItem(format_display(anchor.effective_from))
            )
            self.table.setItem(
                row, 1, QTableWidgetItem(format_display(anchor.base_date))
            )
            self.table.setItem(
                row, 2,
                QTableWidgetItem("Верхняя" if anchor.base_type == "upper" else "Нижняя"),
            )
            self.table.setItem(row, 3, QTableWidgetItem(anchor.comment or ""))

        if anchors:
            current = anchors[-1]
            for widget, value in (
                (self.effective_edit, current.effective_from),
                (self.base_edit, current.base_date),
            ):
                widget.setDate(QDate(value.year, value.month, value.day))
            index = self.type_combo.findData(current.base_type)
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
            self.cycle_label.setText(str(current.cycle_length))

    def create_anchor(self) -> None:
        effective = self.effective_edit.date()
        base = self.base_edit.date()
        try:
            self.anchors.create(
                date(effective.year(), effective.month(), effective.day()),
                date(base.year(), base.month(), base.day()),
                self.type_combo.currentData(),
            )
        except AppError as error:
            self.message.setText(error.message)
            self.message.setStyleSheet(f"color: {COLORS['error']};")
            self.message.setVisible(True)
            return
        self.message.setText("Якорь создан")
        self.message.setStyleSheet(f"color: {COLORS['success']};")
        self.message.setVisible(True)
        self.changed.emit()
        self.refresh()


class BellsTab(QWidget):
    """SET-04: профили звонков по дням."""

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.bells = BellRepository(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Профили звонков задают блоки и время. Правка блоков выполняется в "
            "справочнике звонков (BELL-13…BELL-17)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["День", "Профиль", "Блоков", "Действует"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        from ...core.dates import WEEKDAY_NAMES

        profiles = sorted(
            self.bells.profiles(), key=lambda item: (item.weekday, item.variant)
        )
        self.table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            self.table.setItem(
                row, 0, QTableWidgetItem(WEEKDAY_NAMES.get(profile.weekday, "—"))
            )
            self.table.setItem(
                row, 1, QTableWidgetItem(f"{profile.name} ({profile.variant})")
            )
            self.table.setItem(row, 2, QTableWidgetItem(str(len(profile.slots))))
            self.table.setItem(
                row, 3, QTableWidgetItem("да" if profile.is_active else "нет")
            )


class TransportTab(QWidget):
    """SET-05: тарифы и ключи «Стрелки» (FARE-11, FARE-12)."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = SettingsService(db)
        self.tariffs = TariffService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        # ------------------------------------------------------------ тарифы
        tariff_card = Card("Тарифы")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Вид", "Цена", "Действует", "Комментарий"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(180)
        tariff_card.add_widget(self.table)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.add_tariff_button = QPushButton("Добавить тариф…")
        self.add_tariff_button.clicked.connect(self.add_tariff)
        buttons.addWidget(self.add_tariff_button)
        buttons.addStretch(1)
        tariff_card.add_layout(buttons)
        layout.addWidget(tariff_card)

        # ---------------------------------------------------------- «Стрелка»
        strelka_card = Card("Расчётный период «Стрелки»")
        form = QFormLayout()
        form.setSpacing(8)

        self.anchor_edit = QLineEdit()
        self.anchor_edit.setPlaceholderText("не задано")
        form.addRow("Начало учёта:", self.anchor_edit)

        self.initial_count_spin = QSpinBox()
        self.initial_count_spin.setRange(0, 9999)
        form.addRow("Поездок до начала учёта:", self.initial_count_spin)

        self.period_days_label = QLabel("30")
        self.period_days_label.setObjectName("Muted")
        self.period_days_label.setToolTip("В MVP только чтение (SET-05)")
        form.addRow("Длина периода:", self.period_days_label)

        self.first_limit_spin = QSpinBox()
        self.first_limit_spin.setRange(0, 9999)
        form.addRow("Порог первой ступени:", self.first_limit_spin)

        self.warn_spin = QSpinBox()
        self.warn_spin.setRange(0, 99)
        form.addRow("Предупреждать при остатке на:", self.warn_spin)

        self.payment_combo = QComboBox()
        self.payment_combo.addItem("Стрелка", "strelka")
        self.payment_combo.addItem("Дебетовая карта", "debit_card")
        form.addRow("Оплата автобусов по умолчанию:", self.payment_combo)
        strelka_card.add_layout(form)

        warning = QLabel(
            "Изменение «Начало учёта» и «Поездок до начала учёта» требует полного "
            "пересчёта счётчика (CALC-04, FARE-12)."
        )
        warning.setObjectName("Small")
        warning.setWordWrap(True)
        strelka_card.add_widget(warning)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.recalc_check = QCheckBox("Пересчитать счётчик сейчас")
        self.recalc_check.setChecked(True)
        save_row.addWidget(self.recalc_check)
        self.save_button = QPushButton("Сохранить")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.save)
        save_row.addWidget(self.save_button)
        strelka_card.add_layout(save_row)
        layout.addWidget(strelka_card)

        self.message = QLabel()
        self.message.setObjectName("Small")
        self.message.setVisible(False)
        layout.addWidget(self.message)
        layout.addStretch(1)

    def refresh(self) -> None:
        rows = self.tariffs.rows()
        self.table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(item.kind_caption))
            self.table.setItem(row, 1, QTableWidgetItem(f"{item.price} ₽"))
            self.table.setItem(row, 2, QTableWidgetItem(item.bounds_caption))
            self.table.setItem(row, 3, QTableWidgetItem(item.comment))
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item.tariff_id)

        anchor = self.settings.strelka_period_anchor_date()
        self.anchor_edit.setText(format_display(anchor) if anchor else "")
        self.initial_count_spin.setValue(self.settings.strelka_initial_ride_count())
        self.period_days_label.setText(str(self.settings.strelka_period_days()))
        self.first_limit_spin.setValue(self.settings.strelka_first_limit())
        self.warn_spin.setValue(self.settings.strelka_low_balance_warn())
        index = self.payment_combo.findData(self.settings.default_bus_payment_method())
        if index >= 0:
            self.payment_combo.setCurrentIndex(index)

    def add_tariff(self) -> None:
        dialog = TariffDialog(self.db, self)
        if dialog.exec():
            self.refresh()
            self.changed.emit()

    def save(self) -> None:
        """SET-05: сохранение ключей с предупреждением о пересчёте (CALC-04)."""
        from ...core.transport_service import TransportService
        from ...core.models import TariffKind

        changes = {
            SettingsKeys.STRELKA_FIRST_LIMIT: str(self.first_limit_spin.value()),
            SettingsKeys.STRELKA_LOW_BALANCE_WARN: str(self.warn_spin.value()),
            SettingsKeys.DEFAULT_BUS_PAYMENT_METHOD: self.payment_combo.currentData(),
            SettingsKeys.STRELKA_INITIAL_RIDE_COUNT: str(self.initial_count_spin.value()),
            SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE: self.anchor_edit.text().strip(),
        }
        recalc_needed = any(
            key in RECALC_TRIGGER_KEYS for key in changes
        )
        try:
            self.settings.set_many(changes)
        except AppError as error:
            self._show(error.message, error=True)
            return

        if recalc_needed and self.recalc_check.isChecked():
            try:
                result = TransportService(self.db).recalculate()
            except AppError as error:
                self._show(error.message, error=True)
                return
            self._show(
                f"Сохранено. Пересчитано поездок: {result.rides_changed}."
            )
        else:
            self._show("Сохранено")
        self.changed.emit()

    def _show(self, text: str, *, error: bool = False) -> None:
        self.message.setText(text)
        self.message.setStyleSheet(
            f"color: {COLORS['error'] if error else COLORS['success']};"
        )
        self.message.setVisible(True)


class TariffDialog(BaseDialog):
    """FARE-11: создание и правка тарифа."""

    def __init__(self, db, parent: QWidget | None = None, tariff=None) -> None:
        super().__init__(parent, "Тариф")
        self.settings_service = TariffService(db)
        self.tariff = tariff
        self._error_label = self.error_label()

        from ...core.models import TariffKind

        form = QFormLayout()
        form.setSpacing(8)

        self.kind_combo = QComboBox()
        for kind in TariffKind.ALL:
            self.kind_combo.addItem(TariffKind.label(kind), kind)
        if tariff is not None:
            index = self.kind_combo.findData(tariff.kind)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
            self.kind_combo.setEnabled(False)
        form.addRow("Вид:", self.kind_combo)

        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Например, 36.50")
        if tariff is not None:
            self.price_edit.setText(str(tariff.price))
        form.addRow("Цена, ₽:", self.price_edit)

        self.from_edit = QDateEdit()
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setDisplayFormat("dd.MM.yyyy")
        start = tariff.effective_from if tariff else date.today()
        self.from_edit.setDate(QDate(start.year, start.month, start.day))
        form.addRow("Действует с:", self.from_edit)

        self.forever_check = QCheckBox("Бессрочно")
        self.forever_check.setChecked(tariff is None or tariff.effective_to is None)
        form.addRow("", self.forever_check)

        self.to_edit = QDateEdit()
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("dd.MM.yyyy")
        end = tariff.effective_to if tariff and tariff.effective_to else date.today()
        self.to_edit.setDate(QDate(end.year, end.month, end.day))
        self.to_edit.setEnabled(not self.forever_check.isChecked())
        form.addRow("Действует по:", self.to_edit)
        self.forever_check.toggled.connect(
            lambda checked: self.to_edit.setEnabled(not checked)
        )

        self.comment_edit = QLineEdit()
        if tariff is not None:
            self.comment_edit.setText(tariff.comment)
        form.addRow("Комментарий:", self.comment_edit)
        self.add_form(form)

        hint = QLabel(
            "Правка тарифа не переписывает прошлые поездки: их стоимость хранится "
            "снапшотом (DATA-16)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.finish("Сохранить")

    def apply(self) -> bool:
        price = self.price_edit.text().strip().replace(",", ".")
        if not price:
            raise AppError("Укажите цену тарифа (FARE-01).")
        start = self.from_edit.date()
        effective_from = date(start.year(), start.month(), start.day())
        effective_to = None
        if not self.forever_check.isChecked():
            end = self.to_edit.date()
            effective_to = date(end.year(), end.month(), end.day())

        if self.tariff is None:
            self.settings_service.create(
                self.kind_combo.currentData(), price, effective_from,
                effective_to=effective_to,
                comment=self.comment_edit.text().strip() or None,
            )
        else:
            self.settings_service.update(
                self.tariff.tariff_id,
                price=price,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        return True


class CalendarTab(QWidget):
    """SET-06: управление учебными периодами."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.service = CalendarService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Каникулы и праздники вносятся вручную: предзаполненного списка нет "
            "(CAL-04). В период занятий нет (CAL-02)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Вид", "Название", "Даты", "Дней"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.add_button = QPushButton("Добавить период…")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self.add_period)
        buttons.addWidget(self.add_button)

        self.delete_button = QPushButton("Удалить")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_period)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.empty = EmptyState(
            "Периодов нет",
            hint="Внесите каникулы и праздники, чтобы расписание их учитывало.",
            action_text="Добавить период",
        )
        self.empty.action_clicked.connect(self.add_period)
        # Вес 1: пустое состояние занимает место скрытой таблицы, подпись и
        # кнопка держатся по центру, а не разъезжаются по странице.
        layout.addWidget(self.empty, 1)

    def refresh(self) -> None:
        entries = self.service.all()
        self.table.setVisible(bool(entries))
        self.empty.setVisible(not entries)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(entry.kind_caption))
            self.table.setItem(row, 1, QTableWidgetItem(entry.title))
            self.table.setItem(row, 2, QTableWidgetItem(entry.bounds_caption))
            self.table.setItem(row, 3, QTableWidgetItem(str(entry.days)))
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, entry.period_id)

    def add_period(self) -> None:
        dialog = PeriodDialog(self.db, self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def delete_period(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Календарь", "Выберите период.")
            return
        period_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self, "Удаление периода",
            "Удалить период? Занятия по шаблону вернутся.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.service.delete(period_id)
        self.changed.emit()
        self.refresh()


class DataTab(QWidget):
    """SET-07: путь к БД, резервная копия, стартовый набор, сброс данных."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = SettingsService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        path_card = Card("База данных")
        self.path_label = QLabel()
        self.path_label.setObjectName("Small")
        self.path_label.setWordWrap(True)
        path_card.add_widget(self.path_label)
        self.data_dir_label = MetricRow("Каталог данных")
        path_card.add_widget(self.data_dir_label)
        layout.addWidget(path_card)

        backup_card = Card("Резервные копии")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.backup_button = QPushButton("Создать резервную копию")
        self.backup_button.clicked.connect(self.create_backup)
        row.addWidget(self.backup_button)

        self.restore_button = QPushButton("Восстановить из копии…")
        self.restore_button.clicked.connect(self.restore_backup)
        row.addWidget(self.restore_button)
        row.addStretch(1)
        backup_card.add_layout(row)
        layout.addWidget(backup_card)

        starter_card = Card("Стартовый набор")
        hint = QLabel(
            "«Восстановить стартовый набор» добавляет только отсутствующие записи "
            "Приложения А и не трогает изменённые (FIRST-05)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        starter_card.add_widget(hint)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.seed_button = QPushButton("Восстановить стартовый набор")
        self.seed_button.clicked.connect(self.restore_seed)
        row2.addWidget(self.seed_button)
        row2.addStretch(1)
        starter_card.add_layout(row2)
        layout.addWidget(starter_card)

        danger_card = Card("Сброс данных")
        danger_hint = QLabel(
            "Удаляет все поездки, задания, изменения расписания и периоды. Действие требует "
            "ввода слова подтверждения и необратимо (SET-07, FIRST-12)."
        )
        danger_hint.setObjectName("Small")
        danger_hint.setWordWrap(True)
        danger_card.add_widget(danger_hint)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        row3.addStretch(1)
        self.reset_button = QPushButton("Сбросить данные…")
        self.reset_button.setObjectName("Danger")
        self.reset_button.clicked.connect(self.reset_data)
        row3.addWidget(self.reset_button)
        danger_card.add_layout(row3)
        layout.addWidget(danger_card)

        self.message = QLabel()
        self.message.setObjectName("Small")
        self.message.setVisible(False)
        layout.addWidget(self.message)
        layout.addStretch(1)

    def refresh(self) -> None:
        self.path_label.setText(f"Файл: {default_db_path()}")
        self.data_dir_label.set_value(str(appdata_dir()))

    def create_backup(self) -> None:
        name = f"student_planner_{clock.today().isoformat()}.db"
        target, _ = QFileDialog.getSaveFileName(
            self, "Сохранить резервную копию", name, "База данных (*.db)"
        )
        if not target:
            return
        try:
            self.db.commit()
            shutil.copy2(default_db_path(), target)
        except OSError as error:
            self._show(f"Не удалось создать копию: {error}", error=True)
            return
        self._show(f"Копия сохранена: {target}")

    def restore_backup(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self, "Выбрать резервную копию", "", "База данных (*.db)"
        )
        if not source:
            return
        answer = QMessageBox.question(
            self, "Восстановление",
            "Заменить текущую базу данных копией? Приложение нужно перезапустить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.close()
            shutil.copy2(source, default_db_path())
        except OSError as error:
            self._show(f"Не удалось восстановить: {error}", error=True)
            return
        self._show("Копия восстановлена. Перезапустите приложение.")

    def restore_seed(self) -> None:
        try:
            summary = Seeder(self.db).seed_missing()
        except AppError as error:
            self._show(error.message, error=True)
            return
        self._show(f"Добавлено записей: {summary.total}")
        self.changed.emit()

    def reset_data(self) -> None:
        """SET-07/FIRST-12: подтверждение вводом слова."""
        word, ok = QInputDialog.getText(
            self, "Сброс данных",
            "Введите слово УДАЛИТЬ, чтобы подтвердить сброс всех данных:",
        )
        if not ok or word.strip().upper() != "УДАЛИТЬ":
            if ok:
                self._show("Слово не совпало: данные не изменены.", error=True)
            return

        tables = (
            "homework", "transport_rides", "trip_confirmations", "strelka_topups",
            "schedule_overrides", "study_periods",
        )
        try:
            with self.db.transaction() as conn:
                for table in tables:
                    conn.execute(f"DELETE FROM {table}")
        except AppError as error:
            self._show(error.message, error=True)
            return
        self._show("Данные удалены. Стартовый набор и справочники сохранены.")
        self.changed.emit()

    def _show(self, text: str, *, error: bool = False) -> None:
        self.message.setText(text)
        self.message.setStyleSheet(
            f"color: {COLORS['error'] if error else COLORS['success']};"
        )
        self.message.setVisible(True)


class SettingsPage(QWidget):
    """SET-01: разделы Общие, Недели, Звонки, Транспорт, Календарь, Данные."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        layout.addWidget(SectionHeader("Настройки"))

        self.tabs = QTabWidget()
        self.general_tab = GeneralTab(db)
        self.weeks_tab = WeeksTab(db)
        self.bells_tab = BellsTab(db)
        self.transport_tab = TransportTab(db)
        self.calendar_tab = CalendarTab(db)
        self.data_tab = DataTab(db)

        for tab in (self.general_tab, self.weeks_tab, self.transport_tab,
                    self.calendar_tab, self.data_tab):
            tab.changed.connect(self._on_changed)

        for tab, caption in (
            (self.general_tab, "Общие"),
            (self.weeks_tab, "Недели"),
            (self.bells_tab, "Звонки"),
            (self.transport_tab, "Транспорт"),
            (self.calendar_tab, "Календарь"),
            (self.data_tab, "Данные"),
        ):
            self.tabs.addTab(tab, caption)
        layout.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        for tab in (self.general_tab, self.weeks_tab, self.bells_tab,
                    self.transport_tab, self.calendar_tab, self.data_tab):
            tab.refresh()

    def _on_changed(self) -> None:
        self.changed.emit()


__all__ = ["SettingsPage"]
