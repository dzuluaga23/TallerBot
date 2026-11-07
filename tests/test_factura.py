"""Tests de la generación de facturas PDF (Sprint 7)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import factura  # noqa: E402
from bot import _parsear_pares  # noqa: E402

ITEMS = [
    {"fecha_hora": "2026-11-07T09:15:00", "descripcion": "cambio de aceite",
     "precio": 45000.0, "mecanico": "Pedro"},
    {"fecha_hora": "2026-11-07T11:44:00", "descripcion": "pastillas de freno",
     "precio": 120000.0, "mecanico": "Pedro"},
]


def test_pdf_basico_valido():
    datos = factura.generar_pdf(
        "Taller Los Pistones", "900123-4", "3001112233", "Calle 45 #12-30",
        None, "ABC123", ITEMS,
    )
    assert datos.startswith(b"%PDF")
    assert b"%%EOF" in datos
    assert len(datos) > 500  # un PDF con contenido no cabe en 500 bytes


def test_pdf_sin_datos_de_contacto():
    """NIT/teléfono/dirección vacios: la factura se genera igual."""
    datos = factura.generar_pdf("Taller X", None, None, None, None, "KGH12D", ITEMS[:1])
    assert datos.startswith(b"%PDF")


def test_pdf_colado_emojis_en_descripcion():
    """Los emojis no tumban la generación: se filtran."""
    items_emojis = [
        {"fecha_hora": "2026-11-07T09:15:00", "descripcion": "lavada 🧼 con cera ✨",
         "precio": 30000.0, "mecanico": "Ana 👩‍🔧"},
    ]
    datos = factura.generar_pdf("Taller", None, None, None, None, "ABC123", items_emojis)
    assert datos.startswith(b"%PDF")


def test_pdf_con_30_items_multipagina():
    muchos = [
        {"fecha_hora": f"2026-11-07T0{h % 9}:{m:02d}:00", "descripcion": f"trabajo {i}",
         "precio": 10000.0 + i, "mecanico": "Pedro"}
        for i, (h, m) in enumerate([(h, m) for h in range(1, 9) for m in (5, 25, 45)])
    ]
    datos = factura.generar_pdf("Taller", None, None, None, None, "ABC123", muchos)
    assert datos.startswith(b"%PDF") and b"%%EOF" in datos


def test_latin1_reemplaza_emojis():
    assert "🧼" not in factura._latin1("lavada 🧼")
    assert "lavada" in factura._latin1("lavada 🧼")


def test_parsear_pares_con_valores_de_programas():
    pares = _parsear_pares(
        ["nit=900123-4", "dir=Calle", "45", "#12-30", "nombre=Taller", "Los", "Pistones"]
    )
    assert pares == {
        "nit": "900123-4",
        "dir": "Calle 45 #12-30",
        "nombre": "Taller Los Pistones",
    }


def test_parsear_pares_vacos():
    assert _parsear_pares(["?", "sin igual"]) == {}
