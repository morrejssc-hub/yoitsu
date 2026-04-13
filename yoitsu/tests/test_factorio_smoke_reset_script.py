from pathlib import Path


SCRIPT_PATH = Path("scripts/reset-factorio-smoke-env.sh")


def test_reset_factorio_smoke_env_script_contains_required_reset_steps():
    script = SCRIPT_PATH.read_text()

    assert "cleanup-test-data.sh --skip-backup" in script
    assert "build-job-image.sh --no-cache" in script
    assert "deploy-quadlet.sh --skip-build" in script
    assert "--create \"$SAVE_PATH\"" in script
    assert "--start-server \"$SAVE_PATH\"" in script
    assert "yoitsu-clean-" in script
