"""Base de datos del taller (SQLite).

Sprint 6 - MULTI-TENANT: varios talleres, cada uno con sus usuarios.
- talleres:    cada taller registrado (/nuevotaller)
- usuarios:    quien pertenece a que taller y con que rol (dueno/mecanico)
- invitaciones: codigos para links tipo https://t.me/BOT?start=CODIGO
- solicitudes: la peticion "quiero unirme" que el dueno acepta o rechaza
- trabajos:    1 fila por trabajo registrado. SIEMPRE lleva taller_id y
               queda firmada con usuario_id/mecanico.
"""
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "taller.db"

MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

ROL_DUENO = "dueno"
ROL_MECANICO = "mecanico"

_ROW_FACTORY = sqlite3.Row


def conectar() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db(duenos_antiguos: dict[int, str] | None = None) -> None:
    """
    Crea/actualiza las tablas y SI hace migracion desde el modelo viejo:
    si existian trabajos sin taller, se agrupan automaticamente en el
    taller 'Taller Prueba' y los duenos antiguos del .env quedan como tal.
    """
    with conectar() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS talleres (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre    TEXT NOT NULL,
                creado    TEXT NOT NULL,
                nit       TEXT,    -- datos para el encabezado de la factura (S7)
                direccion TEXT,
                telefono  TEXT,
                logo      TEXT     -- ruta del logo subido por el dueño
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id   INTEGER PRIMARY KEY,       -- 1 usuario = 1 taller
                taller_id INTEGER NOT NULL,
                nombre    TEXT NOT NULL,
                rol       TEXT NOT NULL,             -- 'dueno' | 'mecanico'
                activo    INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invitaciones (
                codigo     TEXT PRIMARY KEY,
                taller_id  INTEGER NOT NULL,
                rol        TEXT NOT NULL,
                creada_por INTEGER NOT NULL,           -- dueno que genero el link
                activa     INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS solicitudes (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo  TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                nombre  TEXT NOT NULL,
                estado  TEXT NOT NULL DEFAULT 'pendiente'   -- pendiente/aceptada/rechazada
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS codigos_usados (
                codigo    TEXT PRIMARY KEY,       -- codigo de venta: un solo uso
                taller_id INTEGER NOT NULL,
                user_id   INTEGER NOT NULL,       -- quien lo redimio
                fecha     TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trabajos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_hora  TEXT    NOT NULL,
                placa       TEXT    NOT NULL,
                descripcion TEXT    NOT NULL,
                precio      REAL    NOT NULL,
                chat_id     INTEGER NOT NULL,
                anulado     INTEGER NOT NULL DEFAULT 0,
                taller_id   INTEGER,                    -- de que taller es (S6)
                usuario_id  INTEGER,                    -- quien lo registro
                mecanico    TEXT
            )
            """
        )
        # Migraciones para BD nacidas antes que los sprints (idempotentes)
        # Sprint 9: cierre logico de talleres (1 abierto / 0 cerrado)
        _asegurar_columna(
            conn, "talleres", "activo", "INTEGER NOT NULL DEFAULT 1"
        )
        for columna, tipo in (
            ("anulado", "INTEGER NOT NULL DEFAULT 0"),
            ("usuario_id", "INTEGER"),
            ("mecanico", "TEXT"),
            ("taller_id", "INTEGER"),
        ):
            _asegurar_columna(conn, "trabajos", columna, tipo)
        # Datos comerciales de la factura (Sprint 7)
        for columna in ("nit", "direccion", "telefono", "logo"):
            _asegurar_columna(conn, "talleres", columna, "TEXT")
            # Limpieza de la version rota del ALTER (S7 dev): si los datos
            # comerciales terminaron mal cargados en trabajos, fuera.
            _borrar_columna_si_existe(conn, "trabajos", columna)

        _migrar_antiguo(conn, duenos_antiguos or {})


def _asegurar_columna(conn: sqlite3.Connection, tabla: str, columna: str, tipo: str) -> None:
    """ALTER TABLE idempotente (SQLite no tiene IF NOT EXISTS para columnas)."""
    try:
        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
    except sqlite3.OperationalError:
        pass  # ya existe


def _borrar_columna_si_existe(conn: sqlite3.Connection, tabla: str, columna: str) -> None:
    """Retira una columna que quedó mal agregada por una migración anterior."""
    columnas = [fila[1] for fila in conn.execute(f"PRAGMA table_info({tabla})")]
    if columna in columnas:
        try:
            conn.execute(f"ALTER TABLE {tabla} DROP COLUMN {columna}")
        except sqlite3.OperationalError:
            pass  # SQLite viejo sin DROP COLUMN: quedará como datos residuales


def _migrar_antiguo(conn: sqlite3.Connection, duenos_antiguos: dict[int, str]) -> None:
    """Instalaciones previas: trabajos sin taller + duenos del .env -> BD."""
    n_talleres = conn.execute("SELECT COUNT(*) FROM talleres").fetchone()[0]
    n_trabajos = conn.execute("SELECT COUNT(*) FROM trabajos").fetchone()[0]
    if n_talleres > 0 or (n_trabajos == 0 and not duenos_antiguos):
        return

    creado = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO talleres (nombre, creado) VALUES ('Taller Prueba', ?)",
        (creado,),
    )
    taller_id = conn.execute(
        "SELECT id FROM talleres ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    print(f"Migracion: trabajos antiguos -> nuevo taller #{taller_id} 'Taller Prueba'")

    conn.execute(
        "UPDATE trabajos SET taller_id = ? WHERE taller_id IS NULL", (taller_id,)
    )
    for user_id, nombre in duenos_antiguos.items():
        conn.execute(
            "INSERT OR IGNORE INTO usuarios (user_id, taller_id, nombre, rol, activo) "
            "VALUES (?, ?, ?, 'dueno', 1)",
            (user_id, taller_id, nombre or "Dueño"),
        )


# ----------------------- Talleres y usuarios -----------------------


def crear_taller(nombre: str, dueno_id: int, dueno_nombre: str) -> int:
    """Registra un taller nuevo con su dueno. Devuelve el id del taller."""
    ahora = datetime.now().isoformat()
    with conectar() as conn:
        cursor = conn.execute(
            "INSERT INTO talleres (nombre, creado) VALUES (?, ?)",
            (nombre, ahora),
        )
        taller_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO usuarios (user_id, taller_id, nombre, rol, activo) "
            "VALUES (?, ?, ?, 'dueno', 1)",
            (dueno_id, taller_id, dueno_nombre),
        )
        return taller_id


def agregar_usuario(user_id: int, taller_id: int, nombre: str, rol: str) -> bool:
    """Agrega (o reactiva) un usuario en un taller con rol dueno/mecanico."""
    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO usuarios (user_id, taller_id, nombre, rol, activo)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                taller_id = excluded.taller_id,
                nombre    = excluded.nombre,
                rol       = excluded.rol,
                activo    = 1
            """,
            (user_id, taller_id, nombre, rol),
        )
        return cursor.rowcount == 1


def cambiar_rol(user_id: int, rol: str, taller_id: int) -> bool:
    with conectar() as conn:
        cursor = conn.execute(
            "UPDATE usuarios SET rol = ? WHERE user_id = ? AND taller_id = ?",
            (rol, user_id, taller_id),
        )
        return cursor.rowcount == 1


def expulsar_usuario(user_id: int, taller_id: int) -> bool:
    """Desactiva al usuario (borrado logico; puede volver con otro link)."""
    with conectar() as conn:
        cursor = conn.execute(
            "UPDATE usuarios SET activo = 0 WHERE user_id = ? AND taller_id = ?",
            (user_id, taller_id),
        )
        return cursor.rowcount == 1


def usuario_por_id(user_id: int) -> sqlite3.Row | None:
    """El perfil (taller, rol, nombre) de un usuario ACTIVO de taller ABIERTO.

    Si el taller estaba cerrado la membresia no vale (Sprint 9): el usuario
    queda 'sin taller' y tiene que unirse a otro (con su codigo o invitacion).
    """
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            """
            SELECT u.* FROM usuarios u
            JOIN talleres t ON t.id = u.taller_id
            WHERE u.user_id = ? AND u.activo = 1 AND t.activo = 1
            """,
            (user_id,),
        ).fetchone()


def personal_del_taller(taller_id: int) -> list[sqlite3.Row]:
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            "SELECT * FROM usuarios WHERE taller_id = ? ORDER BY rol, nombre",
            (taller_id,),
        ).fetchall()


