from typing import List

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# database
db = SQLAlchemy(model_class=Base)


class OauthState(db.Model):
    __tablename__ = "oauth_state"
    state: Mapped[str] = mapped_column(primary_key=True)
    expiration: Mapped[int]


class RedoistUsers(db.Model):
    __tablename__ = "redoist_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    api_key: Mapped[str] = mapped_column(unique=True)
    sync_token: Mapped[str] = mapped_column(nullable=True)
    manifests: Mapped[List["RedoistManifests"]] = relationship()


class RedoistManifests(db.Model):
    __tablename__ = "redoist_manifests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("redoist_users.id"))
    source_id: Mapped[str]
    target_id: Mapped[str]


class RedoistNoteIdMap(db.Model):
    __tablename__ = "redoist_note_id_map"
    source_id: Mapped[str] = mapped_column(primary_key=True)
    target_id: Mapped[str]


class SnoozerUsers(db.Model):
    __tablename__ = "snoozer_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    api_key: Mapped[str] = mapped_column(unique=True)


class SnoozerMap(db.Model):
    __tablename__ = "snoozer_map"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("snoozer_users.id"))
    source_project_id: Mapped[str]
    target_section_id: Mapped[str]
