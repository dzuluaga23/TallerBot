"""Tests de los campos comerciales del taller y del logo (Sprint 7)."""
from db import ROL_MECANICO  # noqa: E402  (sys.path ya lo pone conftest.py)


def test_guardar_datos_taller_con_whitelist(bd_temporal):
    bd = bd_temporal
    taller_id = bd.crear_taller("Taller Prueba", 1, "Duque")
    bd.guardar_datos_taller(
        taller_id,
        {"nombre": "Taller Los Pistones", "nit": "900123-4"},
    )
    fila_taller = bd.obtener_taller(taller_id)
    assert fila_taller["nombre"] == "Taller Los Pistones"
    assert fila_taller["nit"] == "900123-4"
    assert fila_taller["direccion"] is None  # los campos no pedidos quedan intactos


def test_guardar_logo(bd_temporal):
    bd = bd_temporal
    taller_id = bd.crear_taller("X", 1, "Duque")
    bd.guardar_logo(taller_id, "logos/taller_1.jpg")
    assert bd.obtener_taller(taller_id)["logo"] == "logos/taller_1.jpg"


# ── Cierre de talleres (Sprint 9) ───────────────────────────────────────


def test_cerrar_taller_bloquea_staff_y_revoca_links(bd_temporal):
    bd = bd_temporal
    taller_id = bd.crear_taller("Taller Que Cierra", 1, "Duque")
    bd.agregar_usuario(2, taller_id, "Mecanico", ROL_MECANICO)
    codigo_inv = bd.crear_invitacion(taller_id, ROL_MECANICO, 1)

    assert bd.cerrar_taller(taller_id) is True
    # cierre logico: los datos viven, pero nadie accede
    assert bd.obtener_taller(taller_id)["activo"] == 0
    assert bd.usuario_por_id(1) is None   # el dueno queda fuera
    assert bd.usuario_por_id(2) is None   # el mecanico queda fuera
    # los links dispara el cierre
    assert bd.invitacion_por_codigo(codigo_inv)["activa"] == 0
    # idempotente: cerrar dos veces no hace nada nuevo
    assert bd.cerrar_taller(taller_id) is False


def test_listar_talleres_da_estado_y_cifras(bd_temporal):
    bd = bd_temporal
    t1 = bd.crear_taller("Taller Uno", 1, "Duque")
    t2 = bd.crear_taller("Taller Dos", 2, "Otro")
    bd.agregar_usuario(3, t2, "MecanicoN", ROL_MECANICO)
    bd.agregar_trabajo("ABC123", "cambio de aceite", 45000.0, t1, 1)
    id_tr2 = bd.agregar_trabajo("XYZ789", "prueba t2", 5000.0, t2, 2)
    bd.anular_trabajo(id_tr2, t2)  # los anulados no cuentan en la cifra

    filas = {f["id"]: f for f in bd.listar_talleres()}
    assert filas[t1]["activo"] == 1
    assert filas[t1]["n_staff"] == 1
    assert filas[t1]["n_trabajos"] == 1
    assert filas[t2]["n_trabajos"] == 0  # solo trabaja vigente

    bd.cerrar_taller(t2)
    filas = {f["id"]: f for f in bd.listar_talleres()}
    assert filas[t2]["activo"] == 0
