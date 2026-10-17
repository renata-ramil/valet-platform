from app.models import Role
from app.whatif import PRECOMPUTED_GRID, run_whatif

from tests.conftest import make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.json()["csrf_token"]


def test_run_whatif_live_returns_a_point_and_interval_for_each_metric():
    result = run_whatif(6, 1.0)
    assert result["source"] == "live_simulation"
    assert result["seeds"] == 10
    for metric in ("on_time_rate", "wait_p95_seconds", "relocations_per_retrieval"):
        assert metric in result
        assert f"{metric}_ci" in result
        low, high = result[f"{metric}_ci"]
        assert low <= result[metric] <= high


def test_run_whatif_falls_back_to_precomputed_grid_when_simulation_unavailable(monkeypatch):
    import app.whatif as whatif_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(whatif_module, "_run_live", _boom)
    result = run_whatif(6, 1.0)
    assert result["source"] == "precomputed_grid"
    assert result["on_time_rate"] == PRECOMPUTED_GRID[(6, 1.0)]["on_time_rate"]
    assert "note" in result


def test_manager_what_if_endpoint(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "manager@example.com")
    csrf = _login(client, "manager@example.com")

    response = client.get(
        "/manager/what-if", params={"valet_count": 6, "demand_multiplier": 1.0},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] in ("live_simulation", "precomputed_grid")
    assert 0 <= body["on_time_rate"] <= 1


def test_manager_what_if_rejects_out_of_range_inputs(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "manager2@example.com")
    csrf = _login(client, "manager2@example.com")

    response = client.get(
        "/manager/what-if", params={"valet_count": 100, "demand_multiplier": 1.0},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 400
