#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""


def no_op(*args, **kwargs) -> None:
    pass


def tautology(*args, **kwargs) -> bool:
    return True


def cli_arg(plan, cli_opt):
    plan_dict = plan.to_dict()
    args = plan_dict["services"]["alertmanager"]["command"].split()
    for arg in args:
        opt_list = arg.split("=")
        if len(opt_list) == 2 and opt_list[0] == cli_opt:
            return opt_list[1]
        if len(opt_list) == 1 and opt_list[0] == cli_opt:
            return opt_list[0]
    return None
