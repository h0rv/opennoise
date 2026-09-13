"""Source-neutral, abstention-first cold-label alignment."""

from opennoise.ml.label_alignment.contracts import (
    ColdLabelAlignmentArtifact,
    ColdLabelAlignmentReceipt,
    ColdLabelAlignmentSettings,
    SeedPartitionRow,
)
from opennoise.ml.label_alignment.pipeline import (
    ColdLabelAlignmentInputs,
    build_cold_label_alignment,
    verify_cold_label_alignment,
    write_cold_label_alignment,
)

__all__ = [
    "ColdLabelAlignmentArtifact",
    "ColdLabelAlignmentInputs",
    "ColdLabelAlignmentReceipt",
    "ColdLabelAlignmentSettings",
    "SeedPartitionRow",
    "build_cold_label_alignment",
    "verify_cold_label_alignment",
    "write_cold_label_alignment",
]
