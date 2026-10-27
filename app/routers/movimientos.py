from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import Movimiento, Periodo, TipoMovimiento, Usuario
from app.services.calculos import (
    get_config_porcentajes,
    periodo_actual,
    periodo_hasta,
    periodo_para_fecha,
)
from app.services.montos import parse_monto
from app.templating import templates

router = APIRouter(prefix="/movimientos")

TIPOS_VALIDOS = {t.value for t in TipoMovimiento}
TIPO_LABEL = {
    "ofrenda": "Ofrenda",
    "diezmo": "Diezmo",
    "donacion": "Donación a caja",
    "salida_caja": "Salida de caja",
}


def _to_decimal(valor: str) -> Decimal | None:
    return parse_monto(valor)


def _to_date(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(valor)
    except (ValueError, TypeError):
        return None


def _to_int(valor: str | None) -> int | None:
    try:
        return int(valor)
    except (ValueError, TypeError):
        return None


@router.get("")
def listar(
    request: Request,
    periodo_id: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    tipo: str | None = None,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    periodos = list(
        db.scalars(
            select(Periodo).order_by(Periodo.fecha_inicio.desc(), Periodo.id.desc())
        ).all()
    )

    pid = _to_int(periodo_id)
    desde = _to_date(desde)
    hasta = _to_date(hasta)

    # Determinar el rango: periodo_id → rango desde/hasta → periodo abierto → todo.
    periodo = None
    if pid is not None:
        periodo = db.get(Periodo, pid)
    elif desde is None and hasta is None:
        periodo = periodo_actual(db)

    if periodo is not None:
        desde = periodo.fecha_inicio
        hasta = periodo_hasta(periodo)

    stmt = select(Movimiento)
    if desde is not None:
        stmt = stmt.where(Movimiento.fecha >= desde)
    if hasta is not None:
        stmt = stmt.where(Movimiento.fecha <= hasta)
    if tipo in TIPOS_VALIDOS:
        stmt = stmt.where(Movimiento.tipo == TipoMovimiento(tipo))
    stmt = stmt.order_by(Movimiento.fecha.desc(), Movimiento.id.desc())
    movimientos = list(db.scalars(stmt).all())

    return templates.TemplateResponse(
        "movimientos/lista.html",
        {
            "request": request,
            "usuario": usuario,
            "movimientos": movimientos,
            "periodos": periodos,
            "periodo": periodo,
            "desde": desde,
            "hasta": hasta,
            "tipo": tipo or "",
            "tipo_label": TIPO_LABEL,
        },
    )


def _redirect_a_periodo_de(db: Session, fecha: date) -> str:
    """URL del listado apuntando al periodo que contiene la fecha (o al rango del día)."""
    periodo = periodo_para_fecha(db, fecha)
    if periodo is not None:
        return f"/movimientos?periodo_id={periodo.id}"
    return f"/movimientos?desde={fecha.isoformat()}&hasta={fecha.isoformat()}"


@router.get("/nuevo")
def nuevo_form(
    request: Request,
    tipo: str = "ofrenda",
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    if tipo not in TIPOS_VALIDOS:
        tipo = "ofrenda"
    pct = get_config_porcentajes(db)
    return templates.TemplateResponse(
        "movimientos/form.html",
        {
            "request": request,
            "usuario": usuario,
            "mov": None,
            "tipo": tipo,
            "tipo_label": TIPO_LABEL,
            "pct_donacion_pastor": pct["pct_donacion_pastor"],
            "error": None,
        },
    )


def _leer_form(form) -> dict:
    return {
        "fecha": _to_date(form.get("fecha")),
        "monto": _to_decimal(form.get("monto")),
        "recogido_por_tesorero": form.get("recogido_por_tesorero") == "on",
        "recogido_por": (form.get("recogido_por") or "").strip() or None,
        "excluir_entrega": form.get("excluir_entrega") == "on",
        "origen": (form.get("origen") or "").strip() or None,
        "motivo": (form.get("motivo") or "").strip() or None,
        "comentario": (form.get("comentario") or "").strip() or None,
    }


@router.post("/nuevo")
async def crear(
    request: Request,
    tipo: str = Form(...),
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    datos = _leer_form(form)
    pct = get_config_porcentajes(db)

    if tipo not in TIPOS_VALIDOS or datos["fecha"] is None or datos["monto"] is None:
        return templates.TemplateResponse(
            "movimientos/form.html",
            {
                "request": request, "usuario": usuario, "mov": None, "tipo": tipo,
                "tipo_label": TIPO_LABEL, "pct_donacion_pastor": pct["pct_donacion_pastor"],
                "error": "Revisa la fecha y el monto (debe ser un número positivo).",
            },
            status_code=400,
        )

    tipo_enum = TipoMovimiento(tipo)
    mov = Movimiento(
        fecha=datos["fecha"],
        tipo=tipo_enum,
        monto=datos["monto"],
        comentario=datos["comentario"],
    )
    if tipo_enum in (TipoMovimiento.ofrenda, TipoMovimiento.diezmo):
        mov.recogido_por_tesorero = datos["recogido_por_tesorero"]
        mov.recogido_por = None if datos["recogido_por_tesorero"] else datos["recogido_por"]
        mov.excluir_entrega = datos["excluir_entrega"]
    elif tipo_enum == TipoMovimiento.donacion:
        mov.origen = datos["origen"]
    elif tipo_enum == TipoMovimiento.salida_caja:
        mov.motivo = datos["motivo"]

    db.add(mov)
    db.flush()  # obtener mov.id

    # Donación del pastor a partir del diezmo (opcional)
    if tipo_enum == TipoMovimiento.diezmo and form.get("generar_donacion_pastor") == "on":
        monto_don = _to_decimal(form.get("monto_donacion_pastor"))
        if monto_don and monto_don > 0:
            db.add(
                Movimiento(
                    fecha=datos["fecha"],
                    tipo=TipoMovimiento.donacion,
                    monto=monto_don,
                    origen="Pastor (donación del diezmo)",
                    movimiento_padre_id=mov.id,
                    comentario="Generada automáticamente desde el diezmo.",
                )
            )

    db.commit()
    return RedirectResponse(url=_redirect_a_periodo_de(db, datos["fecha"]), status_code=303)


@router.get("/{mov_id}/editar")
def editar_form(
    mov_id: int,
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    mov = db.get(Movimiento, mov_id)
    if mov is None:
        return RedirectResponse(url="/movimientos", status_code=303)
    pct = get_config_porcentajes(db)
    return templates.TemplateResponse(
        "movimientos/form.html",
        {
            "request": request, "usuario": usuario, "mov": mov, "tipo": mov.tipo.value,
            "tipo_label": TIPO_LABEL, "pct_donacion_pastor": pct["pct_donacion_pastor"],
            "error": None,
        },
    )


@router.post("/{mov_id}/editar")
async def actualizar(
    mov_id: int,
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    mov = db.get(Movimiento, mov_id)
    if mov is None:
        return RedirectResponse(url="/movimientos", status_code=303)
    form = await request.form()
    datos = _leer_form(form)
    pct = get_config_porcentajes(db)

    if datos["fecha"] is None or datos["monto"] is None:
        return templates.TemplateResponse(
            "movimientos/form.html",
            {
                "request": request, "usuario": usuario, "mov": mov, "tipo": mov.tipo.value,
                "tipo_label": TIPO_LABEL, "pct_donacion_pastor": pct["pct_donacion_pastor"],
                "error": "Revisa la fecha y el monto (debe ser un número positivo).",
            },
            status_code=400,
        )

    mov.fecha = datos["fecha"]
    mov.monto = datos["monto"]
    mov.comentario = datos["comentario"]
    if mov.tipo in (TipoMovimiento.ofrenda, TipoMovimiento.diezmo):
        mov.recogido_por_tesorero = datos["recogido_por_tesorero"]
        mov.recogido_por = None if datos["recogido_por_tesorero"] else datos["recogido_por"]
        mov.excluir_entrega = datos["excluir_entrega"]
    elif mov.tipo == TipoMovimiento.donacion:
        mov.origen = datos["origen"]
    elif mov.tipo == TipoMovimiento.salida_caja:
        mov.motivo = datos["motivo"]

    db.commit()
    return RedirectResponse(url=_redirect_a_periodo_de(db, datos["fecha"]), status_code=303)


@router.post("/{mov_id}/eliminar")
def eliminar(
    mov_id: int,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    mov = db.get(Movimiento, mov_id)
    fecha = mov.fecha if mov else date.today()
    if mov is not None:
        db.delete(mov)
        db.commit()
    return RedirectResponse(url=_redirect_a_periodo_de(db, fecha), status_code=303)
