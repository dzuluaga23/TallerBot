"""Tests de los builders y el teclado del menú con botones (Sprint 10)."""
import db  # noqa: E402  (conftest.py ya arregla el sys.path)
import bot  # noqa: E402


def test_texto_historial_hoy_vacio(bd_temporal):
    texto = bot._texto_historial_hoy(1, 111, es_dueno=True)
    assert "Sin trabajos" in texto


def test_texto_historial_hoy_dueno_vs_mecanico(bd_temporal):
    bd = bd_temporal
    taller = bd.crear_taller("Taller Menu", 111, "Duque")
    bd.agregar_trabajo("ABC123", "cambio de aceite", 45000.0, 111, taller)

    texto_dueno = bot._texto_historial_hoy(taller, 111, es_dueno=True)
    assert "Trabajos de hoy" in texto_dueno
    assert "Total del día" in texto_dueno
    assert "$ 45.000" in texto_dueno

    # el mecánico solo ve lo suyo, sin 'del día' y sin otros registros
    bd.agregar_trabajo("XYZ789", "lavada", 20000.0, 222, taller, usuario_id=222)
    texto_mec = bot._texto_historial_hoy(taller, 222, es_dueno=False)
    assert "Tus trabajos de hoy" in texto_mec
    assert "lavada" in texto_mec
    assert "cambio de aceite" not in texto_mec
    assert "Total: $ 20.000" in texto_mec


def test_texto_ganancias_dias_y_mes(bd_temporal):
    bd = bd_temporal
    taller = bd.crear_taller("Taller Menu", 111, "Duque")
    bd.agregar_trabajo("ABC123", "frenos", 100000.0, 111, taller)

    texto_7 = bot._texto_ganancias(taller, 111, 7, False, ver_todos=True)
    assert "$ 100.000" in texto_7
    assert "Por mecánico" in texto_7

    texto_mes = bot._texto_ganancias(taller, 111, None, True, ver_todos=True)
    assert "$ 100.000" in texto_mes

    # mecánico sin trabajos en el periodo: texto amable, no error
    texto_vacio = bot._texto_ganancias(taller, 999, 7, False, ver_todos=False)
    assert "Sin trabajos tuyos" in texto_vacio


def test_texto_personal_solo_activos(bd_temporal):
    bd = bd_temporal
    taller = bd.crear_taller("Taller Menu", 111, "Duque")
    bd.agregar_usuario(222, taller, "Pedro", db.ROL_MECANICO)
    bd.agregar_usuario(333, taller, "Maria", db.ROL_MECANICO)
    bd.expulsar_usuario(333, taller)

    texto = bot._texto_personal(taller)
    assert "Pedro" in texto
    assert "Maria" not in texto
    assert "/expulsar ID" in texto


def test_texto_datos_taller_campos_y_faltantes(bd_temporal):
    bd = bd_temporal
    taller = bd.crear_taller("Taller Datos", 111, "Duque")
    texto_vacio = bot._texto_datos_taller(taller)
    assert "Taller Datos" in texto_vacio
    assert "Faltan" in texto_vacio  # nit/dirección/teléfono aún sin llenar

    bd.guardar_datos_taller(
        taller, {"nit": "900123-4", "direccion": "Calle 1", "telefono": "300"}
    )
    texto_lleno = bot._texto_datos_taller(taller)
    assert "900123-4" in texto_lleno
    assert "Calle 1" in texto_lleno
    assert "Faltan" not in texto_lleno


def test_teclado_menu_por_rol(bd_temporal):
    teclado_dueno = bot._teclado_menu(es_dueno=True)
    textos_dueno = [btn.text for fila in teclado_dueno.inline_keyboard for btn in fila]
    teclado_mec = bot._teclado_menu(es_dueno=False)
    textos_mec = [btn.text for fila in teclado_mec.inline_keyboard for btn in fila]

    # comunes: hoy + ganancias
    for texto in ("🌅 Hoy", "🙋 Mis ganancias", "💼 7 días", "💼 Mes"):
        assert texto in textos_mec
    # exclusivos del dueño
    assert "👥 Personal" in textos_dueno
    assert "🏢 Datos taller" in textos_dueno
    assert "👥 Personal" not in textos_mec
    assert "🏢 Datos taller" not in textos_mec
    # solo callbacks del namespace del menu
    for fila in teclado_dueno.inline_keyboard:
        for btn in fila:
            assert btn.callback_data.startswith("mnu:")
