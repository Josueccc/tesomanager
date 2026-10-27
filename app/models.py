import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TipoMovimiento(str, enum.Enum):
    ofrenda = "ofrenda"
    diezmo = "diezmo"
    donacion = "donacion"
    salida_caja = "salida_caja"


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(255))
    hash_password: Mapped[str] = mapped_column(String(255))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Configuracion(Base):
    __tablename__ = "configuracion"

    clave: Mapped[str] = mapped_column(String(64), primary_key=True)
    valor: Mapped[str] = mapped_column(String(255))
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Movimiento(Base):
    __tablename__ = "movimientos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    tipo: Mapped[TipoMovimiento] = mapped_column(Enum(TipoMovimiento), index=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    # Aplica a ofrenda / diezmo:
    recogido_por_tesorero: Mapped[bool] = mapped_column(Boolean, default=True)
    recogido_por: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Caso "evento entregado a alguien especial": se reporta pero no genera entrega
    excluir_entrega: Mapped[bool] = mapped_column(Boolean, default=False)

    # Donaciones: de dónde viene (ej. "pastor 30% diezmo", "donante X")
    origen: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Salidas de caja: motivo
    motivo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Vincula la donación del pastor con el diezmo que la originó
    movimiento_padre_id: Mapped[int | None] = mapped_column(
        ForeignKey("movimientos.id", ondelete="SET NULL"), nullable=True
    )
    movimiento_padre: Mapped["Movimiento | None"] = relationship(
        "Movimiento", remote_side=[id], backref="donaciones_hijas"
    )

    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CorteCaja(Base):
    """Corte / apertura de un periodo contable de la caja.

    Cada seis meses (o cuando se hace el reporte general) el conteo de la caja se
    reinicia usando el balance de cierre como base. Este registro guarda ese
    `saldo_inicial` con la `fecha` a partir de la cual entra en vigor: los movimientos
    anteriores a esa fecha pertenecen a un periodo ya cerrado y no se vuelven a contar.
    """

    __tablename__ = "cortes_caja"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    saldo_inicial: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Periodo(Base):
    """Periodo de reporte flexible (no atado al mes calendario).

    Los reportes de la iglesia normalmente no coinciden con el mes calendario: se
    toman las últimas semanas del mes anterior y cierran antes de que termine el mes
    (ej. el reporte de "julio" va del 28 de junio al 19 de julio). Un `Periodo` guarda
    ese rango con identidad propia: los movimientos se agrupan por su `fecha` dentro de
    `[fecha_inicio, fecha_fin]`. Puede haber huecos entre periodos; solo la caja se
    mantiene continua (acumula por fecha, ver `saldo_caja`).

    `fecha_fin` en None significa "en curso" (el periodo abierto). Para los cálculos, un
    periodo abierto se considera hasta hoy.
    """

    __tablename__ = "periodos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    fecha_inicio: Mapped[date] = mapped_column(Date, index=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    cerrado: Mapped[bool] = mapped_column(Boolean, default=False)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ComentarioMensual(Base):
    __tablename__ = "comentarios_mensuales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[int] = mapped_column(Integer, index=True)
    texto: Mapped[str] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
