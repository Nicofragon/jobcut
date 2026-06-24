# ADR-002 — Rich application tracking (additive data-model evolution)

> Propósito: diseñar (NO aplicar) una evolución **aditiva** del modelo de datos que desbloquee el tracker rico que el owner pide — historial de estado, próxima acción/seguimiento, rondas de entrevista y notas con timeline — preservando el invariante de que un re-score **nunca** toca datos del usuario. — 2026-06-23

- **Estado:** PROPUESTO — requiere aprobación explícita del owner antes de implementar.
- **Tipo:** cambio de **contrato de DB** (schema_version 4 → 5) + extensión aditiva de API.
- **Alcance:** sólo diseño y artefacto. No se modifica `src/` ni `web/` en esta ronda.
- **Decide:** owner (es un cambio de contrato, no un default que el agente pueda elegir).

---

## 1. Contexto y problema

El tracker de aplicaciones es la superficie peor evaluada de la auditoría (score 34/100) y choca de frente con los 3 dolores nombrados por el owner. La causa raíz **no es UI**: es que la tabla `applications` es **plana**.

Estado actual del modelo (`src/jobcut/db.py:47`):

```python
APPLICATION_COLS = ["job_id", "status", "status_category", "applied_at", "updated_at", "notes", "source"]
```

- **`notes` es un único `TEXT` sin versionar** (`db.py:110`), sobrescrito por completo en cada write (`set_application_status`, `db.py:307`, last-write-wins). No hay timeline, no hay timestamp por nota.
- **No hay historial de estado.** `set_application_status` (`db.py:285-313`) pisa `status` + `updated_at` en cada cambio sin escribir una fila de auditoría. `applied_at` se preserva; todo lo demás se pierde. → imposible calcular *tiempo-en-etapa*, *aplicaciones estancadas*, o cómo evolucionó el funnel.
- **No hay campos estructurados** de tracking: ni `next_action`/`next_action_date`, ni `contact`/recruiter, ni `cv_version`, ni `priority`, ni flag de follow-up, ni estructura de rondas de entrevista. `status.py` (`LIVE`, líneas 23-25) trata `Interview` como un único bucket sin contar rondas.

**Por qué importa (mapeo a los dolores del owner):**

| Dolor del owner | Bloqueo de datos hoy |
|---|---|
| #1 Tracker demasiado básico, no puedo actualizar directo | Hay un único write-path (`set_application_status`) que **siempre exige un `status`**: no existe escritura de "solo notas" ni de campos estructurados. |
| #2 KPIs/funnel "no dicen nada" | Sin historial → no hay tiempo-en-etapa, ni estancados, ni evolución temporal. El funnel sólo conoce el estado *actual*. |
| #3 Detalle + notas pobres | `notes` es un blob plano sin historia; guardar una nota fuerza `status='applied'` (ver §3). |

**El invariante a preservar** (constraint del proyecto): un re-score reescribe únicamente la tabla `scores` (derivada). Nunca toca `applications` ni ninguna tabla nueva propiedad del usuario. Todo el diseño de abajo respeta esto por construcción: las nuevas tablas/columnas las escribe **sólo** el camino de aplicaciones, jamás el pipeline de scoring.

### Bug de contrato relacionado (a corregir junto con la migración, no antes)

