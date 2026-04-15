# Cubelake

Data engineering platform for collecting, processing, and analyzing App Store data.

## Architecture

The project is organized as a monorepo with the following services:

| Service | Description |
|---------|-------------|
| **appstore-core** | Shared library with common models, utilities, and configurations |
| **appstore-dags** | Airflow DAGs for orchestrating data pipelines |
| **ingestion-apple-rss** | Ingestion service for Apple RSS feeds |
| **ingestion-apple-itunes** | Ingestion service for Apple iTunes API |
| **infra** | Infrastructure as Code (Terraform, Docker, CI/CD) |

## Tech Stack

- **Language:** Python 3.13+
- **Package Manager:** [uv](https://github.com/astral-sh/uv) (workspace mode)
- **Orchestration:** Apache Airflow
- **Infrastructure:** Terraform, Docker

## Getting Started

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/Cubelake/cubelake.git

# Install dependencies
uv sync
```

## License

This project is proprietary. See [LICENSE](LICENSE) for details.
