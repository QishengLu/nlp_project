import pytest

from apr_agent.tools.finish import FinishTool
from apr_agent.tools.registry import ToolRegistry


def test_registry_register_and_get():
    reg = ToolRegistry()
    reg.register(FinishTool())
    assert reg.get("finish").name == "finish"
    schemas = reg.openai_schemas()
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "finish"


def test_registry_rejects_duplicate():
    reg = ToolRegistry()
    reg.register(FinishTool())
    with pytest.raises(ValueError):
        reg.register(FinishTool())


def test_finish_tool_returns_done_marker():
    tool = FinishTool()
    result = tool.invoke({"rationale": "I fixed it."})
    assert result.is_error is False
    assert result.output == ""
    assert result.meta == {"rationale": "I fixed it."}
    assert tool.terminates_loop is True


def test_tool_abstract_contract():
    t = FinishTool()
    assert isinstance(t.name, str)
    assert isinstance(t.description, str)
    assert isinstance(t.parameters, dict)
