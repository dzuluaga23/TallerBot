"""Generador de facturas PDF (Sprint 7).

Módulo independiente del bot a propósito: se puede probar sin Telegram.
Es una FACTURA SIMPLE (no fiscal): sirve como comprobante brillante
para el cliente, no es una factura electrónica ante la DIAN.
"""
import os
from datetime import datetime

from fpdf import FPDF

MARGEN = 10
ANCHO_USABLE = 190
COL_HORA = 24
COL_PRECIO = 46
COL_TRABAJO = ANCHO_USABLE - COL_HORA - COL_PRECIO  # = 120


def _latin1(texto: str) -> str:
    """Los emojis no caben en el PDF: se dejan fuera sin romper la generación."""
    return (texto or "").encode("latin-1", "replace").decode("latin-1")


def _fmt_precio(valor: float) -> str:
    return f"$ {valor:,.0f}".replace(",", ".")


def _nueva_linea(pdf: FPDF) -> None:
    pdf.cell(0, 0, "", new_x="LMARGIN", new_y="NEXT")


def _contacto(nit: str | None, telefono: str | None, direccion: str | None) -> str:
    partes = []
    if nit:
        partes.append(f"NIT: {nit}")
    if telefono:
        partes.append(f"Tel: {telefono}")
    if direccion:
        partes.append(direccion)
    return "  ·  ".join(partes)


def generar_pdf(
    nombre_taller: str,
    nit: str | None,
    telefono: str | None,
    direccion: str | None,
    logo: str | None,
    placa: str,
    items: list,
) -> bytes:
    """
    Arma el PDF de la factura.

    items: lista de filas de la BD (o dicts) con fecha_hora, descripcion y precio
    del MISMO DÍA y la MISMA placa.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Encabezado: logo + datos del taller ──
    x_nombre = MARGEN
    if logo and os.path.exists(logo):
        try:
            pdf.image(logo, x=MARGEN, y=MARGEN, w=26)
            x_nombre = 42
        except Exception:
            pass  # imagen corrupta: la factura sale sin logo, no tumba nada
    pdf.set_xy(x_nombre, 12)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, _latin1(nombre_taller), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(x_nombre)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _latin1(_contacto(nit, telefono, direccion)), new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(max(pdf.get_y(), 38))  # el logo no empuja el resto si es alto
    pdf.set_draw_color(120)
    pdf.line(MARGEN, pdf.get_y(), MARGEN + ANCHO_USABLE, pdf.get_y())
    pdf.ln(5)

    # ── Título ──
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, "FACTURA SIMPLE (NO FISCAL)", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    fecha = datetime.now().strftime("%d/%m/%Y")
    pdf.cell(95, 6, f"Comprobante de pago: {fecha}")
    pdf.cell(0, 6, f"Placa: {placa}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ──Tabla de items ──
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(215, 215, 215)
    pdf.cell(COL_HORA, 8, "Hora", fill=True)
    pdf.cell(COL_TRABAJO, 8, "Trabajo", fill=True)
    pdf.cell(COL_PRECIO, 8, "Valor", fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for item in items:
        hora = datetime.fromisoformat(item["fecha_hora"]).strftime("%I:%M %p").lower()
        alto = 7
        pdf.cell(COL_HORA, alto, _latin1(hora))
        pdf.cell(COL_TRABAJO, alto, _latin1(item["descripcion"]))
        pdf.cell(COL_PRECIO, alto, _fmt_precio(float(item["precio"])), align="R",
                 new_x="LMARGIN", new_y="NEXT")

    # ── Total ──
    total = sum(float(item["precio"]) for item in items)
    pdf.set_draw_color(120)
    pdf.ln(2)
    pdf.line(MARGEN, pdf.get_y(), MARGEN + ANCHO_USABLE, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(COL_HORA + COL_TRABAJO, 9, "TOTAL")
    pdf.cell(COL_PRECIO, 9, _fmt_precio(total), align="R", new_x="LMARGIN", new_y="NEXT")

    # ── Quien atendió ──
    firmas = []
    for item in items:
        if "mecanico" in item.keys() and item["mecanico"]:
            firmas.append(item["mecanico"])
    atendido = sorted(set(firmas))
    if atendido:
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _latin1(f"Cobrado y atendido por: {', '.join(atendido)}"),
                 new_x="LMARGIN", new_y="NEXT")

    # ── Pie ──
    pdf.set_y(-25)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110)
    pdf.cell(0, 4, "Documento no fiscal generado por TallerBot.",
             align="C", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
