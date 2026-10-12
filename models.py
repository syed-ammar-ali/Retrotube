"""SQLAlchemy 2.0 models for RetroTube's local "nostalgia engine"."""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(20))
    # Case-insensitive uniqueness: "Bob" and "bob" are the same account.
    username_lower: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    about: Mapped[str] = mapped_column(Text, default="", server_default="")
    # {"bg_color": "#RRGGBB", "bg_url": "https://..."}  (validated on write and render)
    profile_theme: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # Newest-first list of {"body": str, "created_at": iso8601}; capped at 10.
    bulletins: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class WatchHistory(Base):
    __tablename__ = "watch_history"
    __table_args__ = (Index("ix_history_user_time", "user_id", "watched_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[str] = mapped_column(String(11))
    title: Mapped[str] = mapped_column(String(300))
    channel: Mapped[str] = mapped_column(String(200), default="")
    thumbnail: Mapped[str] = mapped_column(String(500), default="")
    watched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LocalRating(Base):
    __tablename__ = "local_ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "video_id", name="uq_rating_user_video"),
        CheckConstraint("stars BETWEEN 1 AND 5", name="ck_rating_stars_range"),
        Index("ix_ratings_video", "video_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    video_id: Mapped[str] = mapped_column(String(11))
    stars: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LocalComment(Base):
    __tablename__ = "local_comments"
    __table_args__ = (Index("ix_comments_video_time", "video_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    video_id: Mapped[str] = mapped_column(String(11))
    body: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "video_id", name="uq_fav_user_video"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[str] = mapped_column(String(11))
    title: Mapped[str] = mapped_column(String(300))
    channel: Mapped[str] = mapped_column(String(200), default="")
    thumbnail: Mapped[str] = mapped_column(String(500), default="")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VideoResponse(Base):
    __tablename__ = "video_responses"
    __table_args__ = (Index("ix_responses_parent", "parent_video_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_video_id: Mapped[str] = mapped_column(String(11))
    response_video_id: Mapped[str] = mapped_column(String(11))
    title: Mapped[str] = mapped_column(String(300))
    thumbnail: Mapped[str] = mapped_column(String(500), default="")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlaylistItem(Base):
    __tablename__ = "playlist_items"
    __table_args__ = (
        UniqueConstraint("playlist_id", "video_id", name="uq_playlist_video"),
        Index("ix_playlist_items_pos", "playlist_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"))
    video_id: Mapped[str] = mapped_column(String(11))
    title: Mapped[str] = mapped_column(String(300))
    thumbnail: Mapped[str] = mapped_column(String(500), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

