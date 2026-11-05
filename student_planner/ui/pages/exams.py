"""Страница «Экзамены» (§13: EXAM-01…EXAM-12).

Список испытаний сессии с обратным отсчётом, форма создания и правки,
быстрая отметка «сдан». Наследует оформление остальных страниц: карточки
тем, бейджи, пустое состояние, сообщения под формой.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QDate

from ...core import clock
from ...core.dates import format_display
from ...core.errors import AppError
from ...core.exam_service import ExamRow, ExamService
from ...core.models import ExamStatus
from ...core.subject_names import SubjectNameService
from ..dialogs import BaseDialog
from ..widgets import (
    Badge,
    Card,
    EmptyState,
    MetricRow,
    SectionHeader,
    show_message,
)


#: Фильтры списка: (ключ, подпись). «Все» включает сданные.
FILTERS: tuple[tuple[str, str], ...] = (
    ("upcoming", "Не сданные"),
    ("all", "Все"),
    ("passed", "Сданные"),
    ("overdue", "Прошедшие без отметки"),
)


class ExamDialog(BaseDialog):
    """EXAM-04: форма создания и правки испытания."""

    def __init__(self, db, *, exam_id: int | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent, "Испытание")
        self.db = db
        self.exam_id = exam_id
        self.service = ExamService(db)

        form = QFormLayout()
        form.setSpacing(8)

        self.subject_combo = QComboBox()
        for subject in self.service.subject_choices():
            self.subject_combo.addItem(subject.name, subject.id)
        form.addRow("Предмет:", self.subject_combo)

        self.kind_combo = QComboBox()
        for key, caption in self.service.kind_choices():
            self.kind_combo.addItem(caption, key)
        form.addRow("Вид:", self.kind_combo)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate())
        form.addRow("Дата:", self.date_edit)

        self.time_edit = QLineEdit()
        self.time_edit.setPlaceholderText("ЧЧ:ММ (необязательно)")
        form.addRow("Время:", self.time_edit)

        self.room_edit = QLineEdit()
        self.room_edit.setPlaceholderText("например, 312")
        form.addRow("Кабинет:", self.room_edit)

        self.teacher_edit = QLineEdit()
        form.addRow("Преподаватель:", self.teacher_edit)

        self.status_combo = QComboBox()
        for key, caption in self.service.status_choices():
            self.status_combo.addItem(caption, key)
        form.addRow("Состояние:", self.status_combo)

        self.comment_edit = QLineEdit()
        form.addRow("Заметка:", self.comment_edit)

        self.layout_.addLayout(form)

        self.message = self.error_label()

        # Свои кнопки вместо стандартной панели: у испытания подпись «Отмена»
        # рядом с «Сохранить» читается лучше, чем унаследованный набор.
        # Стандартную панель убираем совсем — иначе она остаётся скрытым
        # дочерним элементом и перехватывает клавишу Enter.
        self.buttons.setParent(None)
        self.buttons.deleteLater()

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.save_button = QPushButton("Сохранить")
        self.save_button.setObjectName("Primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        row.addWidget(self.save_button)
        self.layout_.addLayout(row)

        if exam_id is not None:
            self._load()

    def _load(self) -> None:
        exam = self.service.repo.require(self.exam_id)
        # Отключённого предмета нет в списке активных: добавляем его отдельным
        # пунктом, иначе «Сохранить» перевешивает испытание на первый предмет.
        subject = self.service.subject_name(exam.subject_id)
        index = self.subject_combo.findData(exam.subject_id)
        if index >= 0:
            self.subject_combo.setCurrentIndex(index)
        else:
            self.subject_combo.addItem(f"{subject} (отключён)", exam.subject_id)
            self.subject_combo.setCurrentIndex(self.subject_combo.count() - 1)
        index = self.kind_combo.findData(exam.kind)
        if index >= 0:
            self.kind_combo.setCurrentIndex(index)
        self.date_edit.setDate(QDate(exam.date.year, exam.date.month, exam.date.day))
        self.time_edit.setText(exam.time or "")
        self.room_edit.setText(exam.room or "")
        self.teacher_edit.setText(exam.teacher or "")
        index = self.status_combo.findData(exam.status)
        if index >= 0:
            self.status_combo.setCurrentIndex(index)
        self.comment_edit.setText(exam.comment or "")

    def save(self) -> None:
        subject_id = self.subject_combo.currentData()
        if subject_id is None:
            show_message(self.message, "Сначала добавьте предмет в справочнике.", error=True)
            return
        picked = self.date_edit.date()
        when = date(picked.year(), picked.month(), picked.day())
        payload = {
            "subject_id": int(subject_id),
            "when": when,
            "kind": self.kind_combo.currentData(),
            "room": self.room_edit.text(),
            "teacher": self.teacher_edit.text(),
            "status": self.status_combo.currentData(),
            "comment": self.comment_edit.text(),
        }
        try:
            if self.exam_id is None:
                self.service.repo.create(
                    int(subject_id),
                    when,
                    kind=payload["kind"],
                    time=self.time_edit.text(),
                    room=payload["room"],
                    teacher=payload["teacher"],
                    status=payload["status"],
                    comment=payload["comment"],
                )
            else:
                self.service.repo.update(
                    self.exam_id,
                    subject_id=int(subject_id),
                    when=when,
                    kind=payload["kind"],
                    time=self.time_edit.text(),
                    room=payload["room"],
                    teacher=payload["teacher"],
                    status=payload["status"],
                    comment=payload["comment"],
                )
        except AppError as error:
            show_message(self.message, error.message, error=True)
            return
        self.accept()


class ExamRowWidget(QFrame):
    """Строка испытания: предмет, вид, дата, обратный отсчёт, действия.

    ``subject_caption`` — подпись по настройкам сокращённых названий (UI-14):
    полное название остаётся в подсказке и в самой строке данных.
    """

    edit_requested = Signal(int)
    delete_requested = Signal(int)
    passed_requested = Signal(int)

    def __init__(
        self,
        row: ExamRow,
        parent: QWidget | None = None,
        *,
        subject_caption: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.row = row
        self.exam_id = row.exam.id
        self.setObjectName("Card")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        caption = subject_caption or row.subject_name
        self.subject_label = QLabel(caption)
        self.subject_label.setObjectName("SubjectName")
        if caption != row.subject_name:
            self.subject_label.setToolTip(row.subject_name)
        title_row.addWidget(self.subject_label)

        self.kind_badge = Badge(row.exam.kind_short, "neutral")
        title_row.addWidget(self.kind_badge)

        if row.is_passed:
            title_row.addWidget(Badge("Сдан", "success"))
        elif row.exam.status == ExamStatus.POSTPONED:
            title_row.addWidget(Badge("Перенесён", "warning"))
        title_row.addStretch(1)
        left.addLayout(title_row)

        details = [row.when_caption]
        if row.exam.room:
            details.append(f"каб. {row.exam.room}")
        if row.exam.teacher:
            details.append(row.exam.teacher)
        self.details_label = QLabel(" · ".join(details))
        self.details_label.setObjectName("Muted")
        left.addWidget(self.details_label)

        if row.exam.comment:
            comment = QLabel(row.exam.comment)
            comment.setObjectName("Small")
            comment.setWordWrap(True)
            left.addWidget(comment)

        layout.addLayout(left, 1)

        # Отсчёт: красный для «сегодня/завтра», обычный — дальше.
        self.countdown_label = QLabel(row.countdown)
        self.countdown_label.setObjectName(
            "WarningText" if row.days_left <= 1 and not row.is_passed else "Muted"
        )
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.countdown_label)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        if not row.is_passed:
            self.passed_button = QPushButton("Сдан")
            self.passed_button.setObjectName("Flat")
            self.passed_button.setToolTip("Отметить испытание сданным")
            self.passed_button.clicked.connect(lambda: self.passed_requested.emit(self.exam_id))
            actions.addWidget(self.passed_button)
        else:
            self.passed_button = None

        self.edit_button = QPushButton("Изменить")
        self.edit_button.setObjectName("Flat")
        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(self.exam_id))
        actions.addWidget(self.edit_button)

        self.delete_button = QPushButton("Удалить")
        self.delete_button.setObjectName("Flat")
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.exam_id))
        actions.addWidget(self.delete_button)
        layout.addLayout(actions)


class ExamsPage(QWidget):
    """§13: страница испытаний сессии (EXAM-01…EXAM-12)."""

    changed = Signal()

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._today: date = clock.today()
        self._filter = "upcoming"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = SectionHeader("Экзамены и зачёты")
        layout.addWidget(header)

        self.add_button = QPushButton("Добавить испытание")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self.add_exam)
        header.add_action(self.add_button)

        # ------------------------------------------------------------ сводка
        summary = Card("Сессия")
        self.total_row = MetricRow("Всего испытаний")
        summary.add_widget(self.total_row)
        self.planned_row = MetricRow("Предстоит")
        summary.add_widget(self.planned_row)
        self.next_row = MetricRow("Ближайшее")
        summary.add_widget(self.next_row)
        layout.addWidget(summary)

        # ----------------------------------------------------------- фильтры
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.filter_combo = QComboBox()
        for key, caption in FILTERS:
            self.filter_combo.addItem(caption, key)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        controls.addWidget(self.filter_combo)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по предмету, кабинету…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        controls.addWidget(self.search_edit)
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

        self.empty = EmptyState("Испытаний нет", action_text="Добавить испытание")
        self.empty.action_clicked.connect(self.add_exam)
        layout.addWidget(self.empty, 1)

        self.refresh()

    # ------------------------------------------------------------------ данные
    def _on_filter_changed(self) -> None:
        self._filter = self.filter_combo.currentData()
        self.refresh()

    def _on_search_changed(self, _text: str) -> None:
        self.refresh()

    def _query(self) -> str:
        return self.search_edit.text() if hasattr(self, "search_edit") else ""

    def refresh(self) -> None:
        service = ExamService(self.db)
        self._today = clock.today()
        summary = service.summary(today=self._today)
        self.total_row.set_value(str(summary["total"]))
        self.planned_row.set_value(str(summary["planned"]))

        # UI-14: подписи предметов — по настройкам сокращённых названий.
        names = SubjectNameService(self.db)
        upcoming = service.next_exam(today=self._today)
        self.next_row.set_value(
            f"{names.display(upcoming.subject_name)} · {upcoming.countdown}"
            if upcoming else "—"
        )

        rows = service.rows(today=self._today, query=self._query())
        self._filter = self.filter_combo.currentData()
        if self._filter == "upcoming":
            # «Не сданные» — всё, кроме сданного. Раньше здесь стояло
            # ``days_left >= 0``, и испытание, у которого при переносе дата
            # оказалась в прошлом, пропадало из списка целиком: в календаре
            # метка горела, а строки не было — выглядело как потеря записи.
            # Перенесённое тоже остаётся: перенос это другая дата, а не
            # отмена, и работа всё ещё не сделана.
            rows = [row for row in rows if not row.is_passed]
        elif self._filter == "passed":
            rows = [row for row in rows if row.is_passed]
        elif self._filter == "overdue":
            rows = [row for row in rows if row.is_overdue]

        self.add_button.setEnabled(service.has_subjects)

        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        for row in rows:
            widget = ExamRowWidget(
                row, subject_caption=names.display(row.subject_name)
            )
            widget.edit_requested.connect(self.edit_exam)
            widget.delete_requested.connect(self.delete_exam)
            widget.passed_requested.connect(self.mark_passed)
            self.list_layout.addWidget(widget)

        self.list_layout.addStretch(1)
        self.count_label.setText(f"Испытаний: {len(rows)}" if rows else "")

        if not rows and self._query().strip():
            self.empty.set_caption("Ничего не найдено")
            self.empty.set_hint("Измените запрос или выберите другой фильтр.")
        elif not rows and service.summary(today=self._today)["total"] > 0:
            # Записи есть, но текущий фильтр их не показывает. Прямо говорим
            # об этом: иначе пустой список читается как «испытание пропало» —
            # именно так и выглядела жалоба про перенос экзамена.
            self.empty.set_caption("В этом фильтре испытаний нет")
            self.empty.set_hint(
                "Всего записей: "
                f"{service.summary(today=self._today)['total']}. "
                "Выберите «Все» или «Не сданные», чтобы увидеть их."
            )
        else:
            self.empty.set_caption(service.empty_hint)
            self.empty.set_hint(
                "Добавьте предмет в справочнике, чтобы создать испытание."
                if not service.has_subjects else ""
            )
        self.scroll.setVisible(bool(rows))
        self.empty.setVisible(not rows)

    # ------------------------------------------------------------------ действия
    def add_exam(self) -> None:
        if not ExamService(self.db).has_subjects:
            QMessageBox.information(
                self, "Экзамены",
                "Сначала добавьте предмет в справочнике «Настройки → Предметы».",
            )
            return
        dialog = ExamDialog(self.db, parent=self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def edit_exam(self, exam_id: int) -> None:
        dialog = ExamDialog(self.db, exam_id=exam_id, parent=self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def delete_exam(self, exam_id: int) -> None:
        exam = ExamService(self.db).repo.require(exam_id)
        answer = QMessageBox.question(
            self, "Удаление",
            f"Удалить испытание по предмету «{ExamService(self.db).subject_name(exam.subject_id)}» "
            f"от {format_display(exam.date)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        ExamService(self.db).delete(exam_id)
        self.changed.emit()
        self.refresh()

    def mark_passed(self, exam_id: int) -> None:
        ExamService(self.db).mark_passed(exam_id)
        self.changed.emit()
        self.refresh()


__all__ = ["ExamsPage", "ExamDialog", "ExamRowWidget", "FILTERS"]
