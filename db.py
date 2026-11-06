"""Base de datos del taller (SQLite).

Un solo archivo: taller.db. Se crea automaticamente al iniciar el bot.
Sprint 1: guardar trabajos.
Sprint 2: consultas (historial del dia, ganancias, buscar placa, anular).
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "taller.db"


def conectar() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Crea las tablas si no existen. Se llama al arrancar el bot."""
    with conectar() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trabajos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_hora  TEXT    NOT NULL,       -- fecha y hora ISO del registro
                placa       TEXT    NOT NULL,       -- ej: ABC123, ABC12D
                descripcion TEXT    NOT NULL,       -- trabajo realizado
                precio      REAL    NOT NULL,       -- valor cobrado
                chat_id     INTEGER NOT NULL        -- de quien vino el mensaje (staff)
            )
            """
        )
        # Sprint 2: columna para anular en vez de borrar (S2-4)
        try:
            conn.execute(
                "ALTER TABLE trabajos ADD COLUMN anulado INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # la columna ya existe


MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def agregar_trabajo(placa: str, descripcion: str, precio: float, chat_id: int) -> int:
    """Guarda un trabajo y devuelve el id asignado."""
    ahora = datetime.now().isoformat()  # ej: 2026-11-06T14:05:32.123456
    with conectar() as conn:
        cursor = conn.execute(
            "INSERT INTO trabajos (fecha_hora, placa, descripcion, precio, chat_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ahora, placa, descripcion, precio, chat_id),
        )
        return cursor.lastrowid


# ------------------------- Consultas (Sprint 2) -------------------------

_ROW_FACTORY = sqlite3.Row


def _trabajos_entre(inicio: str, fin: str) -> list[sqlite3.Row]:
    """Trabajos activos entre dos fechas ISO 'YYYY-MM-DD' (inclusive)."""
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            "SELECT * FROM trabajos "
            "WHERE anulado = 0 AND substr(fecha_hora, 1, 10) >= ? "
            "AND substr(fecha_hora, 1, 10) <= ? ORDER BY id",
            (inicio, fin),
        ).fetchall()


def _resumen_entre(inicio: str, fin: str) -> tuple[int, float]:
    """(cantidad, suma) de trabajos activos entre dos fechas ISO."""
    with conectar() as conn:
        fila = conn.execute(
            "SELECT COUNT(*) AS cantidad, IFNULL(SUM(precio), 0) AS suma "
            "FROM trabajos WHERE anulado = 0 "
            "AND substr(fecha_hora, 1, 10) >= ? AND substr(fecha_hora, 1, 10) <= ?",
            (inicio, fin),
        ).fetchone()
        return fila["cantidad"], fila["suma"]


def trabajos_hoy() -> list[sqlite3.Row]:
    """Los trabajos de HOY, en orden de registro (S2-1)."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    return _trabajos_entre(hoy, hoy)


def resumen_periodo(dias: int | None = None, mes: bool = False) -> tuple[str, int, float]:
    """
    Devuelve (etiqueta, cantidad, suma) del periodo elegido (S2-2).

    dias=None -> hoy | dias=7 -> ultimos 7 dias (incluyendo hoy) | mes=True -> mes en curso.
    """
    hoy = datetime.now()
    if mes:
        inicio = hoy.strftime("%Y-%m-01")
        etiqueta = f"el mes de {MESES_ES[hoy.month - 1]}"
    elif dias:
        inicio = (hoy - timedelta(days=dias - 1)).strftime("%Y-%m-%d")
        etiqueta = f"los últimos {dias} días"
    else:
        inicio = hoy.strftime("%Y-%m-%d")
        etiqueta = "hoy"
    cantidad, suma = _resumen_entre(inicio, hoy.strftime("%Y-%m-%d"))
    return etiqueta, cantidad, suma


def historial_placa(placa: str, limite: int = 20) -> tuple[list[sqlite3.Row], int, float]:
    """
    Historial de un vehículo (S2-3).

    Devuelve (trabajos_recientes_mas_unlimite, total_de_fechas, suma_total_pagada).
    """
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        filas = conn.execute(
            "SELECT * FROM trabajos WHERE anulado = 0 AND placa = ? ORDER BY id DESC LIMIT ?",
            (placa, limite),
        ).fetchall()
        fila = conn.execute(
            "SELECT COUNT(*) AS cantidad, IFNULL(SUM(precio), 0) AS suma "
            "FROM trabajos WHERE anulado = 0 AND placa = ?",
            (placa,),
        ).fetchone()
        return filas, fila["cantidad"], fila["suma"]


def trabajo_por_id(trabajo_id: int) -> sqlite3.Row | None:
    """Busca un trabajo específico (para confirmar antes de anular, S2-4)."""
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            "SELECT * FROM trabajos WHERE id = ?", (trabajo_id,)
        ).fetchone()


def anular_trabajo(trabajo_id: int) -> bool:
    """Marca un trabajo como anulado (no lo borra fisicamente). True si existía."""
    with conectar() as conn:
        cursor = conn.execute(
            "UPDATE trabajos SET anulado = 1 WHERE id = ? AND anulado = 0",
            (trabajo_id,),
        )
        return cursor.rowcount == 1
