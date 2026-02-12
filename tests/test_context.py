from __future__ import annotations

from orchestra.models.context import Context


def test_clone_isolation() -> None:
    ctx = Context()
    ctx.set("key", "original")

    cloned = ctx.clone()
    cloned.set("key", "modified")

    assert ctx.get("key") == "original"
    assert cloned.get("key") == "modified"


def test_clone_nested_dict_isolation() -> None:
    ctx = Context()
    ctx.set("nested", {"inner": [1, 2, 3]})

    cloned = ctx.clone()
    cloned.get("nested")["inner"].append(4)

    assert ctx.get("nested")["inner"] == [1, 2, 3]
    assert cloned.get("nested")["inner"] == [1, 2, 3, 4]


def test_clone_empty_context() -> None:
    ctx = Context()
    cloned = ctx.clone()

    assert cloned.snapshot() == {}

    cloned.set("new_key", "value")
    assert ctx.get("new_key") is None
    assert cloned.get("new_key") == "value"


def test_clone_preserves_all_keys() -> None:
    ctx = Context()
    ctx.set("a", 1)
    ctx.set("b", "two")
    ctx.set("c", [3])

    cloned = ctx.clone()
    assert cloned.snapshot() == {"a": 1, "b": "two", "c": [3]}
