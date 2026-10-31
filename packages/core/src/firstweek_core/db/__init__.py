"""Database layer: declarative base, models and sessions."""

from firstweek_core.db import models
from firstweek_core.db.base import EMBEDDING_DIM, Base

__all__ = ["EMBEDDING_DIM", "Base", "models"]
