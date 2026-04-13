from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PALIMPSEST_SRC = ROOT / "palimpsest"
FACTORIO_ROOT = ROOT / "evo" / "factorio"
PREPARATION_PATH = FACTORIO_ROOT / "lib" / "preparation.py"

if str(PALIMPSEST_SRC) not in sys.path:
    sys.path.insert(0, str(PALIMPSEST_SRC))
if str(FACTORIO_ROOT) not in sys.path:
    sys.path.insert(0, str(FACTORIO_ROOT))


def _load_preparation_module():
    spec = importlib.util.spec_from_file_location("test_factorio_preparation_module", PREPARATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _RuntimeContext:
    def __init__(self) -> None:
        self.resources: dict[str, object] = {}
        self.cleanups: list[object] = []

    def register_cleanup(self, fn) -> None:
        self.cleanups.append(fn)


class _FakeRCONClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.connected = False
        self.commands: list[str] = []
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def send_command(self, command: str) -> str:
        self.commands.append(command)
        return "ok"

    def close(self) -> None:
        self.closed = True


def test_prepare_factorio_runtime_clears_mount_contents_without_removing_mountpoint(tmp_path, monkeypatch):
    preparation = _load_preparation_module()

    evo_root = tmp_path / "evo"
    src_scripts = evo_root / "factorio" / "scripts"
    src_scripts.mkdir(parents=True)
    (src_scripts / "ping.lua").write_text("-- ping\n")

    dst = tmp_path / "mods" / "factorio-agent" / "scripts"
    dst.mkdir(parents=True)
    (dst / "stale.lua").write_text("-- stale\n")

    monkeypatch.setenv("FACTORIO_MOD_SCRIPTS_DIR", str(dst))

    fake_rcon_module = types.ModuleType("factorio.lib.rcon")
    fake_rcon_module.RCONClient = _FakeRCONClient
    sys.modules["factorio.lib.rcon"] = fake_rcon_module

    original_rmtree = preparation.shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        if Path(path) == dst:
            raise OSError(16, "Device or resource busy", str(path))
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(preparation.shutil, "rmtree", guarded_rmtree)

    runtime_context = _RuntimeContext()

    preparation.prepare_factorio_runtime(
        runtime_context=runtime_context,
        evo_root=str(evo_root),
    )

    assert dst.is_dir()
    assert not (dst / "stale.lua").exists()
    assert (dst / "ping.lua").read_text() == "-- ping\n"
    assert "rcon" in runtime_context.resources
    rcon = runtime_context.resources["rcon"]
    assert rcon.connected is True
    assert rcon.commands == ["/silent-command pcall(function() game.reload_script() end)"]
    assert len(runtime_context.cleanups) == 1
