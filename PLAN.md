# TesoManager — Plan de desarrollo

App web para que el tesorero de una iglesia registre ofrendas, diezmos, donaciones
y salidas de caja, haga los cálculos automáticos y genere el reporte mensual para
entregar a la organización.

- **Stack:** Python + FastAPI + Jinja2 + HTMX + Tailwind (CDN) · PostgreSQL · Docker Compose
- **Usuarios:** un solo usuario (el tesorero) con login simple
- **Idioma de la interfaz:** español
- **Moneda:** MXN (pesos mexicanos)

---

## 1. Modelo financiero (reglas de negocio)

Esta es la "fuente de la verdad". Todo cálculo del código debe respetar esto.

### Conceptos

| Concepto | Descripción |
|---|---|
| **Ofrenda** | Colecta semanal. Normalmente NO va a caja: se usa para otros fines o uso del pastor. El tesorero solo retiene un **% para entregar a la organización** (por defecto **10%**). |
| **Diezmo** | Colecta semanal. El tesorero retiene un **% para entregar a la organización** (por defecto **13%**). El resto se usa para otros fines / uso del pastor. |
| **Donación directa** | Entrada que SÍ queda en caja. Ej.: el pastor dona el **30%** del diezmo a caja, u otros donativos. |
| **Salida de caja** | Egreso de la caja por diferentes motivos. Reduce el saldo de caja. |
| **Caja** | **Reserva permanente local** para apoyo de la propia iglesia. Sube con donaciones directas, baja con salidas. **NUNCA se entrega a la organización.** Acumula mes a mes. |

### Casos especiales que la app debe soportar

1. **Recogido por el tesorero** → se retiene el % correspondiente para entregar a la organización.
2. **NO recogido por el tesorero** (te ausentaste, lo recogió otra persona) → **se registra y aparece en el reporte mensual, pero NO genera obligación de entrega** (no tienes ese dinero). Se guarda quién lo recogió.
3. **Donación del pastor desde el diezmo** → entrada a caja, típicamente 30% del diezmo (monto sugerido pero editable). Puede quedar vinculada al diezmo que la originó.
4. **Ofrenda de evento entregada a alguien especial** → se **cuenta y reporta**, pero se marca como *excluida de entrega* (no genera % a entregar y no se retiene).
5. **Salidas de caja** → egresos con motivo.
6. **Comentarios** → notas libres, por movimiento y/o por mes.

### Fórmulas

- `entrega_ofrenda = monto × %ofrenda` **solo si** (recogido_por_tesorero = sí) y (excluir_entrega = no)
- `entrega_diezmo  = monto × %diezmo`  **solo si** (recogido_por_tesorero = sí) y (excluir_entrega = no)
- `entrega_total_mes = Σ entrega_ofrenda + Σ entrega_diezmo`  *(la caja nunca entra aquí)*
- `saldo_caja = saldo_inicial_del_corte_vigente + Σ donaciones − Σ salidas`
  *(reserva local, no se entrega; solo se cuentan los movimientos con fecha ≥ la del corte vigente)*
- **Corte de periodo:** cada seis meses (o al hacer el reporte general) se registra un
  **corte de caja** con el balance de cierre como `saldo_inicial` y su fecha de inicio.
  A partir de esa fecha el conteo se reinicia sobre esa base; los movimientos anteriores
  pertenecen a un periodo ya cerrado y no se vuelven a contar. Sin ningún corte, la caja
  se cuenta desde cero (base 0).
- La **donación del 30% del pastor** es sobre *cada diezmo individual*: monto sugerido y editable
  al registrar el diezmo; a veces se genera, a veces no. Nunca es un descuento mensual.

### Parámetros configurables (tabla `configuracion`)

| Parámetro | Valor por defecto |
|---|---|
| `pct_entrega_ofrenda` | 10% |
| `pct_entrega_diezmo` | 13% |
| `pct_donacion_pastor` | 30% |

---

## 2. Modelo de datos

**`usuarios`** — id, email, nombre, hash_password, creado_en

**`configuracion`** — clave (PK), valor, actualizado_en

**`movimientos`**
- id, fecha, tipo (`ofrenda` \| `diezmo` \| `donacion` \| `salida_caja`)
- monto (numeric 12,2)
- recogido_por_tesorero (bool, aplica a ofrenda/diezmo)
- recogido_por (texto, nullable — quién recogió si no fue el tesorero)
- excluir_entrega (bool — caso evento/entregado a alguien especial)
- origen (texto, nullable — para donaciones: "pastor 30% diezmo", "donante X")
- motivo (texto, nullable — para salidas)
- movimiento_padre_id (FK nullable — vincula donación del pastor a su diezmo)
- comentario (texto, nullable)
- creado_en, actualizado_en

**`cortes_caja`** — id, fecha, saldo_inicial (numeric 12,2), nota (texto, nullable), creado_en
- Marca el inicio de un periodo contable: `saldo_inicial` es la base de la caja desde `fecha`.
- El corte vigente para cualquier fecha es el más reciente con `fecha ≤` esa fecha.

**`periodos`** — id, nombre, fecha_inicio, fecha_fin (nullable = en curso), cerrado (bool), comentario (texto, nullable), nota (texto, nullable), creado_en
- **Periodo de reporte flexible**, NO atado al mes calendario. Los reportes reales
  toman las últimas semanas del mes anterior y cierran antes de fin de mes
  (ej. "Julio 2026" va del 28/jun al 19/jul). El reporte agrupa los movimientos por su
  `fecha` dentro de `[fecha_inicio, fecha_fin]`; puede haber huecos entre periodos.
