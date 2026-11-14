"""API tests against the real processed data (skipped if the pipeline has not been run)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"
pytestmark = pytest.mark.skipif(not (PROCESSED / "fields_summary.json").exists(),
                                reason="run `python tasks.py data` first")


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def field_id(client):
    return client.get("/api/fields").json()["pilot"]["features"][0]["properties"]["field_id"]


def test_meta_lists_priorities_sources_and_glossary(client):
    m = client.get("/api/meta").json()
    assert len(m["criteria"]) == 8 and sum(c["default_weight"] for c in m["criteria"]) == 100
    assert {t["id"] for t in m["glossary"]["terms"]} >= {"et", "ndvi", "sm", "frost", "balance", "satellite"}
    assert "does not replace" in m["glossary"]["disclaimer"]
    assert m["any_demo_data"] is False
    assert any(s["source"] == "nasa_power" and s["status"] == "ok" for s in m["sources"])
    for s in m["sources"]:
        if s["status"] == "failed":
            assert s["action_needed"], f"{s['source']} failed without telling the user what to do"


def test_fields_are_real_polygons_inside_the_pilot_box(client):
    data = client.get("/api/fields").json()
    feats = data["pilot"]["features"]
    assert 5 <= len(feats) <= 20
    w, s, e, n = client.get("/api/meta").json()["pilot"]["bbox"]
    for f in feats:
        p = f["properties"]
        assert w < p["lon"] < e and s < p["lat"] < n and 15 < p["area_ha"] < 90
        assert p["is_demo_data"] is False and "not a surveyed boundary" in p["boundary_source"]


def test_evidence_panels_have_the_required_indicators(client, field_id):
    ev = client.get(f"/api/fields/{field_id}/evidence").json()
    assert {"climate", "water", "greenness", "history", "soil", "terrain", "groundwater",
            "vulnerability", "bare"} <= set(ev)
    annual = ev["climate"]["annual"]
    assert len(annual) >= 30 and {"tmean", "precip", "et0", "days_over_32", "frost_free_days",
                                  "heavy_rain_days"} <= set(annual[0])
    assert len(ev["vulnerability"]["most_vulnerable"]) == 2
    assert len(ev["history"]) >= 8
    assert client.get("/api/fields/NOPE/evidence").status_code == 404


def test_score_returns_three_or_more_strategies_with_full_explanations(client, field_id):
    r = client.post("/api/score", json={"field_id": field_id}).json()
    assert len(r["strategies"]) >= 3 and sum(s["is_existing"] for s in r["strategies"]) == 1
    for s in r["strategies"]:
        for key in ("why", "benefits", "info_gaps", "risks", "verify", "confidence", "criteria", "sequence"):
            assert s[key], f"{s['id']} is missing {key}"
        assert all(c["panel"] and c["inputs"] for c in s["criteria"].values())
    assert r["statement"].startswith("Under your priorities")


def test_sliders_and_scenarios_change_the_result(client, field_id):
    post = lambda **kw: client.post("/api/score", json={"field_id": field_id, **kw}).json()  # noqa: E731
    water = post(weights={"water": 100})
    income = post(weights={"income": 100})
    assert water["ranking"] != income["ranking"]
    base = post()
    hot = post(scenario={"rain_pct": -30, "temp_c": 3})
    need = lambda r: {s["id"]: s["water"]["irrigation_mm"] for s in r["strategies"]}  # noqa: E731
    assert all(need(hot)[k] > v for k, v in need(base).items())
    assert client.post("/api/score", json={"field_id": field_id, "scenario": {"temp_c": 40}}).status_code == 422
    assert client.post("/api/score", json={"field_id": "NOPE"}).status_code == 404


def test_a_drawn_field_is_scored_from_local_data_and_flags_what_is_missing(client):
    lon, lat, d = -116.0155, 39.6400, 0.002
    geom = {"type": "Polygon", "coordinates": [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d],
                                                [lon - d, lat + d], [lon - d, lat - d]]]}
    r = client.post("/api/custom-field", json={"geometry": geom, "name": "Test square"})
    assert r.status_code == 200, r.text
    fid = r.json()["feature"]["properties"]["field_id"]
    assert fid.startswith("CUSTOM-") and r.json()["feature"]["properties"]["sources"]["openet"] is False
    s = client.post("/api/score", json={"field_id": fid}).json()
    existing = next(x for x in s["strategies"] if x["is_existing"])
    assert any("No OpenET record" in g for g in existing["info_gaps"])
    assert existing["criteria"]["water"]["confidence"] == "low"

    far = {"type": "Polygon", "coordinates": [[[-100, 40], [-99.99, 40], [-99.99, 40.01], [-100, 40.01], [-100, 40]]]}
    bad = client.post("/api/custom-field", json={"geometry": far})
    assert bad.status_code == 422 and "pilot area" in bad.json()["detail"]
