from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from models.profile import WorkerProfile


def test_worker_profile_roundtrips_json_under_sqlite(make_profile, session):
    p = make_profile(transcripts={"story": "hi"}, profile_data={"summary": "x"})
    session.expire_all()
    got = session.get(WorkerProfile, p.id)
    assert got.transcripts == {"story": "hi"}
    assert got.profile_data == {"summary": "x"}


def test_profile_json_columns_stay_jsonb_on_postgres():
    ddl = str(CreateTable(WorkerProfile.__table__).compile(dialect=postgresql.dialect()))
    assert "profile_data JSONB" in ddl
    assert "transcripts JSONB" in ddl
