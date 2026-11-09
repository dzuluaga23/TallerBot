"""Tests de la capa de datos, usando una BD temporal por test."""
import sqlite3

import db  # noqa: E402  (sys.path ya lo pone conftest.py)
from db import ROL_DUENO, ROL_MECANICO  # noqa: E402


def test_init_db_repara_esquema_incompleto(bd_temporal, tmp_path, monkeypatch):
    """BD de otra era (sin codigos_usados) queda sana tras init_db (Sprint 4e).

    El respaldo de la nube puede traer una BD de una version vieja; el arranque
    restaura primero y init_db() despues DEBE completar el esquema sin pisar
    los datos existentes.
    """
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE talleres (id INTEGER PRIMARY KEY, nombre TEXT)")
    con.execute("INSERT INTO talleres (id, nombre) VALUES (1, 'Taller Viejo')")
    con.commit()
    con.close()

    monkeypatch.setattr(db, "DB_PATH", ruta)
    db.init_db()

    assert db.codigo_ya_redimido("CUALQUIER-CODIGO") is False  # tabla existe y anda
    con = sqlite3.connect(ruta)
    assert con.execute(
        "SELECT id, nombre FROM talleres"
    ).fetchall() == [(1, "Taller Viejo")]  # datos intactos
    con.close()


def test_resumen_hoy_con_trabajos(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "cambio de aceite", 45000.0, 1, 1)
    bd.agregar_trabajo("KGH12D", "cambio de tiras", 38000.0, 1, 1)
    etiqueta, cantidad, suma = bd.resumen_periodo(1)
    assert etiqueta == "hoy"
    assert cantidad == 2
    assert suma == 83000.0


def test_resumen_sin_trabajos(bd_temporal):
    etiqueta, cantidad, suma = bd_temporal.resumen_periodo(1)
    assert cantidad == 0
    assert suma == 0.0


def test_resumen_7_dias_incluye_hoy(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "lavada", 20000.0, 1, 1)
    etiqueta, cantidad, suma = bd.resumen_periodo(1, dias=7)
    assert etiqueta == "los últimos 7 días"
    assert cantidad == 1


def test_historial_placa_y_total(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "cambio de aceite", 45000.0, 1, 1)
    bd.agregar_trabajo("ABC123", "pastillas", 120000.0, 1, 1)
    bd.agregar_trabajo("KGH12D", "tiras", 38000.0, 1, 1)
    filas, cantidad, suma = bd.historial_placa("ABC123", 1)
    assert cantidad == 2
    assert suma == 165000.0
    assert filas[0]["descripcion"] == "pastillas"


