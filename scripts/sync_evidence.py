#!/usr/bin/env python3
"""
Syncs gold layer data from Azure ADLS to a local DuckDB file for Evidence.dev.

Usage:
    uv run python scripts/sync_evidence.py
    uv run python scripts/sync_evidence.py --days 60
"""
import argparse
import os
import platform
import sys
from pathlib import Path

import duckdb

# Load env vars from infra/.env if not already set
_env_file = Path(__file__).parent.parent / "infra" / "appstore-dags" / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

from common.storage.azure_tokens import GoldToken  # noqa: E402

EVIDENCE_DB = Path(
    os.environ.get(
        "EVIDENCE_DB",
        str(Path(__file__).parent.parent / "evidence-app" / "sources" / "gold" / "gold.duckdb"),
    )
)

TABLES = {
    "gold_daily":    "azure://gold/appstore/daily/snapshot_date=*/worldwide.parquet",
    "gold_weekly":   "azure://gold/appstore/weekly/snapshot_date=*/worldwide.parquet",
    "gold_biweekly": "azure://gold/appstore/biweekly/snapshot_date=*/worldwide.parquet",
    "gold_monthly":  "azure://gold/appstore/monthly/snapshot_date=*/worldwide.parquet",
}


def _init_connection(con: duckdb.DuckDBPyConnection, gold: GoldToken) -> None:
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL azure; LOAD azure;")
    if platform.system() == "Linux":
        con.execute("SET azure_transport_option_type = 'curl';")
        con.execute("SET ca_cert_file = '/etc/ssl/certs/ca-certificates.crt';")
    con.execute(f"SET azure_storage_connection_string = '{gold.connection_string}';")


def sync(days: int = 90) -> None:
    gold = GoldToken()
    EVIDENCE_DB.parent.mkdir(parents=True, exist_ok=True)

    print(f"Syncing last {days} days of gold data → {EVIDENCE_DB}")

    with duckdb.connect(str(EVIDENCE_DB)) as con:
        _init_connection(con, gold)

        for table, path in TABLES.items():
            print(f"  {table}...", end=" ", flush=True)
            con.execute(f"""
                CREATE OR REPLACE TABLE {table} AS
                SELECT *
                FROM read_parquet('{path}')
                WHERE snapshot_date >= CURRENT_DATE - INTERVAL '{days} days'
                ORDER BY snapshot_date DESC
            """)
            count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            dates = con.execute(
                f"SELECT COUNT(DISTINCT snapshot_date) FROM {table}"
            ).fetchone()[0]
            print(f"{count:,} rows across {dates} snapshots")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Days of history to sync")
    args = parser.parse_args()
    sync(days=args.days)
