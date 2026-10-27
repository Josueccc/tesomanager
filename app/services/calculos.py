"""Lógica financiera de TesoManager.

Reglas (ver PLAN.md, sección "Modelo financiero"):

- Ofrenda recogida por el tesorero y no excluida  -> entrega = monto * %ofrenda.
- Diezmo recogido por el tesorero y no excluido    -> entrega = monto * %diezmo.
- Si NO fue recogido por el tesorero, o está marcado como excluido de entrega,
  el movimiento SÍ se reporta pero NO genera obligación de entrega.
- Donación directa -> entra a la CAJA (reserva local permanente).
- Salida de caja   -> reduce la CAJA.
- La CAJA nunca se entrega a la organización.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Configuracion, CorteCaja, Movimiento, Periodo, TipoMovimiento

CENTAVO = Decimal("0.01")

DEFAULTS = {
    "pct_entrega_ofrenda": "10",
    "pct_entrega_diezmo": "13",
    "pct_donacion_pastor": "30",
}


def _q(valor: Decimal) -> Decimal:
    """Redondea a 2 decimales."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def get_config(db: Session) -> dict[str, Decimal]:
    """Devuelve los porcentajes como fracciones decimales (10 -> 0.10)."""
    filas = {c.clave: c.valor for c in db.scalars(select(Configuracion)).all()}
    resultado = {}
    for clave, por_defecto in DEFAULTS.items():
        pct = Decimal(filas.get(clave, por_defecto))
        resultado[clave] = pct / Decimal(100)
    return resultado


def get_config_porcentajes(db: Session) -> dict[str, Decimal]:
    """Devuelve los porcentajes tal cual (para mostrar en la UI: 10, 13, 30)."""
    filas = {c.clave: c.valor for c in db.scalars(select(Configuracion)).all()}
    return {
        clave: Decimal(filas.get(clave, por_defecto))
        for clave, por_defecto in DEFAULTS.items()
    }


def entrega_de_movimiento(mov: Movimiento, cfg: dict[str, Decimal]) -> Decimal:
    """Monto que se debe entregar a la organización por un movimiento.

    Solo ofrendas y diezmos recogidos por el tesorero y no excluidos generan entrega.
    """
    if mov.recogido_por_tesorero is False or mov.excluir_entrega:
        return Decimal("0.00")
    if mov.tipo == TipoMovimiento.ofrenda:
        return _q(mov.monto * cfg["pct_entrega_ofrenda"])
    if mov.tipo == TipoMovimiento.diezmo:
        return _q(mov.monto * cfg["pct_entrega_diezmo"])
    return Decimal("0.00")


def corte_vigente(db: Session, hasta: date | None = None) -> CorteCaja | None:
    """Corte de caja vigente para una fecha: el más reciente con `fecha <= hasta`.

    El corte marca el inicio de un periodo contable nuevo: su `saldo_inicial` es el
    balance de cierre del periodo anterior y sirve de base. Si `hasta` es None, se
    toma el corte más reciente que exista.
    """
    stmt = select(CorteCaja).order_by(CorteCaja.fecha.desc(), CorteCaja.id.desc())
    if hasta is not None:
        stmt = stmt.where(CorteCaja.fecha <= hasta)
    return db.scalars(stmt).first()


def saldo_caja(db: Session, hasta: date | None = None) -> Decimal:
    """Saldo de la caja (reserva local) hasta la fecha dada.

    Parte del `saldo_inicial` del corte vigente y le suma donaciones y resta salidas
    ocurridas desde la fecha de ese corte. Los movimientos anteriores al corte
    pertenecen a un periodo ya cerrado y no se cuentan (su efecto ya está incluido en
    la base). Si no hay ningún corte, se cuenta todo desde el inicio con base cero.
    `hasta` es inclusivo; si es None, considera todos los movimientos.
    """
    corte = corte_vigente(db, hasta)
    total = Decimal(corte.saldo_inicial) if corte else Decimal("0.00")
    desde = corte.fecha if corte else None

    stmt = select(Movimiento).where(
        Movimiento.tipo.in_([TipoMovimiento.donacion, TipoMovimiento.salida_caja])
    )
    if desde is not None:
        stmt = stmt.where(Movimiento.fecha >= desde)
    if hasta is not None:
        stmt = stmt.where(Movimiento.fecha <= hasta)
    for mov in db.scalars(stmt).all():
        if mov.tipo == TipoMovimiento.donacion:
            total += mov.monto
        else:  # salida_caja
            total -= mov.monto
    return _q(total)


def periodo_actual(db: Session) -> Periodo | None:
    """Periodo "en curso": el abierto más reciente; si no hay ninguno abierto, el
    más reciente que exista. None si todavía no se ha creado ningún periodo."""
    abierto = db.scalars(
        select(Periodo)
        .where(Periodo.cerrado.is_(False))
        .order_by(Periodo.fecha_inicio.desc(), Periodo.id.desc())
    ).first()
    if abierto is not None:
        return abierto
    return db.scalars(
        select(Periodo).order_by(Periodo.fecha_inicio.desc(), Periodo.id.desc())
    ).first()


def periodo_para_fecha(db: Session, fecha: date) -> Periodo | None:
    """Periodo cuyo rango contiene la fecha dada (fin abierto = hasta hoy)."""
    candidatos = db.scalars(
        select(Periodo)
        .where(Periodo.fecha_inicio <= fecha)
        .order_by(Periodo.fecha_inicio.desc(), Periodo.id.desc())
    ).all()
    for p in candidatos:
        fin = p.fecha_fin or date.today()
        if fecha <= fin:
            return p
    return None


def periodo_hasta(periodo: Periodo) -> date:
    """Fecha final efectiva de un periodo (hoy si está abierto)."""
    return periodo.fecha_fin or date.today()


