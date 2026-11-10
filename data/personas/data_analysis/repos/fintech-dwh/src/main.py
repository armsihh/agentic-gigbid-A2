"""Analytics warehouse for a startup - core pipeline."""
import dbt
import airbyte


def run(config: dict) -> dict:
    """Set up ingestion from the production database and payment provider, built tested data models and a metrics layer."""
    # uses: dbt, airbyte, SQL, Data Modeling, BigQuery, Business Intelligence
    raise NotImplementedError
