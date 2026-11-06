"""Tests de la capa de datos (Sprint 2), usando una BD temporal por test."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402


@pytest.fixture()
def bd_temporal(tmp_path, monkeypatch):
    """Cada test mira una taller.db limpia y propia."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def test_resumen_hoy_con_trabajos(bd_temporal):
    bd = bd_temporal
    # La fecha la pone agregar_trabajo con datetime.now(), igual que resumen_periodo
    bd.agregar_trabajo("ABC123", "cambio de aceite", 45000.0, 1)
    bd.agregar_trabajo("KGH12D", "cambio de tiras", 38000.0, 1)
    etiqueta, cantidad, suma = bd.resumen_periodo()
    assert etiqueta == "hoy"
    assert cantidad == 2
    assert suma == 83000.0


def test_resumen_sin_trabajos(bd_temporal):
    etiqueta, cantidad, suma = bd_temporal.resumen_periodo()
    assert cantidad == 0
    assert suma == 0.0
    assert etiqueta == "hoy"


def test_resumen_7_dias_incluye_hoy(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "lavada", 20000.0, 1)
    etiqueta, cantidad, suma = bd.resumen_periodo(dias=7)
    assert etiqueta == "los últimos 7 días"
    assert cantidad == 1


def test_historial_placa_y_total(bd_temporal):
    bd = bd_temporal
    bd.agregar_trabajo("ABC123", "cambio de aceite", 45000.0, 1)
    bd.agregar_trabajo("ABC123", "pastillas", 120000.0, 1)
    bd.agregar_trabajo("KGH12D", "tiras", 38000.0, 1)
    filas, cantidad, suma = bd.historial_placa("ABC123")
    assert cantidad == 2
    assert suma == 165000.0
    # Traen los dos trabajos, el mas reciente primero
    assert filas[0]["descripcion"] == "pastillas"


def test_placa_distinta_mayusculas_igual(bd_temporal):
    "Las placas se guardan SIEMPRE en mayúsculas al agregar."
    bd = bd_temporal
    bd.agregar_trabajo("abc123", "lavada", 20000.0, 1)
    filas, cantidad, suma = bd.historial_placa("ABC123")
    assert cantidad == 1


def test_anular_y_trabajo_por_id(bd_temporal):
    bd = bd_temporal
    trabajo_id = bd.agregar_trabajo("ABC123", "frenos", 100000.0, 1)

    fila = bd.trabajo_por_id(trabajo_id)
    assert fila["anulado"] == 0

    assert bd.anular_trabajo(trabajo_id) is True
    # Ya no se puede anular dos veces ni aparece en el resumen del día
    assert bd.anular_trabajo(trabajo_id) is False
    _, cantidad, suma = bd.resumen_periodo()
    assert cantidad == 0
    assert suma == 0.0

    fila = bd.trabajo_por_id(trabajo_id)
    assert fila["anulado"] == 1


def test_anular_trabajo_inexistente(bd_temporal):
    assert bd_temporal.anular_trabajo(999) is False
