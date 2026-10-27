"""Tests de la lógica financiera, cubriendo los casos especiales del PLAN.md.

Usan SQLite en memoria para no depender de PostgreSQL.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Configuracion, CorteCaja, Movimiento, TipoMovimiento
from app.services.calculos import (
    DEFAULTS,
    corte_vigente,
    resumen_mensual,
    saldo_caja,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    for clave, valor in DEFAULTS.items():
        s.add(Configuracion(clave=clave, valor=valor))
    s.commit()
    yield s
    s.close()


def _add(db, **kwargs):
    kwargs.setdefault("fecha", date(2026, 7, 5))
    db.add(Movimiento(**kwargs))
    db.commit()


def _add_corte(db, fecha, saldo_inicial, nota=None):
    db.add(CorteCaja(fecha=fecha, saldo_inicial=Decimal(saldo_inicial), nota=nota))
    db.commit()


def test_ofrenda_recogida_entrega_10pct(db):
    _add(db, tipo=TipoMovimiento.ofrenda, monto=Decimal("1000.00"), recogido_por_tesorero=True)
    r = resumen_mensual(db, 2026, 7)
    assert r.ofrendas.entrega_organizacion == Decimal("100.00")
    assert r.entrega_total == Decimal("100.00")


def test_diezmo_recogido_entrega_13pct(db):
    _add(db, tipo=TipoMovimiento.diezmo, monto=Decimal("1000.00"), recogido_por_tesorero=True)
    r = resumen_mensual(db, 2026, 7)
    assert r.diezmos.entrega_organizacion == Decimal("130.00")


def test_no_recogido_por_tesorero_no_genera_entrega(db):
    # Se ausentó; lo recogió otra persona -> se reporta pero NO se entrega
    _add(db, tipo=TipoMovimiento.diezmo, monto=Decimal("500.00"),
         recogido_por_tesorero=False, recogido_por="Hermano Juan")
    r = resumen_mensual(db, 2026, 7)
    assert r.diezmos.total_bruto == Decimal("500.00")
    assert r.diezmos.total_no_recogido == Decimal("500.00")
    assert r.diezmos.entrega_organizacion == Decimal("0.00")
    assert r.entrega_total == Decimal("0.00")


def test_excluir_entrega_evento_especial(db):
    # Ofrenda de evento entregada a alguien especial: se cuenta pero no se entrega
    _add(db, tipo=TipoMovimiento.ofrenda, monto=Decimal("800.00"),
         recogido_por_tesorero=True, excluir_entrega=True)
    r = resumen_mensual(db, 2026, 7)
    assert r.ofrendas.total_bruto == Decimal("800.00")
    assert r.ofrendas.total_excluido == Decimal("800.00")
    assert r.ofrendas.entrega_organizacion == Decimal("0.00")


def test_donacion_entra_a_caja(db):
    _add(db, tipo=TipoMovimiento.donacion, monto=Decimal("300.00"), origen="Pastor")
    r = resumen_mensual(db, 2026, 7)
    assert r.donaciones_mes == Decimal("300.00")
    assert r.caja_saldo_acumulado == Decimal("300.00")
    assert r.entrega_total == Decimal("0.00")  # la caja no se entrega


def test_salida_reduce_caja(db):
    _add(db, tipo=TipoMovimiento.donacion, monto=Decimal("300.00"))
    _add(db, tipo=TipoMovimiento.salida_caja, monto=Decimal("120.00"), motivo="materiales")
    r = resumen_mensual(db, 2026, 7)
    assert r.salidas_mes == Decimal("120.00")
    assert r.caja_neto_mes == Decimal("180.00")
    assert r.caja_saldo_acumulado == Decimal("180.00")


def test_caja_es_reserva_permanente_acumula_entre_meses(db):
    _add(db, fecha=date(2026, 6, 10), tipo=TipoMovimiento.donacion, monto=Decimal("200.00"))
    _add(db, fecha=date(2026, 7, 10), tipo=TipoMovimiento.donacion, monto=Decimal("100.00"))
    r_jun = resumen_mensual(db, 2026, 6)
    r_jul = resumen_mensual(db, 2026, 7)
    assert r_jun.caja_saldo_acumulado == Decimal("200.00")
    # Julio acumula lo de junio + julio
    assert r_jul.caja_saldo_acumulado == Decimal("300.00")
    # Pero el neto del mes de julio es solo 100
    assert r_jul.caja_neto_mes == Decimal("100.00")


def test_escenario_mensual_completo(db):
    # Ofrenda recogida 1000 (->100), diezmo recogido 2000 (->260),
    # diezmo no recogido 500 (->0), donación pastor 600, salida 150
    _add(db, tipo=TipoMovimiento.ofrenda, monto=Decimal("1000.00"), recogido_por_tesorero=True)
    _add(db, tipo=TipoMovimiento.diezmo, monto=Decimal("2000.00"), recogido_por_tesorero=True)
    _add(db, tipo=TipoMovimiento.diezmo, monto=Decimal("500.00"), recogido_por_tesorero=False, recogido_por="X")
    _add(db, tipo=TipoMovimiento.donacion, monto=Decimal("600.00"), origen="Pastor 30%")
    _add(db, tipo=TipoMovimiento.salida_caja, monto=Decimal("150.00"), motivo="apoyo")
    r = resumen_mensual(db, 2026, 7)
    assert r.ofrendas.entrega_organizacion == Decimal("100.00")
    assert r.diezmos.entrega_organizacion == Decimal("260.00")
    assert r.entrega_total == Decimal("360.00")
    assert r.caja_saldo_acumulado == Decimal("450.00")


def test_saldo_caja_global(db):
    _add(db, fecha=date(2026, 5, 1), tipo=TipoMovimiento.donacion, monto=Decimal("1000.00"))
    _add(db, fecha=date(2026, 6, 1), tipo=TipoMovimiento.salida_caja, monto=Decimal("250.00"))
    assert saldo_caja(db) == Decimal("750.00")
    assert saldo_caja(db, hasta=date(2026, 5, 15)) == Decimal("1000.00")


def test_corte_inicializa_caja_con_saldo_base(db):
    # Se inicializa el sistema con el saldo real de caja del inicio del periodo.
    _add_corte(db, date(2026, 7, 1), "5000.00", nota="Cierre semestral ene-jun")
    _add(db, fecha=date(2026, 7, 10), tipo=TipoMovimiento.donacion, monto=Decimal("300.00"))
    _add(db, fecha=date(2026, 7, 12), tipo=TipoMovimiento.salida_caja, monto=Decimal("100.00"))
    # 5000 base + 300 - 100 = 5200
    assert saldo_caja(db) == Decimal("5200.00")


def test_corte_ignora_movimientos_anteriores_a_su_fecha(db):
    # Lo del periodo anterior ya está incluido en la base: no se vuelve a contar.
    _add(db, fecha=date(2026, 6, 20), tipo=TipoMovimiento.donacion, monto=Decimal("999.00"))
    _add_corte(db, date(2026, 7, 1), "5000.00")
    _add(db, fecha=date(2026, 7, 5), tipo=TipoMovimiento.donacion, monto=Decimal("200.00"))
    assert saldo_caja(db) == Decimal("5200.00")


def test_corte_incluye_movimientos_en_la_misma_fecha(db):
    _add_corte(db, date(2026, 7, 1), "1000.00")
    _add(db, fecha=date(2026, 7, 1), tipo=TipoMovimiento.donacion, monto=Decimal("50.00"))
    assert saldo_caja(db) == Decimal("1050.00")


def test_corte_mas_reciente_vigente_gana(db):
    _add_corte(db, date(2026, 1, 1), "1000.00")
    _add_corte(db, date(2026, 7, 1), "8000.00", nota="Nuevo semestre")
    _add(db, fecha=date(2026, 7, 3), tipo=TipoMovimiento.donacion, monto=Decimal("100.00"))
    # Vigente = corte de julio (8000) + 100
    assert saldo_caja(db) == Decimal("8100.00")
    assert corte_vigente(db).fecha == date(2026, 7, 1)
    # A mitad de junio, el corte vigente sigue siendo el de enero
    assert saldo_caja(db, hasta=date(2026, 6, 15)) == Decimal("1000.00")
    assert corte_vigente(db, hasta=date(2026, 6, 15)).fecha == date(2026, 1, 1)


def test_resumen_mensual_expone_saldo_inicial_del_periodo(db):
    _add_corte(db, date(2026, 7, 1), "5000.00")
    _add(db, fecha=date(2026, 7, 10), tipo=TipoMovimiento.donacion, monto=Decimal("300.00"))
    r = resumen_mensual(db, 2026, 7)
    assert r.caja_saldo_inicial == Decimal("5000.00")
    assert r.corte_fecha == date(2026, 7, 1)
    assert r.caja_saldo_acumulado == Decimal("5300.00")
    # El neto del mes sigue siendo solo el movimiento, sin la base
    assert r.caja_neto_mes == Decimal("300.00")


def test_sin_cortes_comportamiento_igual_que_antes(db):
    # Sin ningún corte, la caja se cuenta desde cero como siempre.
    _add(db, tipo=TipoMovimiento.donacion, monto=Decimal("300.00"))
    assert corte_vigente(db) is None
    r = resumen_mensual(db, 2026, 7)
    assert r.caja_saldo_inicial == Decimal("0.00")
    assert r.corte_fecha is None
    assert r.caja_saldo_acumulado == Decimal("300.00")
