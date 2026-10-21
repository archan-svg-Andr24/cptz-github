"""Подключение к БД, транзакции и защита версии схемы (DATA-01…DATA-19).

Ключевые правила:

* SQLite, один локальный файл, ``journal_mode = DELETE`` (DATA-04) — файл
  пригоден для ручного копирования.
* Каталог создаётся автоматически при первом запуске (DATA-03).
* Каждое изменение — в транзакции (DATA-08). Вложенность безопасна: работает
  счётчик глубины, а не сырой ``BEGIN`` (иначе вложенный вызов ломал бы
  атомарность каскадного пересчёта CALC-04).
* Любое несовпадение ``schema_version`` при открытии (выше **или** ниже) —
  отказ старта, файл не изменяется (DATA-19). Механизм миграции — v1.1.
* БД занята другим процессом — повтор до 5 попыток с интервалом 1 с (ERR).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .. import SCHEMA_VERSION
from .errors import (
    DatabaseBusyError,
    DatabaseCorruptedError,
    SchemaVersionError,
)
from .schema import create_schema, has_table
from .settings_registry import SettingsKeys

log = logging.getLogger(__name__)

#: Пауза между попытками при занятой БД (ERR).
BUSY_RETRY_DELAY = 1.0
#: Число попыток (ERR: «повтор через 1 с до 5 попыток»).
BUSY_RETRIES = 5
#: Таймаут ожидания блокировки внутри sqlite3, секунды.
BUSY_TIMEOUT = 5.0


class Database:
    """Обёртка над ``sqlite3.Connection`` с транзакциями и защитой версии."""

    def __init__(self, path: Path, connection: sqlite3.Connection) -> None:
        self.path = Path(path)
        self._conn = connection
        self._depth = 0
        self.readonly = False

    # ---------------------------------------------------------------- доступ
    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:  # pragma: no cover — на закрытии не падаем
                log.warning("Ошибка при закрытии БД", exc_info=True)
            self._conn = None  # type: ignore[assignment]

    # -------------------------------------------------------------- запросы
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq_of_params: list[tuple]) -> sqlite3.Cursor:
        return self._conn.executemany(sql, seq_of_params)

    def fetchall(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = ()) -> object:
        row = self._conn.execute(sql, params).fetchone()
        return None if row is None else row[0]

    # ----------------------------------------------------------- транзакции
    @property
    def in_transaction(self) -> bool:
        return self._depth > 0

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Атомарная запись (DATA-08), с корректной вложенностью.

        Соединение открыто в режиме ``isolation_level=None`` (autocommit), поэтому
        транзакция начинается **явно**: без ``BEGIN`` откат не вернул бы ничего, и
        требование «частичных строк не остаётся» (ACC-M-100) не выполнялось бы.

        Вложенный вызов не открывает вторую транзакцию, а ставит ``SAVEPOINT``:
        откат внутреннего блока возвращает состояние на его начало, а откат
        внешнего — всё целиком. Это и требуется каскадному пересчёту CALC-04,
        который работает внутри сервисной транзакции.
        """
        if self._depth == 0:
            self._begin_immediate()
            self._depth = 1
            try:
                yield self._conn
            except BaseException:
                self._depth = 0
                self._conn.rollback()
                raise
            else:
                self._depth = 0
                self._conn.commit()
            return

        name = f"dsh_sp_{self._depth}"
        self._conn.execute(f"SAVEPOINT {name}")
        self._depth += 1
        try:
            yield self._conn
        except BaseException:
            self._depth -= 1
            self._conn.execute(f"ROLLBACK TO {name}")
            self._conn.execute(f"RELEASE {name}")
            raise
        else:
            self._depth -= 1
            self._conn.execute(f"RELEASE {name}")

    def _begin_immediate(self) -> None:
        """Начать транзакцию, дождавшись освобождения файла (ERR-06).

        ``BEGIN IMMEDIATE`` сразу берёт блокировку записи, поэтому занятый файл
        обнаруживается здесь, а не на первом ``INSERT``. Повторяем попытки тем
        же образом, что и при открытии.
        """
        last_error: Exception | None = None
        for attempt in range(1, BUSY_RETRIES + 1):
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                return
            except sqlite3.OperationalError as exc:
                text = str(exc).lower()
                if "locked" not in text and "busy" not in text:
                    raise
                last_error = exc
                log.warning("Запись в БД занята (попытка %s из %s)", attempt, BUSY_RETRIES)
                if attempt < BUSY_RETRIES:
                    time.sleep(BUSY_RETRY_DELAY)
        raise DatabaseBusyError(
            "База данных занята другим процессом: изменения не сохранены. "
            "Закройте второй экземпляр приложения и повторите попытку."
        ) from last_error

    def commit(self) -> None:
        if self._depth == 0:
            self._conn.commit()

    def rollback(self) -> None:
        if self._depth == 0:
            self._conn.rollback()

    # ------------------------------------------------------------- PRAGMA
    def journal_mode(self) -> str:
        row = self._conn.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]).lower() if row else ""

    def foreign_keys_enabled(self) -> bool:
        row = self._conn.execute("PRAGMA foreign_keys").fetchone()
        return bool(row and row[0])


