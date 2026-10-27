from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import Periodo, Usuario
from app.services.calculos import periodo_hasta
from app.templating import nombre_mes, templates

router = APIRouter(prefix="/periodos")


def _to_date(valor) -> date | None:
    try:
        return date.fromisoformat(valor)
    except (ValueError, TypeError):
        return None


def _nombre_sugerido(referencia: date) -> str:
    return f"{nombre_mes(referencia.month)} {referencia.year}"


def _inicio_sugerido(db: Session) -> date:
    """El nuevo periodo arranca el día siguiente al fin del último periodo."""
    ultimo = db.scalars(
        select(Periodo).order_by(Periodo.fecha_inicio.desc(), Periodo.id.desc())
    ).first()
    if ultimo is None:
        return date.today()
    return periodo_hasta(ultimo) + timedelta(days=1)


@router.get("")
def listar(
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    periodos = list(
        db.scalars(
            select(Periodo).order_by(Periodo.fecha_inicio.desc(), Periodo.id.desc())
        ).all()
    )
    inicio_sug = _inicio_sugerido(db)
    return templates.TemplateResponse(
        "periodos/lista.html",
        {
            "request": request,
            "usuario": usuario,
            "periodos": periodos,
            "hoy": date.today(),
            "inicio_sugerido": inicio_sug,
            "nombre_sugerido": _nombre_sugerido(inicio_sug),
        },
    )


@router.post("/nuevo")
async def crear(
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    fecha_inicio = _to_date(form.get("fecha_inicio")) or _inicio_sugerido(db)
    fecha_fin = _to_date(form.get("fecha_fin"))  # None = en curso
    nombre = (form.get("nombre") or "").strip() or _nombre_sugerido(fecha_fin or fecha_inicio)

    db.add(Periodo(nombre=nombre, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin))
    db.commit()
    return RedirectResponse(url="/periodos", status_code=303)


@router.post("/{periodo_id}/editar")
async def editar(
    periodo_id: int,
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    periodo = db.get(Periodo, periodo_id)
    if periodo is None:
        return RedirectResponse(url="/periodos", status_code=303)
    form = await request.form()
    inicio = _to_date(form.get("fecha_inicio"))
    if inicio is not None:
        periodo.fecha_inicio = inicio
    periodo.fecha_fin = _to_date(form.get("fecha_fin"))
    nombre = (form.get("nombre") or "").strip()
    if nombre:
        periodo.nombre = nombre
    db.commit()
    return RedirectResponse(url="/periodos", status_code=303)


@router.post("/{periodo_id}/cerrar")
async def cerrar(
    periodo_id: int,
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    periodo = db.get(Periodo, periodo_id)
    if periodo is not None:
        form = await request.form()
        fin = _to_date(form.get("fecha_fin")) or periodo.fecha_fin or date.today()
        periodo.fecha_fin = fin
        periodo.cerrado = True
        db.commit()
    return RedirectResponse(url="/periodos", status_code=303)


@router.post("/{periodo_id}/reabrir")
def reabrir(
    periodo_id: int,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    periodo = db.get(Periodo, periodo_id)
    if periodo is not None:
        periodo.cerrado = False
        db.commit()
    return RedirectResponse(url="/periodos", status_code=303)


@router.post("/{periodo_id}/eliminar")
def eliminar(
    periodo_id: int,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    periodo = db.get(Periodo, periodo_id)
    if periodo is not None:
        db.delete(periodo)
        db.commit()
    return RedirectResponse(url="/periodos", status_code=303)
