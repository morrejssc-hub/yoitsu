from pathlib import Path


def test_start_trenni_uses_venv_python_for_install_and_launch():
    script = Path("deploy/quadlet/bin/start-trenni.sh").read_text()

    assert '"${venv_path}/bin/python" -m pip install' in script
    assert '--force-reinstall' in script
    assert '--no-deps' in script
    assert 'exec "${TRENNI_VENV}/bin/python" -m trenni.cli start -c /etc/yoitsu/trenni.yaml' in script
