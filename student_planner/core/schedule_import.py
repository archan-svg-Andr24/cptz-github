"""Импорт расписания из файла (GRID-10, FIRST-13).

Поддерживается CSV с разделителем ``;`` (как сохраняет Excel в русской
локали) или ``,``. Заголовок не обязателен, но если он есть — колонки
распознаются по названиям, а не по порядку.

Минимальный формат::

    день;тип_недели;блок;предмет
    Пн;upper;1;Математика
    Пн;upper;2;Физика

Дополнительные необязательные колонки: ``кабинет``,
``преподаватель``, ``с``, ``по``.

Импорт **не удаляет** существующее расписание: он только записывает те
ячейки, что есть в файле, и сообщает, что пропущено и почему. Это важно:
молчаливая потеря уже введённых пар недопустима.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .database import Database
from .errors import ValidationError
from .repositories import BellRepository, ScheduleTemplateRepository, SubjectRepository
from .schedule_service import GridService
from .weektype import WeekType

#: Распознаваемые названия колонок (в нижнем регистре, без пробелов).
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "weekday": ("день", "деньнедели", "weekday", "day"),
    "week_type": ("типнедели", "неделя", "weektype", "week_type", "week"),
    "slot": ("блок", "пара", "номер", "slot", "slot_no", "урок"),
    "subject": ("предмет", "subject", "дисциплина", "название"),
    "room": ("кабинет", "аудитория", "room"),
    "teacher": ("преподаватель", "учитель", "teacher"),
    "start": ("с", "начало", "start", "start_time"),
    "end": ("по", "окончание", "end", "end_time"),
}

_WEEKDAYS: dict[str, int] = {
    "пн": 1, "понедельник": 1, "monday": 1, "mon": 1,
    "вт": 2, "вторник": 2, "tuesday": 2, "tue": 2,
    "ср": 3, "среда": 3, "wednesday": 3, "wed": 3,
    "чт": 4, "четверг": 4, "thursday": 4, "thu": 4,
    "пт": 5, "пятница": 5, "friday": 5, "fri": 5,
    "сб": 6, "суббота": 6, "saturday": 6, "sat": 6,
    "вс": 7, "воскресенье": 7, "sunday": 7, "sun": 7,
}

_WEEK_TYPES: dict[str, str] = {
    "верхняя": WeekType.UPPER, "upper": WeekType.UPPER, "в": WeekType.UPPER,
    "нижняя": WeekType.LOWER, "lower": WeekType.LOWER, "н": WeekType.LOWER,
}


@dataclass
class ImportReport:
    """Итог импорта: что записано, что пропущено и почему."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    #: Сообщения о пропущенных строках (номер строки файла и причина).
    problems: list[str] = field(default_factory=list)
    #: Новые предметы, созданные по ходу импорта.
    new_subjects: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated

    @property
    def caption(self) -> str:
        """Короткая сводка для строки состояния."""
        parts = [f"Записано ячеек: {self.total}"]
        if self.skipped:
            parts.append(f"пропущено: {self.skipped}")
        if self.new_subjects:
            parts.append(f"новых предметов: {len(self.new_subjects)}")
        return " · ".join(parts)


def _normalize(text: str) -> str:
    """Убрать пробелы/подчёркивания и привести к нижнему регистру."""
    return (text or "").strip().lower().replace(" ", "").replace("_", "")


def _detect_delimiter(sample: str) -> str:
    """Определить разделитель по первой строке: ``;`` важнее ``,``."""
    first = sample.splitlines()[0] if sample.splitlines() else ""
    if first.count(";") >= first.count(","):
        return ";"
    return ","


def _map_columns(header: list[str]) -> dict[str, int]:
    """Сопоставить колонки файла с полями по названиям."""
    mapping: dict[str, int] = {}
    for index, name in enumerate(header):
        key = _normalize(name)
        for field_name, aliases in _COLUMN_ALIASES.items():
            if key in aliases and field_name not in mapping:
                mapping[field_name] = index
                break
    return mapping


def _looks_like_header(row: list[str]) -> bool:
    """Похожа ли первая строка на заголовок (а не на данные).

    Достаточно **одного** названия колонки из тех, что не могут быть
    значением: «блок», «кабинет», «преподаватель», «тип недели».
    Слова «предмет» и просто «день» сюда не входят: они бывают названием
    предмета и значением дня, и строка ``Пн;upper;1;Математика`` иначе
    принималась бы за заголовок — импорт без заголовка ломался.
    """
    joined = _normalize("".join(row))
    markers = (
        "блок", "кабинет", "преподаватель",
        "типнедели", "деньнедели",
    )
    return any(marker in joined for marker in markers)