def _open_connection(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Открыть соединение с повторами при занятой БД (ERR)."""
    uri = f"file:{path.as_posix()}?mode=ro" if readonly else str(path)
    last_error: Exception | None = None
    for attempt in range(1, BUSY_RETRIES + 1):
        try:
            conn = sqlite3.connect(
                uri,
                timeout=BUSY_TIMEOUT,
                isolation_level=None,  # ручное управление транзакциями
                uri=readonly,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # Внешние ключи обязательны: DATA-15 опирается на них.
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT * 1000)}")
            if not readonly:
                conn.execute("PRAGMA journal_mode = DELETE")  # DATA-04
            return conn
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            last_error = exc
            log.warning("БД занята (попытка %s из %s)", attempt, BUSY_RETRIES)
            if attempt < BUSY_RETRIES:
                time.sleep(BUSY_RETRY_DELAY)
    raise DatabaseBusyError(
        "База данных занята другим процессом. Закройте второй экземпляр приложения "
        "и повторите попытку."
    ) from last_error


def _read_schema_version(conn: sqlite3.Connection) -> str | None:
    """Версия схемы из ``settings`` или ``None``, если БД пустая/без ключа."""
    if not has_table(conn, "settings"):
        return None
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (SettingsKeys.SCHEMA_VERSION,)
    ).fetchone()
    return None if row is None else str(row[0])


def _verify_schema_version(conn: sqlite3.Connection, path: Path) -> None:
    """DATA-19: несовпадение версии — отказ старта, файл не изменяется."""
    stored = _read_schema_version(conn)
    if stored is None:
        # Таблица настроек есть, а ключа версии нет — это не «чистая база»:
        # файл создан не этим приложением либо повреждён. Молча дописывать
        # версию нельзя, иначе можно испортить чужую базу (DATA-19).
        if has_table(conn, "settings"):
            raise SchemaVersionError(
                f"В файле {path.name} отсутствует ключ версии схемы. "
                "Приложение не может открыть эту базу данных и не изменяло её.",
                details={"stored": None, "supported": SCHEMA_VERSION},
            )
        return
    try:
        stored_number = int(str(stored).strip())
    except ValueError as exc:
        raise SchemaVersionError(
            f"Версия схемы в файле {path.name} не читается ({stored!r}). "
            "Приложение не может открыть эту базу данных.",
        ) from exc
    if stored_number != SCHEMA_VERSION:
        relation = "новее" if stored_number > SCHEMA_VERSION else "старше"
        raise SchemaVersionError(
            f"Файл базы данных {path} создан версией схемы {stored_number}, "
            f"которая {relation} поддерживаемой приложением версии {SCHEMA_VERSION}. "
            "Приложение не может открыть этот файл и не изменяло его. "
            "Механизм миграции появится в следующей версии.",
            details={"stored": stored_number, "supported": SCHEMA_VERSION},
        )


def is_initialized(path: Path) -> bool:
    """Есть ли в файле схема приложения версии 1."""
    if not Path(path).exists():
        return False
    conn = sqlite3.connect(str(path))
    try:
        return has_table(conn, "settings") and has_table(conn, "transport_rides")
    finally:
        conn.close()


def open_database(path: str | Path, *, readonly: bool = False) -> Database:
    """Открыть существующую БД с проверкой версии схемы (DATA-19)."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Файл базы данных не найден: {target}")
    try:
        conn = _open_connection(target, readonly=readonly)
    except sqlite3.DatabaseError as exc:
        raise DatabaseCorruptedError(
            f"Файл базы данных {target.name} повреждён. Предлагается создать новую базу "
            "или восстановить данные из резервной копии; старый файл не удаляется.",
        ) from exc
    try:
        _verify_schema_version(conn, target)
    except BaseException:
        conn.close()
        raise
    return Database(target, conn)


def create_database(path: str | Path, *, now_iso: str | None = None) -> Database:
    """Создать файл БД со схемой версии 1 (первый запуск, DATA-03).

    Стартовый набор загружается отдельно (``seed``), чтобы инициализация схемы
    и данные Прил. А оставались независимыми.
    """
    from . import dates as dt

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists() and target.stat().st_size > 0
    conn = _open_connection(target)
    try:
        if existed:
            _verify_schema_version(conn, target)
            if has_table(conn, "settings"):
                return Database(target, conn)  # уже инициализирована (FIRST-04)
        conn.execute("BEGIN IMMEDIATE")
        try:
            create_schema(conn)
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (SettingsKeys.SCHEMA_VERSION, str(SCHEMA_VERSION)),
            )
            _ = now_iso or dt.today_iso()
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise DatabaseCorruptedError(
            f"Не удалось инициализировать базу данных {target.name}: {exc}. "
            "Проверьте права на каталог и свободное место на диске.",
        ) from exc
    except BaseException:
        conn.close()
        raise
    return Database(target, conn)


@contextmanager
def database_at(path: str | Path) -> Iterator[Database]:
    """Открыть БД и гарантированно закрыть её."""
    db = open_database(path)
    try:
        yield db
    finally:
        db.close()


__all__ = [
    "Database",
    "open_database",
    "create_database",
    "database_at",
    "is_initialized",
    "BUSY_RETRY_DELAY",
    "BUSY_RETRIES",
]
