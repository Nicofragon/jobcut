# docs/ — index

Documentation for **jobcut**. Start with the [project README](../README.md) for install
and quick start; this folder holds the deeper user and architecture docs.

## User guides

| Doc | What it covers |
|-----|----------------|
| [MANUAL.md](MANUAL.md) | End-to-end user manual — install, configure, run the pipeline and the web console. |
| [WORKFLOW.md](WORKFLOW.md) | The pipeline walkthrough, stage by stage: pull → store → route → filter → score → surface → market, plus tracking applied roles. |

## Using jobcut with Claude (orchestration engine)

| Doc | What it covers |
|-----|----------------|
| [../integrations/cowork/README.md](../integrations/cowork/README.md) | How Claude drives jobcut: the three skills and the CLI-as-database contract. |
| [../integrations/cowork/SETUP.md](../integrations/cowork/SETUP.md) | Step-by-step setup of the Claude/Cowork bridge (install skills, configure the data dir, choose one run owner). |

## Architecture

| Doc | What it covers |
|-----|----------------|
| [adr-001-web-pipeline-bridge.md](adr-001-web-pipeline-bridge.md) | ADR: the FastAPI bridge between the Python pipeline and the Next.js console. |
| [adr-002-applications-rich-tracking.md](adr-002-applications-rich-tracking.md) | ADR: rich application tracking (status table + append-only timeline). |
| [design-data-dashboard-scoring.md](design-data-dashboard-scoring.md) | Data model and scoring architecture (pluggable backends). |
| [assets/](assets/) | Diagrams and screenshots referenced by the docs. |
