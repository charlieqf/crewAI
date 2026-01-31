from pathlib import Path

from src.crewai_enterprise.server.opencode_file_sync import mirror_session_files


def test_mirror_session_files_copies_new_file(tmp_path: Path):
    storage_root = tmp_path / "storage"
    repo_dir = tmp_path / "repo"
    task_dir = tmp_path / "task"
    session_id = "ses_abc"

    repo_dir.mkdir(parents=True)
    (repo_dir / "output.html").write_text("hello", encoding="utf-8")

    session_dir = storage_root / "session" / "proj123"
    session_dir.mkdir(parents=True)
    session_file = session_dir / f"{session_id}.json"
    session_file.write_text(
        '{"directory": "' + str(repo_dir) + '", "time": {"created": 2000}}',
        encoding="utf-8",
    )

    files_dir = task_dir / "files"
    state_path = task_dir / "sync.json"
    mirror_session_files(
        session_id,
        str(files_dir),
        str(storage_root),
        str(state_path),
    )

    assert (files_dir / "output.html").is_file()


def test_mirror_session_files_uses_default_last_sync(tmp_path: Path):
    storage_root = tmp_path / "storage"
    repo_dir = tmp_path / "repo"
    task_dir = tmp_path / "task"
    session_id = "ses_def"

    repo_dir.mkdir(parents=True)
    old_file = repo_dir / "old.txt"
    old_file.write_text("old", encoding="utf-8")

    session_dir = storage_root / "session" / "proj123"
    session_dir.mkdir(parents=True)
    session_file = session_dir / f"{session_id}.json"
    session_file.write_text(
        '{"directory": "' + str(repo_dir) + '", "time": {"created": 1000}}',
        encoding="utf-8",
    )

    files_dir = task_dir / "files"
    state_path = task_dir / "sync.json"
    mirror_session_files(
        session_id,
        str(files_dir),
        str(storage_root),
        str(state_path),
        9999999999,
    )

    assert not (files_dir / "old.txt").exists()


def test_mirror_session_files_with_workdir(tmp_path: Path):
    storage_root = tmp_path / "storage"
    workdir = tmp_path / "workdir"
    task_dir = tmp_path / "task"
    session_id = "ses_override"

    workdir.mkdir(parents=True)
    (workdir / "report.md").write_text("ok", encoding="utf-8")

    files_dir = task_dir / "files"
    state_path = task_dir / "sync.json"
    mirror_session_files(
        session_id,
        str(files_dir),
        str(storage_root),
        str(state_path),
        workdir=str(workdir),
    )

    assert (files_dir / "report.md").is_file()
