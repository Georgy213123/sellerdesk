import pytest

from tests.db_guard import NotATestDatabaseError, require_test_database


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:5432/sellerdesk",
        "postgresql+psycopg://u:p@localhost:5432/app",
        "postgresql+psycopg://u:p@localhost:5432/test_sellerdesk",
    ],
)
def test_working_database_is_refused(url: str):
    with pytest.raises(NotATestDatabaseError):
        require_test_database(url)


def test_test_database_is_accepted():
    url = "postgresql+psycopg://u:p@localhost:5432/sellerdesk_test"
    assert require_test_database(url) == url
