Integration test notes
======================

HANA
----

- HANA integration tests require a reachable SAP HANA instance and the `hdbcli` driver.
- To run HANA tests locally, set these environment variables:
  - `HANA_HOST` - host
  - `HANA_PORT` - port
  - `HANA_USER` - user
  - `HANA_PASSWORD` - password
  - `HANA_SCHEMA` - schema name
  - `RUN_HANA_TESTS=true` - enable pytest to include `hana` marked tests

Running integration tests
-------------------------

1. Ensure HANA credentials are available and `hdbcli` is installed in the environment.
2. Enable HANA tests by exporting `RUN_HANA_TESTS=true`.
3. Run pytest normally:

```bash
RUN_HANA_TESTS=true python -m pytest -q
```

CI
--

- The included GitHub Actions workflow runs linters, `mypy` (non-blocking) and unit tests excluding HANA.
- To run HANA tests on CI, add secure secrets for HANA connection and set `RUN_HANA_TESTS=true` in the workflow.
