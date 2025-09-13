from services.api.app import _normalize_conninfo


def test_normalize_sqlalchemy_psycopg_url_preserves_password() -> None:
    src = "postgresql+psycopg://user:pass@host:5432/dbname"
    out = _normalize_conninfo(src)
    assert out == "postgresql://user:pass@host:5432/dbname"


def test_normalize_postgresql_url_no_change() -> None:
    src = "postgresql://user:pass@host:5432/dbname"
    out = _normalize_conninfo(src)
    assert out == src

