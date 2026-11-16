"""Sanity checks against the currently published single database."""

from pathlib import Path

from dblp_local_search.storage.database import NotReady, active_metadata

#防止出错 over review
def validate_size(root: Path, new_count: int, minimum_ratio: float) -> None:
    try:
        metadata = active_metadata(root)
    except NotReady:
        return
    if new_count < metadata["paper_count"] * minimum_ratio:
        raise ValueError(
            "New dataset lost too many publications; old database retained"
        )
