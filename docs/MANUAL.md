# jobcut — Manual de usuario

> Cómo funciona toda la plataforma, de punta a punta: el motor (pipeline Python +
> SQLite), el puente FastAPI, el console Next.js, el dashboard Streamlit "lite", y
> cada paso del flujo diario. Versión: post-Fase 2.

## Índice

1. [Qué es jobcut](#1-qué-es-jobcut)
2. [Arquitectura en una página](#2-arquitectura-en-una-página)
3. [Instalación](#3-instalación)
4. [El "data dir": dónde vive todo](#4-el-data-dir-dónde-vive-todo)
5. [Arranque rápido (3 caminos)](#5-arranque-rápido-3-caminos)
6. [El pipeline, paso a paso](#6-el-pipeline-paso-a-paso)
7. [El modelo de datos (SQLite)](#7-el-modelo-de-datos-sqlite)
8. [Targeting derivado del perfil (role-agnostic)](#8-targeting-derivado-del-perfil-role-agnostic)
9. [El scoring (rúbrica)](#9-el-scoring-rúbrica)
10. [El console web, sección por sección](#10-el-console-web-sección-por-sección)
11. [El loop central (uso diario)](#11-el-loop-central-uso-diario)
12. [Referencia de la API](#12-referencia-de-la-api)
13. [Referencia de la CLI](#13-referencia-de-la-cli)
14. [Dashboard Streamlit "lite"](#14-dashboard-streamlit-lite)
15. [Coste y seguridad](#15-coste-y-seguridad)
16. [Configuración (referencia)](#16-configuración-referencia)
17. [Troubleshooting](#17-troubleshooting)
18. [Glosario](#18-glosario)

---

## 1. Qué es jobcut

jobcut es una **plataforma 100% local** para buscar empleo sin scrollear portales.
Una vez al día:

1. descarga tus búsquedas guardadas de LinkedIn (vía el scraper Apify),
2. las deduplica en una base **SQLite** local,
3. descarta lo que no podés tomar (geografía, título fuera de perfil),
4. **puntúa 0–100 el resto contra tu propio perfil**, y
5. te entrega una **shortlist rankeada** que gestionás desde un dashboard:
   marcás ofertas como "aplicada" y las ves avanzar por un **funnel**.

**Nunca aplica por vos** (es decisión humana, por diseño). Como nunca borra filas,
también es tu **dataset de mercado** (qué skills se piden, dónde, cómo cambia).

**Principios:** todo local; tus datos/secretos no salen del equipo (salvo la llamada
a Apify); el scraper de pago solo se dispara con confirmación explícita; funciona sin
ninguna API key de IA (la capa IA es opcional).

---

## 2. Arquitectura en una página

**Un núcleo, dos frontends.** SQLite es la única fuente de verdad; el paquete Python
es el motor; todo lo demás lo consume.

```
                 ┌───────────────── jobcut (paquete Python) ─────────────────┐
                 │   pull · db(SQLite) · route/filter · scoring · surface/market │
                 └───────▲───────────────────────────────▲──────────────────────┘
                         │ import directo                 │ import directo
            FastAPI (uvicorn) ◀── HTTP/SSE ── Next.js     Streamlit "lite" (sin Node)
                         ▲                       ▲
                         └──── `jobcut serve --open` (API + web + abre navegador)
```

- **Motor Python (`src/jobcut/`)** — pull, SQLite, routing/filter, scoring, surface/market, CLI.
- **Puente FastAPI (`jobcut.api`)** — backend fino que **importa** el paquete y lo expone en `/api`. No reimplementa lógica.
- **Console Next.js (`web/`)** — la UI principal (onboarding, shortlist, funnel, etc.).
- **Streamlit "lite" (`dashboard/app.py`)** — camino sin Node: lectura + cambio de status.

Decisiones cerradas (ver `docs/ADR-001`): SQLite única verdad; puente FastAPI (no Node
reimplementando la DB); status de aplicación en tabla propia; targeting derivado del perfil.

---

## 3. Instalación

**Requisitos:** Python 3.10+ (siempre). Node 20.9+ **solo para construir** el console
(no para correrlo). macOS / Linux / Windows.

```bash
git clone git@github.com:Nicofragon/jobcut.git && cd jobcut
pip install -e .            # motor + CLI
```

Extras opcionales (instalá los que uses):

| Extra | Para qué | Comando |
|---|---|---|
| `api` | Puente FastAPI + `jobcut serve` | `pip install -e '.[api]'` |
| `cv` | Importar CV en PDF/DOCX | `pip install -e '.[cv]'` |
| `llm` | Scoring/CV con IA (OpenAI/Anthropic) | `pip install -e '.[llm]'` |
| `dashboard` | Streamlit "lite" | `pip install -e '.[dashboard]'` |
| `dev` | Tests + lint | `pip install -e '.[dev]'` |

---

## 4. El "data dir": dónde vive todo

Todo lo tuyo vive en el **data dir** = `$JOBCUT_DATA_DIR` si está seteado, o el
**directorio actual**. Nada se escribe junto al paquete instalado.

```
<data dir>/
├── .env                    # APIFY_TOKEN y (opcional) ANTHROPIC_API_KEY / OPENAI_API_KEY
├── profile.md              # tu perfil — la entrada de mayor leverage
├── jobcut.db             # la base SQLite (la fuente de verdad)
├── config/
│   ├── config.json         # routing, filtro de títulos, pesos de scoring (overrides)
│   └── taxonomy.json       # skills (regex + estado have/partial/gap) + role_segments
├── searches/*.json         # una búsqueda guardada por archivo (input del actor Apify)
├── out/                    # exports: shortlist.md/csv, market-gaps.md, dashboard.json…
├── last_runs.json          # punteros al último run de Apify (para `pull --read`)
└── market_history.xlsx     # snapshot de demanda de skills por fecha
```

`jobcut init` crea esta estructura desde plantillas (idempotente: no pisa lo editado).
Todo lo personal (`.env`, `profile.md`, `*.db`, `config/*.json`, `searches/*.json`,
`out/`) está **git-ignored**.

---

## 5. Arranque rápido (3 caminos)

### Camino A — Console web (recomendado)

```bash
pip install -e '.[api]'
cd web && npm install && npm run build && cd ..   # construir el console una vez (Node 20.9+)
jobcut serve --open                              # http://127.0.0.1:8000
```

`jobcut serve` levanta uvicorn, sirve el build estático del console y la API **en el
mismo proceso y origen**. La primera vez el console te lleva al **onboarding**.

### Camino B — Desarrollo del console (hot reload, 2 procesos)

```bash
uvicorn jobcut.api.app:app --port 8000     # terminal 1: la API
cd web && npm run dev                          # terminal 2: Next dev en :3000
```

En dev el console detecta el puerto :3000 y pega a `http://localhost:8000/api` (CORS ya
lo permite).

### Camino C — Sin Node (Streamlit "lite")

```bash
pip install -e '.[dashboard]'
jobcut dashboard
```

### Probar sin Apify (datos demo, gratis)

```bash
export JOBCUT_DATA_DIR=$(pwd)/demo-data
jobcut init --no-input
python scripts/seed_demo.py     # siembra ofertas sintéticas
jobcut score                  # las puntúa
jobcut serve --open
```

---

## 6. El pipeline, paso a paso

Flujo diario. Cada etapa es un módulo y (casi todas) un comando de CLI. Todas operan
sobre SQLite; ninguna borra datos.

```
pull → store → route → filter → score → surface → market
```

| # | Etapa | Módulo | Qué hace |
|---|---|---|---|
| 1 | **Pull** | `pull.py` | Lee `searches/*.json`, dispara cada búsqueda en el actor Apify (o re-descarga el último run con `--read`), aplana el payload anidado a columnas limpias. |
| 2 | **Store** | `db.py` | Upsert de 1 fila por `job_id` en la tabla `jobs`. `first_seen` se fija; `last_seen`/`applicants`/`job_state` se refrescan al re-ver la oferta; los campos estables no se pisan. Nunca borra (acumulador histórico). |
| 3 | **Route** | `route.py` | Compuerta geográfica (config-driven): ¿es contratable *para vos*? `home` (full) vs `region` (solo remoto) vs `foreign` (solo market-intel). |
| 4 | **Filter** | `filter.py` | Aplica el filtro de títulos (`include_titles`), excluye lo ya scoreado (incremental) y **colapsa reposts** por un `canonical_id` (empresa|título|ubicación). |
| 5 | **Score** | `scoring/` | Puntúa 0–100 cada representante contra el perfil + una razón de una línea. Reposts heredan el score del canónico; títulos fuera de perfil quedan con un score bajo fijo. |
| 6 | **Surface** | `surface.py` | Une jobs+scores, aplica el funnel, colapsa reposts, **excluye ya-aplicadas** (tabla `applications`), y escribe `out/shortlist.md` + `.csv`. |
| 7 | **Market** | `market.py` | Demanda de skills vs tu perfil sobre toda la DB → `out/market-gaps.md` + `out/market-dashboard.html` + history. |

Equivalente en CLI:

```bash
jobcut pull --read    # gratis (re-descarga el último run) — o `jobcut pull` (pago)
jobcut score
jobcut surface
jobcut market
jobcut export         # vuelca jobs/scores a CSV/JSON en out/
```

Desde el console, "Run scraper" hace el pull (con confirmación de coste) y "Re-score"
hace el score — ambos con progreso en vivo (SSE).

---

## 7. El modelo de datos (SQLite)

Cuatro tablas (`schema_version = 2`):

**`jobs`** — el acumulador madre, 1 fila por `job_id` (PK). ~32 columnas que reflejan el
payload aplanado: `title, company_name, location, workplace_type, applicants,
description, salary_*, recruiter_*, apply_url, linkedin_url, first_seen, last_seen,
source_searches`, etc. `VOLATILE = {last_seen, applicants, job_state}` se refrescan; el
resto es estable. **Nunca se borra.**

**`scores`** — sidecar **derivado** (recomputable), 1 fila por `job_id`:
`canonical_id, match_score, match_reasons, status` (`scored` | `discarded`),
`scored_date`.

**`applications`** — **verdad escrita por vos** (el funnel), separada de `scores` para
que un re-score nunca la pise. PK `job_id` (sin FK → admite entradas manuales):
`status, status_category, applied_at` (se fija una vez), `updated_at` (se refresca),
`notes, source` (`manual` | `import` | futuro `email`). Toda escritura pasa por un único
punto (`db.set_application_status`), que deja sitio a una `status_history` futura.

**`_meta`** — `schema_version`. Las migraciones son aditivas y version-gated (idempotentes).

> Por qué separar `scores` y `applications`: `scores` se reconstruye recomputando; tu
> status de aplicación es input humano que **no debe perderse jamás** en un re-score.

---

## 8. Targeting derivado del perfil (role-agnostic)

**Nada está cableado a un rol.** Tus búsquedas y tu rúbrica se **derivan de
`profile.md`** — sirve igual para una enfermera o un data analyst.

`profile.md` tiene headings estables que el sistema parsea (`profile.py`):

- `## Target roles` → títulos objetivo
- `## Core skills` → skills que tenés hoy
- `## Nice-to-have / learning` → skills "plus"
- `## Location & work mode` → `Based in:` y `Remote:`
- `## Dealbreakers` → requisitos que NO cumplís

De ahí se **genera** (no-destructivo: no pisa archivos existentes salvo que fuerces):

| Derivado | De dónde sale | Lo usa |
|---|---|---|
| `searches/*.json` | target roles + remote mode (geoId = placeholder a completar) | el pull |
| `filter.include_titles` | target roles (sin seniority) | el filter |
| `routing.home` / `routing.region` | tokens de `Based in:` (region = país) | el route |
| `taxonomy.skills` | core skills (status `have`) | el score (stack) + market |
| `scoring.signals` | nice-to-have skills | el score (bonus) |
| `scoring.dealbreakers` | sección Dealbreakers (best-effort, revisá) | el score (penalización) |

Desde el console: **Settings → Profile** edita `profile.md`, "Regenerate" genera los
artefactos, y un re-score aplica la nueva rúbrica. (Endpoints: `GET /api/profile/derived`
previsualiza; `POST /api/profile/derive` escribe.)

**CV → perfil (capa IA opcional):** subís un CV (`txt/md` siempre; `pdf/docx` con el
extra `[cv]`); si hay una key LLM, la IA arma un borrador de `profile.md` con los headings;
si no, cae a un *scaffold* con el texto del CV para que lo organices. **Nunca se guarda
solo** — revisás y confirmás.

---

## 9. El scoring (rúbrica)

**Pluggable** vía la interfaz `Scorer`. Backend por defecto: `rule_based` (Python puro,
sin key, sin coste, transparente). Se elige en `config.scoring.backend`.

### `rule_based` — componentes y pesos (editables en `config.json`)

```text
+30  title       el título matchea un target role (include_titles)
+20  stack       skills del taxonomy presentes (mitad si solo 1)
+15  location    ubicación contratable (home full, region-remote parcial)
+10  signals     skills "nice-to-have" del perfil presentes (default vacío → sin efecto)
+10  employer    empresa nombrada + tamaño plausible
+10  reachable   <50 applicants o recruiter nombrado
−20  dealbreaker un requisito duro que no cumplís
     out-of-profile cap: si el título NO matchea tus target roles → score ≤ 30
```

Todo lo de arriba (títulos, skills, signals, dealbreakers, geografía) **viene de tu
perfil** — no hay listas de roles hardcodeadas. Cada score trae una razón de una línea.

### Tiers opcionales

- **`llm_api`** — puntúa con un LLM (tu key, vía el extra `[llm]`); pide JSON
  `{score, reason}`. Mejor calidad, coste por oferta. Sin key configurada falla con un
  mensaje claro (no rompe el default).
- **`claude_skills`** — adapter para usuarios de Claude (stub; pendiente).

---

## 10. El console web, sección por sección

Paleta GitHub-dark. Navegación: **Today · Applications · Searches · Discovery · Settings**
(+ Onboarding y Detalle).

- **Onboarding** (`/onboarding`) — wizard de primer arranque: (1) credenciales (validar
  Apify gratis + guardar), (2) perfil (subir CV → borrador, o escribir), (3) generar
  búsquedas/rúbrica derivadas, (4) backend de scoring, (5) primer pull. Idempotente, con
  "Skip". El Home redirige acá en el primer arranque (sin token y sin jobs).
- **Today** (`/`) — la shortlist del día rankeada. Filtros (score mínimo, búsqueda con
  debounce). Cada `JobCard`: score, razón, link a la oferta y cambio rápido de status.
  Secciones "New today" + "Backlog". Botones **Re-score** (gratis) y **Run scraper**
  (modal de coste → progreso SSE).
- **Detalle** (`/job?id=…`) — descripción completa, **desglose del score** (chips de
  razones), datos de empresa, control de status, notas, link para aplicar.
- **Applications** (`/applications`) — el **funnel**: KPIs (applied / in-process /
  interview / offers), barras, y tabla editable (cambiar status inline, borrar).
- **Searches** (`/searches`) — CRUD de búsquedas (JSON editable por archivo), crear/borrar,
  y "Run scraper" (con aviso de coste). Recordá poner el `geoId` real.
- **Discovery** (`/discovery`) — market gaps: demanda de skills vs tu perfil
  (have/partial/gap), gaps priorizados, mix de segmentos.
- **Settings** (`/settings`) — credenciales (validar/guardar), backend de scoring, data
  dir + estado de la DB, **export** CSV/JSON, y link a editar el Perfil.
- **Profile** (`/profile`) — editor de `profile.md`, regenerar searches/rúbrica
  (no-destructivo), y editor de **pesos** de scoring.

---

## 11. El loop central (uso diario)

1. Abrí el console (`jobcut serve --open`, o el atajo).
2. **Today** → revisá la shortlist; filtrá por score.
3. Click en una oferta → **Detalle** → mirá el desglose del score → aplicá en LinkedIn/ATS
   (vos, a mano).
4. Marcá el **status** (ej. `applied` → luego `screen`/`interview`/`offer`/…).
5. **Applications** → seguí tu funnel; actualizá estados a medida que avanzás.
6. Cada tanto: **Run scraper** (trae ofertas nuevas, con confirmación de coste) y
   **Re-score**. El status que marcaste **sobrevive** a cualquier re-score.

Ajuste de targeting: **Settings → Profile** → editás `profile.md` → "Regenerate" → el
próximo run mejora.

---

## 12. Referencia de la API

Base: `/api`. JSON in/out. Operaciones largas/caras (`pull`, `score`) van por el modelo
de "run" con **SSE**; el resto es síncrono.

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/status` | Salud: data dir, schema, conteos, flags de credenciales. |
| GET / PUT | `/credentials` | Lee (booleanos) / escribe `.env` (nunca devuelve secretos). |
| POST | `/validate-credentials` | Valida Apify **gratis** (`user().get()`, no dispara actor). |
| GET | `/shortlist` | Shortlist `{today, backlog, meta}`. Query: `min_score, backlog_min, q, location, recency_days, include_applied`. |
| GET | `/jobs/{id}` | Oferta completa + score + estado de aplicación. |
| GET | `/applications` | Todas las aplicaciones (el funnel). |
| GET | `/applications/funnel` | KPIs + funnel + por-categoría + por-semana. |
| GET | `/applications/statuses` | Vocabulario canónico de status + categorías. |
| GET/PUT/DELETE | `/applications/{id}` | Leer / set status (upsert) / borrar. |
| GET | `/searches` · GET/POST/PUT/DELETE `/searches/{name}` | CRUD de búsquedas (nombre validado). |
| GET/PUT | `/profile` | Lee / escribe `profile.md`. |
| GET | `/profile/derived` | Previsualiza searches/config/taxonomy derivados. |
| POST | `/profile/derive` | Escribe los derivados (no-destructivo salvo `force`). |
| POST | `/profile/from-cv` | Borrador de `profile.md` desde texto de CV (IA o scaffold). |
| POST | `/cv/extract` | Extrae texto de un CV subido (txt/md; pdf/docx con `[cv]`). |
| GET/PUT | `/config` | Config efectiva (merge) / escribe overrides. |
| GET/POST | `/market` | Datos de market gaps (GET, read-only) / regenerar artefactos (POST). |
| POST | `/export` | Escribe `out/jobs.csv`, `scores.csv`, `dashboard.json`. |
| POST | `/runs` | Inicia un run `{kind: "pull"\|"score", mode, confirm}`. |
| GET | `/runs/{id}` | Estado del run. |
| GET | `/runs/{id}/events` | **SSE** del progreso (`stage`, `message`, `done`). |

**Guard de coste (regla dura):** `kind:"pull"` + `mode:"trigger"` (Apify de pago)
**exige `confirm:true`**; si no → `409 confirmation_required`. `mode:"read"` y `score`
no requieren confirmación. Docs interactivas: `http://<host>:<port>/docs`.

---

## 13. Referencia de la CLI

```bash
jobcut init [--no-input]    # scaffolding del data dir (idempotente)
jobcut pull [--read]        # pull de Apify (sin flag = PAGO; --read = re-descarga gratis)
jobcut score                # filtra el funnel + scorea contra el perfil
jobcut surface              # escribe out/shortlist.md + .csv
jobcut market               # escribe out/market-gaps.md + dashboard + history
jobcut export               # vuelca la DB a CSV/JSON en out/
jobcut serve [--host H] [--port P] [--open]   # API + console en un proceso
jobcut dashboard            # Streamlit "lite" (extra [dashboard])
```

---

## 14. Dashboard Streamlit "lite"

El camino **sin Node** (modo mantenimiento, sin features nuevas). Tres tabs:

- **Funnel** — lee la tabla `applications`; KPIs, funnel, charts de status/semana, tabla,
  y un **toggle de status** (escribe vía `set_application_status`).
- **Discovery** — la shortlist scoreada desde la DB (buckets de score + tabla).
- **Market gaps** — el reporte `out/market-gaps.md`.

Arranque: `jobcut dashboard`. Es la opción para quien no quiere instalar Node; el
console Next.js es el frontend principal.

---

## 15. Coste y seguridad

- **Apify es de pago** (~$0.04–0.18 por run). `jobcut pull --read` re-descarga el último
  run **gratis** y es el default en desarrollo. En el console, "Run scraper" siempre pide
  confirmación (guard 409 en la API).
- **Secretos:** `APIFY_TOKEN` y keys LLM viven en `<data>/.env` (git-ignored). La API
  nunca devuelve sus valores (solo booleanos "está seteado").
- **Privacidad:** todo es local. Lo único que sale del equipo es la llamada a Apify.
- **Nunca auto-aplica ni auto-genera CVs** (por diseño).

---

## 16. Configuración (referencia)

`config/config.json` (overrides; lo que omitís cae a defaults). Claves principales:

```jsonc
{
  "routing": { "home": "<regex>", "region": "<regex>" },   // geografía contratable
  "filter":  { "include_titles": "<regex>" },              // títulos que valen scorear
  "scoring": {
    "backend": "rule_based",                                // rule_based | llm_api | claude_skills
    "weights": { "title":30,"stack":20,"location":15,"signals":10,
                 "employer":10,"reachable":10,"dealbreaker":-20 },
    "signals": [],            // patrones bonus (derivados de nice-to-have)
    "dealbreakers": [],       // patrones de penalización (derivados de Dealbreakers)
    "out_of_profile_cap": 30
  }
}
```

`config/taxonomy.json`: `skills` (`{cat, status: have|partial|gap, close_via, patterns}`) +
`role_segments` (para el market). **Variables de entorno:** `JOBCUT_DATA_DIR`,
`APIFY_TOKEN`, `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, `NEXT_PUBLIC_API_BASE` (override del
base de la API en el front).

---

## 17. Troubleshooting

| Síntoma | Causa / solución |
|---|---|
| Console dice "API offline" | La API no corre. `uvicorn jobcut.api.app:app --port 8000` o `jobcut serve`. |
| `serve` dice "no build found (web/out)" | Construí el console: `cd web && npm install && npm run build`. (O usá `npm run dev` en :3000.) |
| "Today" vacío pero hay jobs | Las ofertas se scorearon otro día → están en "Backlog". Bajá el score mínimo, o re-scoreá. |
| `pull --read` falla | No hay run previo (`last_runs.json`). Corré `jobcut pull` (pago) una vez. |
| Búsqueda generada no trae nada | El `geoId` quedó en `REPLACE_ME`. Editá `searches/*.json` con tu geoId real de LinkedIn. |
| Una enfermera/rol no-data puntúa bajo | Regenerá el targeting desde tu `profile.md` (Settings → Profile → Regenerate) y re-scoreá. |
| CV PDF no se lee | Instalá el extra: `pip install -e '.[cv]'` (o pegá el texto). |
| `llm_api` da error | Necesita `[llm]` + una key (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`). O usá `rule_based`. |

---

## 18. Glosario

- **funnel** — las ofertas contratables para vos (pasan la compuerta geo); las demás son
  solo market-intel.
- **canonical_id** — clave `empresa|título|ubicación` para colapsar reposts.
- **representante / repost** — al colapsar reposts, se scorea un representante; los reposts
  heredan su score.
- **status vs status_category** — `status` es el valor canónico que marcás
  (`applied/screen/interview/offer/rejected/withdrawn/no_response`); `status_category` es
  la categoría de funnel derivada (Applied, Screen, Interview, Offer, …).
- **data dir** — la carpeta con toda tu data/config (`$JOBCUT_DATA_DIR` o el dir actual).
- **lite** — el dashboard Streamlit (read + toggle), el camino sin Node.

---

*Documentos relacionados: [índice de docs](README.md) · [WORKFLOW](WORKFLOW.md).*
