from agenthub.tui.widgets.log_viewer import LogViewer


def test_log_viewer_instantiable():
    viewer = LogViewer()
    assert viewer is not None


def test_log_viewer_default_id():
    viewer = LogViewer()
    assert viewer.id == "log-viewer"


def test_log_viewer_clear_method_exists():
    viewer = LogViewer()
    assert hasattr(viewer, "clear_log")


def test_log_viewer_write_line_method_exists():
    viewer = LogViewer()
    assert hasattr(viewer, "write_line")