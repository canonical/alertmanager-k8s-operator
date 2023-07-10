from scenario import Context
from helpers import begin_with_initial_hooks_isolated


def test_start_sequence(context: Context):
    state = begin_with_initial_hooks_isolated(context)
    context.run("update-status", state)
