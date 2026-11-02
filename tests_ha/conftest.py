"""Home Assistant test fixtures. All network calls must be mocked."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield
