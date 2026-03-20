"""In-memory storage stubs for report artifact persistence."""

from __future__ import annotations

from src.tw_quant.schema.models import ReportArtifact


class InMemoryArtifactStore:
    """Thread-unsafe in-memory artifact sink for report builder tests."""

    def __init__(self) -> None:
        self._entries: dict[str, bytes] = {}
        self._artifacts: dict[str, ReportArtifact] = {}
        self._history: list[ReportArtifact] = []

    def save_artifact(self, artifact: ReportArtifact, content: bytes) -> None:
        self._entries[artifact.artifact_id] = bytes(content)
        self._artifacts[artifact.artifact_id] = artifact
        self._history.append(artifact)

    def load_artifact(self, artifact_id: str) -> bytes | None:
        return self._entries.get(artifact_id)

    def get_artifact(self, artifact_id: str) -> ReportArtifact | None:
        return self._artifacts.get(artifact_id)

    def list_saved_artifacts(self) -> list[ReportArtifact]:
        return list(self._history)
