from agenthub.tui.widgets.confirm_dialog import ConfirmDialog


def test_confirm_dialog_instantiable():
    dialog = ConfirmDialog()
    assert dialog is not None


def test_confirm_dialog_custom_title():
    dialog = ConfirmDialog(title="执行任务?", message="确定要执行吗？")
    assert dialog._title == "执行任务?"
    assert dialog._message == "确定要执行吗？"


def test_confirm_dialog_default_values():
    dialog = ConfirmDialog()
    assert dialog._title == "确认"
    assert dialog._message == "确定要执行此操作吗？"


def test_confirm_dialog_actions_exist():
    dialog = ConfirmDialog()
    assert hasattr(dialog, "action_confirm")
    assert hasattr(dialog, "action_cancel")