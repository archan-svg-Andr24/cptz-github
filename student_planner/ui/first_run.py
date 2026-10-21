"""Мастер первого запуска (§2.5, §36.15: FIRST-01…FIRST-16).

Порядок шагов соответствует §36.15:

1. FIRST-15 — имя и группа (два поля; отказ оставляет пустые строки, профиль
   показывает «Не указано»);
2. FIRST-16 — предложение ввести расписание: «Ввести расписание» открывает
   редактор недельной сетки, «По умолчанию» не изменяет ни одной строки
   ``schedule_templates``;
3. FIRST-06 — начальный остаток «Стрелки» (запись пополнения, WAL-09);
4. FIRST-14 — число засчитанных поездок и дата начала периода (FARE-12);
   отказ даёт ``cnt0 = 0`` и пустой якорь, счётчик помечается приближённым.

FIRST-04: повторный запуск мастер не показывает — он вызывается только тогда,
когда база создана этим запуском. Собственного ключа «мастер показан» в реестре
§30 нет, поэтому флаг не заводится.
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import clock
from ..core.errors import AppError
from ..core.settings_registry import SettingsKeys
from ..core.settings_service import SettingsService
from ..core.transport_service import WalletService
from .theme import COLORS, stylesheet
from .widgets import Card, MetricRow, Separator

log = logging.getLogger(__name__)

#: Шаги мастера в порядке §36.15.
STEPS = (
    "Имя и группа",
    "Расписание",
    "Остаток «Стрелки»",
    "Начало учёта",
)


class FirstRunWizard(QDialog):
    """Мастер первого запуска: четыре шага, каждый можно пропустить."""

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = SettingsService(db)
        self.setStyleSheet(stylesheet())
        self.setWindowTitle("Первый запуск")
        self.setModal(True)
        self.resize(600, 470)

        self._step = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("Title")
        outer.addWidget(self.title_label)

        self.step_label = QLabel()
        self.step_label.setObjectName("Muted")
        outer.addWidget(self.step_label)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_profile_step())
        self.stack.addWidget(self._build_schedule_step())
        self.stack.addWidget(self._build_wallet_step())
        self.stack.addWidget(self._build_anchor_step())
        outer.addWidget(self.stack, 1)

        navigation = QHBoxLayout()
        navigation.setSpacing(8)

        self.skip_button = QPushButton("Пропустить")
        self.skip_button.setToolTip("Пропустить шаг, ничего не меняя")
        self.skip_button.clicked.connect(self.skip_step)
        navigation.addWidget(self.skip_button)

        navigation.addStretch(1)

        self.back_button = QPushButton("Назад")
        self.back_button.clicked.connect(self.go_back)
        navigation.addWidget(self.back_button)

        self.next_button = QPushButton("Далее")
        self.next_button.setObjectName("Primary")
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self.go_next)
        navigation.addWidget(self.next_button)

        self.finish_button = QPushButton("Начать работу")
        self.finish_button.setObjectName("Primary")
        self.finish_button.setDefault(True)
        self.finish_button.clicked.connect(self.finish)
        navigation.addWidget(self.finish_button)
        outer.addLayout(navigation)

        self._update_step()

    # ---------------------------------------------------- шаг 1: FIRST-15
    def _build_profile_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Имя и группа показываются в левой панели (UI-04). Оба поля можно "
            "оставить пустыми — тогда профиль покажет «Не указано»."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        card = Card("Профиль студента")
        form = QFormLayout()
        form.setSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Иван Иванов")
        form.addRow("Имя студента:", self.name_edit)

        self.group_edit = QLineEdit()
        self.group_edit.setPlaceholderText("ИС-21")
        form.addRow("Группа:", self.group_edit)
        card.add_layout(form)
        layout.addWidget(card)

        note = QLabel("Enter сохраняет значение и переходит к следующему шагу.")
        note.setObjectName("Small")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    # ---------------------------------------------------- шаг 2: FIRST-16
    def _build_schedule_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Стартовый набор Приложения А уже загружен: два типа недель, профили "
            "звонков, девять предметов, тарифы и шаблоны поездок.\n"
            "Можно сразу ввести расписание своей группы — по одной ячейке, "
            "кнопкой «Готово» в редакторе. Кнопка «По умолчанию» ниже оставляет "
            "стартовый набор нетронутым; оба пути допустимы."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        card = Card("Расписание недели")
        self.schedule_choice = MetricRow("Выбор", "по умолчанию")
        card.add_widget(self.schedule_choice)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.edit_grid_button = QPushButton("Ввести расписание…")
        self.edit_grid_button.setObjectName("Primary")
        self.edit_grid_button.clicked.connect(self.open_grid_editor)
        buttons.addWidget(self.edit_grid_button)

        self.default_button = QPushButton("По умолчанию")
        self.default_button.clicked.connect(self.keep_default_schedule)
        buttons.addWidget(self.default_button)
        buttons.addStretch(1)
        card.add_layout(buttons)
        layout.addWidget(card)

        note = QLabel(
            "Передумать можно в любой момент: «Расписание → Изменить чередование "
            "недель…» или кнопка «Вернуть стартовый набор недели» в редакторе "
            "(GRID-11)."
        )
        note.setObjectName("Small")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def open_grid_editor(self) -> None:
        """FIRST-16, путь «Готово»: правки сохраняются по ячейкам."""
        from .grid_editor import GridEditorDialog

        dialog = GridEditorDialog(self.db, clock.today(), self)
        dialog.exec()
        self.schedule_choice.set_value("введено вручную")

    def keep_default_schedule(self) -> None:
        """FIRST-16, путь «По умолчанию»: ни одна строка шаблона не меняется."""
        self.schedule_choice.set_value("стартовый набор без изменений")
        log.info("FIRST-16: выбран путь «По умолчанию»")

    # ----------------------------------------------------- шаг 3: FIRST-06
    def _build_wallet_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Остаток на карте нужен для «Потрачено», «Остаток» и «Экономия» "
            "(WAL-01). Если остаток неизвестен, снимите флажок — тогда "
            "показывается «Остаток не задан», а предупреждение о низком остатке "
            "не выводится (WAL-05)."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        card = Card("Начальный остаток «Стрелки»")
        self.ask_balance_check = QCheckBox("Указать фактический остаток на карте")
        self.ask_balance_check.setChecked(True)
        self.ask_balance_check.toggled.connect(self._on_ask_balance)
        card.add_widget(self.ask_balance_check)

        form = QFormLayout()
        form.setSpacing(8)
        self.wallet_date_edit = QDateEdit()
        self.wallet_date_edit.setCalendarPopup(True)
        self.wallet_date_edit.setDisplayFormat("dd.MM.yyyy")
        today = clock.today()
        self.wallet_date_edit.setDate(QDate(today.year, today.month, today.day))
        form.addRow("Дата остатка:", self.wallet_date_edit)

        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("Например, 150.00")
        form.addRow("Остаток, ₽:", self.amount_edit)
        card.add_layout(form)
        layout.addWidget(card)

        self.wallet_note = QLabel()
        self.wallet_note.setObjectName("Small")
        self.wallet_note.setWordWrap(True)
        layout.addWidget(self.wallet_note)
        layout.addStretch(1)
        return page

    def _on_ask_balance(self, checked: bool) -> None:
        self.wallet_date_edit.setEnabled(checked)
        self.amount_edit.setEnabled(checked)
        self.wallet_note.setText(
            "" if checked else
            "Остаток не будет задан. Пополнение можно добавить позже на странице "
            "«Расходы на транспорт» (WAL-06)."
        )

    # ---------------------------------------------------- шаг 4: FIRST-14
    def _build_anchor_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Приложение считает поездки «Стрелки» скользящим периодом 30 дней "
            "(ALG-02). Если на карте уже есть поездки в текущем периоде, укажите "
            "их число и дату начала — иначе счётчик до конца первого периода "
            "будет приближённым."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        card = Card("Параметры начала учёта")
        form = QFormLayout()
        form.setSpacing(8)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(0, 9999)
        self.count_spin.setToolTip("0 = учёт с нуля (FARE-12)")
        form.addRow("Поездок уже засчитано:", self.count_spin)

        self.anchor_date_edit = QDateEdit()
        self.anchor_date_edit.setCalendarPopup(True)
        self.anchor_date_edit.setDisplayFormat("dd.MM.yyyy")
        today = clock.today()
        self.anchor_date_edit.setDate(QDate(today.year, today.month, today.day))
        form.addRow("Период начался:", self.anchor_date_edit)

        self.no_anchor_check = QCheckBox("Период начнётся с первой поездки")
        self.no_anchor_check.setChecked(True)
        self.no_anchor_check.toggled.connect(
            lambda checked: self.anchor_date_edit.setEnabled(not checked)
        )
        form.addRow("", self.no_anchor_check)
        card.add_layout(form)
        layout.addWidget(card)

        note = QLabel(
            "Дата позже сегодняшней отклоняется (DATA-21). Обе величины можно "
            "изменить позже в «Настройки → Транспорт»; это запускает полный "
            "пересчёт (CALC-04)."
        )
        note.setObjectName("Small")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ навигация
    @property
    def step(self) -> int:
        return self._step

    def _update_step(self) -> None:
        self.stack.setCurrentIndex(self._step)
        self.title_label.setText(STEPS[self._step])
        self.step_label.setText(f"Шаг {self._step + 1} из {len(STEPS)}")
        self.back_button.setVisible(self._step > 0)
        self.skip_button.setVisible(self._step < len(STEPS) - 1)
        self.next_button.setVisible(self._step < len(STEPS) - 1)
        self.finish_button.setVisible(self._step == len(STEPS) - 1)

    def go_next(self) -> None:
        if self._step == 0 and not self._save_profile():
            return
        if self._step == 1 and not self._confirm_schedule():
            return
        if self._step == 2 and not self._save_wallet():
            return
        if self._step == 3 and not self._save_anchor():
            return
        self._step = min(self._step + 1, len(STEPS) - 1)
        self._update_step()

    def go_back(self) -> None:
        self._step = max(self._step - 1, 0)
        self._update_step()

    def skip_step(self) -> None:
        """Отказ допустим на каждом шаге (FIRST-15, FIRST-16, FIRST-14)."""
        log.info("Шаг мастера пропущен: %s", STEPS[self._step])
        self._step = min(self._step + 1, len(STEPS) - 1)
        self._update_step()

    # ------------------------------------------------------------------ сохранение
    def _save_profile(self) -> bool:
        """FIRST-15: отказ оставляет пустые строки, это допустимо."""
        try:
            self.settings.set_student_profile(
                self.name_edit.text().strip(), self.group_edit.text().strip()
            )
        except AppError as error:
            QMessageBox.warning(self, "Профиль", error.message)
            return False
        return True

    def _confirm_schedule(self) -> bool:
        """FIRST-16: вопрос не блокирует переход — выбор уже сделан кнопками."""
        return True

    def _save_wallet(self) -> bool:
        """FIRST-06/WAL-09: начальный остаток — запись пополнения."""
        if not self.ask_balance_check.isChecked():
            return True
        text = self.amount_edit.text().strip().replace(",", ".")
        if not text:
            return True
        value = self.wallet_date_edit.date()
        try:
            WalletService(self.db).add_initial(
                text,
                topup_date=date(value.year(), value.month(), value.day()),
            )
        except AppError as error:
            QMessageBox.warning(self, "Остаток «Стрелки»", error.message)
            return False
        return True

    def _save_anchor(self) -> bool:
        """FIRST-14/FARE-12: cnt0 и дата начала периода; отказ даёт 0 и пусто."""
        count = self.count_spin.value()
        anchor = ""
        if not self.no_anchor_check.isChecked():
            value = self.anchor_date_edit.date()
            anchor = date(value.year(), value.month(), value.day()).isoformat()

        changes = {
            SettingsKeys.STRELKA_INITIAL_RIDE_COUNT: str(count),
            SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE: anchor,
        }
        if not any(value for value in changes.values()):
            return True
        try:
            self.settings.set_many(changes)
        except AppError as error:
            QMessageBox.warning(self, "Начало учёта", error.message)
            return False
        return True

    # ------------------------------------------------------------------ финал
    def finish(self) -> None:
        if self._step == 3 and not self._save_anchor():
            return
        log.info("Мастер первого запуска завершён")
        self.accept()


__all__ = ["FirstRunWizard", "STEPS"]
