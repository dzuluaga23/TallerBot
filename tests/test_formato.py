"""Tests de los formateadores que usa el bot para las respuestas."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import formatear_dinero, formatear_fecha  # noqa: E402


def test_dinero_sencillo():
    assert formatear_dinero(45000) == "$ 45.000"


def test_dinero_grande():
    assert formatear_dinero(4500000) == "$ 4.500.000"


def test_dinero_redondea_decimales():
    assert formatear_dinero(500.0) == "$ 500"


def test_fecha_formato_compacto():
    hora = datetime(2026, 11, 6, 14, 5)
    assert formatear_fecha(hora) == "06/11/2026 02:05 pm"
