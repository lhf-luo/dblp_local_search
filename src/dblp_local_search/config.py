"""Runtime configuration; no implicit dotenv loading."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    query_timeout: float = 15.0
    timezone: str = "Asia/Shanghai"
    update_cron: str = "0 3 * * 0"
    min_record_ratio: float = 0.8

    @classmethod
    def from_env(cls) -> Self:
        settings = cls(
            data_dir=Path(os.getenv("DBLP_DATA_DIR", "data")),
            query_timeout=float(os.getenv("DBLP_QUERY_TIMEOUT", "15")),
            timezone=os.getenv("TZ", "Asia/Shanghai"),
            update_cron=os.getenv("DBLP_UPDATE_CRON", "0 3 * * 0"),
            min_record_ratio=float(os.getenv("DBLP_MIN_RECORD_RATIO", "0.8")),
        )
        if settings.query_timeout <= 0:
            raise ValueError("query timeout must be positive")
        if not 0 < settings.min_record_ratio <= 1:
            raise ValueError("DBLP_MIN_RECORD_RATIO must be in (0,1]")
        return settings