def obtener_taller(taller_id: int) -> sqlite3.Row | None:
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            "SELECT * FROM talleres WHERE id = ?", (taller_id,)
        ).fetchone()


CAMPOS_TALLER = ("nombre", "nit", "direccion", "telefono")


def guardar_datos_taller(taller_id: int, campos: dict[str, str]) -> None:
    """Actualiza campos del encabezado comercial (whitelist S7)."""
    limpios = {k: v for k, v in campos.items() if k in CAMPOS_TALLER and v}
    if not limpios:
        return
    cambios = ", ".join(f"{k} = ?" for k in limpios)
    with conectar() as conn:
        conn.execute(
            f"UPDATE talleres SET {cambios} WHERE id = ?",
            (*limpios.values(), taller_id),
        )


def guardar_logo(taller_id: int, ruta_logo: str) -> None:
    with conectar() as conn:
        conn.execute(
            "UPDATE talleres SET logo = ? WHERE id = ?", (ruta_logo, taller_id)
        )


# ----------------------- Invitaciones y solicitudes -----------------------


def crear_invitacion(taller_id: int, rol: str, creada_por: int) -> str:
    """Genera un codigo para el deep link de invitacion (reusable)."""
    codigo = secrets.token_hex(8)
    with conectar() as conn:
        conn.execute(
            "INSERT INTO invitaciones (codigo, taller_id, rol, creada_por, activa) "
            "VALUES (?, ?, ?, ?, 1)",
            (codigo, taller_id, rol, creada_por),
        )
        return codigo


