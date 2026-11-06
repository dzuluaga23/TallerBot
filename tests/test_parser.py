"""Tests del parser (ticket S1-5). Ejecutar con:

    venv\\Scripts\\python -m pytest tests -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import parser as registro_parser  # noqa: E402
from parser import ParserError, parse  # noqa: E402


def test_mensaje_basico():
    r = parse("ABC123 cambio de aceite 45000")
    assert r.placa == "ABC123"
    assert r.descripcion == "cambio de aceite"
    assert r.precio == 45000.0


def test_placa_al_final():
    r = parse("cambio de aceite y filtros ABC123 45000")
    assert r.placa == "ABC123"
    assert r.descripcion == "cambio de aceite y filtros"
    assert r.precio == 45000.0


def test_precio_con_dolar_y_puntos():
    r = parse("ABC123 cambio de aceite $45.000")
    assert r.precio == 45000.0


def test_precio_con_comas():
    r = parse("ABC123 cambio de aceite 45,000")
    assert r.precio == 45000.0


def test_precio_grande():
    r = parse("ABC123 circuito completo de frenos $4.500.000")
    assert r.descripcion == "circuito completo de frenos"
    assert r.precio == 4500000.0


def test_placa_minusculas():
    r = parse("abC123 lavada de motor 21000")
    assert r.placa == "ABC123"


def test_placa_moto_formato_dos_numeros_una_letra():
    r = parse("KGH12D cambio de tiras 38000")
    assert r.placa == "KGH12D"


def test_precio_tres_digitos():
    r = parse("ABC123 engrase 500")
    assert r.precio == 500.0
    assert r.descripcion == "engrase"


def test_precio_con_puntuacion_pegada():
    r = parse("ABC123 lavada, 45000;")
    assert r.placa == "ABC123"
    assert r.descripcion == "lavada,"
    assert r.precio == 45000.0


def test_falta_placa():
    with pytest.raises(ParserError) as e:
        parse("52000 cambio de aceite")
    assert e.value.motivo == registro_parser.MOTIVO_PLACA


def test_falta_precio():
    with pytest.raises(ParserError) as e:
        parse("ABC123 cambio de aceite")
    assert e.value.motivo == registro_parser.MOTIVO_PRECIO


def test_falta_descripcion():
    with pytest.raises(ParserError) as e:
        parse("ABC123 45000")
    assert e.value.motivo == registro_parser.MOTIVO_DESCRIPCION


def test_texto_vacio():
    with pytest.raises(ParserError) as e:
        parse("   ")
    assert e.value.motivo == registro_parser.MOTIVO_VACIO


def test_varias_placas():
    with pytest.raises(ParserError) as e:
        parse("ABC123 XJZ789 pinta general 50000")
    assert e.value.motivo == registro_parser.MOTIVO_VARIAS_PLACAS
