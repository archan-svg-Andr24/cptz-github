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
    QButtonGroup,
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
    QListWidget,
    QListWidgetItem,
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
from ...core.day_resolution import DayResolver
from ...core.dates import format_display
from ...core.errors import AppError, InUseError
from ...core.paths import (
    appdata_dir,
    clear_pointer,
    default_db_path,
    resolve_db_path,
    write_pointer,
)
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
from ...core.subject_names import SubjectNameService, auto_variant
from ...core.transport_service import TariffService, WalletService
from ..dialogs import BaseDialog, PeriodDialog
from ..theme import THEMES, THEME_ORDER, theme_manager
from ..widgets import (
    Card,
    EmptyState,
    MetricRow,
    SectionHeader,
    Separator,
    show_message,
)


class ThemeCard(QWidget):
    """UI-13: карточка-превью темы: название и её собственные цвета.

    Превью намеренно рисуется цветами **описываемой** темы, а не активной:
    иначе все три карточки выглядели бы одинаково и выбор был бы слепым.
    """

    def __init__(self, theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme_key = theme.key
        colors = theme.colors

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.button = QPushButton(theme.caption)
        self.button.setCheckable(True)
        self.button.setToolTip(theme.description)
        self.button.setMinimumHeight(56)
        # Полоса-превью: фон → панель → акцент. Инлайновый стиль уместен
        # именно здесь: он показывает чужую палитру и не должен следовать
        # за текущей темой.
        self.button.setStyleSheet(
            f"QPushButton {{"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {colors['background']}, stop:0.55 {colors['surface_alt']},"
            f" stop:1 {colors['accent']});"
            f" color: {colors['text']};"
            f" border: 2px solid {colors['border_strong']};"
            f" border-radius: 6px; font-weight: 600; }}"
            f"QPushButton:checked {{"
            f" border: 2px solid {colors['accent_hover']}; }}"
        )
        layout.addWidget(self.button)

        caption = QLabel(theme.description)
        caption.setObjectName("Small")
        caption.setWordWrap(True)
        layout.addWidget(caption)


class GeneralTab(QWidget):
    """SET-02: имя студента, группа, колледж, домашняя точка, форматы, тема."""

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

        # ------------------------------------------------------------ тема
        theme_card = Card("Тема оформления")
        hint = QLabel(
            "Тема применяется сразу: перекрашиваются открытые разделы, диалоги "
            "и календарь. Выбор сохраняется и используется при следующем запуске."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        theme_card.add_widget(hint)

        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_buttons: dict[str, ThemeCard] = {}
        options = QHBoxLayout()
        options.setSpacing(10)
        for key in THEME_ORDER:
            option = ThemeCard(THEMES[key])
            self.theme_group.addButton(option.button)
            self.theme_buttons[key] = option
            options.addWidget(option, 1)
        theme_card.add_layout(options)

        self.theme_message = QLabel()
        self.theme_message.setObjectName("Small")
        self.theme_message.setVisible(False)
        theme_card.add_widget(self.theme_message)
        layout.addWidget(theme_card)

        # ------------------------------------------------- уведомления
        notif_card = Card("Системные уведомления")
        notif_hint = QLabel(
            "Программа напоминает о начале пары, дедлайне задания, близком "
            "экзамене и низком остатке «Стрелки». Напоминания появляются в "
            "системном трее (NOTIF-01…NOTIF-05)."
        )
        notif_hint.setObjectName("Small")
        notif_hint.setWordWrap(True)
        notif_card.add_widget(notif_hint)

        notif_form = QFormLayout()
        notif_form.setSpacing(8)

        self.notify_combo = QComboBox()
        self.notify_combo.addItem("Включены", "1")
        self.notify_combo.addItem("Выключены", "0")
        notif_form.addRow("Напоминания:", self.notify_combo)

        self.notify_exam_spin = QSpinBox()
        self.notify_exam_spin.setRange(0, 60)
        self.notify_exam_spin.setSuffix(" дн.")
        notif_form.addRow("Об экзамене за:", self.notify_exam_spin)

        self.notify_homework_spin = QSpinBox()
        self.notify_homework_spin.setRange(0, 30)
        self.notify_homework_spin.setSuffix(" дн.")
        notif_form.addRow("О дедлайне задания за:", self.notify_homework_spin)

        self.notify_lesson_spin = QSpinBox()
        self.notify_lesson_spin.setRange(0, 120)
        self.notify_lesson_spin.setSuffix(" мин.")
        notif_form.addRow("О начале пары за:", self.notify_lesson_spin)

        self.notify_balance_combo = QComboBox()
        self.notify_balance_combo.addItem("Да", "1")
        self.notify_balance_combo.addItem("Нет", "0")
        notif_form.addRow("О низком остатке «Стрелки»:", self.notify_balance_combo)

        notif_card.add_layout(notif_form)

        notif_save_row = QHBoxLayout()
        notif_save_row.addStretch(1)
        self.notify_save_button = QPushButton("Сохранить напоминания")
        self.notify_save_button.clicked.connect(self.save_notifications)
        notif_save_row.addWidget(self.notify_save_button)
        notif_card.add_layout(notif_save_row)

        self.notify_message = QLabel()
        self.notify_message.setObjectName("Small")
        self.notify_message.setVisible(False)
        notif_card.add_widget(self.notify_message)
        layout.addWidget(notif_card)

        # Сигнал нажатия, а не переключения: повторный выбор уже активной темы
        # не должен считаться изменением, но и вреда от него нет.
        self.theme_group.buttonClicked.connect(self._on_theme_clicked)

        self.message = QLabel()
        self.message.setObjectName("Small")
        self.message.setVisible(False)
        layout.addWidget(self.message)
        layout.addStretch(1)

        # Отметить действующую тему сразу: до первого refresh() карточки
        # выглядели бы невыбранными, хотя тема уже применена.
        self._sync_theme()
        # SET-08: поля заполняются и при самостоятельном открытии вкладки, не
        # только через refresh() страницы настроек.
        self.refresh()

    def refresh(self) -> None:
        self.name_edit.setText(self.settings.student_name())
        self.group_edit.setText(self.settings.group_title())
        self.group_edit.setPlaceholderText("Не указано")
        self.name_edit.setPlaceholderText("Не указано")
        # SET-02: колледж и домашнюю точку тоже нужно прочитать из настроек.
        # Без этих двух строк поля оставались пустыми при каждом открытии, а
        # кнопка «Сохранить» записывала пустоту — данные стирались молча.
        self.college_edit.setText(self.settings.raw(SettingsKeys.COLLEGE_NAME))
        self.home_edit.setText(self.settings.raw(SettingsKeys.HOME_POINT_NAME))
        self._set_combo(self.date_format_combo, self.settings.display_format())
        self._set_combo(self.time_format_combo, self.settings.time_format())
        self.refresh_notifications()
        self._sync_theme()

    def refresh_notifications(self) -> None:
        """NOTIF-01: показать сохранённые значения напоминаний."""
        self._set_combo(
            self.notify_combo, self.settings.raw(SettingsKeys.NOTIFY_ENABLED) or "1"
        )
        self._set_combo(
            self.notify_balance_combo,
            self.settings.raw(SettingsKeys.NOTIFY_LOW_BALANCE) or "1",
        )
        self.notify_exam_spin.setValue(
            self.settings.get_int(SettingsKeys.NOTIFY_EXAM_DAYS)
        )
        self.notify_homework_spin.setValue(
            self.settings.get_int(SettingsKeys.NOTIFY_HOMEWORK_DAYS)
        )
        self.notify_lesson_spin.setValue(
            self.settings.get_int(SettingsKeys.NOTIFY_LESSON_MINUTES)
        )

    def save_notifications(self) -> None:
        """Сохранить параметры напоминаний (NOTIF-01…NOTIF-05)."""
        try:
            self.settings.set_many(
                {
                    SettingsKeys.NOTIFY_ENABLED: self.notify_combo.currentData(),
                    SettingsKeys.NOTIFY_EXAM_DAYS: str(self.notify_exam_spin.value()),
                    SettingsKeys.NOTIFY_HOMEWORK_DAYS: str(self.notify_homework_spin.value()),
                    SettingsKeys.NOTIFY_LESSON_MINUTES: str(self.notify_lesson_spin.value()),
                    SettingsKeys.NOTIFY_LOW_BALANCE: self.notify_balance_combo.currentData(),
                }
            )
        except AppError as error:
            show_message(self.notify_message, error.message, error=True)
            return
        show_message(self.notify_message, "Настройки напоминаний сохранены")

    def _sync_theme(self) -> None:
        """Подсветить карточку действующей темы (UI-13)."""
        current = theme_manager(self.db).key
        for key, option in self.theme_buttons.items():
            option.button.setChecked(key == current)

    def _on_theme_clicked(self, button) -> None:
        """UI-13: применить тему сразу, без кнопки «Сохранить»."""
        key = next(
            (
                theme_key
                for theme_key, option in self.theme_buttons.items()
                if option.button is button
            ),
            None,
        )
        if key is None:
            return
        # Настройка пишется в БД внутри apply, поэтому отдельное «Сохранить»
        # для темы не нужно: иначе легко уйти со страницы без применения.
        # Перекраску страниц выполняет главное окно по сигналу менеджера.
        theme_manager(self.db).apply(key)
        self.theme_message.setText(f"Тема: {THEMES[key].caption}")
        self.theme_message.setVisible(True)
        self._sync_theme()

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
        # SET-02: формат применяется сразу. Прямая запись в settings минует
        # set_display_formats, поэтому применяем явно — иначе выбранный
        # «ГГГГ-ММ-ДД» оставался бы только строкой в базе.
        self.settings.apply_display_formats()
        self._show("Сохранено")
        self.changed.emit()

    def _show(self, text: str, *, error: bool = False) -> None:
        show_message(self.message, text, error=error)


class WeeksTab(QWidget):
    """SET-03: действующий якорь, исторические якоря (WEEK-08) и сетка недели."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.anchors = WeekAnchorRepository(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        # ------------------------------------------------------- сетка недели
        # GRID-01: тот же редактор, что и на странице «Расписание», вызванный
        # из настроек — расписание правится в любой момент, без перехода.
        grid_card = Card("Расписание недели")
        grid_hint = QLabel(
            "Предметы по дням и парам задаются в редакторе недельной сетки. "
            "Выбор сохраняется сразу по ячейке, общего «Сохранить» нет (GRID-02); "
            "очистка убирает только ячейку, слоты и звонки остаются (GRID-05)."
        )
        grid_hint.setObjectName("Small")
        grid_hint.setWordWrap(True)
        grid_card.add_widget(grid_hint)

        grid_row = QHBoxLayout()
        grid_row.setSpacing(8)
        self.grid_button = QPushButton("Редактировать сетку недели…")
        self.grid_button.setObjectName("Primary")
        self.grid_button.clicked.connect(self.open_grid_editor)
        grid_row.addWidget(self.grid_button)
        grid_row.addStretch(1)
        grid_card.add_layout(grid_row)
        layout.addWidget(grid_card)

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

    def open_grid_editor(self) -> None:
        """GRID-01: открыть редактор недельной сетки из настроек.

        Используется тот же диалог, что и на странице «Расписание»: одна
        реализация, один способ сохранения (по ячейке). После закрытия
        передаётся ``changed``, чтобы страница расписания перерисовалась.
        """
        from ..grid_editor import GridEditorDialog

        try:
            week_type = DayResolver(self.db).week_type(clock.today()) or "lower"
        except AppError:  # pragma: no cover - защита интерфейса
            week_type = "lower"
        dialog = GridEditorDialog(self.db, clock.today(), self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

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
            show_message(self.message, error.message, error=True)
            return
        show_message(self.message, "Якорь создан")
        self.changed.emit()
        self.refresh()


class BellBlockDialog(BaseDialog):
    """BELL-12/BELL-13: правка частей блока звонков.

    Блок задаётся списком частей «занятие» и «перемена» с временами. Пустое
    поле времени игнорируется, поэтому убрать перемену можно просто очистив
    обе её границы — так пользователю не нужно знать про «части» вообще.
    """

    def __init__(self, db, slot, parent: QWidget | None = None) -> None:
        super().__init__(parent, f"Блок {slot.slot_no}")
        self.db = db
        self.slot = slot
        self.bells = BellRepository(db)

        hint = QLabel(
            "Блок состоит из частей: занятие и, при необходимости, перемена после "
            "него. Блоки одного профиля не могут пересекаться по времени (BELL-17)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        self.layout_.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)

        self.name_edit = QLineEdit(slot.display_name or "")
        self.name_edit.setPlaceholderText("например, «1 пара»")
        form.addRow("Название:", self.name_edit)

        self.pair_spin = QSpinBox()
        self.pair_spin.setRange(0, 12)
        self.pair_spin.setSpecialValueText("не задан")
        self.pair_spin.setValue(slot.pair_no or 0)
        form.addRow("Номер пары:", self.pair_spin)

        self.parts_table = QTableWidget(0, 3)
        self.parts_table.setHorizontalHeaderLabels(["Тип", "Начало", "Окончание"])
        self.parts_table.verticalHeader().setVisible(False)
        self.parts_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.parts_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        form.addRow(self.parts_table)
        self.layout_.addLayout(form)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.add_lesson_button = QPushButton("Добавить занятие")
        self.add_lesson_button.setObjectName("Flat")
        self.add_lesson_button.clicked.connect(lambda: self._add_row("lesson"))
        buttons.addWidget(self.add_lesson_button)

        self.add_break_button = QPushButton("Добавить перемену")
        self.add_break_button.setObjectName("Flat")
        self.add_break_button.setToolTip(
            "Перемена ставится перед последним занятием: по BELL-17 первая и "
            "последняя части блока — всегда занятие."
        )
        self.add_break_button.clicked.connect(self._add_break)
        buttons.addWidget(self.add_break_button)

        self.remove_row_button = QPushButton("Убрать часть")
        self.remove_row_button.setObjectName("Flat")
        self.remove_row_button.clicked.connect(self._remove_row)
        buttons.addWidget(self.remove_row_button)
        buttons.addStretch(1)
        self.layout_.addLayout(buttons)

        self.message = self.error_label()
        self.finish("Сохранить")

        for part in slot.parts:
            self._add_row(part.part_type, part.start_time, part.end_time)

    def _add_row(self, part_type: str, start: str = "", end: str = "") -> None:
        row = self.parts_table.rowCount()
        self.parts_table.insertRow(row)
        kind = QComboBox()
        kind.addItem("занятие", "lesson")
        kind.addItem("перемена", "break")
        index = kind.findData(part_type)
        if index >= 0:
            kind.setCurrentIndex(index)
        self.parts_table.setCellWidget(row, 0, kind)
        self.parts_table.setItem(row, 1, QTableWidgetItem(start))
        self.parts_table.setItem(row, 2, QTableWidgetItem(end))

    def _add_break(self) -> None:
        """Вставить перемену перед последним занятием (BELL-17).

        Проверка схемы требует, чтобы блок начинался и заканчивался занятием:
        перемена в конце была бы отклонена с ошибкой, поэтому кнопка ставит
        её в середину, а если занятия всего одно — сначала добавляет второе.
        """
        rows = self.parts_table.rowCount()
        if rows < 2:
            self._add_row("lesson")
            rows = self.parts_table.rowCount()
        self._insert_row(rows - 1, "break")

    def _insert_row(self, index: int, part_type: str, start: str = "", end: str = "") -> None:
        self.parts_table.insertRow(index)
        kind = QComboBox()
        kind.addItem("занятие", "lesson")
        kind.addItem("перемена", "break")
        found = kind.findData(part_type)
        if found >= 0:
            kind.setCurrentIndex(found)
        self.parts_table.setCellWidget(index, 0, kind)
        self.parts_table.setItem(index, 1, QTableWidgetItem(start))
        self.parts_table.setItem(index, 2, QTableWidgetItem(end))

    def _remove_row(self) -> None:
        row = self.parts_table.currentRow()
        if row < 0 and self.parts_table.rowCount():
            row = self.parts_table.rowCount() - 1
        if row >= 0:
            self.parts_table.removeRow(row)

    def _parts(self) -> list[tuple[str, str, str]]:
        """Собрать части из таблицы; строки без времён пропускаются."""
        result = []
        for row in range(self.parts_table.rowCount()):
            widget = self.parts_table.cellWidget(row, 0)
            part_type = widget.currentData() if widget is not None else "lesson"
            start_item = self.parts_table.item(row, 1)
            end_item = self.parts_table.item(row, 2)
            start = part_type and (start_item.text().strip() if start_item else "")
            end = end_item.text().strip() if end_item else ""
            if not start and not end:
                continue
            result.append((part_type, start, end))
        return result

    def save(self) -> None:
        """Сохранить блок и закрыть диалог (BELL-12/BELL-13).

        Метод назван ``save`` исторически; ``BaseDialog`` вызывает ``apply``,
        поэтому базовый класс теперь умеет вызывать и ``save`` (см.
        ``BaseDialog._submit``). Здесь же возвращается результат, чтобы диалог
        не закрывался при ошибке проверки BELL-17.
        """
        parts = self._parts()
        try:
            self.bells.update_slot_parts(self.slot.id, parts)
            name = self.name_edit.text().strip()
            pair_no = self.pair_spin.value() or None
            if name != (self.slot.display_name or "") or pair_no != self.slot.pair_no:
                self.bells.rename_slot(self.slot.id, name=name, pair_no=pair_no)
        except AppError as error:
            show_message(self.message, error.message, error=True)
            return
        self.accept()

    def apply(self) -> bool:
        """Точка входа ``BaseDialog``: сохранить и сообщить об успехе.

        Без этого метода ``BaseDialog._on_accept`` вызывал базовый ``apply``,
        который всегда возвращал ``True``: диалог закрывался «успешно», а
        правка блока терялась.
        """
        self.save()
        return self.result() == self.DialogCode.Accepted


class BellsTab(QWidget):
    """SET-04/BELL-13…BELL-17: профили звонков и правка их блоков."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.bells = BellRepository(db)
        self.settings_service = SettingsService(db)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Профиль звонков задаёт блоки и время для дня недели. Выберите профиль "
            "слева — справа появятся его блоки; двойной щелчок по блоку открывает "
            "правку времени (BELL-13…BELL-17)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # TPL-05: альтернативная пятница. Вариант профиля выбирается здесь,
        # потому что «классный час» — свойство пятницы, а не отдельного блока.
        friday_row = QHBoxLayout()
        friday_row.setSpacing(8)
        friday_row.addWidget(QLabel("Пятница:"))
        self.friday_combo = QComboBox()
        self.friday_combo.addItem("Обычное расписание", "standard")
        self.friday_combo.addItem("С классным часом", "friday_class_hour")
        self.friday_combo.setToolTip(
            "Если в пятницу действует особый профиль звонков (классный час, "
            "укороченные пары), выберите его здесь (TPL-05)."
        )
        friday_row.addWidget(self.friday_combo)
        self.friday_save_button = QPushButton("Применить")
        self.friday_save_button.setObjectName("Flat")
        self.friday_save_button.clicked.connect(self.save_friday_variant)
        friday_row.addWidget(self.friday_save_button)
        friday_row.addStretch(1)
        layout.addLayout(friday_row)

        body = QHBoxLayout()
        body.setSpacing(10)

        # ------------------------------------------------------ список профилей
        left = QVBoxLayout()
        left.setSpacing(6)
        left_caption = QLabel("Профили")
        left_caption.setObjectName("Subtitle")
        left.addWidget(left_caption)

        self.profile_list = QListWidget()
        self.profile_list.setMinimumWidth(190)
        self.profile_list.currentItemChanged.connect(self._on_profile_changed)
        left.addWidget(self.profile_list, 1)

        profile_buttons = QHBoxLayout()
        profile_buttons.setSpacing(6)
        self.new_profile_button = QPushButton("Новый…")
        self.new_profile_button.setObjectName("Flat")
        self.new_profile_button.clicked.connect(self.create_profile)
        profile_buttons.addWidget(self.new_profile_button)

        self.delete_profile_button = QPushButton("Удалить")
        self.delete_profile_button.setObjectName("Flat")
        self.delete_profile_button.clicked.connect(self.delete_profile)
        profile_buttons.addWidget(self.delete_profile_button)
        left.addLayout(profile_buttons)
        body.addLayout(left)

        # --------------------------------------------------------- блоки
        right = QVBoxLayout()
        right.setSpacing(6)
        right_caption = QLabel("Блоки профиля")
        right_caption.setObjectName("Subtitle")
        right.addWidget(right_caption)

        self.slots_table = QTableWidget(0, 3)
        self.slots_table.setHorizontalHeaderLabels(["Блок", "Время", "Части"])
        self.slots_table.verticalHeader().setVisible(False)
        self.slots_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.slots_table.setAlternatingRowColors(True)
        self.slots_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.slots_table.doubleClicked.connect(self.edit_slot)
        right.addWidget(self.slots_table, 1)

        slot_buttons = QHBoxLayout()
        slot_buttons.setSpacing(6)
        self.add_slot_button = QPushButton("Добавить блок")
        self.add_slot_button.setObjectName("Flat")
        self.add_slot_button.clicked.connect(self.add_slot)
        slot_buttons.addWidget(self.add_slot_button)

        self.edit_slot_button = QPushButton("Изменить блок")
        self.edit_slot_button.setObjectName("Flat")
        self.edit_slot_button.clicked.connect(self.edit_slot)
        slot_buttons.addWidget(self.edit_slot_button)

        self.delete_slot_button = QPushButton("Удалить блок")
        self.delete_slot_button.setObjectName("Flat")
        self.delete_slot_button.clicked.connect(self.delete_slot)
        slot_buttons.addWidget(self.delete_slot_button)
        slot_buttons.addStretch(1)
        right.addLayout(slot_buttons)
        body.addLayout(right, 1)

        layout.addLayout(body, 1)

        self.message = QLabel()
        self.message.setObjectName("Small")
        self.message.setWordWrap(True)
        self.message.setVisible(False)
        layout.addWidget(self.message)

    # ------------------------------------------------------------------ данные
    def _profiles(self):
        return sorted(self.bells.profiles(), key=lambda item: (item.weekday, item.variant))

    def refresh(self) -> None:
        from ...core.dates import WEEKDAY_NAMES

        # TPL-05: показать действующий вариант пятницы.
        stored = self.settings_service.raw(SettingsKeys.FRIDAY_DEFAULT_VARIANT) or "standard"
        index = self.friday_combo.findData(stored)
        self.friday_combo.setCurrentIndex(index if index >= 0 else 0)

        current = self._current_profile_id()
        profiles = self._profiles()
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for profile in profiles:
            item = QListWidgetItem(
                f"{WEEKDAY_NAMES.get(profile.weekday, '—')} · {profile.name}"
                + ("" if profile.is_active else " (неактивен)")
            )
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.profile_list.addItem(item)
        self.profile_list.blockSignals(False)

        if profiles:
            index = 0
            if current is not None:
                for row, profile in enumerate(profiles):
                    if profile.id == current:
                        index = row
                        break
            self.profile_list.setCurrentRow(index)
        self._reload_slots()

    def _current_profile_id(self) -> int | None:
        item = self.profile_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _current_profile(self):
        profile_id = self._current_profile_id()
        return self.bells.profile(profile_id) if profile_id is not None else None

    def _on_profile_changed(self, *_args) -> None:
        self._reload_slots()

    def _reload_slots(self) -> None:
        from ...core.dates import format_time_display

        profile = self._current_profile()
        slots = profile.slots if profile is not None else ()
        self.slots_table.setRowCount(len(slots))
        for row, slot in enumerate(slots):
            self.slots_table.setItem(row, 0, QTableWidgetItem(slot.caption))
            item = QTableWidgetItem(
                f"{format_time_display(slot.start_time)}–{format_time_display(slot.end_time)}"
                if slot.start_time and slot.end_time else "—"
            )
            item.setData(Qt.ItemDataRole.UserRole, slot.id)
            self.slots_table.setItem(row, 1, item)
            self.slots_table.setItem(
                row, 2, QTableWidgetItem(", ".join(
                    "занятие" if part.part_type == "lesson" else "перемена"
                    for part in slot.parts
                ))
            )

    def _selected_slot(self):
        profile = self._current_profile()
        if profile is None:
            return None
        row = self.slots_table.currentRow()
        if row < 0:
            return None
        item = self.slots_table.item(row, 1)
        slot_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        for slot in profile.slots:
            if slot.id == slot_id:
                return slot
        return None

    # ------------------------------------------------------------------ действия
    def save_friday_variant(self) -> None:
        """TPL-05: запомнить вариант пятницы."""
        try:
            self.settings_service.set(
                SettingsKeys.FRIDAY_DEFAULT_VARIANT, self.friday_combo.currentData()
            )
        except AppError as error:
            show_message(self.message, error.message, error=True)
            return
        show_message(
            self.message,
            "Вариант пятницы сохранён. Если особого профиля нет, пятница "
            "останется обычной.",
        )
        self.changed.emit()

    def create_profile(self) -> None:
        from ...core.dates import WEEKDAY_NAMES

        days = [WEEKDAY_NAMES[key] for key in sorted(WEEKDAY_NAMES)]
        day, ok = QInputDialog.getItem(
            self, "Новый профиль", "День недели:", days, 0, False
        )
        if not ok:
            return
        weekday = list(sorted(WEEKDAY_NAMES))[days.index(day)]
        name, ok = QInputDialog.getText(
            self, "Новый профиль", "Название профиля:", text=day
        )
        if not ok or not name.strip():
            return
        try:
            profile = self.bells.create_profile(weekday, name.strip())
        except AppError as error:
            show_message(self.message, error.message, error=True)
            return
        show_message(self.message, f"Профиль «{profile.name}» создан")
        self.changed.emit()
        self.refresh()

    def delete_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        answer = QMessageBox.question(
            self, "Удаление",
            f"Удалить профиль «{profile.name}»? Если на него ссылаются занятия, "
            "удаление будет отклонено с предложением деактивации (BELL-20).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.bells.delete_profile(profile.id)
        except InUseError as error:
            show_message(self.message, error.message, error=True)
            return
        except AppError as error:
            show_message(self.message, error.message, error=True)
            return
        show_message(self.message, "Профиль удалён")
        self.changed.emit()
        self.refresh()

    def add_slot(self) -> None:
        profile = self._current_profile()
        if profile is None:
            show_message(self.message, "Сначала выберите профиль.", error=True)
            return
        # BELL-13: новый блок добавляется в конец профиля. Части обязательны:
        # BELL-02 запрещает блок без частей, поэтому сразу задаём занятие.
        # Время берётся из последнего блока (следующая пара через 10 минут
        # после перемены) либо 08:30 для первого блока — так новый блок не
        # пересекается с существующими и не требует правки с нуля.
        start, end = self._next_block_time(profile)
        try:
            slot = self.bells.add_slot(
                profile.id, "pair",
                pair_no=len(profile.slots) + 1,
                parts=[("lesson", start, end)],
            )
        except AppError as error:
            show_message(self.message, error.message, error=True)
            return
        dialog = BellBlockDialog(self.db, slot, self)
        if dialog.exec():
            show_message(self.message, "Блок сохранён")
            self.changed.emit()
        else:
            # Отмена: блок уже создан, но пользователь отказался его править.
            # Удаляем, чтобы «Отмена» действительно ничего не меняла.
            try:
                self.bells.delete_slot(slot.id)
            except AppError:  # pragma: no cover - блок без ссылок удаляется
                pass
        self.refresh()

    @staticmethod
    def _next_block_time(profile) -> tuple[str, str]:
        """Свободное время для нового блока после последнего существующего."""
        from ...core import dates as dt
        from ...core.dates import format_time_display  # noqa: F401 - для читаемости

        last = max(
            (slot for slot in profile.slots if slot.end_time),
            key=lambda slot: slot.end_time or "",
            default=None,
        )
        if last is None or not last.end_time:
            return "08:30", "09:15"
        start_minutes = dt.time_to_minutes(last.end_time) + 10
        end_minutes = start_minutes + 45
        if end_minutes > 23 * 60 + 59:
            return "08:30", "09:15"
        return dt.minutes_to_time(start_minutes), dt.minutes_to_time(end_minutes)

    def edit_slot(self, *_args) -> None:
        slot = self._selected_slot()
        if slot is None:
            show_message(self.message, "Выберите блок в таблице.", error=True)
            return
        dialog = BellBlockDialog(self.db, slot, self)
        if dialog.exec():
            show_message(self.message, "Блок сохранён")
            self.changed.emit()
        self.refresh()

    def delete_slot(self) -> None:
        slot = self._selected_slot()
        if slot is None:
            show_message(self.message, "Выберите блок в таблице.", error=True)
            return
        answer = QMessageBox.question(
            self, "Удаление",
            f"Удалить блок «{slot.caption}»? Удаление блока из середины профиля "
            "запрещено, пока на него ссылаются занятия (BELL-16).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.bells.delete_slot(slot.id)
        except AppError as error:
            show_message(self.message, error.message, error=True)
            return
        show_message(self.message, "Блок удалён")
        self.changed.emit()
        self.refresh()


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
        """SET-05: сохранение ключей с предупреждением о пересчёте (CALC-04).

        Дата начала учёта показывается в формате отображения (``01.09.2026``),
        а хранится в ISO. Раньше в базу писался текст поля как есть, поэтому
        проверка отклоняла сохранение — и вместе с ним отменялись **все**
        остальные поля формы (тарифы, порог, способ оплаты), причём сообщение
        об ошибке оставалось скрытым. Теперь дата разбирается тем же
        ``parse_display``, которым выводится, и переводится в ISO.
        """
        from ...core import dates as dt
        from ...core.transport_service import TransportService
        from ...core.models import TariffKind

        anchor_text = self.anchor_edit.text().strip()
        if anchor_text:
            try:
                anchor_iso = dt.to_iso(dt.parse_display(anchor_text))
            except AppError as error:
                self._show(
                    f"Дата начала учёта: {error.message}. Введите дату в виде "
                    f"{dt.active_display_format()} или оставьте поле пустым.",
                    error=True,
                )
                return
        else:
            anchor_iso = ""

        changes = {
            SettingsKeys.STRELKA_FIRST_LIMIT: str(self.first_limit_spin.value()),
            SettingsKeys.STRELKA_LOW_BALANCE_WARN: str(self.warn_spin.value()),
            SettingsKeys.DEFAULT_BUS_PAYMENT_METHOD: self.payment_combo.currentData(),
            SettingsKeys.STRELKA_INITIAL_RIDE_COUNT: str(self.initial_count_spin.value()),
            SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE: anchor_iso,
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
        show_message(self.message, text, error=error)


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

        # SET-07/DATA-02: выбор файла базы. Настройка ``db_path`` хранится
        # внутри самой базы, поэтому выбранный путь ещё и запоминается
        # файлом-указателем — иначе следующий запуск о нём не узнает.
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.choose_db_button = QPushButton("Выбрать другой файл базы…")
        self.choose_db_button.clicked.connect(self.choose_database)
        path_row.addWidget(self.choose_db_button)

        self.reset_db_button = QPushButton("Вернуть путь по умолчанию")
        self.reset_db_button.setObjectName("Flat")
        self.reset_db_button.clicked.connect(self.reset_database_path)
        path_row.addWidget(self.reset_db_button)
        path_row.addStretch(1)
        path_card.add_layout(path_row)
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
        current = Path(self.db.path) if getattr(self.db, "path", None) else default_db_path()
        self.path_label.setText(f"Файл: {current}")
        self.data_dir_label.set_value(str(appdata_dir()))

    def choose_database(self) -> None:
        """SET-07: переключить рабочую базу на выбранный файл.

        Файл не копируется и не перезаписывается: приложение просто начнёт
        открывать его со следующего запуска. Так исключается потеря данных
        текущей базы из-за случайного выбора.
        """
        current = Path(self.db.path) if getattr(self.db, "path", None) else default_db_path()
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Выбрать файл базы данных",
            str(current),
            "База данных (*.db);;Все файлы (*)",
        )
        if not chosen:
            return
        target = Path(chosen)
        try:
            self.settings.set(SettingsKeys.DB_PATH, str(target))
            write_pointer(target)
        except (AppError, OSError) as error:
            message = getattr(error, "message", str(error))
            self._show(f"Не удалось сохранить путь: {message}", error=True)
            return
        self.refresh()
        self._show(
            f"Путь сохранён: {target}. Приложение откроет этот файл при "
            "следующем запуске."
        )

    def reset_database_path(self) -> None:
        """Вернуть путь по умолчанию и убрать файл-указатель."""
        try:
            self.settings.set(SettingsKeys.DB_PATH, str(default_db_path()))
            clear_pointer()
        except (AppError, OSError) as error:
            message = getattr(error, "message", str(error))
            self._show(f"Не удалось вернуть путь: {message}", error=True)
            return
        self.refresh()
        self._show(f"Путь по умолчанию: {default_db_path()}")

    def create_backup(self) -> None:
        """SET-07: сохранить копию **рабочей** базы.

        Раньше копировался файл по умолчанию, а не фактически открытый
        (``SET-07``/``DATA-02`` позволяет выбрать другой путь). При выбранной
        другой базе копия делалась с чужого файла — или падала, если файла по
        умолчанию не было.
        """
        current = Path(self.db.path) if getattr(self.db, "path", None) else default_db_path()
        name = f"student_planner_{clock.today().isoformat()}.db"
        target, _ = QFileDialog.getSaveFileName(
            self, "Сохранить резервную копию", name, "База данных (*.db)"
        )
        if not target:
            return
        try:
            self.db.commit()
            shutil.copy2(current, target)
        except OSError as error:
            self._show(f"Не удалось создать копию: {error}", error=True)
            return
        self._show(f"Копия сохранена: {target}")

    def restore_backup(self) -> None:
        """SET-07: заменить рабочую базу копией.

        После подмены файла приложение **закрывается**: соединение с прежней
        базой уже разорвано, и любое следующее действие страниц упало бы с
        обращением к закрытому соединению. Пользователь видит сообщение и
        перезапускает программу.
        """
        current = Path(self.db.path) if getattr(self.db, "path", None) else default_db_path()
        source, _ = QFileDialog.getOpenFileName(
            self, "Выбрать резервную копию", "", "База данных (*.db)"
        )
        if not source:
            return
        answer = QMessageBox.question(
            self, "Восстановление",
            "Заменить текущую базу данных копией? Приложение будет закрыто, "
            "после чего его нужно запустить снова.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.close()
            shutil.copy2(source, current)
        except OSError as error:
            self._show(f"Не удалось восстановить: {error}", error=True)
            return
        QMessageBox.information(
            self, "Восстановление",
            "Копия восстановлена. Приложение будет закрыто — запустите его снова.",
        )
        # Закрываем окно целиком: продолжать работу с закрытым соединением
        # нельзя, иначе каждое действие страниц даёт AttributeError.
        window = self.window()
        if window is not None:
            window.close()

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

        # SET-07: сбрасываются все пользовательские данные, но справочники
        # (предметы, тарифы, звонки, якоря) остаются. Экзамены забывались —
        # после «Сброса данных» они продолжали занимать календарь, хотя
        # сообщение обещало, что данные удалены.
        tables = (
            "homework", "transport_rides", "trip_confirmations", "strelka_topups",
            "schedule_overrides", "study_periods", "exams", "calendar_day_marks",
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
        show_message(self.message, text, error=error)


class SubjectDialog(BaseDialog):
    """SUBJ-01/SUBJ-04: создание и правка предмета справочника.

    С v1.1 (UI-14) здесь же задаются **оба** варианта сокращённого названия:
    среднее и минимальное. Поля предзаполнены действующими подписями, поэтому
    видно, что именно попадёт в расписание; прочерк ``-`` оставляет предмет с
    полным названием.
    """

    def __init__(self, db, parent: QWidget | None = None, subject=None) -> None:
        super().__init__(parent, "Предмет")
        self.subjects = SubjectRepository(db)
        self.names = SubjectNameService(db)
        self.subject = subject
        self._error_label = self.error_label()

        form = QFormLayout()
        form.setSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Компьютерные сети")
        if subject is not None:
            self.name_edit.setText(subject.name)
        form.addRow("Название:", self.name_edit)

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("МДК.01.02")
        if subject is not None:
            self.code_edit.setText(subject.code or "")
        form.addRow("Код:", self.code_edit)

        self.teacher_edit = QLineEdit()
        self.teacher_edit.setPlaceholderText("Ветрова К.В.")
        if subject is not None:
            self.teacher_edit.setText(subject.teacher or "")
        form.addRow("Преподаватель:", self.teacher_edit)

        self.room_edit = QLineEdit()
        self.room_edit.setPlaceholderText("Каб. №44")
        if subject is not None:
            self.room_edit.setText(subject.room or "")
        form.addRow("Кабинет:", self.room_edit)

        # UI-14: сокращения. Для нового предмета значения обновляются по мере
        # набора названия, если пользователь их ещё не правил сам.
        self.medium_edit = QLineEdit()
        self.medium_edit.setPlaceholderText("Разработка ПМ")
        self.medium_edit.setToolTip(
            "Среднее сокращение: для обычного показа расписания. "
            "Прочерк «-» — показывать полное название."
        )
        form.addRow("Среднее сокращение:", self.medium_edit)

        self.minimal_edit = QLineEdit()
        self.minimal_edit.setPlaceholderText("РПМ")
        self.minimal_edit.setToolTip(
            "Минимальное сокращение: для плотной сетки недели. "
            "Прочерк «-» — показывать полное название."
        )
        form.addRow("Минимальное сокращение:", self.minimal_edit)

        if subject is not None:
            medium, minimal = self.names.variants(subject.name)
            self._set_short_edit(self.medium_edit, medium)
            self._set_short_edit(self.minimal_edit, minimal)
        self._short_touched = False
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.medium_edit.textEdited.connect(self._mark_short_touched)
        self.minimal_edit.textEdited.connect(self._mark_short_touched)
        self.add_form(form)

        hint = QLabel(
            "Название обязательно, остальное — по желанию. Пара «код + название» "
            "не может повторяться (SUBJ-02); одинаковый код у разных предметов "
            "допустим. Сокращения показываются в расписании и правой панели, "
            "полное название остаётся в подсказке и в диалогах."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.finish("Сохранить")

    @staticmethod
    def _short_edit_text(value: str) -> str:
        """Текст поля: отказ от сокращения показывается прочерком."""
        return "-" if value == "" else value

    @staticmethod
    def _short_value(text: str) -> str | None:
        """Значение из поля: пусто — не задано, прочерк — не сокращать."""
        raw = (text or "").strip()
        if not raw:
            return None
        return "" if raw in ("-", "—") else raw

    def _set_short_edit(self, edit: QLineEdit, value: str) -> None:
        edit.setText(self._short_edit_text(value))

    def _mark_short_touched(self, _text: str) -> None:
        self._short_touched = True

    def _on_name_edited(self, _text: str) -> None:
        """Подставить предложенные сокращения, пока их не правили вручную."""
        if self._short_touched:
            return
        name = self.name_edit.text().strip()
        if not name:
            self.medium_edit.clear()
            self.minimal_edit.clear()
            return
        self._set_short_edit(
            self.medium_edit, auto_variant(name, "medium")
        )
        self._set_short_edit(
            self.minimal_edit, auto_variant(name, "short")
        )

    def apply(self) -> bool:
        name = self.name_edit.text().strip()
        if not name:
            raise AppError("Название предмета не может быть пустым (SUBJ-01).")
        code = self.code_edit.text().strip() or None
        teacher = self.teacher_edit.text().strip() or None
        room = self.room_edit.text().strip() or None
        medium = self._short_value(self.medium_edit.text())
        minimal = self._short_value(self.minimal_edit.text())

        if self.subject is None:
            self.subjects.create(name, code=code, teacher=teacher, room=room)
        else:
            self.subjects.update(
                self.subject.id, name=name, code=code, teacher=teacher, room=room
            )
            # Сокращения привязаны к названию: при переименовании их нужно
            # перенести, иначе правка «теряется» и подпись остаётся старой.
            if self.subject.name != name:
                self.names.rename(self.subject.name, name)
        self.names.set_variants(name, medium, minimal)
        return True


class SubjectsTab(QWidget):
    """SUBJ-04: справочник предметов и сокращения названий (UI-14).

    Сокращения правятся прямо в таблице: колонка «Сокращение» редактируется
    двойным щелчком и сохраняется по Enter или уходу фокуса. Это дешевле
    отдельного диалога и позволяет видеть все девять предметов сразу.
    """

    changed = Signal()

    #: Колонки с сокращениями в таблице предметов (UI-14).
    MEDIUM_COLUMN = 5
    MINIMAL_COLUMN = 6
    #: Все колонки сокращений — одной парой для циклов.
    SHORT_COLUMNS = (MEDIUM_COLUMN, MINIMAL_COLUMN)

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.subjects = SubjectRepository(db)
        self.names = SubjectNameService(db)
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Предметы используются в расписании и домашних заданиях (SUBJ-03). "
            "Используемый предмет удалить нельзя — его можно отключить: он "
            "перестанет предлагаться в списках, но останется в прошлых записях "
            "(SUBJ-04)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # -------------------------------- UI-14: сокращённые названия предметов
        abbreviations = Card("Сокращённые названия")
        self.short_hint = QLabel(
            "Короткие подписи нужны в колонке дня и в правой панели: полное "
            "название занимает три-четыре строки. У каждого предмета два "
            "независимых варианта: «Среднее» («Разработка ПМ», «Комп. сети») и "
            "«Минимальное» («РПМ», «КС», «Физ-ра») — для плотной сетки недели. "
            "Оба варианта правятся в таблице: двойной щелчок по ячейке, затем "
            "Enter. Прочерк «-» означает «показывать полное название», пустая "
            "ячейка — «брать из набора»."
        )
        self.short_hint.setObjectName("Small")
        self.short_hint.setWordWrap(True)
        abbreviations.add_widget(self.short_hint)

        short_row = QHBoxLayout()
        short_row.setSpacing(8)
        self.short_enabled_check = QCheckBox("Показывать сокращённые названия")
        self.short_enabled_check.setToolTip(
            "Выключите, чтобы расписание показывало полные названия предметов "
            "(UI-14). Сохранённые сокращения при этом не теряются."
        )
        self.short_enabled_check.toggled.connect(self._on_short_enabled_toggled)
        short_row.addWidget(self.short_enabled_check)

        short_row.addWidget(QLabel("Сейчас действует:"))
        self.short_style_combo = QComboBox()
        self.short_style_combo.addItem("Среднее", "medium")
        self.short_style_combo.addItem("Минимальное (плотная сетка)", "short")
        self.short_style_combo.setToolTip(
            "Какой из двух вариантов показывать в расписании. Второй вариант "
            "хранится рядом и включается без потери правок."
        )
        self.short_style_combo.currentIndexChanged.connect(self._on_short_style_changed)
        short_row.addWidget(self.short_style_combo)

        self.short_fill_button = QPushButton("Заполнить оба по наборам")
        self.short_fill_button.setObjectName("Flat")
        self.short_fill_button.setToolTip(
            "Записать в таблицу стандартные среднее и минимальное сокращения "
            "для всех предметов, включая новые. Собственные варианты будут "
            "заменены."
        )
        self.short_fill_button.clicked.connect(self.fill_short_names)
        short_row.addWidget(self.short_fill_button)

        self.short_reset_button = QPushButton("Убрать свои")
        self.short_reset_button.setObjectName("Flat")
        self.short_reset_button.setToolTip(
            "Удалить переопределения: оба варианта снова берутся из стандартных "
            "наборов."
        )
        self.short_reset_button.clicked.connect(self.reset_short_names)
        short_row.addWidget(self.short_reset_button)
        short_row.addStretch(1)
        abbreviations.add_layout(short_row)
        layout.addWidget(abbreviations)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Название", "Преподаватель", "Кабинет", "Код", "Активен",
                "Среднее сокращение", "Минимальное сокращение",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        # UI-14: «Название» забирает остаток ширины, а короткие колонки
        # поджимаются по содержимому. При равномерном Stretch на все семь
        # колонок каждой доставалось по 225 px, и «Документирование программных
        # средств» обрезалось, хотя места на экране хватало.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4, *self.SHORT_COLUMNS):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        # Перенос строк в ячейках: «Документирование программных средств» и
        # «Иностранный язык в профессиональной деятельности» не влезают в одну
        # строку таблицы, а обрезать название справочника нельзя — по нему
        # пользователь и ищет предмет.
        self.table.setWordWrap(True)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        # Двойной щелчок по колонкам сокращений открывает правку ячейки, а по
        # остальным — диалог предмета: иначе сокращение правилось бы через
        # модальное окно, которого пользователь не ждал.
        self.table.doubleClicked.connect(self._on_double_click)
        # UI-14: правка сокращения сохраняется по Enter и по уходу фокуса —
        # отдельной кнопки «Сохранить» нет, как и у редактора сетки (GRID-02).
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        # Сообщение и пустое состояние идут до кнопок: под ними они уходили
        # за нижнюю границу вкладки, когда таблица занимала всю высоту.
        self.empty_label = QLabel("Предметов нет — добавьте первый кнопкой «Добавить»")
        self.empty_label.setObjectName("Empty")
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

        self.message = QLabel()
        self.message.setObjectName("Small")
        self.message.setWordWrap(True)
        self.message.setVisible(False)
        layout.addWidget(self.message)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self.add_button = QPushButton("Добавить")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self.add_subject)
        buttons.addWidget(self.add_button)

        self.edit_button = QPushButton("Изменить")
        self.edit_button.clicked.connect(self.edit_subject)
        self.edit_button.setEnabled(False)
        buttons.addWidget(self.edit_button)

        self.toggle_button = QPushButton("Отключить")
        self.toggle_button.clicked.connect(self.toggle_subject)
        self.toggle_button.setEnabled(False)
        buttons.addWidget(self.toggle_button)

        self.delete_button = QPushButton("Удалить")
        self.delete_button.clicked.connect(self.delete_subject)
        self.delete_button.setEnabled(False)
        buttons.addWidget(self.delete_button)

        buttons.addStretch(1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ данные
    def refresh(self) -> None:
        # UI-14: настройки сокращений перечитываются при каждом обновлении,
        # иначе правка из другого места страницы показывала бы старое значение.
        self.names = SubjectNameService(self.db)
        self._loading = True
        self.table.blockSignals(True)
        try:
            self.short_enabled_check.setChecked(self.names.enabled)
            index = self.short_style_combo.findData(self.names.style)
            if index >= 0:
                self.short_style_combo.setCurrentIndex(index)
            subjects = self.subjects.all()
            self.table.setRowCount(len(subjects))
            for row, subject in enumerate(subjects):
                self.table.setItem(row, 0, QTableWidgetItem(subject.name))
                self.table.setItem(row, 1, QTableWidgetItem(subject.teacher or "—"))
                self.table.setItem(row, 2, QTableWidgetItem(subject.room or "—"))
                self.table.setItem(row, 3, QTableWidgetItem(subject.code or "—"))
                state = "да" if subject.is_active else "нет"
                self.table.setItem(row, 4, QTableWidgetItem(state))
                # UI-14: два независимых варианта сокращения. В ячейке лежит
                # действующая подпись, а в подсказке видно, задана она вручную
                # или взята из набора: иначе непонятно, что именно изменится.
                for column, style in (
                    (self.MEDIUM_COLUMN, "medium"),
                    (self.MINIMAL_COLUMN, "short"),
                ):
                    item = QTableWidgetItem(self.names.short(subject.name, style))
                    caption = "Среднее" if style == "medium" else "Минимальное"
                    source = (
                        "задано вручную"
                        if self.names.table.is_custom(subject.name, style)
                        else "из набора"
                    )
                    item.setToolTip(
                        f"{caption} сокращение ({source}). Двойной щелчок — "
                        "правка, Enter — сохранить. Прочерк «-» — показывать "
                        "полное название, пустая ячейка — взять из набора."
                    )
                    self.table.setItem(row, column, item)
                # Идентификатор хранится в первой ячейке строки.
                self.table.item(row, 0).setData(
                    Qt.ItemDataRole.UserRole, subject.id
                )
                if not subject.is_active:
                    for column in range(self.table.columnCount()):
                        item = self.table.item(row, column)
                        if item is not None:
                            item.setForeground(Qt.GlobalColor.darkGray)
        finally:
            self.table.blockSignals(False)
            self._loading = False

        # UI-14: при выключенных сокращениях колонки скрыты, кнопки неактивны —
        # правка невидимой колонки выглядела бы как «ничего не происходит».
        enabled = self.names.enabled
        for column in (self.MEDIUM_COLUMN, self.MINIMAL_COLUMN):
            self.table.setColumnHidden(column, not enabled)
        self._set_short_controls_enabled(enabled)

        self.empty_label.setVisible(not subjects)
        self._on_selection_changed()

    def selected_subject(self):
        """Предмет из выделенной строки таблицы или ``None``."""
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        subject_id = item.data(Qt.ItemDataRole.UserRole)
        if subject_id is None:
            return None
        return self.subjects.by_id(int(subject_id))

    def _on_selection_changed(self) -> None:
        subject = self.selected_subject()
        self.edit_button.setEnabled(subject is not None)
        self.delete_button.setEnabled(subject is not None)
        self.toggle_button.setEnabled(subject is not None)
        if subject is None:
            self.toggle_button.setText("Отключить")
        else:
            self.toggle_button.setText(
                "Включить" if not subject.is_active else "Отключить"
            )

    # ---------------------------------------------------------- сокращения (UI-14)
    def _column_style(self, column: int) -> str | None:
        """Вариант сокращения по номеру колонки: ``medium`` или ``short``."""
        if column == self.MEDIUM_COLUMN:
            return "medium"
        if column == self.MINIMAL_COLUMN:
            return "short"
        return None

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """UI-14: сохранить сокращение, изменённое в таблице.

        Сохранение идёт по факту правки ячейки, как у редактора сетки
        (GRID-02): общего «Сохранить» у таблицы нет. Правка одной колонки не
        трогает вторую: среднее и минимальное сокращения независимы. Название
        строки берётся из первой колонки, а не из текста ячейки: пользователь
        мог переименовать предмет, и тогда старое сокращение ему не подходит.
        """
        style = self._column_style(item.column())
        if self._loading or style is None:
            return
        row = item.row()
        name_item = self.table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text().strip()
        if not name:
            return
        raw = item.text().strip()
        # Пустая ячейка — «взять из набора» (None), прочерк — «не сокращать».
        value: str | None = None if raw == "" else ("" if raw in ("-", "—") else raw)
        try:
            self.names.set_variant(name, style, value)
        except AppError as error:
            self._notify(error.message, error=True)
            self.refresh()
            return
        caption = "Среднее" if style == "medium" else "Минимальное"
        if value is None:
            self._notify(f"«{name}»: {caption.lower()} — из набора")
        elif value == "":
            self._notify(f"«{name}»: показывается полностью")
        else:
            self._notify(f"«{name}»: {caption.lower()} сокращение «{value}»")
        # Подсказка «из набора / задано вручную» устарела — обновляем строку,
        # но только её, чтобы не сбить курсор в других ячейках.
        self._refresh_row(row, name)
        self.changed.emit()

    def _refresh_row(self, row: int, name: str) -> None:
        """Переписать подсказки двух ячеек сокращений после правки."""
        for column, style in (
            (self.MEDIUM_COLUMN, "medium"),
            (self.MINIMAL_COLUMN, "short"),
        ):
            item = self.table.item(row, column)
            if item is None:
                continue
            caption = "Среднее" if style == "medium" else "Минимальное"
            source = (
                "задано вручную"
                if self.names.table.is_custom(name, style)
                else "из набора"
            )
            item.setToolTip(
                f"{caption} сокращение ({source}). Двойной щелчок — правка, "
                "Enter — сохранить. Прочерк «-» — показывать полное название, "
                "пустая ячейка — взять из набора."
            )

    def _on_double_click(self, index) -> None:
        """UI-14: правка ячейки сокращения — только в своих колонках.

        В остальных колонках двойной щелчок по-прежнему открывает диалог
        предмета: это привычный способ правки справочника (SUBJ-04).
        """
        if index.column() in self.SHORT_COLUMNS:
            self.table.editItem(self.table.item(index.row(), index.column()))
            return
        self.edit_subject()

    def _on_short_enabled_toggled(self, checked: bool) -> None:
        """UI-14: включение и выключение показа сокращений без перезапуска."""
        if self._loading:
            return
        try:
            self.names.set_enabled(checked)
        except AppError as error:
            self._notify(error.message, error=True)
            return
        self.short_hint.setVisible(True)
        for column in self.SHORT_COLUMNS:
            self.table.setColumnHidden(column, not checked)
        self._set_short_controls_enabled(checked)
        self._notify(
            "Сокращённые названия включены" if checked
            else "Показываются полные названия предметов"
        )
        self.changed.emit()

    def _on_short_style_changed(self) -> None:
        """UI-14: смена набора сокращений («средние» или «минимальные»)."""
        if self._loading:
            return
        style = self.short_style_combo.currentData()
        try:
            self.names.set_style(style)
        except AppError as error:
            self._notify(error.message, error=True)
            return
        caption = "минимальные" if style == "short" else "средние"
        self._notify(f"Набор сокращений: {caption}")
        self.refresh()
        self.changed.emit()

    def fill_short_names(self) -> None:
        """UI-14: записать в таблицу стандартные подписи для всех предметов.

        Заполняются **оба** варианта сразу: средний и минимальный. Иначе после
        массового заполнения пришлось бы отдельно проходить по колонке, хотя
        наборы для неё уже есть в коде.
        """
        answer = QMessageBox.question(
            self, "Сокращённые названия",
            "Записать среднее и минимальное сокращения из наборов для всех "
            "предметов? Собственные варианты будут заменены, новые предметы "
            "получат подписи.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        overrides: dict[str, tuple[str | None, str | None]] = {
            subject.name: (
                self.names.suggested(subject.name, "medium"),
                self.names.suggested(subject.name, "short"),
            )
            for subject in self.subjects.all()
            if subject.name
        }
        try:
            self.names.save_overrides(overrides)
        except AppError as error:
            self._notify(error.message, error=True)
            return
        self.refresh()
        self._notify(
            f"Подписи заполнены: {len(overrides)} предметов, оба варианта"
        )
        self.changed.emit()

    def reset_short_names(self) -> None:
        """UI-14: убрать переопределения обоих вариантов."""
        answer = QMessageBox.question(
            self, "Сокращённые названия",
            "Убрать свои сокращения? Оба варианта снова будут браться из "
            "стандартных наборов, правки в таблице будут потеряны.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.names.reset_to_stock()
        except AppError as error:
            self._notify(error.message, error=True)
            return
        self.refresh()
        self._notify("Свои сокращения убраны: действуют стандартные наборы")
        self.changed.emit()

    def _set_short_controls_enabled(self, enabled: bool) -> None:
        """UI-14: правка сокращений недоступна при выключенном показе."""
        for widget in (
            self.short_style_combo, self.short_fill_button, self.short_reset_button,
        ):
            widget.setEnabled(enabled)

    # ------------------------------------------------------------------ запись
    def add_subject(self) -> None:
        dialog = SubjectDialog(self.db, self)
        if dialog.exec():
            self.refresh()
            self._notify("Предмет добавлен")
            self.changed.emit()

    def edit_subject(self) -> None:
        subject = self.selected_subject()
        if subject is None:
            return
        dialog = SubjectDialog(self.db, self, subject=subject)
        if dialog.exec():
            self.refresh()
            self._notify("Изменения сохранены")
            self.changed.emit()

    def toggle_subject(self) -> None:
        """SUBJ-04: отключение вместо удаления используемого предмета."""
        subject = self.selected_subject()
        if subject is None:
            return
        try:
            self.subjects.set_active(subject.id, not subject.is_active)
        except AppError as error:
            self._notify(error.message, error=True)
            return
        self.refresh()
        self._notify("Предмет включён" if not subject.is_active else "Предмет отключён")
        self.changed.emit()

    def delete_subject(self) -> None:
        """SUBJ-04: удаление разрешено, только если предмет нигде не используется.

        Если предмет уже стоит в расписании, предлагается не ошибка, а выбор:
        отключить его или отказаться (SUBJ-04, HW-09).
        """
        subject = self.selected_subject()
        if subject is None:
            return

        references = self.subjects.references(subject.id)
        if references:
            answer = QMessageBox.question(
                self,
                "Предмет используется",
                f"«{subject.name}» используется: {references}.\n\n"
                "Удалить его нельзя, потому что он останется в прошлых записях. "
                "Отключить предмет? Он перестанет предлагаться в списках, но "
                "расписание и задания сохранятся (SUBJ-04).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.subjects.set_active(subject.id, False)
                self.refresh()
                self._notify("Предмет отключён")
                self.changed.emit()
            return

        answer = QMessageBox.question(
            self,
            "Удалить предмет",
            f"Удалить предмет «{subject.name}»? Он нигде не используется, поэтому "
            "удаление безопасно.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.subjects.delete(subject.id)
        except AppError as error:
            self._notify(error.message, error=True)
            return
        self.refresh()
        self._notify("Предмет удалён")
        self.changed.emit()

    def _notify(self, text: str, *, error: bool = False) -> None:
        show_message(self.message, text, error=error)


class SettingsPage(QWidget):
    """SET-01: разделы Общие, Предметы, Недели, Звонки, Транспорт, Календарь, Данные."""

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
        self.subjects_tab = SubjectsTab(db)
        self.weeks_tab = WeeksTab(db)
        self.bells_tab = BellsTab(db)
        self.transport_tab = TransportTab(db)
        self.calendar_tab = CalendarTab(db)
        self.data_tab = DataTab(db)

        # SET-04: «Звонки» тоже уведомляют окно — правка блоков меняет время
        # пар в расписании, и без сигнала страница расписания и правая панель
        # оставались со старыми временами до ручного переключения раздела.
        for tab in (self.general_tab, self.subjects_tab, self.weeks_tab,
                    self.bells_tab, self.transport_tab, self.calendar_tab,
                    self.data_tab):
            tab.changed.connect(self._on_changed)

        for tab, caption in (
            (self.general_tab, "Общие"),
            (self.subjects_tab, "Предметы"),
            (self.weeks_tab, "Недели"),
            (self.bells_tab, "Звонки"),
            (self.transport_tab, "Транспорт"),
            (self.calendar_tab, "Календарь"),
            (self.data_tab, "Данные"),
        ):
            self.tabs.addTab(tab, caption)
        layout.addWidget(self.tabs, 1)

        # SET-08: экран заполняется сразу, не дожидаясь первого refresh() от
        # главного окна — иначе открытие «Настроек» до любой правки показывало
        # бы пустые поля.
        self.refresh()

    def refresh(self) -> None:
        for tab in (self.general_tab, self.subjects_tab, self.weeks_tab,
                    self.bells_tab, self.transport_tab, self.calendar_tab,
                    self.data_tab):
            tab.refresh()

    def _on_changed(self) -> None:
        self.changed.emit()


__all__ = ["SettingsPage"]
