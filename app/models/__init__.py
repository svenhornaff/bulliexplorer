"""SQLAlchemy models — import Base and all models here for Alembic discovery."""

from app.models.base import Base
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.models.route import Route

__all__ = ["Base", "PointOfInterest", "Post", "Route"]
