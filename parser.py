"""Parser del mensaje que envia el mecanico.

Formato esperado (flexible): PLACA + descripcion + precio, en ese orden
o con la placa al final. Ejemplos validos:

    ABC123 cambio de aceite 45000
    cambio de aceite y filtro ABC123 $45.000
    kgH12d cambio de tiras 38,000

Reglas:
- Placa: 3 letras + 3 numeros (carros) o 3 letras + 2 numeros + 1 letra (motos).
  No importa mayusculas/minusculas.
- Precio: ultimo numero del mensaje, con $, "." o "," de miles opcionales.
- Si falta algo se lanza ParserError con un motivo que el bot usa para
  explicar al mecanico que corregir.
"""
import re
from dataclasses import dataclass

# Carros: ABC123 | Motos: ABC12D
PLACA_RE = re.compile(r"[A-Z]{3}\d{3}|[A-Z]{3}\d{2}[A-Z]")

# Precio: $, separadores de miles opcionales, minimo 3 digitos.
# Validos: 45000, $45.000, 45,000, $4.500.000, 500
PRECIO_RE = re.compile(r"\$?(?:\d{1,3}(?:[.,]\d{3})+|\d{3,})")

# Puntuacion que se tolera pegada a la placa o al precio (ej: "ABC123," )
PUNCTUACION = ",.:;"

MOTIVO_VACIO = "vacio"
MOTIVO_PLACA = "placa"
MOTIVO_PRECIO = "precio"
MOTIVO_DESCRIPCION = "descripcion"
MOTIVO_VARIAS_PLACAS = "varias_placas"


class ParserError(Exception):
    """El mensaje no se pudo interpretar. `.motivo` explica por que."""

    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


@dataclass
class ResultadoParser:
    placa: str
    descripcion: str
    precio: float


def _normalizar(token: str) -> str:
    """Mayusculas sin puntuacion pegada, para probar si es placa o precio."""
    return token.strip(PUNCTUACION).upper()


def parse(texto: str) -> ResultadoParser:
    """
    Interpreta 'PLACA descripcion precio'.

    Lanza ParserError con motivo 'vacio', 'placa', 'precio',
    'descripcion' o 'varias_placas' cuando no puede leerse bien.
    """
    tokens = texto.strip().split()
    if not tokens:
        raise ParserError(MOTIVO_VACIO)

    normalizados = [_normalizar(t) for t in tokens]

    # --- Placa: debe haber exactamente una ---
    candidatos = [t for t in normalizados if PLACA_RE.fullmatch(t)]
    if not candidatos:
        raise ParserError(MOTIVO_PLACA)
    if len(set(candidatos)) > 1:
        raise ParserError(MOTIVO_VARIAS_PLACAS)
    placa = candidatos[0]
    idx_placa = normalizados.index(placa)

    # --- Precio: el ultimo token tipo numero (de derecha a izquierda) ---
    idx_precio = None
    for i in range(len(normalizados) - 1, -1, -1):
        if i == idx_placa:
            continue
        if PRECIO_RE.fullmatch(normalizados[i]):
            idx_precio = i
            break
    if idx_precio is None:
        raise ParserError(MOTIVO_PRECIO)

    limpio = normalizados[idx_precio].replace("$", "").replace(".", "").replace(",", "")
    precio = float(limpio)

    # --- Descripcion: el resto de las palabras, en su orden original ---
    descripcion = " ".join(
        tokens[i] for i in range(len(tokens)) if i not in (idx_placa, idx_precio)
    )
    if not descripcion:
        raise ParserError(MOTIVO_DESCRIPCION)

    return ResultadoParser(placa=placa, descripcion=descripcion, precio=precio)