class ScheduleImporter:
    """GRID-10: импорт сетки из CSV (FIRST-13)."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.grid = GridService(db)
        self.templates = ScheduleTemplateRepository(db)
        self.subjects = SubjectRepository(db)
        self.bells = BellRepository(db)

    # ------------------------------------------------------------------ чтение
    def parse_text(self, text: str, *, on_date: date | None = None) -> ImportReport:
        """Разобрать содержимое файла и записать ячейки.

        ``on_date`` — дата, с которой действуют записанные ячейки. Без неё
        история не создаётся: строка заменяет базовую версию позиции.
        """
        if not text or not text.strip():
            raise ValidationError("Файл пуст.", field="file")
        delimiter = _detect_delimiter(text)
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)

        rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            raise ValidationError("В файле нет строк с данными.", field="file")

        mapping: dict[str, int] = {}
        start_index = 0
        if _looks_like_header(rows[0]):
            mapping = _map_columns(rows[0])
            start_index = 1
            if "subject" not in mapping:
                raise ValidationError(
                    "В заголовке не найдена колонка «предмет». Ожидаются колонки "
                    "«день; блок; предмет».",
                    field="file",
                )
        else:
            # Без заголовка порядок фиксирован: день, блок, предмет. Если во
            # второй колонке стоит тип недели («upper»/«нижняя»), значит
            # формат «день; тип недели; блок; предмет» — распознаём его.
            second = _normalize(rows[0][1]) if len(rows[0]) > 1 else ""
            if second in _WEEK_TYPES:
                mapping = {"weekday": 0, "week_type": 1, "slot": 2, "subject": 3}
            else:
                mapping = {"weekday": 0, "slot": 1, "subject": 2}

        report = ImportReport()
        profiles = {
            profile.weekday: profile
            for profile in self.bells.profiles(include_inactive=False)
            if profile.variant == "default"
        }
        subject_cache = {subject.name.casefold(): subject for subject in self.subjects.all()}

        for line_no, row in enumerate(rows[start_index:], start=start_index + 1):
            try:
                parsed = self._parse_row(row, mapping)
            except ValidationError as error:
                report.skipped += 1
                report.problems.append(f"Строка {line_no}: {error.message}")
                continue
            if parsed is None:
                continue

            weekday, week_type, slot_no, subject_name = parsed
            profile = profiles.get(weekday)
            if profile is None:
                report.skipped += 1
                report.problems.append(
                    f"Строка {line_no}: нет профиля звонков на этот день недели."
                )
                continue
            # Проверяем по номерам блоков, а не по их количеству: нумерация
            # может иметь пропуски (блок 4 при трёх блоках), и импорт в
            # существующий блок ошибочно отбрасывался.
            known_slots = {slot.slot_no for slot in profile.slots}
            if slot_no not in known_slots:
                report.skipped += 1
                report.problems.append(
                    f"Строка {line_no}: блока №{slot_no} нет в профиле "
                    f"(есть блоки: {', '.join(str(n) for n in sorted(known_slots))})."
                )
                continue

            subject = subject_cache.get(subject_name.casefold())
            if subject is None:
                subject = self._create_subject(subject_name, row, mapping)
                subject_cache[subject.name.casefold()] = subject
                report.new_subjects.append(subject.name)

            try:
                existing = self.templates.cell(
                    profile.id, week_type, slot_no,
                    on_date=on_date,
                )
                self.grid.set_cell(
                    profile.id, week_type, slot_no, subject.id,
                    effective_from=on_date,
                )
            except Exception as error:  # noqa: BLE001 - отчёт важнее падения
                report.skipped += 1
                report.problems.append(f"Строка {line_no}: {error}")
                continue
            if existing is not None and existing.subject_id is not None:
                report.updated += 1
            else:
                report.created += 1
        return report

    def _parse_row(self, row: list[str], mapping: dict[str, int]):
        """День, тип недели, блок, предмет из строки файла."""

        def cell(name: str) -> str:
            index = mapping.get(name)
            if index is None or index >= len(row):
                return ""
            return (row[index] or "").strip()

        weekday_text = _normalize(cell("weekday"))
        if not weekday_text:
            # Пустой день — это ошибка строки, а не «тихий пропуск». Раньше
            # возвращался None, счётчик skipped не рос, problems оставался
            # пустым, и файл без колонки «день» импортировался «успешно» с
            # нулём записанных ячеек (GRID-10 требует отчёта о проблемах).
            raise ValidationError("не указан день недели")
        weekday = _WEEKDAYS.get(weekday_text)
        if weekday is None:
            weekday = _WEEKDAYS.get(weekday_text[:2])
        if weekday is None:
            raise ValidationError(f"неизвестный день недели: {cell('weekday')!r}")

        week_type_text = _normalize(cell("week_type"))
        week_type = _WEEK_TYPES.get(week_type_text, WeekType.LOWER)

        slot_text = cell("slot")
        if not slot_text:
            raise ValidationError("не указан блок")
        try:
            slot_no = int(slot_text.split("-")[0].split(".")[0].strip())
        except ValueError as error:
            raise ValidationError(f"блок должен быть числом: {slot_text!r}") from error

        subject_name = cell("subject")
        if not subject_name:
            raise ValidationError("не указан предмет")

        return weekday, week_type, slot_no, subject_name

    def _create_subject(self, name: str, row: list[str], mapping: dict[str, int]):
        """Создать отсутствующий предмет, подставив кабинет и преподавателя."""
        room = (row[mapping["room"]] if "room" in mapping and mapping["room"] < len(row) else "") or None
        teacher = (
            row[mapping["teacher"]]
            if "teacher" in mapping and mapping["teacher"] < len(row)
            else ""
        ) or None
        return self.subjects.create(
            name, code=None,
            teacher=(teacher or "").strip() or None,
            room=(room or "").strip() or None,
        )

    # -------------------------------------------------------------- из файла
    def parse_file(self, path: str | Path, *, on_date: date | None = None) -> ImportReport:
        """Прочитать CSV с диска и записать ячейки."""
        target = Path(path)
        try:
            raw = target.read_bytes()
        except OSError as error:
            raise ValidationError(f"Не удалось прочитать файл: {error}", field="file") from error
        text = _decode(raw)
        return self.parse_text(text, on_date=on_date)


def _decode(raw: bytes) -> str:
    """Декодировать файл: UTF-8 (с BOM или без), иначе cp1251 как у Excel."""
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


__all__ = ["ScheduleImporter", "ImportReport"]
