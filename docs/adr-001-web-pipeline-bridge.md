# ADR-001: Puente Web↔Pipeline, rol de Streamlit y modelo de status

**Status:** Proposed (a aceptar por Nico)
**Date:** 2026-06-16
**Deciders:** Nico
**Resuelve:** el puente web↔pipeline, el rol de Streamlit y el modelo de status.

## Contexto

`jobcut` ya tiene un motor en **Python**: pull (Apify), SQLite (`db.py`), routing/filter,
scoring pluggable, surface/market/export, CLI y tests verdes. Se decidió construir un **console
Next.js** local-first como frontend principal, con onboarding visual, click-to-update de status
y arranque de un comando. Constraints que mandan:

- **100% local**, datos y secretos nunca salen del equipo (excepto la llamada a Apify).
- **Open-source para cualquiera**: fricción mínima de instalación ("descarga y funciona").
- **Reuso**: el motor Python existe y funciona — no reescribirlo.
- **Una sola fuente de verdad** para el esquema y la lógica de datos (evitar drift).

Fuerza clave: **Python es obligatorio igualmente** (Apify client, pandas, scoring viven en
Python). Ninguna opción elimina Python; la pregunta real es *cómo* habla la web con él.

## Decisión

1. **Puente = backend FastAPI fino que envuelve el paquete `jobcut`**, consumido por Next.js.
   El paquete Python + SQLite siguen siendo el núcleo y única fuente de verdad.
2. **Streamlit se mantiene como modo "lite" opcional sin Node** (lee el paquete directamente),
   en modo mantenimiento; Next.js es el frontend principal. Se re-evalúa retirarlo tras v1.
3. **Status de aplicación en una tabla `applications` separada** (no columnas en `scores`).

## Opciones consideradas (puente)

### Opción A — FastAPI (Python) + Next.js
| Dimensión | Evaluación |
|-----------|------------|
| Complejidad | Media (dos procesos, un launcher) |
| Coste | Bajo (todo local, OSS) |
| Escalabilidad | Alta para el caso (single-user local; SSE para progreso de runs) |
| Familiaridad equipo | Alta (Python ya es el core; FastAPI es estándar) |
| Reuso de lógica | **Total** — un solo `db.py`/scoring; cero duplicación |

**Pros:** una sola implementación de DB y de negocio; FastAPI autodoc; permite *streaming* del
progreso del pull/score (SSE/websocket); separación limpia; gran pieza de portfolio AI-eng.
**Cons:** dos runtimes (Python + Node) en dev y empaquetado; requiere un launcher (`jobcut serve`).

### Opción B — Solo Next.js (API routes + `better-sqlite3` + shell-out al CLI)
| Dimensión | Evaluación |
|-----------|------------|
| Complejidad | Media-alta (lógica de DB duplicada en Node + subprocess) |
| Coste | Bajo |
| Escalabilidad | Limitada (shell-out difícil de monitorizar/stremear) |
| Familiaridad equipo | Media (obliga a reimplementar acceso a datos en TS) |
| Reuso de lógica | **Parcial** — el esquema/queries se reescriben en Node → riesgo de drift |

**Pros:** un solo servidor (Node); deploy/onboarding aparentemente más simple.
**Cons:** **no elimina Python** (el pipeline sigue siendo Python → shell-out frágil: venv, env,
rutas); duplica el acceso a SQLite en Node (dos verdades del esquema); progreso de runs difícil.

### Opción C — Solo Streamlit interactivo (sin Next.js)
**Pros:** un runtime, mínima fricción, máximo reuso, lo más rápido.
**Cons:** techo de UX; no es la "plataforma muy visual" buscada. *Descartada por decisión previa
de ir a Next.js, pero sobrevive como modo lite (ver decisión 2).*

## Trade-off analysis

El argumento decisivo: como **Python es obligatorio de todos modos**, la supuesta ventaja de B
("un solo runtime") es ilusoria — sigues necesitando Python para el pipeline, y encima le pides
a Node que reimplemente el acceso a la BD y orqueste subprocesos. A elige el camino limpio:
expone el Python que ya existe detrás de una API, manteniendo **una sola implementación** del
esquema y la lógica. El coste real de A es de **empaquetado** (dos procesos), que se resuelve una
vez con `jobcut serve` + un bootstrap, no es un problema de arquitectura.

Arquitectura resultante (núcleo compartido, dos frontends):

```
                 ┌───────────────── jobcut (paquete Python) ─────────────────┐
                 │   pull · db(SQLite) · route/filter · scoring · surface/market │
                 └───────▲───────────────────────────────▲──────────────────────┘
                         │ import directo                 │ import directo
            FastAPI (uvicorn) ◀── HTTP/SSE ── Next.js     Streamlit "lite" (sin Node)
                         ▲                       ▲
                         └──── `jobcut serve --open` (API + web + abre navegador)
```

## Streamlit: por qué se mantiene como "lite"

Para "open-source para cualquiera", un camino **sin Node** tiene valor real: usuarios que no
quieren instalar Node tienen un dashboard funcional (read + toggle de status) corriendo solo con
Python. Habla con el paquete directamente (no necesita FastAPI). Coste: mantener dos UIs → se
acota dejándolo en modo mantenimiento (sin features nuevas), y se decide retirarlo tras validar v1.

## Status model: por qué tabla `applications` separada

- `scores` es **derivado** del pipeline (recomputable, se puede reconstruir). El status de
  aplicación es **verdad escrita por el usuario** y no debe perderse nunca en un re-score.
  Mezclarlos arriesga clobbering en cada run.
- Una tabla `applications` (PK `job_id`, + `status`, `status_category`, `applied_at`,
  `updated_at`, `notes`, `source`) habilita el funnel directo y deja sitio para una
  `status_history` futura (necesaria para el auto-status por email).
- El CSV/xlsx pasa a ser export/import, no la fuente.

## Consequences

- **Más fácil:** una sola lógica de datos; progreso de runs en vivo; AI layer se enchufa en el
  core y la sirven ambos frontends; status del usuario a salvo de los re-scores.
- **Más difícil:** empaquetar/documentar dos runtimes; mantener (temporalmente) dos frontends.
- **A revisar:** retirar Streamlit tras v1; opción de empaquetado con icono propio (Tauri) como
  Later; mecanismo de arranque en Windows.

## Action items
1. [ ] Definir el contrato de la API FastAPI (endpoints: pull, score, surface, market, shortlist,
   applications CRUD/status, searches CRUD, profile, validate-credentials).
2. [ ] Añadir tabla `applications` en `db.py` + migración; mover la clasificación de `tracker.py`.
3. [ ] `jobcut serve --open`: arranca uvicorn + sirve Next.js build + abre navegador.
4. [ ] Bootstrap idempotente (valida Python/Node, instala deps, crea data dir).
5. [ ] Marcar Streamlit como modo lite (read + status toggle), sin features nuevas.
