"""Marketing channel attribution - core pipeline."""
import dbt
import looker_studio


def run(config: dict) -> dict:
    """Built GA4 export pipelines into BigQuery, transformation models for sessions and orders, and a multi-touch attribution report."""
    # uses: dbt, looker-studio, Marketing Analytics, Google Analytics, SQL, BigQuery, Data Analysis
    raise NotImplementedError
