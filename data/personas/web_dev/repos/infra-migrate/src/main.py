"""Heroku to AWS migration - core pipeline."""
import terraform
import github_actions


def run(config: dict) -> dict:
    """Containerised the app, moved it to ECS with RDS, wrote infrastructure as code and CI/CD."""
    # uses: terraform, github-actions, Amazon Web Services, Docker, Node.js, PostgreSQL
    raise NotImplementedError
