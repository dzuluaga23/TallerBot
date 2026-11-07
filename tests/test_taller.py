"""Tests de los campos comerciales del taller y del logo (Sprint 7)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402


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
