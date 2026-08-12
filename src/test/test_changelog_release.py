import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "changelog.py"
SPEC = importlib.util.spec_from_file_location("release_manager_changelog", SCRIPT)
assert SPEC and SPEC.loader
changelog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(changelog)


def test_new_version_is_added_at_head(tmp_path, monkeypatch):
    release = tmp_path / "ReleaseHistory.md"
    release.write_text("## [4.2.11] 2026-08-09\nbuild 3\n* existing\n", encoding="utf-8")
    class FixedDate:
        @staticmethod
        def today():
            return type("Day", (), {"isoformat": lambda self: "2026-08-10"})()

    monkeypatch.setattr(changelog, "date", FixedDate)

    assert changelog.add_release_head(release, "4.2.12", "1")
    assert release.read_text(encoding="utf-8") == (
        "## [4.2.12] 2026-08-10\nbuild 1\n"
        "## [4.2.11] 2026-08-09\nbuild 3\n* existing\n"
    )
    assert changelog.read_release_head(release) == ("4.2.12", "1")


def test_build_is_prepended_without_replacing_history(tmp_path):
    release = tmp_path / "ReleaseHistory.md"
    release.write_text("## [4.2.11] 2026-08-09\nbuild 2\n* existing\n", encoding="utf-8")

    assert changelog.set_build_line(release, "3")
    assert changelog.set_build_line(release, "3")
    assert release.read_text(encoding="utf-8") == (
        "## [4.2.11] 2026-08-09\nbuild 3\nbuild 2\n* existing\n"
    )


def test_head_build_does_not_leak_from_older_section(tmp_path):
    release = tmp_path / "ReleaseHistory.md"
    release.write_text(
        "## [4.2.12] 2026-08-10\n* pending\n"
        "## [4.2.11] 2026-08-09\nbuild 7\n",
        encoding="utf-8",
    )

    assert changelog.read_release_head(release) == ("4.2.12", "")
