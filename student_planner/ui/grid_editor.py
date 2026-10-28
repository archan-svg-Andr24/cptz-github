"""Редактор недельной сетки (§9.2: GRID-01…GRID-11, SUBJ-05, DATA-20).

Один экран со всей неделей Пн–Сб × все слоты профиля выбранного типа недели.
Выбор предмета сохраняет ячейку сразу, общего «Сохранить» нет (GRID-02);
очистка удаляет только строку шаблона (GRID-05).
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import clock
from ..core.dates import format_display
from ..core.errors import AppError
from ..core.schedule_service import GridService
from ..core.settings_registry import SettingsKeys
from ..core.settings_service import SettingsService
from .dialogs import BaseDialog
from .theme import COLORS, stylesheet
from .widgets import Badge

log = logging.getLogger(__name__)

#: Маркер «набранный текст не соответствует ни одному предмету».
_UNRESOLVED = object()


class SubjectCellWidget(QWidget):
    """Ячейка сетки: выпадающий список предметов с автодополнением (GRID-02)."""

    def __init__(self, subjects, current_id, on_change, on_clear,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._blocked = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.addItem("", None)
        for subject in subjects:
            caption = f"{subject.name} — {subject.teacher}" if subject.teacher else subject.name
            self.combo.addItem(caption, subject.id)
        index = self.combo.findData(current_id) if current_id is not None else 0
        self.combo.setCurrentIndex(max(index, 0))

        completer = QCompleter([self.combo.itemText(i) for i in range(self.combo.count())])
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.combo.setCompleter(completer)

        self.combo.activated.connect(self._on_activated)
        self.combo.lineEdit().editingFinished.connect(self._on_activated)
        # Выбор из раскрывающегося списка автодополнения не порождает
        # ``comboBox.activated`` — сигнал приходит только от completer.
        completer.activated.connect(self._on_completer_activated)
        layout.addWidget(self.combo, 1)

        self.clear_button = QPushButton("✕")
        self.clear_button.setObjectName("Flat")
        self.clear_button.setFixedWidth(24)
        self.clear_button.setToolTip("Очистить ячейку")
        self.clear_button.clicked.connect(on_clear)
        self.clear_button.setEnabled(current_id is not None)
        layout.addWidget(self.clear_button)

        self._on_change = on_change
        self._current_id = current_id
        # Пары «имя предмета → id»: в поле пользователь набирает имя без
        # преподавателя, а в списке подпись склеена как «Имя — Преподаватель».
        self._by_name = {subject.name.strip(): subject.id for subject in subjects}

    def _subject_from_text(self):
        """Определить предмет по тому, что набрано в поле (GRID-02).

        ``combo.currentData()`` возвращает данные по текущему *индексу*, а не по
        набранному тексту: при ручном вводе индекс остаётся прежним, и выбор
        терялся. Поэтому предмет ищется по тексту, а несовпадение возвращает
        ``_UNRESOLVED`` — тогда подпись восстанавливается, и ячейка не меняется.
        """
        text = self.combo.currentText().strip()
        if not text:
            return None
        index = self.combo.findText(text, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            return self.combo.itemData(index)
        # Набрано имя без преподавателя — так пользователь и печатает.
        if text in self._by_name:
            return self._by_name[text]
        # Регистр не важен: сравниваем без учёта регистра.
        lowered = text.casefold()
        for name, subject_id in self._by_name.items():
            if name.casefold() == lowered:
                return subject_id
        return _UNRESOLVED

    def _on_completer_activated(self, text: str) -> None:
        index = self.combo.findText(text, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        self._on_activated()

    def _on_activated(self) -> None:
        if self._blocked:
            return
        value = self._subject_from_text()
        if value is _UNRESOLVED:
            # Набран фрагмент, не совпавший с предметом: возвращаем подпись,
            # чтобы в ячейке не остался текст, не соответствующий БД.
            self.set_subject(self._current_id)
            return
        if value == self._current_id:
            return
        self._current_id = value
        self.clear_button.setEnabled(value is not None)
        self._on_change(value)

    def set_subject(self, subject_id) -> None:
        self._blocked = True
        index = self.combo.findData(subject_id) if subject_id is not None else 0
        self.combo.setCurrentIndex(max(index, 0))
        self._current_id = subject_id
        self.clear_button.setEnabled(subject_id is not None)
        self._blocked = False


class GridEditorDialog(BaseDialog):
    """GRID-01: вся недельная сетка на одном экране."""

    def __init__(self, db, day: date, parent: QWidget | None = None) -> None:
        super().__init__(parent, "Редактор недельной сетки")
        self.db = db
        self.service = GridService(db)
        self._error_label = self.error_label()
        self.resize(1120, 640)

        from ..core.day_resolution import DayResolver

        try:
            week_type = DayResolver(db).week_type(day) or "lower"
        except AppError:  # pragma: no cover - защита интерфейса
            week_type = "lower"
        self._week_type = week_type
        # TPL-08: правка действует с выбранной даты; по умолчанию — сегодня.
        self._effective_from: date = day

        # --------------------------------------------------------- заголовок
        top = QHBoxLayout()
        top.setSpacing(8)
        caption = QLabel("Тип недели:")
        top.addWidget(caption)

        self.upper_button = QPushButton("Верхняя")
        self.upper_button.setCheckable(True)
        self.upper_button.clicked.connect(lambda: self.switch_week("upper"))
        top.addWidget(self.upper_button)

        self.lower_button = QPushButton("Нижняя")
        self.lower_button.setCheckable(True)
        self.lower_button.clicked.connect(lambda: self.switch_week("lower"))
        top.addWidget(self.lower_button)

        top.addStretch(1)

        # TPL-08: дата, с которой действует правка.
        top.addWidget(QLabel("Действует с:"))
        self.effective_edit = QDateEdit()
        self.effective_edit.setCalendarPopup(True)
        self.effective_edit.setDisplayFormat("dd.MM.yyyy")
        self.effective_edit.setDate(QDate(self._effective_from.year, self._effective_from.month,
                                          self._effective_from.day))
        self.effective_edit.setToolTip(
            "Правки сетки действуют с этой даты. Прошлые недели сохраняют "
            "прежнее расписание (TPL-08)."
        )
        self.effective_edit.dateChanged.connect(self._on_effective_changed)
        top.addWidget(self.effective_edit)

        self.restore_button = QPushButton("Вернуть стартовый набор недели")
        self.restore_button.clicked.connect(self.restore_seed)
        top.addWidget(self.restore_button)
        self.layout_.addLayout(top)

        hint = QLabel(
            "Выбор предмета сохраняется сразу, общего «Сохранить» нет (GRID-02). "
            "Очистка убирает пару с выбранной даты, слоты и время остаются "
            "(GRID-05). Прошлые недели не меняются: правка действует с даты "
            "«Действует с» (TPL-08)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        self.layout_.addWidget(hint)

        # ----------------------------------------------------------- таблица
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.layout_.addWidget(self.table, 1)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setVisible(False)
        self.warning.setStyleSheet(
            f"color: {COLORS['warning_text']}; background-color: {COLORS['warning_bg']}; "
            f"border: 1px solid {COLORS['warning']}; border-radius: 6px; padding: 6px;"
        )
        self.layout_.addWidget(self.warning)

        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Готово")
        self.layout_.addWidget(self.buttons)

        self.refresh()

    # ------------------------------------------------------------------ данные
    def switch_week(self, week_type: str) -> None:
        if week_type == self._week_type:
            self._sync_week_buttons()
            return
        self._week_type = week_type
        self.refresh()

    def _on_effective_changed(self, value: QDate) -> None:
        """TPL-08: показываем состояние сетки на выбранную дату."""
        self._effective_from = date(value.year(), value.month(), value.day())
        self.refresh()

    def refresh(self) -> None:
        self._sync_week_buttons()
        view = self.service.view(self._week_type, on_date=self._effective_from)
        subjects = self.service.subjects_for_cell()

        self.table.clear()
        self.table.setRowCount(view.max_slots)
        self.table.setColumnCount(len(view.columns))

        self.table.setHorizontalHeaderLabels(
            [f"{column.caption}" for column in view.columns]
        )
        row_labels: list[str] = []
        for index in range(view.max_slots):
            caption = f"Блок {index + 1}"
            for column in view.columns:
                if index < len(column.slots):
                    slot = column.slots[index]
                    if slot.display_name:
                        caption = f"{index + 1}. {slot.display_name}"
                        if slot.is_two_part:
                            caption += f" ({slot.time_caption})"
                        break
            row_labels.append(caption)
        self.table.setVerticalHeaderLabels(row_labels)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        for column_index, column in enumerate(view.columns):
            for row_index in range(view.max_slots):
                if row_index >= len(column.slots) or not column.has_profile:
                    item = QTableWidgetItem("—")
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    item.setForeground(Qt.GlobalColor.darkGray)
                    self.table.setItem(row_index, column_index, item)
                    continue
                slot = column.slots[row_index]
                self.table.setItem(
                    row_index, column_index,
                    QTableWidgetItem(slot.time_caption),
                )
                self.table.setCellWidget(
                    row_index, column_index,
                    SubjectCellWidget(
                        subjects, slot.subject_id,
                        on_change=lambda value, profile=column.profile_id,
                        slot_no=slot.slot_no: self.save_cell(profile, slot_no, value),
                        on_clear=lambda _checked=False, profile=column.profile_id,
                        slot_no=slot.slot_no, row=row_index,
                        col=column_index: self.clear_cell(profile, slot_no, row, col),
                    ),
                )
                if slot.is_empty:
                    self.table.setToolTip("Ячейка пуста — выберите предмет")

        if view.orphan_warnings:
            self.warning.setText(
                "\n".join(view.orphan_warnings)
                + "\nИзменения сохранены и станут сиротскими: их можно удалить "
                  "в расписании (ALG-10)."
            )
            self.warning.setVisible(True)
        else:
            self.warning.setVisible(False)

    def _sync_week_buttons(self) -> None:
        self.upper_button.setChecked(self._week_type == "upper")
        self.lower_button.setChecked(self._week_type == "lower")

    # ------------------------------------------------------------------ запись
    def save_cell(self, profile_id: int, slot_no: int, subject_id) -> None:
        try:
            self.service.set_cell(
            profile_id, self._week_type, slot_no, subject_id,
            effective_from=self._effective_from,
        )
        except AppError as error:
            log.info("Ячейка не сохранена: %s", error)
            self.show_error(error)
            self.refresh()
            return
        self._after_change()

    def clear_cell(self, profile_id: int, slot_no: int, row: int, column: int) -> None:
        try:
            self.service.clear_cell(
            profile_id, self._week_type, slot_no,
            effective_from=self._effective_from,
        )
        except AppError as error:
            self.show_error(error)
            return
        widget = self.table.cellWidget(row, column)
        if isinstance(widget, SubjectCellWidget):
            widget.set_subject(None)
        self._after_change()

    def restore_seed(self) -> None:
        caption = "верхней" if self._week_type == "upper" else "нижней"
        answer = QMessageBox.question(
            self, "Вернуть стартовый набор",
            f"Восстановить строки {caption} недели из стартового набора?\n"
            "Изменения расписания на отдельные даты, профили звонков и второй тип "
            "недели не затрагиваются (GRID-11).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        restored = self.service.restore_seed_week(
            self._week_type, effective_from=self._effective_from
        )
        log.info("Восстановлено ячеек: %d", restored)
        self.refresh()

    def _after_change(self) -> None:
        self.refresh()

    def apply(self) -> bool:
        return True


__all__ = ["GridEditorDialog", "SubjectCellWidget"]
