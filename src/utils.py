import functools
import hashlib
import urllib.request
from typing import Union


def leader_only(func):
    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        if not self.unit.is_leader():
            return
        func(*args, **kwargs)

    return wrapped


def append_unless(unless, base, appendable):
    """
    Conditionally append one object to another. Currently the intended usage is for strings.
    :param unless: a value of base for which should not append (and return as is)
    :param base: the base value to which append
    :param appendable: the value to append to base
    :return: base, if base == unless; base + appendable, otherwise.
    """
    return base if base == unless else base + appendable


def md5(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values"""
    if isinstance(hashable, str):
        hashable = hashable.encode('utf-8')
    return hashlib.md5(hashable).hexdigest()


def fetch_url(url: str) -> Union[str, None]:
    try:
        with urllib.request.urlopen(url) as response:
            html = response.read()
            code = response.getcode()
            return html if code < 400 else None
    except:
        return None
