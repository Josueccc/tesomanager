from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import Configuracion, CorteCaja, Usuario
from app.security import hash_password, verify_password
from app.services.calculos import DEFAULTS, corte_vigente, get_config_porcentajes
from app.services.montos import parse_monto
from app.templating import templates

router = APIRouter(prefix="/configuracion")


def _parse_pct(valor: str) -> str | None:
    try:
        d = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        return None
    if d < 0 or d > 100:
        return None
    return str(d)


def _parse_saldo(valor: str) -> Decimal | None:
    return parse_monto(valor)


def _parse_fecha(valor: str) -> date | None:
    try:
        return date.fromisoformat(str(valor))
    except (ValueError, TypeError):
        return None


@router.get("")
def configuracion_form(
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
    ok: str | None = None,
    error: str | None = None,
):
    cortes = list(
        db.scalars(
            select(CorteCaja).order_by(CorteCaja.fecha.desc(), CorteCaja.id.desc())
        ).all()
    )
    return templates.TemplateResponse(
        "configuracion.html",
        {
            "request": request,
            "usuario": usuario,
            "pct": get_config_porcentajes(db),
            "cortes": cortes,
            "corte_actual": corte_vigente(db),
            "ok": ok,
            "error": error,
        },
    )


@router.post("/porcentajes")
async def guardar_porcentajes(
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    for clave in DEFAULTS:
        nuevo = _parse_pct(form.get(clave, ""))
        if nuevo is None:
            return RedirectResponse(
                url="/configuracion?error=Porcentaje inválido (usa un número entre 0 y 100).",
                status_code=303,
            )
        fila = db.get(Configuracion, clave)
        if fila is None:
            db.add(Configuracion(clave=clave, valor=nuevo))
        else:
            fila.valor = nuevo
    db.commit()
    return RedirectResponse(url="/configuracion?ok=Porcentajes actualizados.", status_code=303)


@router.post("/password")
async def cambiar_password(
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    actual = form.get("actual", "")
    nueva = form.get("nueva", "")
    if not verify_password(actual, usuario.hash_password):
        return RedirectResponse(url="/configuracion?error=La contraseña actual no es correcta.", status_code=303)
    if len(nueva) < 6:
        return RedirectResponse(url="/configuracion?error=La nueva contraseña debe tener al menos 6 caracteres.", status_code=303)
    usuario.hash_password = hash_password(nueva)
    db.commit()
    return RedirectResponse(url="/configuracion?ok=Contraseña actualizada.", status_code=303)


@router.post("/cortes")
async def crear_corte(
    request: Request,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    fecha = _parse_fecha(form.get("fecha"))
    saldo = _parse_saldo(form.get("saldo_inicial", ""))
    nota = (form.get("nota") or "").strip() or None
    if fecha is None or saldo is None:
        return RedirectResponse(
            url="/configuracion?error=Revisa la fecha y el saldo inicial (número positivo).",
            status_code=303,
        )
    db.add(CorteCaja(fecha=fecha, saldo_inicial=saldo, nota=nota))
    db.commit()
    return RedirectResponse(
        url="/configuracion?ok=Corte de caja registrado. El saldo se cuenta desde esa fecha.",
        status_code=303,
    )


@router.post("/cortes/{corte_id}/eliminar")
def eliminar_corte(
    corte_id: int,
    usuario: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    corte = db.get(CorteCaja, corte_id)
    if corte is not None:
        db.delete(corte)
        db.commit()
    return RedirectResponse(url="/configuracion?ok=Corte eliminado.", status_code=303)
