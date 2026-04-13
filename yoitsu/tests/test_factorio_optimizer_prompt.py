from pathlib import Path


PROMPT_PATH = Path("evo/factorio/prompts/optimizer.md")


def test_factorio_optimizer_prompt_uses_valid_review_proposal_enums():
    prompt = PROMPT_PATH.read_text()

    assert '"action_type": "improve_tool"' in prompt
    assert '"category": "other"' in prompt
    assert 'tool_efficiency' not in prompt
    assert '"action_type": "update_tool"' not in prompt
