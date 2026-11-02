from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core.config import settings


def _alembic_config() -> Config:
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("script_location", str(Path("alembic").resolve()))
    return config


def test_intent_profiles_migration_is_reversible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "intent_migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    config = _alembic_config()

    command.upgrade(config, "015_evidence_scope_columns")
    command.upgrade(config, "016_intent_profiles")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "intent_profiles" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("intent_profiles")}
        assert {
            "profile_id",
            "merchant_id",
            "session_id",
            "created_by",
            "status",
            "ai_used",
            "model_name",
            "bundle",
            "created_at",
            "updated_at",
        } <= columns
        indexes = {index["name"] for index in inspector.get_indexes("intent_profiles")}
        assert {
            "ix_intent_profiles_merchant_id",
            "ix_intent_profiles_session_id",
            "ix_intent_profiles_merchant_created",
            "ix_intent_profiles_session_created",
        } <= indexes
    finally:
        engine.dispose()

    command.downgrade(config, "015_evidence_scope_columns")
    engine = create_engine(database_url)
    try:
        assert "intent_profiles" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
