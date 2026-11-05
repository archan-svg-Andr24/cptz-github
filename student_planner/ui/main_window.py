"""Главное окно: три колонки (UI-02) и переключение страниц (UI-06).

Каркас §20–§23: навигация слева, рабочая зона в центре, виджеты справа. Сами
страницы живут в :mod:`student_planner.ui.pages` и не знают о раскладке.
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QWidget,
)

from .. import APP_TITLE, APP_VERSION
from ..core import clock
from ..core.dates import format_display
from ..core.day_resolution import DayResolver
from ..core.errors import AppError
from ..core.notification_service import NotificationService
from ..core.settings_registry import SettingsKeys
from ..core.settings_service import SettingsService
from ..core.schedule_service import CalendarService, HomeworkService, OverrideService
from ..core.transport_service import TransportService
from ..core.trip_service import TripPlanService
from .dialogs import ConfirmTripsDialog, RecalculateDialog
from .nav_panel import NavPanel
from .theme import theme_manager
from .widgets_panel import WidgetsPanel

log = logging.getLogger(__name__)

#: UI-23: ширина правой панели по умолчанию и допустимые границы.
DEFAULT_WIDGETS_WIDTH = 280
MIN_WIDGETS_WIDTH = 220
MAX_WIDGETS_WIDTH = 480

#: UI-25: ширина полосы-границы со «язычком».
EDGE_WIDTH = 14


class EdgeCollapseButton(QWidget):
    """UI-25: вертикальная полоса-граница со «язычком» для сворачивания панели.

    Заменяет прежнюю кнопку-«язычок» отдельной строкой сверху: та занимала
    26 px высоты (3 % панели) и висела в пустоте у левого края. Полоса идёт по
    всей высоте, лежит на границе панели, показывает курсор изменения размера
    и двойным щелчком возвращает ширину по умолчанию.
    """

    clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EdgeStrip")
        self.setFixedWidth(EDGE_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._collapsed = False
        self._hover = False
        self._update_tooltip()

    # ------------------------------------------------------------------ вид
    def set_collapsed(self, collapsed: bool) -> None:
        """Обновить направление «язычка» под состояние панели."""
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._update_tooltip()
        self.update()

    def _update_tooltip(self) -> None:
        if self._collapsed:
            self.setToolTip(
                "Развернуть правую панель (двойной щелчок — ширина по умолчанию)"
            )
        else:
            self.setToolTip(
                "Свернуть правую панель (двойной щелчок — ширина по умолчанию)"
            )

    # --------------------------------------------------------------- события
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Нажатие запоминаем, а щелчок отдаём только если это не
            # двойной: иначе одиночный срабатывал бы перед двойным.
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        """Нарисовать полосу и «язычок» стрелкой.

        Рисуем вручную, а не стилем: полоса должна занимать всю высоту и
        подсвечиваться при наведении, а QSS для такого «язычка» пришлось бы
        дублировать в каждой теме.
        """
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
        from PySide6.QtCore import QPointF

        from .theme import COLORS

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            width, height = self.width(), self.height()
            background = QColor(COLORS["surface_high"] if self._hover else COLORS["surface"])
            painter.fillRect(self.rect(), background)

            # Тонкая линия по левому краю — визуальная граница панели.
            pen = QPen(QColor(COLORS["border"]))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(0, 0, 0, height)

            # «Язычок»: треугольник в середине по высоте, смотрит в сторону
            # сворачивания (влево — свернуть, вправо — развернуть).
            center_y = height // 2
            size = 4
            cx = width / 2
            if self._collapsed:
                points = [QPointF(cx - size / 2, center_y - size),
                          QPointF(cx + size / 2, center_y),
                          QPointF(cx - size / 2, center_y + size)]
            else:
                points = [QPointF(cx + size / 2, center_y - size),
                          QPointF(cx - size / 2, center_y),
                          QPointF(cx + size / 2, center_y + size)]
            path = QPainterPath()
            path.addPolygon(QPolygonF(points))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["text_muted"]))
            painter.drawPath(path)

            # Короткие «насечки» сверху и снизу язычка — намёк на перетаскивание.
            painter.setPen(pen)
            for offset in (-6, -4, 4, 6):
                painter.drawLine(
                    width // 2 - 2, center_y + offset * 3,
                    width // 2 + 2, center_y + offset * 3,
                )
        finally:
            painter.end()


class MainWindow(QMainWindow):
    """UI-02: три колонки — навигация, рабочая зона, виджеты."""

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = SettingsService(db)
        self._selected_date: date = clock.today()
        self._pages: dict[str, QWidget] = {}
        self._current_page = "schedule"
        # UI-25/UI-23: состояние и ширина правой панели.
        self._collapsed_state = False
        self._widgets_width = DEFAULT_WIDGETS_WIDTH
        self._width_timer: QTimer | None = None

        self.setWindowTitle(f"{APP_TITLE} {APP_VERSION}")
        # UI-13: тема применяется ко всему приложению (QApplication), поэтому
        # её получают и диалоги, и меню, и всплывающие подсказки. Окно только
        # слушает сигнал, чтобы перекрасить то, что рисует цвета само.
        # load() до подписки: сохранённая тема применяется молча, обработчику
        # ещё нечего перекрашивать — календарь и страницы не созданы.
        self.themes = theme_manager(db)
        self.themes.load()
        self.themes.theme_changed.connect(self._on_theme_changed)
        self.resize(1400, 880)
        self.setMinimumSize(1080, 680)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        # ---------------------------------------------------------- навигация
        self.nav = NavPanel(db)
        self.nav.page_requested.connect(self.open_page)
        self.nav.date_selected.connect(self.on_date_selected)
        # UI-05: при листании месяца пересчитываем точки-метки для нового
        # месяца, иначе они остаются от предыдущего.
        self.nav.month_changed.connect(self._refresh_calendar_marks)
        splitter.addWidget(self.nav)

        # ------------------------------------------------------- рабочая зона
        self.stack = QStackedWidget()
        # Страницы содержат длинные подписи и таблицы, поэтому их
        # minimumSizeHint (до 1000 px) распирал сплиттер: ручку нельзя было
        # сдвинуть влево, календарь оставался обрезанным. Сжимаемость важнее
        # «естественного» минимума — содержимое переносится и прокручивается.
        self.stack.setMinimumWidth(360)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        splitter.addWidget(self.stack)

        # ---------------------------------------------------------- виджеты
        self.widgets = WidgetsPanel(db)
        self.widgets.confirm_requested.connect(self.confirm_trips)
        self.widgets.recalculate_requested.connect(self.recalculate_counter)
        self.widgets.homework_requested.connect(lambda: self.open_page("homework"))
        self.widgets.exams_requested.connect(lambda: self.open_page("exams"))
        # UI-25: кнопка сворачивания живёт в шапке панели, рядом с часами.
        self.widgets.collapse_requested.connect(self.toggle_widgets)

        # Обёртка нужна, чтобы при сворачивании оставалась узкая полоса с
        # кнопкой разворота: спрятать панель целиком значило бы потерять
        # единственный способ её вернуть.
        self.widgets_host = QWidget()
        widgets_layout = QHBoxLayout(self.widgets_host)
        widgets_layout.setContentsMargins(0, 0, 0, 0)
        widgets_layout.setSpacing(0)

        self.edge_button = EdgeCollapseButton()
        self.edge_button.clicked.connect(self.toggle_widgets)
        widgets_layout.addWidget(self.edge_button)
        widgets_layout.addWidget(self.widgets, 1)
        splitter.addWidget(self.widgets_host)
        self._splitter = splitter

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        # UI-23: ширину правой колонки запоминаем после перетаскивания.
        splitter.splitterMoved.connect(self._on_splitter_moved)
        # Ширина колонок: левая вмещает мини-календарь целиком (258 px),
        # правая — виджеты; обе регулируются пользователем.
        splitter.setSizes([312, 808, DEFAULT_WIDGETS_WIDTH])

        self.setStatusBar(QStatusBar())
        self.status_label = QLabel("Готово")
        self.statusBar().addWidget(self.status_label, 1)
        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setObjectName("Small")
        self.statusBar().addPermanentWidget(self.version_label)

        # NOTIF-01: значок в трее. Создаётся до первого напоминания, но
        # показывается только если система поддерживает трей — в тестах и на
        # головых сборках без трея он просто не появится.
        self._tray: QSystemTrayIcon | None = None
        self._setup_tray()

        self._build_pages()
        self._install_shortcuts()
        # UI-03: календарь создаётся с датой Qt по умолчанию — это реальная
        # дата машины, а «сегодня» приложения берётся из ``clock.today()``
        # (в тестах она заморожена). Пока даты не совпадали, календарь
        # показывал чужой месяц, и подсветка недель для видимых дней не
        # строилась. Синхронизируем явно.
        self.nav.set_selected_date(self._selected_date)
        # UI-05: метки и типы недель нужны сразу на старте. Без этого
        # календарь оставался без подсветки до первой правки данных —
        # любое действие вызывало refresh_all, и только тогда цвета
        # появлялись, что выглядело как «подсветка включается после
        # добавления пары».
        self._refresh_calendar_marks()
        self._restore_widgets_state()
        self.open_page("schedule")

        # UI-07: часы в правой панели тикают раз в секунду; здесь только
        # ежедневное обновление даты, чтобы «сегодня» не отставало.
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(self._check_day_change)
        self._day_timer.start()
        self._last_today = clock.today()

        # NOTIF-01: напоминания проверяются раз в минуту. Отдельный таймер,
        # потому что он не должен зависеть от настроек отображения даты.
        self.notifications = NotificationService(db)
        self._notify_timer = QTimer(self)
        self._notify_timer.setInterval(60_000)
        self._notify_timer.timeout.connect(self.check_notifications)
        self._notify_timer.start()
        # Первая проверка — не сразу: окно ещё не показано, и системный
        # трей только создаётся. Таймер привязан к окну (родитель), поэтому
        # отменяется вместе с ним и не вызывает метод у закрытого окна.
        self._first_check = QTimer(self)
        self._first_check.setSingleShot(True)
        self._first_check.setInterval(3_000)
        self._first_check.timeout.connect(self.check_notifications)
        self._first_check.start()

    def closeEvent(self, event) -> None:
        """Остановить таймеры, убрать трей и отписаться от темы.

        Без этого закрытое окно продолжало жить: таймеры остаются у
        родителя-объекта, а сигнал ``theme_changed`` у синглтона
        ``theme_manager`` держит ссылку на обработчик окна. Пока ссылка жива,
        окно и все его виджеты не уничтожаются, и каждая смена темы
        перекрашивает в том числе закрытые окна — в тестах это накапливалось
        и замедляло прогон до полной остановки.
        """
        for timer in (
            getattr(self, "_day_timer", None),
            getattr(self, "_notify_timer", None),
            getattr(self, "_first_check", None),
            self._width_timer,
        ):
            if timer is not None:
                timer.stop()
        # Часы в правой панели тикают раз в секунду — их тоже нужно остановить.
        widgets = getattr(self, "widgets", None)
        if widgets is not None:
            widgets.stop_timers()
        # UI-23: ширину сохраняем и здесь — на случай, если пользователь закрыл
        # окно сразу после перетаскивания, а отложенный таймер не успел.
        try:
            self._persist_widgets_width()
        except Exception:  # pragma: no cover - защита закрытия
            pass
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.hide()
        try:
            self.themes.theme_changed.disconnect(self._on_theme_changed)
        except (RuntimeError, TypeError):  # pragma: no cover - уже отписались
            pass
        super().closeEvent(event)

    # ------------------------------------------------------------ уведомления
    def _setup_tray(self) -> None:
        """NOTIF-01: значок в системном трее для всплывающих напоминаний."""
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            icon = self._make_tray_icon()
            tray = QSystemTrayIcon(icon, self)
            tray.setToolTip(f"{APP_TITLE} {APP_VERSION}")
            tray.activated.connect(self._on_tray_activated)
            tray.show()
            self._tray = tray
        except Exception as error:  # pragma: no cover - среда без трея
            log.warning("Трей недоступен: %s", error)
            self._tray = None

    @staticmethod
    def _make_tray_icon():
        """Иконка трея: рисуется программно, чтобы не тащить файл ресурсов."""
        from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setBrush(QColor("#4a84f5"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(2, 2, size - 4, size - 4, 7, 7)
            painter.setPen(QColor("#ffffff"))
            font = painter.font()
            font.setPointSize(13)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "С")
        finally:
            painter.end()
        return QIcon(pixmap)

    def _on_tray_activated(self, reason) -> None:
        """Щелчок по значку возвращает окно на передний план."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def check_notifications(self) -> None:
        """NOTIF-01…NOTIF-05: показать одно ближайшее напоминание.

        По одному за проверку: очередь из четырёх окон подряд выглядела бы
        как сбой, а не как забота.
        """
        try:
            item = self.notifications.next_notification()
        except Exception as error:  # pragma: no cover - защита таймера
            log.warning("Не удалось проверить уведомления: %s", error)
            return
        if item is None:
            return
        self.notifications.mark_shown(item)
        self.show_notification(item)

    def show_notification(self, item) -> None:
        """Показать напоминание: в трее, если он есть, иначе в строке состояния.

        Трей — не украшение: ``QSystemTrayIcon.showMessage`` даёт системное
        всплывающее окно, которое видно даже когда приложение свёрнуто.
        Если трея нет (или он не поддерживается), сообщение не теряется —
        уходит в строку состояния.
        """
        shown = False
        if self._tray is not None and self._tray.isSystemTrayAvailable():
            self._tray.showMessage(
                item.title, item.message, self._tray.icon(), 10_000
            )
            shown = True
        if not shown:
            self.statusBar().showMessage(f"{item.title}: {item.message}", 15_000)
        self.status_label.setText(item.title)

    # ------------------------------------------------------------------ страницы
    def _build_pages(self) -> None:
        from .pages import (
            ExamsPage,
            ExpensesPage,
            HomeworkPage,
            SchedulePage,
            SettingsPage,
            TripsPage,
        )

        self._pages = {
            "schedule": SchedulePage(self.db, self),
            "trips": TripsPage(self.db, self),
            "expenses": ExpensesPage(self.db, self),
            "homework": HomeworkPage(self.db, self),
            "exams": ExamsPage(self.db, self),
            "settings": SettingsPage(self.db, self),
        }
        for page in self._pages.values():
            self.stack.addWidget(page)
            if hasattr(page, "changed"):
                page.changed.connect(self.refresh_all)
        # SCH-09: навигация внутри страницы расписания (стрелки, «Сегодня»,
        # смена режима) переводит дату всего окна — календарь и бейдж типа
        # недели слева обязаны следовать за ней.
        schedule_page = self._pages.get("schedule")
        if hasattr(schedule_page, "date_changed"):
            schedule_page.date_changed.connect(self.on_date_selected)

    def _install_shortcuts(self) -> None:
        for index, key in enumerate(("schedule", "trips", "expenses",
                                    "homework", "exams", "settings"), start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(
                lambda page=key: self.open_page(page)
            )
        today_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        today_shortcut.activated.connect(lambda: self.on_date_selected(clock.today()))
        # UI-13: смена темы по кругу без похода в настройки.
        theme_shortcut = QShortcut(QKeySequence("Ctrl+Shift+T"), self)
        theme_shortcut.activated.connect(self.themes.cycle)
        # UI-25: свернуть/развернуть правую панель с клавиатуры.
        widgets_shortcut = QShortcut(QKeySequence("Ctrl+Shift+W"), self)
        widgets_shortcut.activated.connect(self.toggle_widgets)

    # ------------------------------------------------------ правая панель
    @property
    def widgets_collapsed(self) -> bool:
        """UI-25: свёрнута ли правая панель."""
        return self.settings.raw(SettingsKeys.WIDGETS_COLLAPSED) == "1"

    def toggle_widgets(self) -> None:
        """UI-25: свернуть или развернуть правую панель."""
        self.set_widgets_collapsed(not self.widgets_collapsed)

    def set_widgets_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        """Свернуть панель: скрыть её и сузить колонку.

        Скрывать одну панель мало: колонка сплиттера осталась бы шириной
        280 px пустого места. Поэтому сохраняется прежняя ширина и колонка
        сжимается до ширины «язычка», а при развороте возвращается.
        """
        if collapsed == self._collapsed_state:
            # Уже в нужном состоянии: повторный вызов не должен затирать
            # сохранённую ширину (иначе после перезапуска панель
            # разворачивалась на минимуме вместо прежней ширины).
            return
        sizes = self._splitter.sizes()
        if collapsed:
            if len(sizes) >= 3 and sizes[2] - EDGE_WIDTH > MIN_WIDGETS_WIDTH:
                self._widgets_width = sizes[2] - EDGE_WIDTH
            self.widgets.setVisible(False)
            # Колонка сжимается до ширины полосы-«язычка»: панель скрыта,
            # но кнопка разворота остаётся на прежнем месте.
            self._splitter.setSizes([sizes[0], sizes[1] + sizes[2], EDGE_WIDTH])
            self._collapsed_state = True
        else:
            self.widgets.setVisible(True)
            width = self._widgets_width or self.saved_widgets_width()
            total = sum(sizes) or 1400
            column = width + EDGE_WIDTH
            self._splitter.setSizes(
                [sizes[0], max(200, total - sizes[0] - column), column]
            )
            self._collapsed_state = False
        if self.edge_button is not None:
            self.edge_button.set_collapsed(collapsed)
        # Кнопка в шапке меняет направление: свернуть ⟩ / развернуть ⟨.
        self.widgets.set_collapsed_hint(collapsed)
        if persist:
            try:
                self.settings.set(SettingsKeys.WIDGETS_COLLAPSED, "1" if collapsed else "0")
            except AppError as error:  # pragma: no cover - защита интерфейса
                log.warning("Не удалось сохранить состояние панели: %s", error)

    # ------------------------------------------------------ ширина панели
    def saved_widgets_width(self) -> int:
        """Сохранённая пользователем ширина правой панели (UI-23)."""
        try:
            raw = self.settings.raw(SettingsKeys.WIDGETS_WIDTH)
        except AppError:  # pragma: no cover - защита интерфейса
            return DEFAULT_WIDGETS_WIDTH
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_WIDGETS_WIDTH
        return min(max(value, MIN_WIDGETS_WIDTH), MAX_WIDGETS_WIDTH)

    def _on_splitter_moved(self, *_args) -> None:
        """UI-23: запомнить ширину панели после перетаскивания разделителя.

        Пишем не на каждое движение мыши, а через короткую паузу: иначе за
        одно перетаскивание в базу уходили десятки записей.
        """
        if self._collapsed_state:
            return
        if self._width_timer is None:
            self._width_timer = QTimer(self)
            self._width_timer.setSingleShot(True)
            self._width_timer.setInterval(300)
            self._width_timer.timeout.connect(self._persist_widgets_width)
        self._width_timer.start()

    def _persist_widgets_width(self) -> None:
        """Сохранить текущую ширину правой панели в настройки.

        Из ширины колонки вычитается полоса-граница: пользователь настраивает
        саму панель, а не колонку сплиттера вместе с «язычком».
        """
        sizes = self._splitter.sizes()
        if len(sizes) < 3 or self._collapsed_state:
            return
        width = sizes[2] - EDGE_WIDTH
        if width < MIN_WIDGETS_WIDTH:
            return
        self._widgets_width = width
        try:
            self.settings.set(SettingsKeys.WIDGETS_WIDTH, str(width))
        except AppError as error:  # pragma: no cover - защита интерфейса
            log.warning("Не удалось сохранить ширину панели: %s", error)

    def _apply_widgets_width(self, width: int) -> None:
        """Задать ширину правой колонки с учётом полосы-границы.

        Колонка сплиттера содержит и полосу со «язычком» (``EDGE_WIDTH``), и
        саму панель. Пользователь настраивает ширину **панели**, поэтому к
        запрошенному значению прибавляется ширина полосы — иначе панель
        выходила на 14 px уже заданной и «сброс к 280» давал 266.
        """
        sizes = self._splitter.sizes()
        if len(sizes) < 3:
            return
        total = sum(sizes) or 1400
        column = width + EDGE_WIDTH
        self._splitter.setSizes(
            [sizes[0], max(200, total - sizes[0] - column), column]
        )

    def reset_widgets_width(self) -> None:
        """UI-23: вернуть ширину панели по умолчанию (двойной щелчок)."""
        self._apply_widgets_width(DEFAULT_WIDGETS_WIDTH)
        self._widgets_width = DEFAULT_WIDGETS_WIDTH
        try:
            self.settings.set(SettingsKeys.WIDGETS_WIDTH, str(DEFAULT_WIDGETS_WIDTH))
        except AppError:  # pragma: no cover - защита интерфейса
            pass

    def _restore_widgets_state(self) -> None:
        """UI-25/UI-23: применить сохранённые состояние и ширину панели."""
        self._widgets_width = self.saved_widgets_width()
        self._apply_widgets_width(self._widgets_width)
        if self.widgets_collapsed:
            self.set_widgets_collapsed(True, persist=False)

    # ------------------------------------------------------------------- тема
    def _on_theme_changed(self, key: str) -> None:
        """UI-13: перекрасить то, что тема не обновляет автоматически.

        Виджеты перерисовывает Qt, но мини-календарь хранит цвета в
        ``QTextCharFormat``, а таблицы — в ячейках; их нужно обновить руками.
        """
        log.info("Тема интерфейса: %s", key)
        self.nav.calendar.apply_theme()
        self.status_label.setText(f"Тема: {self.themes.theme.caption}")
        self.refresh_all()

    def set_theme(self, key: str) -> None:
        """Применить тему и запомнить выбор (UI-13)."""
        self.themes.apply(key)

    def open_page(self, page: str) -> None:
        """UI-06: переключение раздела.

        Перед обновлением странице передаётся выбранная в календаре дата.
        Раньше этого не делалось, и «Поездки», «Расходы» и «Домашние задания»
        продолжали жить со своей датой, взятой при создании (``clock.today()``):
        выбрав 9 декабря на «Расписании» и открыв «Поездки», пользователь
        видел 31 октября и подтверждал поездки не того дня.
        """
        widget = self._pages.get(page)
        if widget is None:
            log.warning("Неизвестный раздел: %s", page)
            return
        self._current_page = page
        self.stack.setCurrentWidget(widget)
        self.nav.set_current_page(page)
        if hasattr(widget, "set_date"):
            widget.set_date(self._selected_date)
        if hasattr(widget, "refresh"):
            widget.refresh()
        self.widgets.refresh(self._selected_date)
        self._update_week_badge()
        self.status_label.setText(self.nav.page_caption(page))

    # ------------------------------------------------------------------ дата
    @property
    def selected_date(self) -> date:
        return self._selected_date

    def on_date_selected(self, value: date) -> None:
        """UI-03: выбранная дата сменилась.

        Защита от повторного входа: страница расписания при смене даты сама
        вызывает ``refresh()`` и затем эмитит ``date_changed``, который
        приходит сюда. Если здесь снова позвать ``set_date()``, страница
        перерисуется второй раз, и так по кругу до глубины 2. Поэтому дата
        передаётся странице, только когда она действительно другая.
        """
        self._selected_date = value
        self.nav.set_selected_date(value)
        page = self._pages.get(self._current_page)
        if page is not None and hasattr(page, "set_date"):
            current = getattr(page, "_date", None)
            if current != value:
                page.set_date(value)
        self.widgets.refresh(value)
        # UI-04/ALG-01: бейдж типа недели относится к выбранной дате, а не к
        # сегодняшней. Без этого при просмотре другой недели он показывал тип
        # предыдущей недели (или «—» до первого refresh_all).
        self._update_week_badge()
        self.status_label.setText(
            f"{self.nav.page_caption(self._current_page)} · {format_display(value)}"
        )

    def _update_week_badge(self) -> None:
        """UI-04: привести бейдж типа недели к выбранной дате (ALG-01)."""
        try:
            week_type = DayResolver(self.db).week_type(self._selected_date)
        except AppError as error:  # pragma: no cover - защита интерфейса
            log.warning("Не удалось определить тип недели: %s", error)
            week_type = None
        self.nav.set_week_type(week_type)

    def _check_day_change(self) -> None:
        today = clock.today()
        if today != self._last_today:
            self._last_today = today
            self.nav.refresh()
            self.on_date_selected(today)

    # ------------------------------------------------------------------ обновление
    def refresh_all(self) -> None:
        """Перечитать виджеты и текущую страницу после правки данных."""
        page = self._pages.get(self._current_page)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()
        self.widgets.refresh(self._selected_date)
        self.nav.refresh()
        self._refresh_calendar_marks()

    def _refresh_calendar_marks(self) -> None:
        """UI-05: точки-метки мини-календаря."""
        try:
            # Метки нужны для месяца, который календарь показывает сейчас,
            # а не для текущего: иначе после листания точки пропадали.
            shown_year, shown_month = self.nav.calendar.shown_month()
            overrides = OverrideService(self.db)
            transport = TransportService(self.db)
            calendar = CalendarService(self.db)
            homework = HomeworkService(self.db)

            marks: dict[date, list[str]] = {}
            for value in overrides.overrides.dates_with_overrides():
                marks.setdefault(value, []).append("override")
            for value in transport.rides.dates():
                marks.setdefault(value, []).append("rides")
            for entry in calendar.all():
                current = entry.start_date
                while current <= entry.end_date:
                    marks.setdefault(current, []).append("period")
                    if current >= date.max:
                        # Период, доходящий до 31.12.9999: следующей даты нет,
                        # date.fromordinal выбросил бы ValueError и метки
                        # перестали бы строиться целиком.
                        break
                    current = date.fromordinal(current.toordinal() + 1)
            for value in homework.due_dates():
                marks.setdefault(value, []).append("homework")
            # EXAM-06: метка дня испытания. Считается отдельно по видимому
            # диапазону календаря, потому что страница экзаменов может быть
            # ещё не создана в момент первого refresh.
            from ..core.exam_repository import ExamRepository

            exam_repo = ExamRepository(self.db)
            grid = _grid_dates(shown_year, shown_month)
            for value in exam_repo.dates_with_exams(grid[0], grid[-1]):
                marks.setdefault(value, []).append("exam")

            self.nav.set_marks({key: " ".join(value) for key, value in marks.items()})

            resolver = DayResolver(self.db)
            # Календарь получает разделитель и считает тип недели сам: при
            # листании месяца подсветка больше не пропадает, а дни сетки по
            # краям (соседние месяцы) тоже подсвечены.
            self.nav.set_type_resolver(resolver)
            types: dict[date, str] = {}
            for value in _grid_dates(shown_year, shown_month):
                types[value] = resolver.week_type(value) or ""
            self.nav.set_week_types(types)
            self.nav.set_week_type(resolver.week_type(self._selected_date))
        except AppError as error:  # pragma: no cover - защита интерфейса
            log.warning("Не удалось обновить метки календаря: %s", error)
            self.show_error(error)

    # ------------------------------------------------------------------ действия
    def confirm_trips(self, value: date) -> None:
        """UI-08: подтверждение поездок дня из правой панели."""
        dialog = ConfirmTripsDialog(self.db, value, self)
        if dialog.exec():
            self.refresh_all()

    def recalculate_counter(self) -> None:
        """REP-08: пересчёт счётчика «Стрелки» с подтверждением."""
        dialog = RecalculateDialog(self.db, self)
        if dialog.exec():
            self.refresh_all()

    # ------------------------------------------------------------------ ошибки
    def show_error(self, error: Exception) -> None:
        """ERR-*: сообщение об ошибке с кодом и подсказкой."""
        if isinstance(error, AppError):
            text = error.message
            details = f"\nКод: {error.code}" if error.code else ""
        else:  # pragma: no cover - непредвиденная ошибка
            text = str(error)
            details = ""
        QMessageBox.critical(self, "Ошибка", f"{text}{details}")
        self.status_label.setText(f"Ошибка: {text.splitlines()[0]}")


def _month_dates(value: date) -> list[date]:
    from calendar import monthrange

    last_day = monthrange(value.year, value.month)[1]
    return [
        date(value.year, value.month, day)
        for day in range(1, last_day + 1)
    ]


def _grid_dates(year: int, month: int) -> list[date]:
    """Даты, которые реально видны в сетке месяца, включая края.

    Сетка ``QCalendarWidget`` начинается с понедельника недели, содержащей
    первое число, и заканчивается воскресеньем недели с последним числом.
    Без этих дней подсветка типа недели обрывалась на границах месяца.

    Края ограничены допустимыми датами: у января 1-го года ведущие дни уходят
    за ``date.min``, у декабря 9999-го хвостовые — за ``date.max``, и
    ``date.fromordinal`` бросает ``ValueError``.
    """
    from calendar import monthrange

    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    start = max(first.toordinal() - first.weekday(), date.min.toordinal())
    end = min(last.toordinal() + (6 - last.weekday()), date.max.toordinal())
    return [date.fromordinal(value) for value in range(start, end + 1)]


__all__ = ["MainWindow"]
