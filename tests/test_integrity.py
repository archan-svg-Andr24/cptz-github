"""Слой 1: первый запуск, схема и целостность БД (ACC-M-68…72, 97…101, 105, 106).

Проверяется DATA-19 (отказ при несовпадении версии схемы без изменения файла),
DATA-04/15 (журнал и внешние ключи), FIRST-01…FIRST-15 (создание и восстановление
стартового набора) и устойчивость к занятому файлу (ERR-06).
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from student_planner import SCHEMA_VERSION
from student_planner.core.database import (
    Database,
    create_database,
    database_at,
    is_initialized,
    open_database,
)
from student_planner.core.errors import (
    DatabaseBusyError,
    DatabaseCorruptedError,
    SchemaVersionError,
)
from student_planner.core.schema import TABLE_ORDER, create_schema, has_table, table_names
from student_planner.core.seeding import InitializationResult, Seeder, initialize_database


# ---------------------------------------------------------------------------
# ACC-M-97 — ровно 18 таблиц из Прил. Б.
# ---------------------------------------------------------------------------
def test_acc_m_97_exactly_eighteen_tables(db: Database) -> None:
    names = set(table_names(db))
    expected = set(TABLE_ORDER)
    assert len(TABLE_ORDER) == 18, "Прил. Б описывает 18 таблиц"
    assert names >= expected
    # Лишних таблиц быть не должно (кроме системных sqlite_*).
    extra = {name for name in names - expected if not name.startswith("sqlite_")}
    assert extra == set(), f"Неизвестные таблицы: {sorted(extra)}"


def test_acc_m_97_all_required_tables_present(db: Database) -> None:
    for table in TABLE_ORDER:
        assert has_table(db, table), f"Таблица «{table}» отсутствует (Прил. Б)"


# ---------------------------------------------------------------------------
# ACC-M-99 — файл переносим: путь нигде не зашит абсолютно.
# ---------------------------------------------------------------------------
def test_acc_m_99_database_is_portable(tmp_path: Path) -> None:
    first_path = tmp_path / "first" / "planner.db"
    first = create_database(first_path)
    Seeder(first).seed_all()
    first.close()

    # Переносим файл в другое место — база должна открыться и работать.
    second_path = tmp_path / "moved" / "planner.db"
    second_path.parent.mkdir(parents=True, exist_ok=True)
    first_path.replace(second_path)

    moved = open_database(second_path)
    try:
        assert moved.scalar("SELECT COUNT(*) FROM subjects") == 9
    finally:
        moved.close()


def test_acc_m_99_no_absolute_paths_inside_db(db: Database) -> None:
    """В настройках хранятся шаблоны с ``%APPDATA%``, а не абсолютные пути."""
    Seeder(db).seed_all()
    for row in db.fetchall("SELECT key, value FROM settings"):
        value = row["value"]
        assert not (len(value) > 2 and value[1] == ":"), (
            f"Значение «{row['key']}» содержит абсолютный путь: {value}"
        )


# ---------------------------------------------------------------------------
# ACC-M-68 / ACC-M-69 — создание и восстановление стартового набора.
# ---------------------------------------------------------------------------
def test_acc_m_68_first_run_creates_expected_records(tmp_path: Path) -> None:
    path = tmp_path / "planner.db"
    result = initialize_database(path)
    assert isinstance(result, InitializationResult)
    assert result.created is True, "Первый запуск создаёт файл"
    summary = result.summary
    assert summary is not None

    db = open_database(path)
    try:
        assert db.scalar("SELECT COUNT(*) FROM subjects") == 9
        assert db.scalar("SELECT COUNT(*) FROM bell_profiles") == 7, "Пн–Сб + воскресенье"
        assert db.scalar("SELECT COUNT(*) FROM tariffs") == 5
        assert db.scalar("SELECT COUNT(*) FROM week_anchors") >= 1
        assert db.scalar("SELECT COUNT(*) FROM schedule_templates") == 32, (
            "А.7 п. 2: по 16 заполненных ячеек в верхней и нижней неделе"
        )
        assert db.scalar("SELECT COUNT(*) FROM trip_templates") == 7
    finally:
        db.close()


def test_acc_m_69_reopen_existing_database_does_not_reseed(tmp_path: Path) -> None:
    path = tmp_path / "planner.db"
    initialize_database(path)

    second = initialize_database(path)
    assert second.created is False, "Повторный запуск не пересоздаёт файл"
    db = open_database(path)
    try:
        assert db.scalar("SELECT COUNT(*) FROM subjects") == 9, "Дубликатов нет"
    finally:
        db.close()


def test_first_run_writes_schema_version_setting(tmp_path: Path) -> None:
    path = tmp_path / "planner.db"
    initialize_database(path)
    db = open_database(path)
    try:
        row = db.fetchone("SELECT value FROM settings WHERE key = 'schema_version'")
        assert row is not None and row["value"] == str(SCHEMA_VERSION)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# ACC-M-71 / ACC-M-72 — отказ при несовпадении версии схемы (DATA-19).
# ---------------------------------------------------------------------------
def _make_database_with_version(path: Path, version: str) -> None:
    create_database(path).close()
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("UPDATE settings SET value = ? WHERE key = 'schema_version'", (version,))
        conn.commit()
    finally:
        conn.close()


def test_acc_m_71_higher_schema_version_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    _make_database_with_version(path, "99")
    before = path.read_bytes()

    with pytest.raises(SchemaVersionError) as excinfo:
        open_database(path)
    assert "99" in str(excinfo.value), "Сообщение называет найденную версию"
    assert path.read_bytes() == before, "Файл не изменён при отказе (DATA-19)"


def test_acc_m_72_lower_schema_version_refused(tmp_path: Path) -> None:
    """Понижение версии тоже отказ: миграций в MVP нет (DATA-19)."""
    path = tmp_path / "old.db"
    _make_database_with_version(path, "0")
    before = path.read_bytes()

    with pytest.raises(SchemaVersionError) as excinfo:
        open_database(path)
    assert "0" in str(excinfo.value)
    assert path.read_bytes() == before


def test_missing_schema_version_key_refused(tmp_path: Path) -> None:
    """Отсутствие ключа версии — тоже несовпадение, а не «пустая база»."""
    path = tmp_path / "nokey.db"
    create_database(path).close()
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("DELETE FROM settings WHERE key = 'schema_version'")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(SchemaVersionError):
        open_database(path)


def test_non_numeric_schema_version_refused(tmp_path: Path) -> None:
    path = tmp_path / "weird.db"
    _make_database_with_version(path, "abc")
    with pytest.raises(SchemaVersionError):
        open_database(path)


# ---------------------------------------------------------------------------
# ACC-M-105 / ACC-M-106 — повреждённый и занятый файл (ERR-02, ERR-06).
# ---------------------------------------------------------------------------
def test_acc_m_105_corrupted_file_reported(tmp_path: Path) -> None:
    path = tmp_path / "broken.db"
    path.write_bytes(b"this is definitely not a sqlite database" * 100)
    with pytest.raises(DatabaseCorruptedError):
        open_database(path)


def test_acc_m_106_busy_file_reported(tmp_path: Path, monkeypatch) -> None:
    """Занятый файл: сообщение «Файл занят», без потери данных (ERR-06).

    Бюджет повторов сокращён: по ТЗ это 5 попыток по 1 с, и в тесте нет смысла
    ждать полные 30 секунд — проверяется сам факт отказа и текст сообщения.
    """
    from student_planner.core import database as database_module

    monkeypatch.setattr(database_module, "BUSY_RETRIES", 2)
    monkeypatch.setattr(database_module, "BUSY_RETRY_DELAY", 0.01)
    monkeypatch.setattr(database_module, "BUSY_TIMEOUT", 0.05)

    path = tmp_path / "busy.db"
    create_database(path).close()

    blocker = sqlite3.connect(str(path))
    try:
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute("INSERT INTO settings(key, value) VALUES ('probe', '1')")

        db = open_database(path)
        try:
            with pytest.raises(DatabaseBusyError) as excinfo:
                with db.transaction():
                    pass
            assert "занят" in str(excinfo.value).lower()
        finally:
            db.close() if hasattr(db, "close") else None
    finally:
        blocker.rollback()
        blocker.close()


# ---------------------------------------------------------------------------
# ACC-M-100 / ACC-M-101 — транзакции и линейность роста.
# ---------------------------------------------------------------------------
def test_acc_m_100_is_initialized_detects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    path.touch()
    assert is_initialized(path) is False

    create_database(path).close()
    assert is_initialized(path) is True


def test_acc_m_101_storage_grows_linearly(db: Database) -> None:
    """Рост объёма при добавлении поездок близок к линейному (ACC-M-101)."""
    from datetime import timedelta

    def size_of(database: Database, path: Path) -> int:
        database.commit()
        return path.stat().st_size

    path = Path(db.path)
    baseline = size_of(db, path)

    def fill(count: int, start: int) -> None:
        rows = []
        base = date(2026, 9, 1)
        for index in range(start, start + count):
            day = base + timedelta(days=index // 2)
            rows.append(
                (day.isoformat(), day.isoformat(), "home_to_college", "bus", "22",
                 "50.00", "25.00", "25.00", "strelka", "2026-09-01 08:00:00")
            )
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO transport_rides(study_date, ride_date, direction, transport_type, "
                "vehicle, base_price, paid_price, discount_amount, payment_method, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    fill(500, 0)
    size_500 = size_of(db, path)
    fill(4500, 500)
    size_5000 = size_of(db, path)

    growth_500 = size_500 - baseline
    growth_5000 = size_5000 - baseline
    assert growth_500 > 0 and growth_5000 > growth_500
    # 10-кратный рост данных не даёт квадратичного роста файла.
    assert growth_5000 / growth_500 < 12, (
        f"Рост нелинейный: 500 → {growth_500} Б, 5000 → {growth_5000} Б"
    )
    assert size_5000 < 2 * 1024 * 1024, "5000 поездок укладываются в 2 МиБ"


# ---------------------------------------------------------------------------
# DATA-04 / DATA-15 — журнал и внешние ключи.
# ---------------------------------------------------------------------------
def test_data_04_journal_mode_delete(db: Database) -> None:
    assert db.journal_mode().lower() == "delete", "DATA-04: журнал DELETE"


def test_data_15_foreign_keys_enabled(db: Database) -> None:
    assert db.foreign_keys_enabled() is True


def test_data_15_foreign_key_violation_rejected(db: Database) -> None:
    with pytest.raises(Exception):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO schedule_templates(profile_id, week_type, slot_no, subject_id) "
                "VALUES (999, 'lower', 1, NULL)"
            )


def test_data_04_no_wal_files_created(db: Database) -> None:
    """В режиме DELETE файлов ``-wal``/``-shm`` не появляется (DATA-04)."""
    path = Path(db.path)
    Seeder(db).seed_all()
    assert not path.with_suffix(path.suffix + "-wal").exists()
    assert not path.with_suffix(path.suffix + "-shm").exists()


# ---------------------------------------------------------------------------
# FIRST-05 — восстановление только отсутствующего.
# ---------------------------------------------------------------------------
def test_first_05_seed_missing_preserves_user_edits(db: Database) -> None:
    Seeder(db).seed_all()
    db.execute("UPDATE settings SET value = 'Мой колледж' WHERE key = 'college_name'")
    db.commit()

    Seeder(db).seed_missing()
    row = db.fetchone("SELECT value FROM settings WHERE key = 'college_name'")
    assert row is not None and row["value"] == "Мой колледж", (
        "FIRST-05: существующие значения не перезаписываются"
    )


def test_seed_all_does_not_duplicate_on_second_call(db: Database) -> None:
    first = Seeder(db).seed_all()
    second = Seeder(db).seed_all()
    assert second.total == 0, "Повторный набор ничего не добавляет"
    assert first.subjects_added == 9