@dataclass
class SeccionTotales:
    """Totales de un tipo (ofrenda o diezmo) dentro de un mes."""

    total_bruto: Decimal = Decimal("0.00")           # todo lo contado
    total_recogido_tesorero: Decimal = Decimal("0.00")
    total_no_recogido: Decimal = Decimal("0.00")     # lo recogió otra persona
    total_excluido: Decimal = Decimal("0.00")        # eventos / entregado a alguien
    entrega_organizacion: Decimal = Decimal("0.00")  # % a entregar
    movimientos: list = field(default_factory=list)


@dataclass
class ResumenPeriodo:
    desde: date
    hasta: date
    titulo: str
    ofrendas: SeccionTotales
    diezmos: SeccionTotales
    donaciones_mes: Decimal         # donaciones del periodo (a caja)
    salidas_mes: Decimal            # salidas del periodo
    entrega_total: Decimal          # ofrendas + diezmos a entregar a la organización
    caja_neto_mes: Decimal          # donaciones - salidas del periodo
    caja_saldo_acumulado: Decimal   # reserva total hasta el fin del periodo
    caja_saldo_inicial: Decimal     # base del corte vigente al fin del periodo (0 si no hay)
    corte_fecha: date | None = None  # fecha del corte vigente al fin del periodo
    periodo_id: int | None = None    # Periodo del que sale este resumen (None = rango suelto)
    donaciones: list = field(default_factory=list)
    salidas: list = field(default_factory=list)


def resumen_periodo(
    db: Session,
    desde: date,
    hasta: date,
    *,
    titulo: str | None = None,
    periodo_id: int | None = None,
) -> ResumenPeriodo:
    """Resumen financiero de los movimientos con fecha en `[desde, hasta]` (inclusivo).

    El acumulado de caja se calcula hasta `hasta`; el neto de caja solo cuenta las
    donaciones y salidas dentro del rango.
    """
    cfg = get_config(db)

    stmt = (
        select(Movimiento)
        .where(Movimiento.fecha >= desde)
        .where(Movimiento.fecha <= hasta)
        .order_by(Movimiento.fecha, Movimiento.id)
    )
    movimientos = list(db.scalars(stmt).all())

    ofrendas = SeccionTotales()
    diezmos = SeccionTotales()
    donaciones: list[Movimiento] = []
    salidas: list[Movimiento] = []

    for mov in movimientos:
        if mov.tipo in (TipoMovimiento.ofrenda, TipoMovimiento.diezmo):
            seccion = ofrendas if mov.tipo == TipoMovimiento.ofrenda else diezmos
            seccion.movimientos.append(mov)
            seccion.total_bruto += mov.monto
            if mov.excluir_entrega:
                seccion.total_excluido += mov.monto
            elif mov.recogido_por_tesorero:
                seccion.total_recogido_tesorero += mov.monto
            else:
                seccion.total_no_recogido += mov.monto
            seccion.entrega_organizacion += entrega_de_movimiento(mov, cfg)
        elif mov.tipo == TipoMovimiento.donacion:
            donaciones.append(mov)
        else:
            salidas.append(mov)

    for s in (ofrendas, diezmos):
        s.total_bruto = _q(s.total_bruto)
        s.total_recogido_tesorero = _q(s.total_recogido_tesorero)
        s.total_no_recogido = _q(s.total_no_recogido)
        s.total_excluido = _q(s.total_excluido)
        s.entrega_organizacion = _q(s.entrega_organizacion)

    donaciones_mes = _q(sum((m.monto for m in donaciones), Decimal("0.00")))
    salidas_mes = _q(sum((m.monto for m in salidas), Decimal("0.00")))
    entrega_total = _q(ofrendas.entrega_organizacion + diezmos.entrega_organizacion)

    corte = corte_vigente(db, hasta=hasta)

    return ResumenPeriodo(
        desde=desde,
        hasta=hasta,
        titulo=titulo or f"{desde.strftime('%d/%m/%Y')} – {hasta.strftime('%d/%m/%Y')}",
        ofrendas=ofrendas,
        diezmos=diezmos,
        donaciones_mes=donaciones_mes,
        salidas_mes=salidas_mes,
        entrega_total=entrega_total,
        caja_neto_mes=_q(donaciones_mes - salidas_mes),
        caja_saldo_acumulado=saldo_caja(db, hasta=hasta),
        caja_saldo_inicial=_q(Decimal(corte.saldo_inicial)) if corte else Decimal("0.00"),
        corte_fecha=corte.fecha if corte else None,
        periodo_id=periodo_id,
        donaciones=donaciones,
        salidas=salidas,
    )


def _fin_de_mes(anio: int, mes: int) -> date:
    if mes == 12:
        primero_siguiente = date(anio + 1, 1, 1)
    else:
        primero_siguiente = date(anio, mes + 1, 1)
    return primero_siguiente - timedelta(days=1)


def resumen_mensual(db: Session, anio: int, mes: int) -> ResumenPeriodo:
    """Resumen de un mes calendario. Modo de consulta rápido; internamente usa
    `resumen_periodo` con el rango [día 1, último día del mes]."""
    from app.templating import nombre_mes

    desde = date(anio, mes, 1)
    hasta = _fin_de_mes(anio, mes)
    return resumen_periodo(db, desde, hasta, titulo=f"{nombre_mes(mes)} {anio}")


def resumen_de_periodo(db: Session, periodo: Periodo) -> ResumenPeriodo:
    """Resumen de un `Periodo` guardado (fin abierto = hasta hoy)."""
    return resumen_periodo(
        db,
        periodo.fecha_inicio,
        periodo_hasta(periodo),
        titulo=periodo.nombre,
        periodo_id=periodo.id,
    )
