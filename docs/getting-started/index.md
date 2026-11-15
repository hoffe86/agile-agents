# Getting started

Three steps take a repository from nothing to a first reviewed change:

1. [**Install**](installation.md) the `agile-agents-core` plugin from the
   `agentic-universe` marketplace.
2. [**Bootstrap**](bootstrap.md) the repository with `bootstrapper`, which writes
   the approved `.github/solution-profile.yaml`.
3. [**Run a first requirement**](first-requirement.md) with `dev-lead` and approve
   its plan.

Run them in order: when the profile is missing or incomplete, `dev-lead` first
hands intake to `bootstrapper`, and stops if any of the six required fields is
still empty. Bootstrapping first keeps that setup out of your first delivery run.

The optional [Solution profile canvas](../README.md#solution-profile-canvas) lets
hosts with canvas support edit the profile with validation and an explicit save.
