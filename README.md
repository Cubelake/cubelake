# Cubelake

> Data engineering platform for collecting, processing, and analyzing Apple App Store data.

![Python](https://img.shields.io/badge/Python-3.13+-3776AB?logo=python&logoColor=white)
![Airflow](https://img.shields.io/badge/Apache_Airflow-3.2+-017CEE?logo=apacheairflow&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-1.10+-FF694B?logo=dbt&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-1.2+-FFF000?logo=duckdb&logoColor=black)
![Azure](https://img.shields.io/badge/Azure_ADLS_Gen2-0078D4?logo=microsoftazure&logoColor=white)
![License](https://img.shields.io/badge/License-Proprietary-red)

Cubelake implements a **medallion architecture** (bronze → silver → gold) with automated daily ingestion from the Apple RSS Feeds and iTunes API, orchestrated via Apache Airflow and transformed through dbt on top of DuckDB. All data lands in Azure Data Lake Storage Gen2.

---

## Table of Contents

- [Architecture](#architecture)
- [Components](#components)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Install](#install)
  - [Environment Variables](#environment-variables)
- [Running the Platform](#running-the-platform)
  - [Airflow (Docker)](#airflow-docker)
  - [Airflow (standalone)](#airflow-standalone)
  - [dbt manually](#dbt-manually)
- [Project Internals](#project-internals)
- [Repository Structure](#repository-structure)
- [License](#license)

---

## Architecture

```
Apple RSS Feeds
      │ @daily
      ▼
[bronze_top_daily]
      │ BRONZE_APPSTORE_RSS
      ▼
[silver_transform_top_daily]
      │ SILVER_APPSTORE_RSS ──────────────────────────────────────────────┐
      ▼                                                                    │
[bronze_itunes_lookup_daily]                                               │
  reads silver RSS to discover app IDs → fetches iTunes metadata          │
      │ BRONZE_APPSTORE_ITUNES                                             │
      ▼                                                                    │
[silver_transform_itunes_lookup_daily]                                     │
      │ SILVER_APPSTORE_ITUNES                                             │
      └──────────────────────────────────┬────────────────────────────────┘
                                         │ schedule=[SILVER_APPSTORE_RSS,
                                         │           SILVER_APPSTORE_ITUNES]
                                         ▼
                          [silver_transform_appstore_apps_daily]
                            joins RSS + iTunes for matching snapshot_dates
                                         │ SILVER_APPSTORE_APPS
                                         ▼
                               [gold_transform_daily]
                                 fct_top_apps + fct_genre_stats
                                         │ GOLD_APPSTORE_DAILY
                                         ▼
                              [gold_transform_dim_apps]
                                 gold_dim_apps (SCD Type 1)
                                         │ GOLD_DIM_APPS

[gold_transform_biweekly]  0 4 1,15 * *  →  fct_app_rank_history (incremental)
[gold_transform_monthly]   0 5 1   * *   →  fct_app_rank_history (full refresh)
```

### DAG Flow

| DAG | Schedule | Trigger | Emits | dbt selector |
|-----|----------|---------|-------|--------------|
| `bronze_top_daily` | `@daily` | — | `BRONZE_APPSTORE_RSS` | — |
| `silver_transform_top_daily` | asset | `BRONZE_APPSTORE_RSS` | `SILVER_APPSTORE_RSS` | `+silver_top_apps` |
| `bronze_itunes_lookup_daily` | asset | `SILVER_APPSTORE_RSS` | `BRONZE_APPSTORE_ITUNES` | — |
| `silver_transform_itunes_lookup_daily` | asset | `BRONZE_APPSTORE_ITUNES` | `SILVER_APPSTORE_ITUNES` | `+silver_itunes_app_details` |
| `silver_transform_appstore_apps_daily` | asset | `SILVER_APPSTORE_RSS` or `SILVER_APPSTORE_ITUNES`* | `SILVER_APPSTORE_APPS` | `silver_appstore_apps` |
| `gold_transform_daily` | asset | `SILVER_APPSTORE_APPS` | `GOLD_APPSTORE_DAILY` | `gold_fct_top_apps gold_fct_genre_stats` |
| `gold_transform_dim_apps` | asset | `GOLD_APPSTORE_DAILY` | `GOLD_DIM_APPS` | `gold_dim_apps` |
| `gold_transform_biweekly` | `0 4 1,15 * *` | — | `GOLD_FCT_RANK_HISTORY` | `gold_fct_app_rank_history` |
| `gold_transform_monthly` | `0 5 1 * *` | — | — | `gold_fct_app_rank_history --full-refresh` |

> \* `silver_transform_appstore_apps_daily` is declared with `schedule=[SILVER_APPSTORE_RSS, SILVER_APPSTORE_ITUNES]`, so Airflow triggers it when either asset is updated. The `discover_missing_snapshots` task then computes the **intersection** of dates present in both silver RSS and silver iTunes, so a snapshot is only processed when both sources are ready.

> `bronze_itunes_lookup_daily` triggers on `SILVER_APPSTORE_RSS`, not on the bronze RSS directly. It queries the silver RSS Parquet to discover which app IDs charted that day, then calls the iTunes lookup API for those IDs.

> On the 1st of each month, both `gold_transform_biweekly` and `gold_transform_monthly` run. The biweekly is an incremental append; the monthly is a full recompute of the entire rank history table.

Bronze snapshots use Hive-style partitioning (`snapshot_date=YYYY-MM-DD/`). Silver DAGs use Airflow dynamic task expansion (`.expand()`, up to 4 concurrent tasks) to parallelize dbt runs per unprocessed snapshot.

### dbt Models

```
models/
├── staging/
│   ├── apple_rss/stg_bronze_top_apps.sql          # Unnest + clean RSS JSON
│   └── apple_itunes/stg_bronze_itunes.sql         # Parse iTunes JSON
└── marts/
    ├── apple_rss/silver_top_apps.sql              # Top-apps table (Parquet, per snapshot)
    ├── apple_itunes/silver_itunes_app_details.sql # App metadata (Parquet, per snapshot)
    ├── appstore/silver_appstore_apps.sql          # RSS + iTunes joined (Parquet, per snapshot)
    └── gold/
        ├── gold_fct_top_apps.sql                  # Daily chart positions fact
        ├── gold_fct_genre_stats.sql               # Daily genre aggregates fact
        ├── gold_dim_apps.sql                      # App dimension (SCD Type 1, single file)
        └── gold_fct_app_rank_history.sql          # All-time rank history (full recompute)
```

---

## Components

The project is a monorepo of git submodules, each independently versioned:

| Submodule | Description |
|-----------|-------------|
| **appstore-core** | Shared library — `BaseIngestor`, Azure storage abstractions, Pydantic data models |
| **appstore-dags** | Airflow DAGs — orchestrates bronze ingestion, silver & gold transformations |
| **ingestion-apple-rss** | Async ingestion service for Apple RSS top-apps feeds (GBR, USA, JPN, …) |
| **ingestion-apple-itunes** | Async ingestion service for the iTunes lookup API (app metadata) |
| **appstore-transform** | dbt project — SQL models for all three medallion layers |
| **infra** | Infrastructure — Docker Compose, Dockerfiles, GitHub Actions CI/CD |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.13+ |
| Package manager | [uv](https://github.com/astral-sh/uv) (workspace mode) |
| Orchestration | Apache Airflow 3.2+ |
| Transformation | dbt-duckdb 1.10+ |
| In-process compute | DuckDB 1.2+ |
| Cloud storage | Azure Data Lake Storage Gen2 |
| HTTP client | httpx (async) |
| Data validation | Pydantic 2.x |
| Logging | loguru |
| Containerization | Docker, Docker Compose |
| Metadata DB | PostgreSQL 16 (Airflow) |
| CI/CD | GitHub Actions |

---

## Getting Started

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker & Docker Compose (for the full Airflow stack)
- Azure Data Lake Storage Gen2 account with SAS tokens for bronze, silver, and gold containers

### Install

```bash
git clone --recurse-submodules https://github.com/Cubelake/cubelake.git
cd cubelake
uv sync
```

If you already cloned without submodules:

```bash
git submodule update --init --recursive
```

### Environment Variables

Create `.env` files from the templates inside `infra/<service>/`. Minimum required variables:

```bash
# Azure Storage account URL
ACCOUNT_URL=https://<storage_account>.dfs.core.windows.net

# Bronze container tokens
BRONZE_SAS_TOKEN=<sas_token>
BRONZE_RSS_SAS_TOKEN=<sas_token>
BRONZE_ITUNES_SAS_TOKEN=<sas_token>

# Silver container tokens
SILVER_SAS_TOKEN=<sas_token>
SILVER_RSS_SAS_TOKEN=<sas_token>
SILVER_ITUNES_SAS_TOKEN=<sas_token>

# Gold container token
GOLD_SAS_TOKEN=<sas_token>

# Absolute path to the dbt project (used by Airflow silver/gold DAGs)
DBT_PROJECT_DIR=/path/to/appstore-transform
```

---

## Running the Platform

### Airflow (Docker)

The full Airflow stack (API server, scheduler, DAG processor, triggerer, PostgreSQL) is defined in `infra/appstore-dags/docker-compose.yml`.

```bash
cd infra/appstore-dags

# First-time setup — initialise DB and create admin user
docker compose up airflow-init

# Start all services
docker compose up -d

# Tail logs
docker compose logs -f
```

Airflow UI is available at **http://localhost:8080** (default credentials in `.env`).

### Airflow (standalone)

For local development without Docker:

```bash
export AIRFLOW_HOME=/opt/airflow
export AIRFLOW__CORE__DAGS_FOLDER=$(pwd)/appstore-dags/dags
uv run airflow standalone
```

### dbt manually

```bash
# Verify DuckDB connection and ADLS secrets
uv run --env-file .env dbt debug --project-dir appstore-transform

# Run all models
uv run --env-file .env dbt run --project-dir appstore-transform

# Run models for a specific snapshot date
uv run --env-file .env dbt run --project-dir appstore-transform \
  --vars '{"snapshot_date": "2025-01-01"}'

# Run only gold models
uv run --env-file .env dbt run --project-dir appstore-transform \
  --select marts/gold

# Run dbt tests
uv run --env-file .env dbt test --project-dir appstore-transform
```

---

## Project Internals

### BaseIngestor

All ingestion services extend `appstore-core`'s `BaseIngestor`, which provides:

- Async HTTP fetching via `httpx`
- Configurable `batch_size`, `timeout`, and `max_retries`
- JSON serialisation and ADLS write logic

Default config: `batch_size=10`, `timeout=15s`, `max_retries=2`.

### Token Model Pattern

Storage access is encapsulated in Pydantic models that auto-load SAS credentials from environment variables and initialize a DuckDB connection pointed at ADLS on instantiation. Silver DAGs use these tokens to query ADLS directly (via DuckDB) to discover unprocessed bronze snapshots before launching dbt.

### Airflow Asset Lineage

Bronze DAGs emit Airflow Assets on completion. Silver DAGs declare `schedule=[BRONZE_ASSET]`, so they trigger automatically and data lineage is tracked in the Airflow UI without any manual wiring.

### dbt Azure Secrets

On every `dbt run`, on-run-start hooks create named DuckDB secrets for each ADLS container:

| Secret | Scope |
|--------|-------|
| `bronze_secret` | `azure://bronze` |
| `silver_secret` | `azure://silver` |
| `silver_rss_secret` | `azure://silver/appstore_rss` |
| `silver_itunes_secret` | `azure://silver/appstore_itunes` |
| `gold_secret` | `azure://gold` |

---

## Repository Structure

```
cubelake/
├── appstore-core/           # Shared library (submodule)
├── appstore-dags/           # Airflow DAGs (submodule)
├── appstore-transform/      # dbt project (submodule)
├── ingestion-apple-rss/     # RSS ingestion service (submodule)
├── ingestion-apple-itunes/  # iTunes ingestion service (submodule)
├── infra/                   # Docker, CI/CD (submodule)
├── pyproject.toml           # uv workspace root
├── uv.lock
└── .gitmodules
```

---

## License

This project is proprietary. All rights reserved. See [LICENSE](LICENSE) for details.
