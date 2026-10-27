from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import NotAuthenticated
from app.config import settings
from app.routers import auth as auth_router
from app.routers import configuracion as config_router
from app.routers import movimientos as movimientos_router
from app.routers import periodos as periodos_router
from app.routers import reportes as reportes_router
from app.seed import init_db

app = FastAPI(title="TesoManager")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=60 * 60 * 24 * 14)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/login", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth_router.router)
app.include_router(movimientos_router.router)
app.include_router(periodos_router.router)
app.include_router(reportes_router.router)
app.include_router(config_router.router)
