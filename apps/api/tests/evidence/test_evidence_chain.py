import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import init_db
from app.evidence.hashchain import EvidenceChain
from app.models.base import Base
from app.models.evidence import (
    EvidenceChainHead,
    EvidenceLogEntry,
    EvidencePayload,
)


def make_scratch_chain():
    engine = create_engine("sqlite:///:memory:")
    EvidenceChainHead.__table__.create(engine)
    EvidenceLogEntry.__table__.create(engine)
    EvidencePayload.__table__.create(engine)
    session = Session(engine)
    return engine, session, EvidenceChain(session)


def test_evidence_append_and_verify(db_session):
    chain = EvidenceChain(db_session)
    r1 = chain.append("login", {"type": "login", "session_id": str(uuid.uuid4())})
    r2 = chain.append("payout", {"type": "payout", "amount": 1000})
    assert r1["seq"] == 1
    assert r2["seq"] == 2
    res = chain.verify()
    assert res["valid"] is True
    assert res["checked"] >= 2


def test_evidence_tamper_detected():
    engine, db_session, chain = make_scratch_chain()
    chain.append("login", {"type": "login"})
    chain.append("payout", {"type": "payout"})

    p = db_session.query(EvidencePayload).filter_by(seq=1).first()
    p.payload = {"type": "tampered"}
    db_session.commit()
    res = chain.verify()
    assert res["valid"] is False
    assert res["first_broken_seq"] == 1
    db_session.close()
    engine.dispose()


def test_evidence_detects_previous_hash_tampering():
    engine, db_session, chain = make_scratch_chain()
    chain.append("login", {"type": "login"})
    chain.append("payout", {"type": "payout"})

    entry = db_session.get(EvidenceLogEntry, 2)
    entry.prev_hash = "f" * 64
    db_session.commit()

    result = chain.verify()
    assert result["valid"] is False
    assert result["first_broken_seq"] == 2
    assert result["reason"] == "prev_hash_mismatch"
    db_session.close()
    engine.dispose()


def test_evidence_detects_deleted_middle_entry():
    engine, db_session, chain = make_scratch_chain()
    for seq in range(1, 4):
        chain.append(f"event-{seq}", {"seq": seq})

    db_session.delete(db_session.get(EvidencePayload, 2))
    db_session.delete(db_session.get(EvidenceLogEntry, 2))
    db_session.commit()

    result = chain.verify()
    assert result["valid"] is False
    assert result["first_broken_seq"] == 2
    assert result["reason"] == "sequence_gap"
    db_session.close()
    engine.dispose()


def test_evidence_detects_deleted_tail_against_checkpoint():
    engine, db_session, chain = make_scratch_chain()
    chain.append("login", {"type": "login"})
    chain.append("payout", {"type": "payout"})

    db_session.delete(db_session.get(EvidencePayload, 2))
    db_session.delete(db_session.get(EvidenceLogEntry, 2))
    db_session.commit()

    result = chain.verify()
    assert result["valid"] is False
    assert result["first_broken_seq"] == 2
    assert result["reason"] == "head_checkpoint_mismatch"
    db_session.close()
    engine.dispose()


def test_sqlite_evidence_storage_rejects_mutation(db_session):
    if db_session.get_bind().dialect.name != "sqlite":
        pytest.skip("SQLite trigger behavior is specific to the local development database.")

    init_db()
    chain = EvidenceChain(db_session)
    chain.append("guard-check", {"type": "guard-check"})

    with pytest.raises(IntegrityError, match="evidence records are append-only"):
        db_session.query(EvidenceLogEntry).filter_by(seq=1).update({"event_ref": "changed"})
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError, match="evidence records are append-only"):
        db_session.query(EvidenceLogEntry).filter_by(seq=1).delete()
        db_session.commit()
    db_session.rollback()

    assert db_session.query(EvidenceLogEntry).filter_by(seq=1).one().event_ref == "guard-check"


def test_evidence_seal_is_idempotent_and_blocks_session_appends(db_session):
    chain = EvidenceChain(db_session)
    session_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    merchant_id = uuid.uuid4()
    chain.append("login", {"type": "login", "session_id": str(session_id)})

    seal = chain.seal(incident_id, session_id, merchant_id)
    head_before = chain.head()
    repeated_seal = chain.seal(incident_id, session_id, merchant_id)

    assert repeated_seal == seal
    assert chain.head() == head_before
    assert chain.verify()["valid"] is True
    try:
        chain.append("late_event", {"type": "late_event", "session_id": str(session_id)})
    except ValueError as exc:
        assert "sealed session" in str(exc)
    else:
        raise AssertionError("Appending evidence for a sealed session must be rejected.")


def test_concurrent_evidence_appends_remain_linear(tmp_path):
    database_path = tmp_path / "evidence-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        execution_options={"schema_translate_map": {"honey": None}},
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine)

    def append_event(index: int) -> None:
        with sessions() as session:
            EvidenceChain(session).append(f"event-{index}", {"index": index})

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(append_event, range(50)))

    with Session(engine) as session:
        result = EvidenceChain(session).verify()
        assert result["valid"] is True
        assert result["checked"] == 50
    engine.dispose()
