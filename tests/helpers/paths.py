from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
TESTS_DIR: Path = REPO_ROOT / "tests"
FIXTURES_DIR: Path = TESTS_DIR / "fixtures"
