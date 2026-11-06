"""Base de datos del taller (SQLite).

Un solo archivo: taller.db. Se crea automaticamente al iniciar el bot.

Esquema: cada trabajo queda FIRMADO con el usuario de Telegram que lo
registro (usuario_id + mecanico). Sprint 5: consultas filtradas por rol
(los mecanicos solo ven lo suyo; el dueno ve todo y desgloses).
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "taller.db"

MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_ROW_FACTORY = sqlite3.Row


def conectar() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Crea/actualiza las tablas. Se llama al arrancar el bot."""
    with conectar() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trabajos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_hora  TEXT    NOT NULL,       -- fecha y hora ISO del registro
                placa       TEXT    NOT NULL,       -- ej: ABC123, ABC12D
                descripcion TEXT    NOT NULL,       -- trabajo realizado
                precio      REAL    NOT NULL,       -- valor cobrado
                chat_id     INTEGER NOT NULL,       -- chat de Telegram del registro
                anulado     INTEGER NOT NULL DEFAULT 0,  -- 1 = borrado logico
                usuario_id  INTEGER,                -- Telegram de quien registro (Sprint 5)
                mecanico    TEXT                    -- nombre legible (Sprint 5)
            )
            """
        )
        # Migracion para BD creadas antes del Sprint 5
        for columna, tipo in (
            ("anulado", "INTEGER NOT NULL DEFAULT 0"),
            ("usuario_id", "INTEGER"),
            ("mecanico", "TEXT"),
        ):
            try:
                conn.execute(f"ALTER TABLE trabajos ADD COLUMN {columna} {tipo}")
            except sqlite3.OperationalError:
                pass  # ya existia


def agregar_trabajo(
    placa: str,
    descripcion: str,
    precio: float,
    chat_id: int,
    usuario_id: int | None = None,
    mecanico: str | None = None,
) -> int:
    """Guarda un trabajo firmado por quien lo registro. Devuelve el id."""
    ahora = datetime.now().isoformat()
    with conectar() as conn:
        cursor = conn.execute(
            "INSERT INTO trabajos (fecha_hora, placa, descripcion, precio, chat_id, anulado, usuario_id, mecanico) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (ahora, placa.strip().upper(), descripcion, precio, chat_id, usuario_id, mecanico),
        )
        return cursor.lastrowid


# ------------------------- Consultas -------------------------


def _trabajos_entre(
    inicio: str, fin: str, usuario_id: int | None = None
) -> list[sqlite3.Row]:
    """Trabajos activos entre dos fechas ISO 'YYYY-MM-DD'.

    usuario_id filtra solo la firma de ese mecanico (None = todos).
    """
    sql = (
        "SELECT * FROM trabajos "
        "WHERE anulado = 0 AND substr(fecha_hora, 1, 10) >= ? "
        "AND substr(fecha_hora, 1, 10) <= ?"
    )
    parametros: list = [inicio, fin]
    if usuario_id is not None:
        sql += " AND usuario_id = ?"
        parametros.append(usuario_id)
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(sql + " ORDER BY id", parametros).fetchall()


def _resumen_entre(
    inicio: str, fin: str, usuario_id: int | None = None
) -> tuple[int, float]:
    """(cantidad, suma) de trabajos activos entre dos fechas."""
    sql = (
        "SELECT COUNT(*) AS cantidad, IFNULL(SUM(precio), 0) AS suma "
        "FROM trabajos WHERE anulado = 0 "
        "AND substr(fecha_hora, 1, 10) >= ? AND substr(fecha_hora, 1, 10) <= ?"
    )
    parametros: list = [inicio, fin]
    if usuario_id is not None:
        sql += " AND usuario_id = ?"
        parametros.append(usuario_id)
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        fila = conn.execute(sql, parametros).fetchone()
        return fila["cantidad"], fila["suma"]


def rango_periodo(dias: int | None = None, mes: bool = False) -> tuple[str, str, str]:
    """(inicio, fin, etiqueta) del periodo: hoy / N dias / mes en curso."""
    hoy = datetime.now()
    fin = hoy.strftime("%Y-%m-%d")
    if mes:
        inicio = hoy.strftime("%Y-%m-01")
        etiqueta = f"el mes de {MESES_ES[hoy.month - 1]}"
    elif dias:
        inicio = (hoy - timedelta(days=dias - 1)).strftime("%Y-%m-%d")
        etiqueta = f"los últimos {dias} días"
    else:
        inicio = fin
        etiqueta = "hoy"
    return inicio, fin, etiqueta


def trabajos_hoy(usuario_id: int | None = None) -> list[sqlite3.Row]:
    """Trabajos de HOY en orden de registro (S2-1). Filtrables por mecánico."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    return _trabajos_entre(hoy, hoy, usuario_id)


def resumen_periodo(
    dias: int | None = None, mes: bool = False, mecanico_id: int | None = None
) -> tuple[str, int, float]:
    """(etiqueta, cantidad, suma) del periodo, opcionalmente solo de un mecánico."""
    inicio, fin, etiqueta = rango_periodo(dias, mes)
    cantidad, suma = _resumen_entre(inicio, fin, mecanico_id)
    return etiqueta, cantidad, suma


def desglose_mecanicos(
    dias: int | None = None, mes: bool = False
) -> tuple[str, list[tuple[str, int, float]]]:
    """(etiqueta, [(mecanico, cantidad, suma), ...]) para el dueño (S5-3)."""
    inicio, fin, etiqueta = rango_periodo(dias, mes)
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        filas = conn.execute(
            "SELECT mecanico, COUNT(*) AS cantidad, IFNULL(SUM(precio), 0) AS suma "
            "FROM trabajos WHERE anulado = 0 "
            "AND substr(fecha_hora, 1, 10) >= ? AND substr(fecha_hora, 1, 10) <= ? "
            "GROUP BY mecanico ORDER BY suma DESC",
            (inicio, fin),
        ).fetchall()
    resumen = [
        (fila["mecanico"] if fila["mecanico"] else "sin firmar", fila["cantidad"], fila["suma"])
        for fila in filas
    ]
    return etiqueta, resumen


def historial_placa(
    placa: str, usuario_id: int | None = None, limite: int = 20
) -> tuple[list[sqlite3.Row], int, float]:
    """(trabajos_recientes, total_historico, suma_total) de un vehículo."""
    sql_base = "FROM trabajos WHERE anulado = 0 AND placa = ?"
    parametros: list = [placa]
    if usuario_id is not None:
        sql_base += " AND usuario_id = ?"
        parametros.append(usuario_id)
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        filas = conn.execute(
            f"SELECT * {sql_base} ORDER BY id DESC LIMIT ?", parametros + [limite]
        ).fetchall()
        fila = conn.execute(
            f"SELECT COUNT(*) AS cantidad, IFNULL(SUM(precio), 0) AS suma {sql_base}",
            parametros,
        ).fetchone()
        return filas, fila["cantidad"], fila["suma"]


def trabajo_por_id(trabajo_id: int) -> sqlite3.Row | None:
    """Un trabajo específico (para confirmar antes de anular, S2-4)."""
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            "SELECT * FROM trabajos WHERE id = ?", (trabajo_id,)
        ).fetchone()


def anular_trabajo(trabajo_id: int) -> bool:
    """Marca un trabajo como anulado (no borra fisicamente). True si existia."""
    with conectar() as conn:
        cursor = conn.execute(
            "UPDATE trabajos SET anulado = 1 WHERE id = ? AND anulado = 0",
            (trabajo_id,),
        )
        return cursor.rowcount == 1