Guardar una nota sobre un job sólo "guardado" (sin aplicar) **fabrica una aplicación**: `web/app/job/page.tsx:90-95` llama `setStatus(id, status ?? "applied", notes)`, y como no hay write-path de solo-notas, `db.py:300-305` inserta una fila `applications` con `status_category='Applied'` y `applied_at=now`, inflando el funnel que el owner ya desconfía (dolor #2 ↔ #3). El diseño de abajo crea ese camino de solo-notas.

---

## 2. Decisión — diseño aditivo

Tres adiciones, todas **nullable / con default**, todas escritas exclusivamente por el camino de aplicaciones. Bump de schema: **4 → 5**.

### 2.A — Nueva tabla `application_events` (timeline append-only)

Una tabla append-only de eventos es la pieza central: resuelve historial de estado **y** notas con timeline **y** rondas de entrevista con una sola estructura, sin tocar nunca filas existentes.

```
application_events
  event_id    INTEGER PRIMARY KEY AUTOINCREMENT
  job_id      TEXT NOT NULL                 -- mismo id que applications.job_id (sin FK, igual que applications)
  ts          TEXT NOT NULL                 -- ISO8601, igual formato que applied_at/updated_at
  kind        TEXT NOT NULL                 -- 'status_change' | 'note' | 'interview' | 'next_action'
  from_status TEXT                          -- sólo kind='status_change'
  to_status   TEXT                          -- sólo kind='status_change'
  body        TEXT DEFAULT ''               -- texto de la nota / detalle de la ronda / descripción
  meta        TEXT DEFAULT ''               -- JSON opcional (p.ej. round_number, interviewer) — extensible sin nuevo bump
```

Diseño:
- **Append-only.** Nunca se hace `UPDATE`/`DELETE` de filas históricas en operación normal. Un borrado de aplicación puede limpiar sus eventos (cascade lógico en código), pero el historial nunca se reescribe.
- **`kind='status_change'`** se escribe *dentro* del choke-point existente `set_application_status` (`db.py:285`): cada transición agrega una fila `{from_status, to_status, ts}`. De ahí se deriva tiempo-en-etapa y el flag "estancado > N días".
- **`kind='note'`** habilita notas con timestamp e historia (dolor #3) y, crucialmente, un **write-path de solo-nota** que NO requiere un `status` → mata el bug de §1.
- **`kind='interview'`** con `meta` = `{"round": 2, ...}` da rondas de entrevista sin columnas rígidas.
- `meta` como JSON-en-TEXT deja crecer el detalle por evento **sin** un futuro schema bump (patrón ya usado de facto por `match_reasons`).

Índice: `CREATE INDEX IF NOT EXISTS idx_app_events_job ON application_events(job_id);`

### 2.B — Columnas aditivas en `applications` (estado estructurado "vivo")

Lo que el timeline NO modela bien es el **estado actual de "qué hago ahora"** (necesita lectura O(1) y orden por fecha). Para eso, columnas nullable en `applications`:

```
priority          TEXT     -- 'high' | 'normal' | 'low' (nullable)
next_action       TEXT     -- texto libre: "enviar follow-up", "preparar case"
next_action_date  TEXT     -- ISO date; alimenta la sección "Follow-ups due / Needs attention"
contact           TEXT     -- recruiter / hiring manager (nombre, email, link)
cv_version        TEXT     -- qué versión de CV se envió
```

Todas nullable → filas existentes quedan válidas sin backfill. `APPLICATION_COLS` pasa a:

```python
APPLICATION_COLS = ["job_id", "status", "status_category", "applied_at", "updated_at",
                    "notes", "source",
                    "priority", "next_action", "next_action_date", "contact", "cv_version"]
```

> `notes` se **mantiene** como "última nota / atajo" para compatibilidad y para el textarea actual; la historia vive en `application_events`. No se borra ninguna columna.

**Decisión tabla-vs-columna:** eventos repetibles y temporales (estado, notas, rondas) → tabla `application_events`. Atributos singleton del estado actual (prioridad, próxima acción, contacto, CV) → columnas en `applications`. Esto mantiene "follow-ups due" como un query barato sobre `applications` sin agregar el timeline.

---

## 3. Boceto de migración (idempotente, aditiva, backward-compatible)

Sigue **exactamente** el patrón ya presente en `init_schema` (`db.py:86-141`): `CREATE TABLE IF NOT EXISTS` para DBs nuevas + `ALTER ... ADD COLUMN` guardado por `PRAGMA table_info` para DBs viejas + bump de `_meta.schema_version`. Sin pasos destructivos.

```
SCHEMA_VERSION = 5   # 4 -> 5

# en init_schema(), dentro del executescript inicial (cubre DBs nuevas):
CREATE TABLE IF NOT EXISTS application_events (
  "event_id"    INTEGER PRIMARY KEY AUTOINCREMENT,
  "job_id"      TEXT NOT NULL,
  "ts"          TEXT NOT NULL,
  "kind"        TEXT NOT NULL,
  "from_status" TEXT,
  "to_status"   TEXT,
  "body"        TEXT DEFAULT '',
  "meta"        TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_app_events_job ON application_events(job_id);

# para DBs creadas antes de v5 (CREATE IF NOT EXISTS no agrega columnas a una tabla existente):
app_cols = {r[1] for r in conn.execute("PRAGMA table_info(applications)")}
for col in ("priority", "next_action", "next_action_date", "contact", "cv_version"):
    if col not in app_cols:
        conn.execute(f'ALTER TABLE applications ADD COLUMN "{col}" TEXT')

# bump _meta.schema_version 4 -> 5 (igual que el bloque actual de db.py:134-140)
```

Propiedades garantizadas:
- **Idempotente:** re-ejecutable; `IF NOT EXISTS` y el guard de `PRAGMA` evitan duplicados/errores.
- **Backward-compatible:** filas `applications` existentes siguen válidas (columnas nuevas = `NULL`); sin `application_events` previos, las lecturas de timeline devuelven vacío y el tracker degrada a su comportamiento actual.
- **Preserva el invariante:** ni `CREATE` ni `ALTER` tocan `scores`/`score_runs`; el pipeline de scoring no lee ni escribe nada de lo nuevo.
- **Sin backfill obligatorio.** Opcional y no destructivo: sembrar un `status_change` inicial por cada `applications` existente con `to_status=status, ts=applied_at`, para que tiempo-en-etapa tenga punto de partida. Si se omite, el tiempo-en-etapa simplemente arranca desde el primer cambio post-migración.

---

## 4. Superficie de API (extensión aditiva — sin escribir código aquí)

Cambios en `src/jobcut/api/routers/applications.py`. Todos aditivos: los endpoints actuales (`GET ""`, `GET /funnel`, `GET /statuses`, `GET /{job_id}`, `PUT /{job_id}`, `DELETE /{job_id}`) mantienen su contrato.

**Nuevos / extendidos:**

- **`PATCH /applications/{job_id}`** — write-path de campos estructurados **sin** tocar `status` (resuelve el acople notas↔status). Body parcial: cualquier subconjunto de `{priority, next_action, next_action_date, contact, cv_version, notes}`. Si la fila no existe y sólo se manda `notes`, crea/usa un estado neutro NO-funnel (ver §7, alternativa de estado `saved`) en vez de fabricar `applied`.
- **`POST /applications/{job_id}/events`** — agrega un evento al timeline. Body: `{kind, body?, meta?}`. Para `kind='note'` no requiere status → camino de nota append-only.
- **`GET /applications/{job_id}/events`** — devuelve el timeline (reverse-chron) para el detalle.
- **`PUT /applications/{job_id}` (extendido):** sigue siendo el choke-point de estado; ahora **además** escribe un `status_change` en `application_events` dentro de la misma transacción (cero cambio de contrato para el caller).
- **`GET /applications` (extendido, opcional):** incluir campos nuevos + `next_action_date` para que el front arme "Follow-ups due" sin N+1.
- **`GET /applications/funnel` (extendido, opcional):** sumar `by_stage_time` / `stalled_count` derivados de los eventos (no cambia las claves existentes; sólo agrega).

Contratos del `status.py` (`STATUSES`, `classify`, `summarize`) se mantienen; se pueden **extender** aditivamente para exponer tiempo-en-etapa, sin romper las claves actuales del funnel.

---

## 5. Qué mejora de UX se desbloquea con qué

Separa lo que es **puro frontend hoy** (no necesita esta migración) de lo que **requiere** este cambio de esquema. Esto evita pedir aprobación de DB para cosas que ya se pueden hacer.

### Ya posible sin esta migración (frontend, datos ya existen)
- Funnel real con etapas mutuamente excluyentes + % de conversión (la data ya está en `summarize`: `counts`, `rejected`, `no_response`). *(hallazgo P0 funnel)*
- KPIs como ratios (response rate, interview conversion, delta semana vs semana vía `by_week`). *(P0)*
- Lista con filtro/orden/agrupación + `StatusSelect` inline (el `PUT` ya existe). *(P0 dolor #1)*
- Labels amigables de estados, separar destructivos. *(P2)*
- Detalle "application-only" para imports sin job row (esconder ring/company en vez de "—"). *(P1)*

### Sólo posible DESPUÉS de esta migración
- **Notas con timeline e historia** + write-path de solo-nota que no fabrica `applied`. → `application_events (kind='note')` + `PATCH`/`POST events`. *(P0 dolor #3 + bug §1)*
- **Tiempo-en-etapa / "estancado > N días" / "Needs attention".** → `application_events (status_change)`. *(P2/P1 dolor #2)*
- **"Follow-ups due / próxima acción".** → columnas `next_action`, `next_action_date`. *(P1)*
- **Prioridad, contacto/recruiter, versión de CV** en el detalle. → columnas nuevas. *(P1)*
- **Rondas de entrevista estructuradas** (R1/R2/case). → `application_events (kind='interview', meta.round)`. *(P1)*

---

## 6. Feasibility map (hallazgo prioritario → capa requerida)

| Hallazgo prioritario (auditoría) | Capa |
|---|---|
| Pipeline bar matemáticamente sin sentido → funnel real con conversión | **frontend-only** (data ya en `summarize`) |
| KPIs sin señal → ratios + sparkline `by_week` | **frontend-only** |
| Lista plana sin filtro/orden/grupo + status inline | **frontend-only** (`PUT` ya existe) |
| Status tokens crudos → labels amigables | **frontend-only** |
| Detalle degradado para imports (ring/company "—") | **frontend-only** (esconder paneles) |
| Step bar no representa rejected/withdrawn/no_response | **frontend-only** |
| Notas hostage de un status write (fabrica `applied`) | **needs-schema** (write-path solo-nota) |
| Notas = blob sin versión/historia/autosave | **needs-schema** (`application_events`) |
| Sin historial → tiempo-en-etapa / estancados desconocidos | **needs-schema** (`application_events`) |
| Sin next-action/fecha/contacto/CV/prioridad → "qué hago ahora" | **needs-schema** (columnas aditivas) |
| Rondas de entrevista (R1/R2) | **needs-schema** (`application_events.meta`) |
| `GET /jobs/{id}` hace 404 en imports sin job row | **needs-API** (devolver 200 con `job:null`) |
| Funnel expone `stalled_count`/tiempo-en-etapa | **needs-API** (deriva de eventos) |

---

## 7. Alternativas consideradas

1. **Columnas para todo (sin tabla de eventos).** Agregar `notes_history JSON`, `status_history JSON` como blobs en `applications`. Rechazado: re-introduce el problema last-write-wins (reescribir el blob entero en cada cambio = no append-only, riesgo de pérdida en escrituras concurrentes), y dificulta queries de tiempo-en-etapa. La tabla de eventos es append-only y consultable.
2. **Tabla de eventos para todo (sin columnas nuevas).** Derivar `next_action`/`priority` del último evento de ese `kind`. Rechazado para el estado "vivo": "follow-ups due" se vuelve un query caro (último evento por job por kind) en cada render; las columnas dan lectura O(1). Se usan **ambas**, cada una para lo que rinde.
3. **Nuevo estado no-funnel `saved`/`note`** en `status.py` para notas sin aplicar, en vez de un `PATCH` separado. Compatible y recomendable como complemento: `classify('saved')` mapea fuera de `LIVE`/`Applied`, de modo que una nota nunca infle el funnel. Es aditivo (nuevo token en `STATUSES`) y no rompe el contrato.
4. **No migrar; resolver en frontend.** Cubre los P0 del funnel/lista/KPIs (ver §5) pero **no** notas-con-historia, tiempo-en-etapa, ni next-action — es decir, deja sin tocar el núcleo de los dolores #2/#3. Por eso esta migración es necesaria, pero **después** de cosechar las mejoras frontend-only.

---

## 8. Riesgos

- **Es un cambio de contrato de DB** → requiere aprobación del owner (este ADR no lo aplica).
- **Doble fuente de verdad** entre `applications.notes` (última nota) y `application_events(kind='note')`: mitigar definiendo que el timeline es la verdad y `notes` un espejo de la última, escrito en la misma transacción.
- **Crecimiento de `application_events`**: irrelevante a escala mono-usuario (decenas-cientos de apps); índice por `job_id` cubre las lecturas del detalle.
- **Backfill opcional**: si no se siembra el `status_change` inicial, tiempo-en-etapa arranca desde la migración (degradación aceptable, no error).
- **Consistencia transaccional**: el `status_change` debe escribirse en la **misma** transacción que el `UPDATE applications` para no dejar estado e historial divergentes (el choke-point único `set_application_status` lo facilita).
- **Regresión del invariante de scoring**: bajo, por construcción — ninguna ruta de scoring referencia las nuevas estructuras. Cubrir con un test que verifique que un re-score no modifica `applications` ni `application_events`.

---

## 9. Rollout por fases

- **Fase 0 (sin esta migración):** cosechar todo lo frontend-only de §5/§6 (funnel real, KPIs ratio, lista con filtro/orden/inline status, labels, detalle application-only). Cierra gran parte del dolor #1 y #2 sin tocar el contrato.
- **Fase 1 (esta migración — requiere aprobación):** bump 4→5, `application_events` + columnas aditivas; `set_application_status` escribe `status_change`; `PATCH`/`POST events`/`GET events`. UI: notas-timeline + write-path solo-nota (mata el bug §1). Cierra dolor #3.
- **Fase 2:** derivados de eventos — tiempo-en-etapa, "estancado > N días", sección "Follow-ups due" sobre `next_action_date`, rondas de entrevista. Cierra el resto del dolor #2.
- **Fase 3 (opcional):** `GET /jobs/{id}` 200-con-`job:null` para imports; estado no-funnel `saved`; backfill del evento inicial.

---

## 10. Aprobación requerida

Implementar la Fase 1+ **requiere aprobación explícita del owner**, por ser un cambio del contrato de DB (`schema_version` 4→5) y de la superficie de API. La Fase 0 es pura UI y puede avanzar sin este ADR. Hasta la aprobación, este documento es sólo diseño.
