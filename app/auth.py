from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario


class NotAuthenticated(Exception):
    """Se lanza cuando no hay sesión válida; el handler redirige a /login."""


def current_user(request: Request, db: Session = Depends(get_db)) -> Usuario:
    user_id = request.session.get("user_id")
    if not user_id:
        raise NotAuthenticated()
    usuario = db.get(Usuario, user_id)
    if usuario is None:
        request.session.clear()
        raise NotAuthenticated()
    return usuario


def redirect_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)
