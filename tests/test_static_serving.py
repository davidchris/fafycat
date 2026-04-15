"""Parity tests for ``/static/*`` URL routing.

These assertions are the green light for the static-files phase of the
packaging refactor: they must pass both pre- and post-refactor.
"""

import pytest


@pytest.mark.parametrize(
    ("path", "expected_substring"),
    [
        ("/static/css/theme.css", ":root"),
        ("/static/css/components.css", "/*"),
        ("/static/js/main.js", "function"),
        ("/static/js/analytics.js", "Analytics"),
        ("/static/favicon.svg", "<svg"),
    ],
)
def test_static_asset_served(test_client, path: str, expected_substring: str) -> None:
    resp = test_client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"
    assert expected_substring in resp.text, f"{path} missing {expected_substring!r}"


def test_static_missing_asset_returns_404(test_client) -> None:
    """The /static mount is a file server, not a catch-all."""
    resp = test_client.get("/static/does-not-exist.css")
    assert resp.status_code == 404
