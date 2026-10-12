"""Tests for SQLAlchemy 2.0 ORM schemas and constraints (Step 2.2)."""
from sqlalchemy import CheckConstraint, UniqueConstraint

from models import Base, Favorite, LocalComment, LocalRating, User, WatchHistory


def test_models_metadata_registered():
    """Verify all 5 tables are registered in Base.metadata."""
    table_names = set(Base.metadata.tables.keys())
    expected = {"users", "watch_history", "local_ratings", "local_comments", "favorites"}
    assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"


def test_user_model_attributes():
    """Verify User columns, types and constraints."""
    user_table = User.__table__
    assert "username_lower" in user_table.c
    assert user_table.c.username_lower.unique is True
    assert user_table.c.password_hash.type.length == 255
    assert user_table.c.profile_theme is not None
    assert user_table.c.bulletins is not None


def test_watch_history_constraints_and_indices():
    """Verify WatchHistory foreign keys and composite indices."""
    table = WatchHistory.__table__
    fk = list(table.foreign_keys)[0]
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"

    index_names = {idx.name for idx in table.indexes}
    assert "ix_history_user_time" in index_names


def test_local_rating_constraints():
    """Verify LocalRating unique constraint and star range check."""
    table = LocalRating.__table__
    fk = list(table.foreign_keys)[0]
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"

    unique_constraints = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_rating_user_video" in unique_constraints

    check_constraints = [c for c in table.constraints if isinstance(c, CheckConstraint)]
    check_names = {c.name for c in check_constraints}
    assert "ck_rating_stars_range" in check_names


def test_local_comment_constraints():
    """Verify LocalComment schema and foreign key cascade."""
    table = LocalComment.__table__
    fk = list(table.foreign_keys)[0]
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"
    assert table.c.body.type.length == 500


def test_favorite_constraints():
    """Verify Favorite table unique constraint on user_id + video_id."""
    table = Favorite.__table__
    fk = list(table.foreign_keys)[0]
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"

    unique_constraints = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_fav_user_video" in unique_constraints
