import pytest


@pytest.fixture(autouse=True)
def _isolated_pin_state(tmp_path, monkeypatch):
    """Point the session board pin (``pandan_cli/pin.py``) at a throwaway state dir for
    every test, so no test reads — or worse, writes — the developer's real pin and
    "no board selected" is the reproducible starting state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
