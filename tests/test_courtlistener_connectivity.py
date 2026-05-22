"""Estate Atlas: SD-MCP — CourtListener API connectivity test.

Confirms that the CourtListener public search API is reachable and returns
a plausible JSON response for a simple San Diego land-use query.

No auth token is required for this test — CourtListener allows unauthenticated
GET requests at low rate limits. The test exercises the exact same code path
that fetch_court_rulings.py uses.

Run with:
    pytest tests/test_courtlistener_connectivity.py -v
    pytest tests/test_courtlistener_connectivity.py -v -m live  # skipped in CI by default

The test is marked `live` so it can be skipped in offline / CI environments:
    pytest -m "not live"
"""
from __future__ import annotations

import pytest

# Mark the whole module as a "live" (network) test so CI can skip it.
pytestmark = pytest.mark.live


def _import_client():
    """Import the client from the pipeline module, handling missing deps gracefully."""
    try:
        import httpx  # noqa: F401
    except ImportError:
        pytest.skip("httpx not installed")

    # The pipeline lives in the parent repo, not inside mcp-server.
    # Add the pipelines root to sys.path so we can import directly.
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]  # david/
    pipelines_root = repo_root / "pipelines"
    if str(pipelines_root) not in sys.path:
        sys.path.insert(0, str(pipelines_root))

    try:
        from scripts.ingestion.fetch_court_rulings import CourtListenerClient
        return CourtListenerClient
    except ImportError as exc:
        pytest.skip(f"Could not import fetch_court_rulings: {exc}")


def test_courtlistener_api_reachable():
    """Confirm that the CourtListener search endpoint returns HTTP 200 and
    a JSON body with a 'count' field for a simple query."""
    CourtListenerClient = _import_client()

    with CourtListenerClient(api_token=None) as client:  # unauthenticated — public API
        ok = client.ping()

    assert ok, (
        "CourtListener ping failed. "
        "Check network connectivity or https://www.courtlistener.com/api/rest/v4/search/"
    )


def test_search_returns_results_for_san_diego():
    """Confirm that a San Diego land-use search returns at least one result
    and that each result has the expected top-level fields."""
    CourtListenerClient = _import_client()

    with CourtListenerClient(api_token=None) as client:
        results = []
        for raw in client.search_opinions(
            query='"City of San Diego" zoning',
            courts=["casd", "calctapp4d"],
            page_size=5,
        ):
            results.append(raw)
            break  # Only need the first page to confirm connectivity

    assert len(results) > 0, (
        "CourtListener returned zero results for 'City of San Diego zoning' "
        "on casd + calctapp4d. Possible causes: changed API, rate limit, "
        "or courts removed from corpus."
    )

    first = results[0]
    # These fields must be present in every opinion search result
    for expected_field in ("caseName", "absolute_url"):
        assert expected_field in first or first.get("case_name"), (
            f"Expected field '{expected_field}' missing from result: {list(first.keys())}"
        )


def test_parse_opinion_result_handles_minimal_input():
    """Unit test: parse_opinion_result should return None on empty dict
    and a valid object on minimal populated dict — no network required."""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root / "pipelines"))

    try:
        from scripts.ingestion.fetch_court_rulings import parse_opinion_result, CourtListenerOpinion
    except ImportError as exc:
        pytest.skip(f"Could not import: {exc}")

    # Empty dict → None
    assert parse_opinion_result({}) is None

    # Minimal valid dict
    raw = {
        "cluster_id": 99999,
        "caseName": "City of San Diego v. Test Owner",
        "court_id": "casd",
        "dateFiled": "2024-01-15",
        "absolute_url": "/opinion/99999/test/",
        "id": 12345,
    }
    result = parse_opinion_result(raw)
    assert result is not None
    assert isinstance(result, CourtListenerOpinion)
    assert result.cluster_id == 99999
    assert result.court_id == "casd"
    assert "San Diego" in result.case_name


def test_tag_land_use_detects_ceqa():
    """Unit test: land-use tagger identifies CEQA keywords — no network required."""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root / "pipelines"))

    try:
        from scripts.ingestion.fetch_court_rulings import tag_land_use
    except ImportError as exc:
        pytest.skip(f"Could not import: {exc}")

    text = (
        "The project triggers a full Environmental Impact Report under CEQA. "
        "The applicant failed to obtain the required conditional use permit. "
        "The setback requirements were not met per the zoning code."
    )
    tags = tag_land_use(text)
    assert "CEQA" in tags
    assert "zoning" in tags
    assert "permit" in tags
    assert "setback" in tags
