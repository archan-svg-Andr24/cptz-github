"""Загрузка стартового набора и инициализация БД (FIRST-01…FIRST-16).

Два режима, различающиеся приёмкой:

* ``seed_all`` — полный набор при создании БД (FIRST-01), идемпотентен
  (FIRST-04, ACC-M-68);
* ``seed_missing`` — «Восстановить стартовый набор»: доливает только
  отсутствующие записи, изменённые не трогает (FIRST-05, ACC-M-69).

Оба режима работают в одной транзакции: частично загруженного набора не
остаётся (DATA-08).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from .. import SCHEMA_VERSION
from . import seed_data as seed
from .database import Database, create_database, is_initialized
from .dates import to_iso
from .models import WeekType
from .money import to_db
from .repositories import BASE_DUE_DATE
from .settings_registry import SettingsKeys, default_registry

log = logging.getLogger(__name__)


class Seeder:
    """Загружает Приложение А в существующую БД."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------------- полный
    def seed_all(self) -> seed.SeedSummary:
        """Полный набор при первом запуске (FIRST-01). Идемпотентен (FIRST-04)."""
        return self._seed(only_missing=False)

    # ------------------------------------------------------------- точечный
    def seed_missing(self) -> seed.SeedSummary:
        """Долить только отсутствующие записи (FIRST-05)."""
        return self._seed(only_missing=True)

    # ------------------------------------------------------------------ общий
    def _seed(self, *, only_missing: bool) -> seed.SeedSummary:
        summary_counts = {
            "settings_added": 0,
            "anchor_added": False,
            "subjects_added": 0,
            "profiles_added": 0,
            "slots_added": 0,
            "cells_added": 0,
            "tariffs_added": 0,
            "templates_added": 0,
        }
        with self.db.transaction() as conn:
            summary_counts["settings_added"] = self._settings(conn, only_missing=only_missing)
            summary_counts["anchor_added"] = self._anchor(conn)
            subject_ids, added = self._subjects(conn)
            summary_counts["subjects_added"] = added
            profile_ids, slot_nos, profiles_added, slots_added = self._bells(conn)
            summary_counts["profiles_added"] = profiles_added
            summary_counts["slots_added"] = slots_added
            summary_counts["cells_added"] = self._templates(conn, subject_ids, profile_ids, slot_nos)
            summary_counts["tariffs_added"] = self._tariffs(conn)
            summary_counts["templates_added"] = self._trip_templates(conn)
        result = seed.SeedSummary(**summary_counts)  # type: ignore[arg-type]
        log.info("Стартовый набор загружен: %s записей", result.total)
        return result

    # -------------------------------------------------------------- настройки
    def _settings(self, conn, *, only_missing: bool) -> int:
        """Ключи реестра §30 со значениями Прил. А.0."""
        added = 0
        registry = default_registry()
        for key, value in registry.defaults().items():
            exists = conn.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone()
            if exists:
                if only_missing:
                    continue
                # Полная загрузка не перезаписывает пользовательские значения
                # (FIRST-04: повторный запуск идемпотентен).
                continue
            conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)", (key, value))
            added += 1
        # Версия схемы всегда актуальна (DATA-19).
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO NOTHING",
            (SettingsKeys.SCHEMA_VERSION, str(SCHEMA_VERSION)),
        )
        return added

    # ------------------------------------------------------------------ якорь
    def _anchor(self, conn) -> bool:
        exists = conn.execute("SELECT 1 FROM week_anchors LIMIT 1").fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO week_anchors(effective_from, base_date, base_type, cycle_length, comment) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                to_iso(seed.ANCHOR_EFFECTIVE_FROM),
                to_iso(seed.ANCHOR_BASE_DATE),
                seed.ANCHOR_BASE_TYPE,
                seed.ANCHOR_CYCLE_LENGTH,
                seed.ANCHOR_COMMENT,
            ),
        )
        return True

    # --------------------------------------------------------------- предметы
    def _subjects(self, conn) -> tuple[dict[str, int], int]:
        ids: dict[str, int] = {}
        added = 0
        for item in seed.SUBJECTS:
            row = conn.execute(
                "SELECT id FROM subjects WHERE name = ? AND code IS ?", (item.name, item.code)
            ).fetchone()
            if row is not None:
                ids[item.key] = int(row["id"] if hasattr(row, "keys") else row[0])
                continue
            cursor = conn.execute(
                "INSERT INTO subjects(code, name, teacher, room, color, is_active) "
                "VALUES (?, ?, ?, ?, NULL, 1)",
                (item.code, item.name, item.teacher, item.room),
            )
            ids[item.key] = int(cursor.lastrowid)
            added += 1
        return ids, added

    # ----------------------------------------------------------------- звонки
    def _bells(self, conn) -> tuple[dict[int, int], dict[int, list[int]], int, int]:
        """Профили и блоки: ``(profile_id по дню, slot_no по дню, добавлено, добавлено)``."""
        profile_ids: dict[int, int] = {}
        slot_map: dict[int, list[int]] = {}
        profiles_added = 0
        slots_added = 0
        for weekday in range(1, 8):
            name = seed.PROFILE_NAMES[weekday]
            row = conn.execute(
                "SELECT id FROM bell_profiles WHERE weekday = ? AND variant = 'default' "
                "AND effective_from IS NULL",
                (weekday,),
            ).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO bell_profiles(weekday, variant, name, effective_from, "
                    "effective_to, is_active) VALUES (?, 'default', ?, NULL, NULL, 1)",
                    (weekday, name),
                )
                profile_id = int(cursor.lastrowid)
                profiles_added += 1
            else:
                profile_id = int(row[0])
            profile_ids[weekday] = profile_id

            blocks = seed.PROFILE_BLOCKS[weekday]
            existing = {
                int(slot_row[0]): int(slot_row[1])
                for slot_row in conn.execute(
                    "SELECT slot_no, id FROM bell_slots WHERE profile_id = ?", (profile_id,)
                ).fetchall()
            }
            slot_nos: list[int] = []
            for index, block in enumerate(blocks, start=1):
                if index in existing:
                    slot_nos.append(index)
                    continue
                cursor = conn.execute(
                    "INSERT INTO bell_slots(profile_id, slot_no, pair_no, block_type, "
                    "display_name, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                    (profile_id, index, block.pair_no, block.block_type, block.display_name, index),
                )
                slot_id = int(cursor.lastrowid)
                for seq, (part_type, start, end) in enumerate(block.parts, start=1):
                    conn.execute(
                        "INSERT INTO bell_slot_parts(slot_id, seq, part_type, start_time, end_time) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (slot_id, seq, part_type, start, end),
                    )
                slot_nos.append(index)
                slots_added += 1
            slot_map[weekday] = sorted(slot_nos)
        return profile_ids, slot_map, profiles_added, slots_added

    # -------------------------------------------------------------- шаблоны
    def _templates(
        self,
        conn,
        subject_ids: dict[str, int],
        profile_ids: dict[int, int],
        slot_map: dict[int, list[int]],
    ) -> int:
        added = 0
        for week_type, days in seed.WEEK_TEMPLATES.items():
            for weekday, cells in days.items():
                profile_id = profile_ids.get(weekday)
                if profile_id is None:
                    continue
                for slot_no, subject_key in cells.items():
                    subject_id = subject_ids.get(subject_key)
                    if subject_id is None:
                        continue
                    exists = conn.execute(
                        "SELECT 1 FROM schedule_templates WHERE profile_id = ? AND week_type = ? "
                        "AND slot_no = ? AND group_mark IS NULL",
                        (profile_id, week_type, slot_no),
                    ).fetchone()
                    if exists:
                        continue
                    conn.execute(
                        "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, "
                        "subject_id, effective_from) VALUES (?, ?, ?, NULL, ?, ?)",
                        (profile_id, week_type, slot_no, subject_id, BASE_DUE_DATE),
                    )
                    added += 1
        return added

    # ----------------------------------------------------------------- тарифы
    def _tariffs(self, conn) -> int:
        added = 0
        for item in seed.TARIFFS:
            exists = conn.execute(
                "SELECT 1 FROM tariffs WHERE kind = ? AND effective_from = ? AND vehicle IS NULL",
                (item.kind, to_iso(item.effective_from)),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO tariffs(kind, price, effective_from, effective_to, vehicle, "
                "is_active, comment) VALUES (?, ?, ?, ?, NULL, 1, ?)",
                (
                    item.kind,
                    to_db(item.price),
                    to_iso(item.effective_from),
                    to_iso(item.effective_to) if item.effective_to else None,
                    item.comment,
                ),
            )
            added += 1
        return added

    # -------------------------------------------------------- шаблоны поездок
    def _trip_templates(self, conn) -> int:
        added = 0
        for order, item in enumerate(seed.TRIP_TEMPLATES, start=1):
            exists = conn.execute(
                "SELECT id FROM trip_templates WHERE direction = ? AND name = ?",
                (item.direction, item.name),
            ).fetchone()
            if exists is not None:
                continue
            default_payment = next(
                (leg.payment_method for leg in item.legs if leg.mode == "bus"), None
            )
            cursor = conn.execute(
                "INSERT INTO trip_templates(direction, name, is_active, default_payment_method, "
                "depart_hint, arrive_hint, note, sort_order) VALUES (?, ?, 1, ?, NULL, NULL, NULL, ?)",
                (item.direction, item.name, default_payment, order),
            )
            template_id = int(cursor.lastrowid)
            for seq, leg in enumerate(item.legs, start=1):
                conn.execute(
                    "INSERT INTO trip_template_legs(template_id, seq, mode, vehicle, is_paid, "
                    "payment_method) VALUES (?, ?, ?, ?, 1, ?)",
                    (template_id, seq, leg.mode, leg.vehicle, leg.payment_method),
                )
            added += 1
        return added


# ===========================================================================
# Инициализация первого запуска
# ===========================================================================
@dataclass
class InitializationResult:
    """Результат открытия/создания БД при старте приложения."""

    db: Database
    created: bool
    summary: seed.SeedSummary | None = None
    is_first_run: bool = False


def initialize_database(path: str | None = None) -> InitializationResult:
    """Открыть БД приложения, создав её со стартовым набором при первом запуске.

    Последовательность первого запуска (FIRST-01): создать файл и каталог,
    создать схему версии 1, загрузить стартовый набор. Открытие существующей БД
    проверяет ``schema_version`` и при несовпадении отказывает в старте, не
    изменяя файл (DATA-19).
    """
    from .paths import default_db_path, resolve_db_path
    from .settings_service import SettingsService

    target = resolve_db_path(path) if path is not None else default_db_path()
    first_run = not is_initialized(target)
    db = create_database(target)
    if first_run:
        summary = Seeder(db).seed_all()
        # schema_version выставляется всегда и только официальным значением.
        SettingsService(db).set(SettingsKeys.SCHEMA_VERSION, str(SCHEMA_VERSION))
        return InitializationResult(db=db, created=True, summary=summary, is_first_run=True)
    # Повторный запуск идемпотентен (FIRST-04): недостающие ключи доливаются,
    # пользовательские значения не перезаписываются.
    summary = Seeder(db).seed_missing()
    return InitializationResult(db=db, created=False, summary=summary, is_first_run=False)


__all__ = ["Seeder", "InitializationResult", "initialize_database", "seed"]
