"""Base de datos del taller (SQLite).

Un solo archivo: taller.db. Se crea automaticamente al iniciar el bot.
En este sprint solo guardamos trabajos; las consultas llegan en el Sprint 2.
"""
import sqlite3
from datetime import datetime
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
    print(f"Base de datos lista en {DB_PATH}")


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