def test_placa_se_guarda_en_mayusculas(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("abc123", "lavada", 20000.0, 1, 1)
    filas, cantidad, suma = bd.historial_placa("ABC123", 1)
    assert cantidad == 1


def test_anular_y_trabajo_por_id(bd_temporal):
    bd = bd_temporal
    trabajo_id = bd.agregar_trabajo("ABC123", "frenos", 100000.0, 1, 1)

    fila = bd.trabajo_por_id(trabajo_id)
    assert fila["anulado"] == 0

    assert bd.anular_trabajo(trabajo_id, 1) is True
    assert bd.anular_trabajo(trabajo_id, 1) is False
    _, cantidad, suma = bd.resumen_periodo(1)
    assert cantidad == 0
    assert suma == 0.0


def test_anular_trabajo_inexistente(bd_temporal):
    assert bd_temporal.anular_trabajo(999, 1) is False


# ---------------- Sprint 5: firma y filtros por mecánico ----------------


def test_filtro_por_mecanico_en_resumen(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "a", 100.0, 1, 1, usuario_id=111, mecanico="Pedro")
    bd.agregar_trabajo("XYZ789", "b", 200.0, 2, 1, usuario_id=222, mecanico="Juan")
    etiqueta, cantidad, suma = bd.resumen_periodo(1, mecanico_id=111)
    assert (cantidad, suma) == (1, 100.0)
    _, cantidad, suma = bd.resumen_periodo(1, mecanico_id=222)
    assert (cantidad, suma) == (1, 200.0)


def test_desglose_mecanicos(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "a", 100.0, 1, 1, usuario_id=111, mecanico="Pedro")
    bd.agregar_trabajo("XYZ789", "b", 200.0, 2, 1, usuario_id=222, mecanico="Juan")
    bd.agregar_trabajo("ABB126", "c", 50.0, 2, 1, usuario_id=222, mecanico="Juan")
    etiqueta, desglose = bd.desglose_mecanicos(1)
    assert etiqueta == "hoy"
    assert desglose == [("Juan", 2, 250.0), ("Pedro", 1, 100.0)]


def test_placa_historial_filtrado_por_mecanico(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "de Pedro", 100.0, 1, 1, usuario_id=111, mecanico="Pedro")
    bd.agregar_trabajo("ABC123", "de Juan", 200.0, 2, 1, usuario_id=222, mecanico="Juan")
    filas, cantidad, suma = bd.historial_placa("ABC123", 1, usuario_id=111)
    assert cantidad == 1
    assert suma == 100.0
    assert filas[0]["descripcion"] == "de Pedro"


def test_trabajo_viejo_sin_firma_no_se_mezcla_con_mecanico(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "sin firma", 100.0, 1, 1)
    _, cantidad, _ = bd.resumen_periodo(1, mecanico_id=111)
    assert cantidad == 0
    _, cantidad, _ = bd.resumen_periodo(1)
    assert cantidad == 1


# ---------------- Sprint 6: multi-taller (aislamiento) ----------------


def test_crear_taller_y_dueno(bd_temporal):
    bd = bd_temporal
    taller_id = bd.crear_taller("Taller Este", 100, "Duque")
    perfil = bd.usuario_por_id(100)
    assert perfil["taller_id"] == taller_id
    assert perfil["rol"] == ROL_DUENO
    assert bd.obtener_taller(taller_id)["nombre"] == "Taller Este"


def test_aislamiento_entre_talleres(bd_temporal):
    """La prueba clave del S6-7: cada taller solo ve lo suyo."""
    bd = bd_temporal
    taller_a = bd.crear_taller("Taller A", 111, "Ana")
    taller_b = bd.crear_taller("Taller B", 222, "Boris")
    bd.agregar_trabajo("ABC123", "de A", 100.0, 1, taller_a, usuario_id=111, mecanico="Ana")
    bd.agregar_trabajo("XYZ789", "de B", 200.0, 2, taller_b, usuario_id=222, mecanico="Boris")

    # El taller A NO ve los datos de B
    _, cantidad_a, suma_a = bd.resumen_periodo(taller_a)
    assert (cantidad_a, suma_a) == (1, 100.0)
    _, cantidad_b, suma_b = bd.resumen_periodo(taller_b)
    assert (cantidad_b, suma_b) == (1, 200.0)
    # /buscar desde A no trae la placa de B
    _, cantidad, _ = bd.historial_placa("XYZ789", taller_a)
    assert cantidad == 0
    # El desglose de A solo muestra a gente de A
    _, desglose = bd.desglose_mecanicos(taller_a)
    assert [nombre for nombre, _, _ in desglose] == ["Ana"]


def test_anulacion_respetando_taller(bd_temporal):
    bd = bd_temporal
    taller_a = bd.crear_taller("A", 111, "Ana")
    taller_b = bd.crear_taller("B", 222, "Boris")
    trabajo_id = bd.agregar_trabajo("ABC123", "job A", 100.0, 1, taller_a)
    # Anular desde el taller B NO debe tocar el trabajo de A
    assert bd.anular_trabajo(trabajo_id, taller_b) is False
    assert bd.anular_trabajo(trabajo_id, taller_a) is True


def test_invitaciones_y_solicitudes(bd_temporal):
    bd = bd_temporal
    taller_id = bd.crear_taller("Mi Taller", 1, "Duque")
    codigo = bd.crear_invitacion(taller_id, ROL_MECANICO, 1)
    invita = bd.invitacion_por_codigo(codigo)
    assert invita["activa"] == 1
    assert invita["rol"] == ROL_MECANICO

    solicitud_id = bd.crear_solicitud(codigo, 500, "Mengaña")
    assert bd.crear_solicitud(codigo, 500, "Mengaña") is None  # ya hay pendiente
    db.decidir_solicitud(solicitud_id, True)
    bd.agregar_usuario(500, taller_id, "Mengaña", ROL_MECANICO)
    perfil_500 = bd.usuario_por_id(500)
    assert perfil_500["rol"] == ROL_MECANICO
    assert perfil_500["nombre"] == "Mengaña"


def test_revocar_invitacion(bd_temporal):
    bd = bd_temporal
    taller_id = bd.crear_taller("X", 1, "Duque")
    codigo = bd.crear_invitacion(taller_id, ROL_MECANICO, 1)
    assert bd.revocar_invitacion(codigo, 999) is False  # otro taller no puede
    assert bd.revocar_invitacion(codigo, taller_id) is True
    assert bd.invitacion_por_codigo(codigo)["activa"] == 0


def test_migracion_de_instalacion_antigua(bd_temporal, tmp_path, monkeypatch):
    """Trabajos de la era pre-Sprint-6 terminan en 'Taller Prueba'."""
    bd = bd_temporal
    # Simular una fila de la era vieja: sin taller_id ni firma
    with bd.conectar() as conn:
        conn.execute(
            "INSERT INTO trabajos (fecha_hora, placa, descripcion, precio, chat_id) "
            "VALUES ('2026-11-01T10:00:00', 'ABC123', 'era vieja', 100.0, 9)"
        )
    monkeypatch.setenv("ADMIN_IDS", "9136002456")
    # Re-llamar init_db con duenos del .env dispara la migracion
    db.init_db(duenos_antiguos={9136002456: "Dueño"})

    with bd.conectar() as conn:
        talleres = conn.execute("SELECT id FROM talleres").fetchall()
        assert len(talleres) == 1
        taller_id = talleres[0][0]
        assert conn.execute(
            "SELECT nombre FROM talleres WHERE id = ?", (taller_id,)
        ).fetchone()[0] == "Taller Prueba"
        # El trabajo viejo ahora siempre pertenece a ese taller
        trabajo = conn.execute("SELECT taller_id FROM trabajos").fetchone()
        assert trabajo[0] == taller_id
    # Y el dueño del .env quedó activo como tal
    dueno = bd.usuario_por_id(9136002456)
    assert dueno["rol"] == ROL_DUENO
    assert dueno["taller_id"] == taller_id


def test_cambiar_rol_y_expulsar(bd_temporal):
    bd = bd_temporal
    taller_id = bd.crear_taller("X", 1, "Duque")
    bd.agregar_usuario(50, taller_id, "Pedro", ROL_MECANICO)
    assert bd.cambiar_rol(50, ROL_DUENO, taller_id) is True
    assert bd.usuario_por_id(50)["rol"] == ROL_DUENO
    assert bd.expulsar_usuario(50, taller_id) is True
    assert bd.usuario_por_id(50) is None  # inactivo = invisble para roles
