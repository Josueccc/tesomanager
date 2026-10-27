import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import ComentarioMensual, Periodo, Usuario
from app.services.calculos import (
    corte_vigente,
    get_config_porcentajes,
    periodo_actual,
    resumen_de_periodo,
    resumen_mensual,
    resumen_periodo,
    saldo_caja,
)
from app.templating import moneda, templates

router = APIRouter()


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


def _resolver_resumen(
    db: Session,
    periodo_id: int | None,
    anio: int | None,
    mes: int | None,
    desde: date | None,
    hasta: date | None,
):
    """Elige el resumen según los parámetros, en orden de prioridad:
    periodo_id explícito → rango desde/hasta → mes calendario → periodo abierto → mes actual.
    Devuelve (resumen, periodo_o_None)."""
    if periodo_id is not None:
        periodo = db.get(Periodo, periodo_id)
        if periodo is not None:
            return resumen_de_periodo(db, periodo), periodo
    if desde is not None and hasta is not None:
        return resumen_periodo(db, desde, hasta), None
    if anio is not None and mes is not None:
        return resumen_mensual(db, anio, mes), None
    periodo = periodo_actual(db)
    if periodo is not None:
        return resumen_de_periodo(db, periodo), periodo
    hoy = date.today()
    return resumen_mensual(db, hoy.year, hoy.month), None


@router.get("/")
def dashboard(
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    hoy = date.today()
    periodo = periodo_actual(db)
    if periodo is not None:
        resumen = resumen_de_periodo(db, periodo)
    else:
        resumen = resumen_mensual(db, hoy.year, hoy.month)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "usuario": usuario,
            "resumen": resumen,
            "periodo": periodo,
            "saldo_caja_total": saldo_caja(db),
            "corte_actual": corte_vigente(db),
            "hoy": hoy,
        },
    )


@router.get("/reporte")
def reporte(
    request: Request,
    periodo_id: str | None = None,
    anio: str | None = None,
    mes: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    resumen, periodo = _resolver_resumen(
        db, _to_int(periodo_id), _to_int(anio), _to_int(mes),
        _to_date(desde), _to_date(hasta),
    )
    if periodo is not None:
        comentario_texto = periodo.comentario or ""
    else:
        comentario = db.scalar(
            select(ComentarioMensual)
            .where(
                ComentarioMensual.anio == resumen.desde.year,
                ComentarioMensual.mes == resumen.desde.month,
            )
            .order_by(ComentarioMensual.id.desc())
        )
        comentario_texto = comentario.texto if comentario else ""
    periodos = list(
        db.scalars(
            select(Periodo).order_by(Periodo.fecha_inicio.desc(), Periodo.id.desc())
        ).all()
    )
    return templates.TemplateResponse(
        "reporte.html",
        {
            "request": request,
            "usuario": usuario,
            "resumen": resumen,
            "periodo": periodo,
            "periodos": periodos,
            "pct": get_config_porcentajes(db),
            "comentario_mensual": comentario_texto,
        },
    )


@router.post("/reporte/comentario")
async def guardar_comentario(
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    texto = (form.get("texto") or "").strip()
    periodo_id = form.get("periodo_id")
    if periodo_id:
        periodo = db.get(Periodo, int(periodo_id))
        if periodo is not None:
            periodo.comentario = texto or None
            db.commit()
        return RedirectResponse(url=f"/reporte?periodo_id={periodo_id}", status_code=303)

    anio = int(form.get("anio"))
    mes = int(form.get("mes"))
    existente = db.scalar(
        select(ComentarioMensual).where(
            ComentarioMensual.anio == anio, ComentarioMensual.mes == mes
        )
    )
    if existente:
        existente.texto = texto
    elif texto:
        db.add(ComentarioMensual(anio=anio, mes=mes, texto=texto))
    db.commit()
    return RedirectResponse(url=f"/reporte?anio={anio}&mes={mes}", status_code=303)


@router.get("/reporte/csv")
def reporte_csv(
    periodo_id: str | None = None,
    anio: str | None = None,
    mes: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    r, _ = _resolver_resumen(
        db, _to_int(periodo_id), _to_int(anio), _to_int(mes),
        _to_date(desde), _to_date(hasta),
    )

    buffer = io.StringIO()
    w = csv.writer(buffer)
    w.writerow([f"Reporte {r.titulo}"])
    w.writerow([f"Periodo: {r.desde.isoformat()} a {r.hasta.isoformat()}"])
    w.writerow([])
    w.writerow(["Concepto", "Monto"])
    w.writerow(["Ofrendas (total contado)", moneda(r.ofrendas.total_bruto)])
    w.writerow(["  Recogido por el tesorero", moneda(r.ofrendas.total_recogido_tesorero)])
    w.writerow(["  Recogido por otra persona", moneda(r.ofrendas.total_no_recogido)])
    w.writerow(["  Excluido (evento/especial)", moneda(r.ofrendas.total_excluido)])
    w.writerow(["  A entregar a la organización", moneda(r.ofrendas.entrega_organizacion)])
    w.writerow(["Diezmos (total contado)", moneda(r.diezmos.total_bruto)])
    w.writerow(["  Recogido por el tesorero", moneda(r.diezmos.total_recogido_tesorero)])
    w.writerow(["  Recogido por otra persona", moneda(r.diezmos.total_no_recogido)])
    w.writerow(["  Excluido (evento/especial)", moneda(r.diezmos.total_excluido)])
    w.writerow(["  A entregar a la organización", moneda(r.diezmos.entrega_organizacion)])
    w.writerow(["TOTAL A ENTREGAR A LA ORGANIZACIÓN", moneda(r.entrega_total)])
    w.writerow([])
    if r.corte_fecha:
        w.writerow([f"Saldo inicial del periodo (corte {r.corte_fecha.isoformat()})", moneda(r.caja_saldo_inicial)])
    w.writerow(["Donaciones del periodo (a caja)", moneda(r.donaciones_mes)])
    w.writerow(["Salidas de caja del periodo", moneda(r.salidas_mes)])
    w.writerow(["Neto de caja del periodo", moneda(r.caja_neto_mes)])
    w.writerow(["SALDO DE CAJA ACUMULADO (reserva local)", moneda(r.caja_saldo_acumulado)])
    w.writerow([])
    w.writerow(["Detalle de movimientos"])
    w.writerow(["Fecha", "Tipo", "Monto", "Recogido tesorero", "Excluido", "Origen/Motivo", "Comentario"])
    for seccion in (r.ofrendas, r.diezmos):
        for m in seccion.movimientos:
            w.writerow([
                m.fecha.isoformat(), m.tipo.value, moneda(m.monto),
                "sí" if m.recogido_por_tesorero else f"no ({m.recogido_por or '-'})",
                "sí" if m.excluir_entrega else "no", "", m.comentario or "",
            ])
    for m in r.donaciones:
        w.writerow([m.fecha.isoformat(), "donacion", moneda(m.monto), "", "", m.origen or "", m.comentario or ""])
    for m in r.salidas:
        w.writerow([m.fecha.isoformat(), "salida_caja", moneda(m.monto), "", "", m.motivo or "", m.comentario or ""])

    buffer.seek(0)
    filename = f"reporte_{r.desde.isoformat()}_a_{r.hasta.isoformat()}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
