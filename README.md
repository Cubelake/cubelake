# Cubelake

Data engineering platform for collecting, processing, and analyzing Apple App Store data. Implements a medallion architecture (bronze → silver) with automated daily ingestion via Airflow and DuckDB-powered transformations through dbt.

## Architecture

```
Apple RSS Feeds + iTunes API
          ↓
    [Bronze Layer]          Raw JSON snapshots in Azure ADLS
          ↓
  [dbt + DuckDB]            Flatten, clean, enrich
          ↓
    [Silver Layer]          Parquet files in Azure ADLS
```

The project is a monorepo of git submodules, each independently versioned:

| Service | Description |
|---------|-------------|
| **appstore-core** | Shared library — base ingestor, Azure storage abstractions, Pydantic models |
| **appstore-dags** | Airflow DAGs — orchestrates bronze ingestion and silver transformations |
| **ingestion-apple-rss** | Ingestion service for Apple RSS top-apps feeds |
| **ingestion-apple-itunes** | Ingestion service for Apple iTunes lookup API |
| **appstore-transform** | dbt project — SQL models for bronze→silver transformation |
| **infra** | Infrastructure as Code (Terraform, Docker, CI/CD) |

### Data Flow

```
[Airflow: bronze DAGs]
  ├── apple_top_daily     → fetch RSS feeds → write JSON → ADLS bronze/rss/
  └── apple_lookup_daily  → fetch iTunes API → write JSON → ADLS bronze/itunes/

[Airflow: silver DAGs]  (triggered by bronze asset completion)
  ├── transform_top_daily   → discover unprocessed snapshots → dbt run → ADLS silver/rss/
  └── transform_lookup_daily→ discover unprocessed snapshots → dbt run → ADLS silver/itunes/
```

Bronze snapshots are partitioned by `snapshot_date`. Silver DAGs use Airflow dynamic task expansion to parallelize transformations per snapshot.

### dbt Models

```
models/
├── staging/
│   ├── apple_rss/stg_bronze_top_apps.sql      # Unnest + clean RSS JSON
│   └── apple_itunes/stg_bronze_itunes.sql     # Parse iTunes JSON
└── marts/
    ├── apple_rss/silver_top_apps.sql           # Final top-apps table (Parquet)
    └── apple_itunes/silver_itunes_app_details.sql  # Final app details (Parquet)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.13+ |
| Package manager | [uv](https://github.com/astral-sh/uv) (workspace mode) |
| Orchestration | Apache Airflow 3.2+ |
| Transformation | dbt-duckdb |
| In-process compute | DuckDB 1.2+ |
| Cloud storage | Azure Data Lake Storage Gen2 (ADLS) |
| HTTP client | httpx (async) |
| Data validation | Pydantic 2.x |
| Logging | loguru |
| Infrastructure | Terraform, Docker |

## Getting Started

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)
- Access to an Azure Data Lake Storage Gen2 account with SAS tokens

### Install

```bash
git clone --recurse-submodules https://github.com/Cubelake/cubelake.git
cd cubelake
uv sync
```

If you cloned without submodules:

```bash
git submodule update --init --recursive
```

### Environment Variables

Copy and populate the required secrets:

```bash
# Azure Storage
ACCOUNT_URL=https://<storage_account>.dfs.core.windows.net

# Bronze layer tokens
BRONZE_SAS_TOKEN=<sas_token>
BRONZE_RSS_SAS_TOKEN=<sas_token>
BRONZE_ITUNES_SAS_TOKEN=<sas_token>

# Silver layer tokens
SILVER_SAS_TOKEN=<sas_token>
SILVER_RSS_SAS_TOKEN=<sas_token>
SILVER_ITUNES_SAS_TOKEN=<sas_token>

# dbt project location (used by Airflow silver DAGs)
DBT_PROJECT_DIR=/path/to/appstore-transform
```

### Run Airflow

```bash
export AIRFLOW_HOME=/opt/airflow
uv run airflow standalone
```

DAGs are discovered automatically from `appstore-dags/dags/`. Set `AIRFLOW__CORE__DAGS_FOLDER` if needed.

### Run dbt manually

```bash
# Debug connection
uv run --env-file .env dbt debug --project-dir appstore-transform

# Run all models
uv run --env-file .env dbt run --project-dir appstore-transform

# Run for a specific snapshot date
uv run --env-file .env dbt run --project-dir appstore-transform \
  --vars '{"snapshot_date": "2025-01-01"}'
```

## Project Internals

### BaseIngestor

All ingestion services extend `appstore-core`'s `BaseIngestor`, which provides:

- Async HTTP fetching via `httpx`
- Configurable batch size, timeout, and retry count
- JSON serialization and ADLS write logic

Default config: `batch_size=10`, `timeout=15s`, `retries=2`.

### Token Model Pattern

Storage tokens are Pydantic models that auto-load SAS credentials from environment variables and initialize a DuckDB connection pointed at ADLS on instantiation. Silver DAGs use DuckDB through these tokens to discover unprocessed bronze snapshots before running dbt.

### Airflow Asset Lineage

Bronze DAGs emit Airflow Assets on completion. Silver DAGs declare `schedule=[BRONZE_ASSET]` so they trigger automatically and data lineage is tracked in the Airflow UI without manual wiring.

## License

This project is proprietary. See [LICENSE](LICENSE) for details.
