import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import ml.registry as registry


def test_load_latest_returns_none_when_nothing_trained(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "ARTIFACTS_DIR", tmp_path / "artifacts")
    payload, metadata = registry.load_latest("nonexistent_model")
    assert payload is None
    assert metadata is None


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "ARTIFACTS_DIR", tmp_path / "artifacts")
    data_file = tmp_path / "training.parquet"
    data_file.write_bytes(b"fake training data")

    version = registry.save_artifact(
        "eta",
        payload={"models": "pretend-models"},
        metrics={"coverage": 0.91},
        calibrated=True,
        training_data_path=data_file,
    )
    assert version

    payload, metadata = registry.load_latest("eta")
    assert payload == {"models": "pretend-models"}
    assert metadata.calibrated is True
    assert metadata.metrics == {"coverage": 0.91}
    assert metadata.version == version


def test_save_twice_latest_points_to_second(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "ARTIFACTS_DIR", tmp_path / "artifacts")
    data_file = tmp_path / "training.parquet"
    data_file.write_bytes(b"v1")
    registry.save_artifact("eta", {"v": 1}, {}, calibrated=False, training_data_path=data_file)

    data_file.write_bytes(b"v2")
    registry.save_artifact("eta", {"v": 2}, {}, calibrated=True, training_data_path=data_file)

    payload, metadata = registry.load_latest("eta")
    assert payload == {"v": 2}
    assert metadata.calibrated is True


def test_load_latest_handles_corrupted_metadata_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "ARTIFACTS_DIR", tmp_path / "artifacts")
    model_dir = tmp_path / "artifacts" / "eta" / "broken"
    model_dir.mkdir(parents=True)
    (model_dir / "model.pkl").write_bytes(b"not a real pickle")
    (tmp_path / "artifacts" / "eta" / "latest.json").write_text('{"version": "broken"}')

    payload, metadata = registry.load_latest("eta")
    assert payload is None
    assert metadata is None
