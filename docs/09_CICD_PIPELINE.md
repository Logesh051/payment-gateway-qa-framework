# Basic GitHub Actions Test Workflow

The workflow at `.github/workflows/qa-pipeline.yml` checks out the repository, sets up Python 3.12, installs requirements, and runs `pytest` when code is pushed to the simplification branch or a pull request is opened against main. It runs tests only; it does not deploy the simulator.