- `fecha_fin` en None = periodo abierto (para cálculos se considera hasta hoy).
- Dashboard, listado de movimientos y reporte usan por defecto el **periodo abierto**;
  si no hay ninguno, caen al mes calendario en curso. El reporte también admite un
  **rango libre** `desde`/`hasta` sin necesidad de guardar un periodo.
- La **caja** sigue siendo continua e independiente de los periodos: acumula por fecha
  desde el corte vigente (ver `cortes_caja`); los periodos solo agrupan el reporte.

**`comentarios_mensuales`** (opcional) — id, anio, mes, texto, creado_en

Índices por `fecha` y `tipo` para los reportes.

---

## 3. Fases, pasos y checks

> Marca cada `[ ]` como `[x]` conforme se complete. Cada fase tiene un **Check**
> (criterio de aceptación) verificable.

### Fase 0 — Andamiaje del proyecto
- [x] Estructura de carpetas (`app/`, `app/templates/`, `app/static/`, `app/routers/`, `migrations/`)
- [x] `requirements.txt` (fastapi, uvicorn, sqlalchemy, alembic, psycopg2-binary, jinja2, python-jose/passlib, python-multipart, pydantic-settings)
- [x] `Dockerfile` de la app
- [x] `docker-compose.yml` (servicios `db` postgres + `app`, volumen de datos, variables de entorno, healthcheck)
- [x] `.env.example` y `.gitignore`
- [x] `README.md` con instrucciones de arranque
- **Check:** `docker compose up` levanta app y db; `GET /health` responde `200 OK`.

### Fase 1 — Base de datos
- [x] Configuración de conexión (SQLAlchemy + settings desde entorno)
- [x] Modelos ORM (usuarios, configuracion, movimientos, comentarios_mensuales)
- [x] Creación de tablas al iniciar (`create_all`) + seed idempotente. *(Alembic queda como mejora futura en Fase 7.)*
- [x] Seed inicial: configuración por defecto (10/13/30) y usuario tesorero
- **Check:** al levantar, las tablas existen y la fila de configuración por defecto está presente.

### Fase 2 — Autenticación
- [x] Registro/creación del usuario tesorero (o seed) + hash de contraseña
- [x] Login con sesión por cookie (JWT o sesión servidor)
- [x] Middleware/dependencia que protege todas las rutas de la app
- [x] Logout
- **Check:** rutas protegidas redirigen a login sin sesión; login válido da acceso; logout cierra sesión.

### Fase 3 — Registro de movimientos (CRUD)
- [x] Formulario/endpoint **Ofrenda** (fecha, monto, recogido_por_tesorero, recogido_por, excluir_entrega, comentario)
- [x] Formulario/endpoint **Diezmo** (idem + opción de generar donación del pastor 30%)
- [x] Formulario/endpoint **Donación directa** (fecha, monto, origen, comentario)
- [x] Formulario/endpoint **Salida de caja** (fecha, monto, motivo, comentario)
- [x] Listado de movimientos con filtro por mes y tipo, editar y borrar
- **Check:** puedo crear los 4 tipos, verlos en el listado, editarlos y borrarlos; la donación del pastor se crea vinculada al diezmo con 30% precargado y editable.

### Fase 4 — Cálculos y lógica financiera
- [x] Servicio de cálculo que aplica las fórmulas y respeta los casos especiales (no recogido → sin entrega; excluir_entrega → sin entrega)
- [x] Cálculo de saldo de caja (acumulado y por mes)
- [x] Cálculo de "total a entregar a la organización" del mes
- [x] La caja nunca entra en la entrega a la organización (reserva local)
- [x] **Tests unitarios** de cada caso especial (recogido/no recogido, excluido, donación, salida)
- **Check:** los tests pasan cubriendo los 6 casos especiales; un mes de ejemplo da los números correctos a mano.

### Fase 5 — Dashboard y reporte mensual
- [x] Dashboard: saldo de caja actual, totales del mes en curso, pendiente a entregar
- [x] Vista de **Reporte mensual**: ofrendas/diezmos (recogidos vs. no recogidos), donaciones, salidas, total a entregar, saldo de caja, comentarios del mes
- [x] Exportar reporte (PDF o CSV imprimible)
- **Check:** el reporte de un mes coincide con el cálculo manual y es imprimible/descargable.

### Fase 6 — Configuración y pulido
- [x] Pantalla de configuración (editar porcentajes y contraseña)
- [x] Validaciones de formularios y mensajes de error claros
- [x] Estilos coherentes (Tailwind), formato de moneda, responsive básico
- [ ] Datos de ejemplo (seed opcional) para probar
- **Check:** cambiar un porcentaje recalcula los reportes; la app se ve y funciona bien en móvil y escritorio.

### Fase 7 — Cierre
- [x] README final con capturas y flujo de uso
- [x] Backup/restore de la base (comando o instrucción)
- [ ] Repaso de seguridad (secrets fuera del repo, contraseña fuerte, HTTPS si se despliega)
- **Check:** un usuario nuevo puede levantar la app siguiendo solo el README.

---

## 4. Cómo levantar (una vez implementado)

```bash
cp .env.example .env      # ajustar credenciales
docker compose up --build # levanta db + app
# abrir http://localhost:8000
```

---

## 5. Decisiones confirmadas

- **Caja:** reserva local permanente para la iglesia; **nunca** se entrega a la organización.
- **Donación del pastor (30%):** sobre cada diezmo individual, monto sugerido y editable;
  a veces se genera, a veces no. Nunca descuento mensual.
- **Moneda:** MXN. Formato `$1,234.56`.
- **Migraciones:** se usa `create_all` en el arranque; Alembic queda como mejora futura.