def invitacion_por_codigo(codigo: str) -> sqlite3.Row | None:
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            "SELECT * FROM invitaciones WHERE codigo = ?", (codigo,)
        ).fetchone()


def revocar_invitacion(codigo: str, taller_id: int) -> bool:
    with conectar() as conn:
        cursor = conn.execute(
            "UPDATE invitaciones SET activa = 0 WHERE codigo = ? AND taller_id = ?",
            (codigo, taller_id),
        )
        return cursor.rowcount == 1


# ------------------- Codigos de venta (Sprint 8) -------------------


def codigo_ya_redimido(codigo: str) -> bool:
    with conectar() as conn:
        return conn.execute(
            "SELECT 1 FROM codigos_usados WHERE codigo = ?", (codigo,)
        ).fetchone() is not None


def redimir_codigo(codigo: str, taller_id: int, user_id: int) -> bool:
    """Quema el codigo ATOMICAMENTE. False si alguien ya lo consumio."""
    with conectar() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO codigos_usados (codigo, taller_id, user_id, fecha) "
            "VALUES (?, ?, ?, ?)",
            (codigo, taller_id, user_id, datetime.now().isoformat()),
        )
        return cursor.rowcount == 1


# ---------------------- Cierre de talleres (Sprint 9) ----------------------


def cerrar_taller(taller_id: int) -> bool:
    """Cierre LOGICO: activo=0 + revoca invitaciones. False si ya estaba."""
    with conectar() as conn:
        cursor = conn.execute(
            "UPDATE talleres SET activo = 0 "
            "WHERE id = ? AND activo = 1", (taller_id,)
        )
        estaba_abierto = cursor.rowcount == 1
        if estaba_abierto:
            # los links de invitacion de un taller cerrado ya no valen nada
            conn.execute(
                "UPDATE invitaciones SET activa = 0 WHERE taller_id = ?",
                (taller_id,),
            )
        return estaba_abierto


def listar_talleres() -> list[sqlite3.Row]:
    """Vista del desarrollador: todos los talleres con su estado y cifras."""
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            """
            SELECT   t.id, t.nombre, t.activo,
                (SELECT COUNT(*) FROM usuarios  u
                 WHERE u.taller_id = t.id AND u.activo = 1)      AS n_staff,
                (SELECT COUNT(*) FROM trabajos  tr
                 WHERE tr.taller_id = t.id AND tr.anulado = 0)   AS n_trabajos
            FROM talleres t
            ORDER BY t.id
            """
        ).fetchall()


def crear_solicitud(codigo: str, user_id: int, nombre: str) -> int | None:
    """Guarda el 'quiero unirme'. Devuelve id o None si ya hay pendiente."""
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        fila = conn.execute(
            "SELECT id, estado FROM solicitudes WHERE codigo = ? AND user_id = ?",
            (codigo, user_id),
        ).fetchone()
        if fila and fila["estado"] == "pendiente":
            return None
        if fila:  # quedo rechazada hace rato: se reintenta
            conn.execute(
                "UPDATE solicitudes SET estado = 'pendiente' WHERE id = ?",
                (fila["id"],),
            )
            return fila["id"]
        cursor = conn.execute(
            "INSERT INTO solicitudes (codigo, user_id, nombre) VALUES (?, ?, ?)",
            (codigo, user_id, nombre),
        )
        return cursor.lastrowid


def solicitud_por_id(solicitud_id: int) -> sqlite3.Row | None:
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            "SELECT * FROM solicitudes WHERE id = ?", (solicitud_id,)
        ).fetchone()


def decidir_solicitud(solicitud_id: int, aceptada: bool) -> None:
    with conectar() as conn:
        conn.execute(
            "UPDATE solicitudes SET estado = ? WHERE id = ?",
            ("aceptada" if aceptada else "rechazada", solicitud_id),
        )


# ----------------------- Trabajos -----------------------


def agregar_trabajo(
    placa: str,
    descripcion: str,
    precio: float,
    chat_id: int,
    taller_id: int,
    usuario_id: int | None = None,
    mecanico: str | None = None,
) -> int:
    """Guarda un trabajo firmado. Devuelve el id."""
    ahora = datetime.now().isoformat()
    with conectar() as conn:
        cursor = conn.execute(
            "INSERT INTO trabajos (fecha_hora, placa, descripcion, precio, chat_id, anulado, taller_id, usuario_id, mecanico) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (ahora, placa.strip().upper(), descripcion, precio, chat_id,
             taller_id, usuario_id, mecanico),
        )
        return cursor.lastrowid


