"""Normalización y parseo de montos ingresados por el usuario.

Los formularios usan `type="text"` con `inputmode="decimal"` para que el punto
decimal se acepte sin depender del locale del navegador. Aquí interpretamos
tanto el punto como la coma como posibles separadores decimales o de miles.
"""

from decimal import Decimal, InvalidOperation

CENTAVOS = Decimal("0.01")


def normalizar_separadores(valor: str) -> str:
    """Convierte una entrada humana a una cadena con punto decimal.

    Casos soportados:
    - "1234.50"      -> "1234.50"
    - "1234,50"      -> "1234.50"  (coma como separador decimal)
    - "1,234.50"     -> "1234.50"  (coma de miles, punto decimal)
    - "1.234,50"     -> "1234.50"  (punto de miles, coma decimal)
    """
    s = str(valor).strip()
    tiene_coma = "," in s
    tiene_punto = "." in s
    if tiene_coma and tiene_punto:
        # El separador que aparece más a la derecha es el decimal.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif tiene_coma:
        s = s.replace(",", ".")
    return s


def parse_monto(valor: str) -> Decimal | None:
    """Devuelve un Decimal >= 0 con 2 decimales, o None si es inválido."""
    try:
        d = Decimal(normalizar_separadores(valor))
    except (InvalidOperation, ValueError):
        return None
    if d < 0:
        return None
    return d.quantize(CENTAVOS)
