# TesoManager 💰

> 🇬🇧 **English summary**.
>
> TesoManager is a self-hosted web app I use as a church treasurer to track
> offerings, tithes, donations and cash withdrawals. It applies the organization's
> remittance rules automatically (a configurable % of each offering/tithe is set
> aside for the parent organization, with exceptions for money the treasurer didn't
> collect or that was earmarked for events), keeps a running balance of the local
> cash reserve with periodic closing cut-offs, and produces a printable monthly
> report with CSV export.
>
> - **Stack:** Python · FastAPI · SQLAlchemy · Jinja2 + Tailwind · PostgreSQL · Docker Compose · pytest
> - **Design:** all financial rules live in a single service module
>   ([`app/services/calculos.py`](app/services/calculos.py)) covered by unit tests;
>   routers and templates only read from it.
> - **Run it:** `cp .env.example .env && docker compose up --build`, then open
>   <http://localhost:8000> and log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`.
> - **Scope:** a single-user tool meant to run locally or on a private network.
>   It is not hardened for exposure to the public internet.

App web para el tesorero de una iglesia: registra **ofrendas**, **diezmos**,
**donaciones** y **salidas de caja**, calcula automáticamente lo que se debe
**entregar a la organización** y lleva el **saldo de la caja** (reserva local),
con **reporte mensual** imprimible y exportable a CSV.

- **Stack:** Python · FastAPI · Jinja2 + Tailwind · PostgreSQL · Docker Compose
- **Moneda:** MXN

## Arranque rápido

Requisitos: Docker y Docker Compose.

```bash
cp .env.example .env      # 1) ajusta credenciales (¡cambia SECRET_KEY y ADMIN_PASSWORD!)
docker compose up --build # 2) levanta la base de datos y la app
```

Abre <http://localhost:8000> e ingresa con el correo/contraseña que pusiste en `.env`
(`ADMIN_EMAIL` / `ADMIN_PASSWORD`). El usuario tesorero se crea solo en el primer arranque.

> Si el puerto 8000 está ocupado, cambia `APP_PORT` en `.env` (p. ej. `APP_PORT=8099`).

### Alcance y seguridad

Es una herramienta de **un solo usuario** (el tesorero) pensada para correr en tu
computadora o en una red privada; **no está preparada para exponerse a internet**.
PostgreSQL solo se publica en `127.0.0.1` (puerto `DB_PORT`). Si algún día la despliegas,
usa contraseñas fuertes, un `SECRET_KEY` aleatorio y HTTPS.

## Cómo se maneja el dinero (reglas)

| Movimiento | Qué hace |
|---|---|
| **Ofrenda** | Si la recoges tú, se aparta el **10%** para entregar a la organización. |
| **Diezmo** | Si lo recoges tú, se aparta el **13%** para entregar a la organización. |
| **Donación a caja** | Entra a la **caja** (reserva local permanente de la iglesia). Ej.: el pastor dona el 30% del diezmo. |
| **Salida de caja** | Egreso con motivo; reduce el saldo de la caja. |

Casos especiales que soporta:

- **No lo recogiste tú** (te ausentaste): se registra y aparece en el reporte, pero **no genera entrega** (no tienes ese dinero). Se guarda quién lo recogió.
- **Evento / entregado a alguien especial**: se cuenta y reporta, pero se marca **excluido de entrega**.
- **Donación del pastor**: al registrar un diezmo puedes generar la donación (30% sugerido, editable) que queda vinculada a ese diezmo.
- **Comentarios** por movimiento y por mes.

La **caja nunca se entrega** a la organización: es una reserva local que acumula mes a mes.

### Saldo inicial / corte de periodo

Para arrancar el sistema con el dinero real que ya tienes en caja (o el balance con que
quedó el último **corte semestral**), ve a **Configuración → Saldo inicial / Corte de
periodo** y registra la **fecha de inicio** y el **saldo base**. Desde esa fecha la caja
se cuenta sobre ese saldo; los movimientos anteriores quedan en el periodo ya cerrado y
no se vuelven a sumar. Cada nuevo periodo registras un corte con el balance de cierre
anterior como base.

Los porcentajes (10% / 13% / 30%) se editan en **Configuración**.

## Reporte mensual

En **Reporte mensual** eliges mes/año y ves: ofrendas y diezmos (recogidos vs. no
recogidos vs. excluidos), total a entregar, movimientos y saldo de caja, y comentarios
del mes. Botones para **Imprimir/PDF** (impresión del navegador) y **descargar CSV**.

## Desarrollo y pruebas

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest                     # tests de la lógica financiera (usan SQLite en memoria)
```

Para correr la app fuera de Docker apunta `DATABASE_URL` a tu PostgreSQL (ver `.env.example`).

## Respaldo de la base de datos

```bash
# Respaldo
docker compose exec db pg_dump -U teso tesomanager > respaldo.sql
# Restaurar
cat respaldo.sql | docker compose exec -T db psql -U teso tesomanager
```

## Estructura

```
app/
  main.py            # arranque FastAPI, sesiones, rutas
  models.py          # tablas (usuarios, configuracion, movimientos, cortes_caja, comentarios)
  services/calculos.py  # TODA la lógica financiera (fuente de la verdad)
  routers/           # auth, movimientos, reportes, configuracion
  templates/         # vistas (Jinja2 + Tailwind)
tests/               # tests de la lógica financiera
PLAN.md              # plan de desarrollo con fases y checks
```

El detalle completo de reglas y avance está en [`PLAN.md`](PLAN.md).

## Licencia

[MIT](LICENSE)
