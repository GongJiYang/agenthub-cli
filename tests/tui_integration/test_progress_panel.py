from agenthub.tui.widgets.progress_panel import ProgressPanel, EXECUTION_STAGES


def test_progress_panel_instantiable():
    panel = ProgressPanel()
    assert panel is not None


def test_progress_panel_stages_initialized():
    panel = ProgressPanel()
    for stage in EXECUTION_STAGES:
        assert panel._stage_states[stage] == "pending"


def test_progress_panel_set_stage_advances():
    panel = ProgressPanel()
    panel.set_stage("context")
    assert panel._stage_states["claim"] == "done"
    assert panel._stage_states["context"] == "active"
    assert panel._stage_states["execute"] == "pending"


def test_progress_panel_set_failed():
    panel = ProgressPanel()
    panel.set_failed("execute")
    assert panel._stage_states["execute"] == "failed"


def test_progress_panel_add_tool_call():
    panel = ProgressPanel()
    panel.add_tool_call("read_file", "path=/tmp/test.py")
    assert len(panel._tool_calls) == 1
    assert "read_file" in panel._tool_calls[0]


def test_progress_panel_add_tool_result():
    panel = ProgressPanel()
    panel.add_tool_result("read_file", "file contents")
    assert len(panel._tool_calls) == 1
    assert "read_file" in panel._tool_calls[0]