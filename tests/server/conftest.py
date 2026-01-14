import pytest


@pytest.fixture(scope="module")
def vcr_cassette_dir(tmp_path_factory):
    # Override project-wide fixture to avoid path issues for server tests
    return str(tmp_path_factory.mktemp("cassettes_server"))


@pytest.fixture(scope="module")
def vcr_config(vcr_cassette_dir: str) -> dict:
    return {
        "cassette_library_dir": vcr_cassette_dir,
        "record_mode": "none",
    }
