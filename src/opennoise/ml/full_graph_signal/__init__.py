"""Public API for the receipt-bound sparse graph signal checkpoint."""

from .contracts import (
    ChannelPairCounts,
    FullGraphSignalArtifact,
    FullGraphSignalInputs,
    FullGraphSignalReceipt,
    FullGraphSignalRunReport,
    FullGraphSignalSettings,
    MatrixBinding,
    full_graph_signal_artifact_sha256,
    full_graph_signal_settings_sha256,
)
from .pipeline import (
    build_full_graph_signal,
    verify_full_graph_signal,
    write_full_graph_signal,
)

__all__ = (
    "ChannelPairCounts",
    "FullGraphSignalArtifact",
    "FullGraphSignalInputs",
    "FullGraphSignalReceipt",
    "FullGraphSignalRunReport",
    "FullGraphSignalSettings",
    "MatrixBinding",
    "build_full_graph_signal",
    "full_graph_signal_artifact_sha256",
    "full_graph_signal_settings_sha256",
    "verify_full_graph_signal",
    "write_full_graph_signal",
)
