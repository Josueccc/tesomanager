"""Crea las tablas y siembra datos iniciales de forma idempotente."""

from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Configuracion, Usuario
from app.security import hash_password
from app.services.calculos import DEFAULTS


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Configuración por defecto (porcentajes)
        for clave, valor in DEFAULTS.items():
            existe = db.get(Configuracion, clave)
            if existe is None:
                db.add(Configuracion(clave=clave, valor=valor))

        # Usuario tesorero inicial
        admin_email = settings.admin_email.strip().lower()
        existe_admin = db.scalar(select(Usuario).where(Usuario.email == admin_email))
        if existe_admin is None:
            db.add(
                Usuario(
                    email=admin_email,
                    nombre=settings.admin_nombre,
                    hash_password=hash_password(settings.admin_password),
                )
            )
        db.commit()
    finally:
        db.close()
