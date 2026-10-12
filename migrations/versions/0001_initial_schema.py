"""Initial schema for RetroTube

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-12 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=20), nullable=False),
        sa.Column("username_lower", sa.String(length=20), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("about", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "profile_theme",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "bulletins",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_users_username_lower"), "users", ["username_lower"], unique=True
    )

    # 2. watch_history table
    op.create_table(
        "watch_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("channel", sa.String(length=200), server_default="", nullable=False),
        sa.Column("thumbnail", sa.String(length=500), server_default="", nullable=False),
        sa.Column(
            "watched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_watch_history_user_id"), "watch_history", ["user_id"], unique=False
    )
    op.create_index(
        "ix_history_user_time",
        "watch_history",
        ["user_id", "watched_at"],
        unique=False,
    )

    # 3. local_ratings table
    op.create_table(
        "local_ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("stars BETWEEN 1 AND 5", name="ck_rating_stars_range"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "video_id", name="uq_rating_user_video"),
    )
    op.create_index(
        "ix_ratings_video", "local_ratings", ["video_id"], unique=False
    )

    # 4. local_comments table
    op.create_table(
        "local_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_comments_video_time",
        "local_comments",
        ["video_id", "created_at"],
        unique=False,
    )

    # 5. favorites table
    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("channel", sa.String(length=200), server_default="", nullable=False),
        sa.Column("thumbnail", sa.String(length=500), server_default="", nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "video_id", name="uq_fav_user_video"),
    )
    op.create_index(op.f("ix_favorites_user_id"), "favorites", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("favorites")
    op.drop_table("local_comments")
    op.drop_table("local_ratings")
    op.drop_table("watch_history")
    op.drop_table("users")
