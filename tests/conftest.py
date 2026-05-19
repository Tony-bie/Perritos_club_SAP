import os
import pytest


def pytest_collection_modifyitems(config, items):
    """Skip tests marked with 'hana' unless RUN_HANA_TESTS env var is 'true'."""
    run_hana = os.getenv("RUN_HANA_TESTS", "false").lower() == "true"
    if run_hana:
        return

    skip_hana = pytest.mark.skip(reason="HANA tests disabled (set RUN_HANA_TESTS=true to enable)")
    for item in list(items):
        if 'hana' in item.keywords:
            item.add_marker(skip_hana)
