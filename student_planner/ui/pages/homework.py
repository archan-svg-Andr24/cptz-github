"""Страница «Домашние задания» (§25: HW-12…HW-16).

Список с группировкой по дате сдачи, четыре фильтра и фильтр по предмету,
отметка выполнения флажком, удаление по правилам HW-16.
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QFrame,
    QVBoxLayout,
    QWidget,
)

from ...core import clock
from ...core.dates import format_display
from ...core.models import HomeworkStatus
from ...core.schedule_service import HomeworkService
from ..dialogs import HomeworkDialog
from ..theme import COLORS
from ..widgets import EmptyState, SectionHeader, Separator

#: HW-13: четыре фильтра. Выбранный фильтр живёт в сеансе, не в настройках.
FILTERS = (
    ("all", "Все"),
    ("active", "Активные"),
    ("done", "Выполненные"),
    ("overdue", "Просроченные"),
)


class HomeworkRowWidget(QFrame):
    """Строка задания (HW-12): флажок, предмет, описание, дедлайн, действия."""

    toggled = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, row, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = row
        self.setObjectName("Card")
        if row.is_overdue:
            self.setStyleSheet(
                f"QFrame#Card {{ background-color: {COLORS['warning_bg']}; "
                f"border: 1px solid {COLORS['warning']}; border-radius: 6px; }}"
            )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(10)

        # HW-15: флажок отмечает выполнение одним действием.
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(row.homework.status == HomeworkStatus.DONE)
        self.checkbox.setToolTip("Отметить выполненным")
        self.checkbox.clicked.connect(lambda: self.toggled.emit(row.homework.id))
        layout.addWidget(self.checkbox, 0, Qt.AlignmentFlag.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(1)

        subject = QLabel(row.subject_name)
        subject.setObjectName("Subtitle")
        subject.setWordWrap(True)
        if row.homework.status == HomeworkStatus.DONE:
            subject.setStyleSheet(f"color: {COLORS['text_muted']};")
        texts.addWidget(subject)

        description = QLabel(row.short_description or "без описания")
        description.setObjectName("Small")
        description.setWordWrap(True)
        description.setToolTip(row.description)
        texts.addWidget(description)

        due = QLabel(f"до {row.due_caption}")
        due.setObjectName("Small")
        if row.is_overdue:
            due.setStyleSheet(f"color: {COLORS['warning_text']}; font-weight: 600;")
            due.setText(f"до {row.due_caption} · просрочено")
        texts.addWidget(due)
        layout.addLayout(texts, 1)

        status = QLabel(row.status_caption)
        status.setObjectName("Muted")
        layout.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)

        edit_button = QPushButton("Изменить")
        edit_button.setObjectName("Flat")
        edit_button.clicked.connect(lambda: self.edit_requested.emit(row.homework.id))
        layout.addWidget(edit_button, 0, Qt.AlignmentFlag.AlignTop)

        delete_button = QPushButton("Удалить")
        delete_button.setObjectName("Flat")
        delete_button.clicked.connect(lambda: self.delete_requested.emit(row.homework.id))
        layout.addWidget(delete_button, 0, Qt.AlignmentFlag.AlignTop)


class HomeworkPage(QWidget):
    """§25: список заданий с фильтрами, быстрым вводом и отметкой выполнения."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._date: date = clock.today()
        # HW-13: фильтр хранится в сеансе.
        self._status_filter = "all"
        self._subject_filter: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = SectionHeader("Домашние задания")
        layout.addWidget(header)

        self.add_button = QPushButton("Добавить задание")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self.add_homework)
        header.add_action(self.add_button)

        # ---------------------------------------------------------- фильтры
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.filter_combo = QComboBox()
        for key, caption in FILTERS:
            self.filter_combo.addItem(caption, key)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        controls.addWidget(self.filter_combo)

        self.subject_combo = QComboBox()
        self.subject_combo.addItem("Все предметы", None)
        self.subject_combo.currentIndexChanged.connect(self._on_subject_changed)
        controls.addWidget(self.subject_combo)

        controls.addStretch(1)

        self.count_label = QLabel()
        self.count_label.setObjectName("Muted")
        controls.addWidget(self.count_label)
        layout.addLayout(controls)

        # ------------------------------------------------------------ список
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_host)
        layout.addWidget(self.scroll, 1)

        self.empty = EmptyState(
            "Заданий нет", action_text="Добавить задание"
        )
        self.empty.action_clicked.connect(self.add_homework)
        # Вес 1: пустое состояние занимает место скрытого списка и держит
        # подпись по центру, а не прижимает её к низу страницы.
        layout.addWidget(self.empty, 1)

        self.refresh()

    # ------------------------------------------------------------------ данные
    def set_date(self, value: date) -> None:
        self._date = value
        self.refresh()

    def _on_filter_changed(self) -> None:
        self._status_filter = self.filter_combo.currentData()
        self.refresh()

    def _on_subject_changed(self) -> None:
        self._subject_filter = self.subject_combo.currentData()
        self.refresh()

    def _reload_subjects(self) -> None:
        service = HomeworkService(self.db)
        subjects = service.subject_choices()
        current = self._subject_filter
        self.subject_combo.blockSignals(True)
        self.subject_combo.clear()
        self.subject_combo.addItem("Все предметы", None)
        for subject in subjects:
            self.subject_combo.addItem(subject.name, subject.id)
        index = self.subject_combo.findData(current)
        if index >= 0:
            self.subject_combo.setCurrentIndex(index)
        else:
            self._subject_filter = None
        self.subject_combo.blockSignals(False)

    def refresh(self) -> None:
        self._reload_subjects()
        service = HomeworkService(self.db)

        # HW-14: при пустом справочнике — подсказка.
        self.empty.set_caption(service.empty_hint)
        self.empty.set_hint(
            "Добавьте предмет в редакторе сетки или справочнике (HW-14)."
            if not service.has_subjects else ""
        )
        self.add_button.setEnabled(service.has_subjects)

        status = None
        only_overdue = False
        if self._status_filter == "active":
            status = HomeworkStatus.ACTIVE
        elif self._status_filter == "done":
            status = HomeworkStatus.DONE
        elif self._status_filter == "overdue":
            status = HomeworkStatus.ACTIVE
            only_overdue = True

        groups = service.groups(
            status=status,
            subject_id=self._subject_filter,
            only_overdue=only_overdue,
            today=clock.today(),
        )

        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # UI-26: без hide()+setParent(None) снятая строка остаётся
                # видимой до отложенного deleteLater и рисуется поверх новой.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        total = 0
        for group in groups:
            caption = QLabel(
                f"{group.caption} · {group.count}"
                if group.count > 1 else group.caption
            )
            caption.setObjectName("Subtitle")
            caption.setStyleSheet(
                f"color: {COLORS['warning_text']};" if group.is_overdue else ""
            )
            self.list_layout.addWidget(caption)

            for row in group.items:
                widget = HomeworkRowWidget(row)
                widget.toggled.connect(self.toggle_homework)
                widget.edit_requested.connect(self.edit_homework)
                widget.delete_requested.connect(self.delete_homework)
                self.list_layout.addWidget(widget)
                total += 1

        self.list_layout.addStretch(1)
        self.count_label.setText(f"Заданий: {total}" if total else "")
        self.scroll.setVisible(total > 0)
        self.empty.setVisible(total == 0)

    # ------------------------------------------------------------------ действия
    def add_homework(self) -> None:
        dialog = HomeworkDialog(self.db, self, default_date=self._date)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def edit_homework(self, homework_id: int) -> None:
        service = HomeworkService(self.db)
        current = service.repo.require(homework_id)
        dialog = HomeworkDialog(self.db, self, homework=current)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def toggle_homework(self, homework_id: int) -> None:
        """HW-15: отметка выполнения без диалога."""
        try:
            HomeworkService(self.db).toggle(homework_id)
        except Exception as error:  # noqa: BLE001 - показываем пользователю
            QMessageBox.warning(self, "Ошибка", getattr(error, "message", str(error)))
        self.changed.emit()
        self.refresh()

    def delete_homework(self, homework_id: int) -> None:
        """HW-16: ``active`` без подтверждения, ``done`` — с подтверждением."""
        service = HomeworkService(self.db)
        try:
            needs = service.needs_confirmation(homework_id)
        except Exception:  # noqa: BLE001 - запись могла исчезнуть
            self.refresh()
            return
        if needs:
            answer = QMessageBox.question(
                self, "Удаление задания",
                "Задание выполнено. Удалить его?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            service.delete(homework_id, confirmed=True)
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "Ошибка", getattr(error, "message", str(error)))
            return
        self.changed.emit()
        self.refresh()


__all__ = ["HomeworkPage", "FILTERS"]
