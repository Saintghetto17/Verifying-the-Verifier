from vtv.data import load_pairs
from vtv.prompts import build_messages, load_prompt, load_registry, resolve_version, safe_messages


def test_registry_covers_thirteen_versions():
    registry = load_registry()
    assert sorted(registry["versions"]) == [f"v{i:02d}" for i in range(1, 14)]
    assert resolve_version("tg") == "v03" and resolve_version("HD") == "v13"
    for version in registry["versions"]:
        prompt = load_prompt(version)
        assert prompt.source.count("<image>") == 1
        assert "<caption>" in prompt.source and "<text>" in prompt.source
    assert load_prompt("hd").hypotheses == 8 and load_prompt("tg").hypotheses == 0


def test_messages_carry_one_image_and_no_defect(data_root):
    pair = load_pairs(data_root)[0]
    messages = build_messages(load_prompt("hd"), pair, "fail")
    parts = messages[1]["content"]
    assert sum(p["type"] == "image_url" for p in parts) == 1
    text = " ".join(p.get("text", "") for p in parts)
    assert pair.caption in text and pair.text_block in text
    assert "block_permutation" not in text and "element_deletion" not in text
    safe = safe_messages(load_prompt("tg"), pair, "orig")
    assert "base64" not in str(safe)
