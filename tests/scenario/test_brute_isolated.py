from scenario import Context, State


def test_start_sequence(context: Context, state_after_begin_with_initial_hooks_isolated):
    context.run("update-status", state_after_begin_with_initial_hooks_isolated)
