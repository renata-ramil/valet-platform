import hashlib
import json
import pickle
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


@dataclass
class ArtifactMetadata:
    model_type: str
    version: str
    created_at: str
    training_data_hash: str
    metrics: dict
    calibrated: bool


def _hash_file(path: Path) -> str:
    if not path.exists():
        return "unknown"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def save_artifact(
    model_type: str,
    payload: object,
    metrics: dict,
    calibrated: bool,
    training_data_path: Path,
) -> str:
    """Saves a pickled payload plus metadata.json into a versioned folder, and
    updates a latest.json pointer the registry's loader reads."""
    version = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    dir_path = ARTIFACTS_DIR / model_type / version
    dir_path.mkdir(parents=True, exist_ok=True)

    with open(dir_path / "model.pkl", "wb") as f:
        pickle.dump(payload, f)

    metadata = ArtifactMetadata(
        model_type=model_type,
        version=version,
        created_at=datetime.now(UTC).isoformat(),
        training_data_hash=_hash_file(training_data_path),
        metrics=metrics,
        calibrated=calibrated,
    )
    (dir_path / "metadata.json").write_text(json.dumps(asdict(metadata), indent=2))

    latest_path = ARTIFACTS_DIR / model_type / "latest.json"
    latest_path.write_text(json.dumps({"version": version}))
    return version


def load_latest(model_type: str) -> tuple[object | None, ArtifactMetadata | None]:
    """Returns (payload, metadata), or (None, None) if nothing has been trained
    yet. Callers fall back to a documented heuristic when this returns None."""
    latest_path = ARTIFACTS_DIR / model_type / "latest.json"
    if not latest_path.exists():
        return None, None
    try:
        version = json.loads(latest_path.read_text())["version"]
        dir_path = ARTIFACTS_DIR / model_type / version
        with open(dir_path / "model.pkl", "rb") as f:
            payload = pickle.load(f)
        metadata = ArtifactMetadata(**json.loads((dir_path / "metadata.json").read_text()))
        return payload, metadata
    except (OSError, json.JSONDecodeError, KeyError, pickle.UnpicklingError):
        return None, None
