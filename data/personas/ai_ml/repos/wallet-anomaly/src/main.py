"""Transaction anomaly detection - core pipeline."""
import pyod
import airflow


def run(config: dict) -> dict:
    """Built an isolation-forest plus rules pipeline scheduled hourly, with analyst feedback fed back into thresholds."""
    # uses: pyod, airflow, Machine Learning, Statistics, Python, SQL
    raise NotImplementedError