# ------------------------- Consultas -------------------------

# TODAS llevan taller_id para el aislamiento multi-taller (S6-5).


def _trabajos_entre(
    inicio: str,
    fin: str,
    taller_id: int,
    usuario_id: int | None = None,
) -> list[sqlite3.Row]:
    """Trabajos activos del taller entre dos fechas ISO 'YYYY-MM-DD'."""
    sql = (
        "SELECT * FROM trabajos "
        "WHERE anulado = 0 AND taller_id = ? "
        "AND substr(fecha_hora, 1, 10) >= ? "
        "AND substr(fecha_hora, 1, 10) <= ?"
    )
    parametros: list = [taller_id, inicio, fin]
    if usuario_id is not None:
        sql += " AND usuario_id = ?"
        parametros.append(usuario_id)
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(sql + " ORDER BY id", parametros).fetchall()


def _resumen_entre(
    inicio: str, fin: str, taller_id: int, usuario_id: int | None = None
) -> tuple[int, float]:
    """(cantidad, suma) activo del taller entre dos fechas."""
    sql = (
        "SELECT COUNT(*) AS cantidad, IFNULL(SUM(precio), 0) AS suma "
        "FROM trabajos WHERE anulado = 0 AND taller_id = ? "
        "AND substr(fecha_hora, 1, 10) >= ? AND substr(fecha_hora, 1, 10) <= ?"
    )
    parametros: list = [taller_id, inicio, fin]
    if usuario_id is not None:
        sql += " AND usuario_id = ?"
        parametros.append(usuario_id)
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        fila = conn.execute(sql, parametros).fetchone()
        return fila["cantidad"], fila["suma"]


def rango_periodo(dias: int | None = None, mes: bool = False) -> tuple[str, str, str]:
    """(inicio, fin, etiqueta): hoy / N dias / mes en curso."""
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


def trabajos_hoy(taller_id: int, usuario_id: int | None = None) -> list[sqlite3.Row]:
    hoy = datetime.now().strftime("%Y-%m-%d")
    return _trabajos_entre(hoy, hoy, taller_id, usuario_id)


def resumen_periodo(
    taller_id: int,
    dias: int | None = None,
    mes: bool = False,
    mecanico_id: int | None = None,
) -> tuple[str, int, float]:
    """(etiqueta, cantidad, suma) del taller, opcional solo de un mecánico."""
    inicio, fin, etiqueta = rango_periodo(dias, mes)
    cantidad, suma = _resumen_entre(inicio, fin, taller_id, mecanico_id)
    return etiqueta, cantidad, suma


def desglose_mecanicos(
    taller_id: int, dias: int | None = None, mes: bool = False
) -> tuple[str, list[tuple[str, int, float]]]:
    """(etiqueta, [(mecanico, cantidad, suma), ...]) para el dueño."""
    inicio, fin, etiqueta = rango_periodo(dias, mes)
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        filas = conn.execute(
            "SELECT mecanico, COUNT(*) AS cantidad, IFNULL(SUM(precio), 0) AS suma "
            "FROM trabajos WHERE anulado = 0 AND taller_id = ? "
            "AND substr(fecha_hora, 1, 10) >= ? AND substr(fecha_hora, 1, 10) <= ? "
            "GROUP BY mecanico ORDER BY suma DESC",
            (taller_id, inicio, fin),
        ).fetchall()
    resumen = [
        (fila["mecanico"] or "sin firmar", fila["cantidad"], fila["suma"])
        for fila in filas
    ]
    return etiqueta, resumen


def historial_placa(
    placa: str, taller_id: int, usuario_id: int | None = None, limite: int = 20
) -> tuple[list[sqlite3.Row], int, float]:
    """(recientes, total_historico, suma_total) del vehículo EN ESE taller."""
    sql_base = "FROM trabajos WHERE anulado = 0 AND taller_id = ? AND placa = ?"
    parametros: list = [taller_id, placa]
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
    with conectar() as conn:
        conn.row_factory = _ROW_FACTORY
        return conn.execute(
            "SELECT * FROM trabajos WHERE id = ?", (trabajo_id,)
        ).fetchone()


def anular_trabajo(trabajo_id: int, taller_id: int) -> bool:
    """Anula solo si el trabajo pertenece al taller (borrado logico)."""
    with conectar() as conn:
        cursor = conn.execute(
            "UPDATE trabajos SET anulado = 1 "
            "WHERE id = ? AND anulado = 0 AND taller_id = ?",
            (trabajo_id, taller_id),
        )
        return cursor.rowcount == 1
