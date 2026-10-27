from datetime import date
from decimal import Decimal

from fastapi.templating import Jinja2Templates

MESES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def moneda(valor) -> str:
    if valor is None:
        valor = 0
    d = Decimal(str(valor)).quantize(Decimal("0.01"))
    entero, _, dec = f"{abs(d):.2f}".partition(".")
    entero = f"{int(entero):,}"
    signo = "-" if d < 0 else ""
    return f"{signo}${entero}.{dec}"


def nombre_mes(mes: int) -> str:
    try:
        return MESES[int(mes)]
    except (IndexError, ValueError, TypeError):
        return str(mes)


templates = Jinja2Templates(directory="app/templates")
templates.env.filters["moneda"] = moneda
templates.env.filters["nombre_mes"] = nombre_mes
templates.env.globals["MESES"] = MESES
templates.env.globals["hoy"] = date.today
