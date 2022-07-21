'''This charm lib provides a CompoundStatus utility.

Example usage:

>>> class StatusPool(CompoundStatus):
>>>     SKIP_UNKNOWN = True
>>>
>>>     workload = Status()
>>>     relation_1 = Status()
>>>     relation_2 = Status(tag='rel2')
>>>
>>> class TesterCharm(CharmBase):
>>>     def __init__(self, framework, key=None):
>>>         super().__init__(framework, key)
>>>         status_pool = StatusPool(self)
>>>
>>>         # pro tip: keep the messages short
>>>         status_pool.relation_1 = ActiveStatus('✅')
>>>         status_pool.commit()  # sync with juju
>>>         # equivalent to self.unit.status = status_pool.coalesce()
>>>
>>>         status_pool.relation_1.unset()  # send status_1 back to unknown, until you set it again.
>>>
>>>         status_pool.relation_2 = WaitingStatus('𝌗: foo')
>>>         status_pool.workload.warning('some debug message about why the workload is blocked')
>>>         status_pool.workload.info('some info about the workload')
>>>         status_pool.workload.error('whoopsiedaisies')
>>>         status_pool.workload = BlockedStatus('blocked', 'see debug-log for the reason')
>>>         status_pool.commit()
'''

# The unique Charmhub library identifier, never change it
LIBID = "2dce4f51241e493dbbbfee1c9bdeb48b"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 4

import inspect
import json
import logging
from collections import Counter
from itertools import chain
from logging import getLogger
from operator import itemgetter
from typing import (
    TYPE_CHECKING,
    Dict,
    Literal,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
    Union,
)

from ops.charm import CharmBase
from ops.framework import Handle, Object, StoredStateData
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    StatusBase,
    WaitingStatus,
)
from ops.storage import NoSnapshotError

log = getLogger("compound-status")

StatusName = Literal["blocked", "waiting", "maintenance", "unknown", "active"]
# are sorted best-to-worst
STATUSES = ("unknown", "active", "maintenance", "waiting", "blocked")
STATUS_PRIORITIES = {val: i for i, val in enumerate(STATUSES)}
STATUS_NAME_TO_CLASS = {
    "blocked": BlockedStatus,
    "waiting": WaitingStatus,
    "maintenance": MaintenanceStatus,
    "active": ActiveStatus
    # omit unknown as it should not be used directly.
}


class _StatusDict(TypedDict, total=False):
    type: Literal["subordinate", "master"]  # noqa
    status: str
    message: str
    tag: str
    attr: str
    user_set: bool


PositiveNumber = Union[float, int]


class Status:
    """Represents a status."""

    _ID = 0

    def __repr__(self):
        return "<Status {} ({}): {}>".format(self._status, self.tag, self._message)

    def __init__(
        self, tag: Optional[str] = None, priority: Optional[PositiveNumber] = None
    ):
        # to keep track of instantiation order
        self._id = Status._ID
        Status._ID += 1

        # if tag is None, we'll guess it from the attr name
        # and late-bind it
        self.tag = tag  # type: str
        self._status = "unknown"  # type: StatusName
        self._message = ""

        # externally managed (and henceforth immutable) state
        self._master = None  # type: Optional[MasterStatus]
        self._logger = None  # type: Optional[logging.Logger]
        self._attr = None  # type: Optional[str]

        if priority is not None:
            if not isinstance(priority, (float, int)):
                raise TypeError(f"priority needs to be float|int, not {type(priority)}")
            if priority <= 0:
                raise TypeError(f"priority needs to be > 0, not {priority}")

        self._priority = priority  # type: Optional[float]  # externally managed

    @property
    def priority(self):
        """Return the priority of this status."""
        return self._priority

    @staticmethod
    def priority_key(status: Union["Status", StatusName]):
        """Return the priority key."""
        if isinstance(status, str):
            return STATUS_PRIORITIES[status]
        return STATUS_PRIORITIES[status.status], -status.priority

    @staticmethod
    def sort(statuses: Sequence["Status"]):
        """Return the statuses, sorted worst-to-best."""
        return sorted(statuses, key=Status.priority_key, reverse=True)

    def log(self, level: int, msg: str, *args, **kwargs):
        """Associate with this status a log entry with level `log`."""
        self._logger.log(level, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """Associate with this status a log entry with level `critical`."""
        self._logger.critical(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """Associate with this status a log entry with level `error`."""
        self._logger.error(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """Associate with this status a log entry with level `warning`."""
        self._logger.warning(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """Associate with this status a log entry with level `info`."""
        self._logger.info(msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        """Associate with this status a log entry with level `debug`."""
        self._logger.debug(msg, *args, **kwargs)

    def _set(self, status: StatusName, msg: str = ""):
        assert status in STATUS_NAME_TO_CLASS, "invalid status: {}".format(status)
        assert isinstance(msg, str), type(msg)

        self._status = status
        self._message = msg

        return self

    def unset(self):
        """Unsets status and message.

        This status will go back to its initial state and be removed from the
        Master clobber.
        """
        self.debug("unset")
        self._status = "unknown"
        self._message = ""

    def __get__(self, instance, owner):
        return self

    def __set__(self, instance, value: StatusBase):
        self._set(value.name, value.message)

    @property
    def status(self) -> StatusName:
        """Return the string representing this status."""
        return self._status

    @property
    def name(self) -> StatusName:
        """Alias for interface-compatibility with ops.model.StatusBase."""
        return self.status

    @property
    def message(self) -> str:
        """Return the message associated with this status."""
        return self._message

    def _snapshot(self) -> _StatusDict:
        """Serialize Status for storage."""
        # tag should not change, and is reloaded on each init.
        attr: str = self._attr
        if attr is None:
            raise RuntimeError(f"{self} has no attr; cannot snapshot.")
        dct: _StatusDict = {
            "type": "subordinate",
            "status": self._status,
            "message": self._message,
            "tag": self.tag,
            "attr": attr,
        }
        return dct

    def _restore(self, dct: _StatusDict):
        """Restore Status from stored state."""
        assert dct["type"] == "subordinate", dct["type"]
        self._status = dct["status"]
        self._message = dct["message"]
        self.tag = dct["tag"]
        self._attr = dct["attr"]

    def __hash__(self):
        return hash((self.tag, self.status, self.message))

    def __eq__(self, other: "Status") -> bool:
        return hash(self) == hash(other)


class Clobberer:
    """Clobberer. Repeat it many times fast."""

    def clobber(self, statuses: Sequence[Status], skip_unknown: bool = False) -> str:
        """Produce a clobbered representation of the statuses."""
        raise NotImplementedError


class WorstOnly(Clobberer):
    """This clobberer provides a worst-only view of the current statuses in the pool.

    e.g. if the status pool has three statuses:
        relation_1 = ActiveStatus('✅')
        relation_2 = WaitingStatus('𝌗: foo')
        workload = BlockedStatus('💔')

    The Summary clobbered status will have as message::
        (workload) 💔
    """

    def __init__(self, fmt: str = "({0}) {1}", sep: str = "; "):
        self._fmt = fmt

    def clobber(self, statuses: Sequence[Status], skip_unknown: bool = False) -> str:
        """Produce a clobbered representation of the statuses."""
        worst = Status.sort(statuses)[0]
        return self._fmt.format(worst.tag, worst.message)


class Summary(Clobberer):
    """This clobberer provides a worst-first, summarized view of all statuses.

    e.g. if the status pool has three statuses:
        relation_1 = ActiveStatus('✅')
        relation_2 = WaitingStatus('𝌗: foo')
        workload = BlockedStatus('💔')

    The Summary clobbered status will have as message:
        (workload:blocked) 💔; (relation_1:active) ✅; (rel2:waiting) 𝌗: foo
    """

    def __init__(self, fmt: str = "({0}:{1}) {2}", sep: str = "; "):
        self._fmt = fmt
        self._sep = sep

    def clobber(self, statuses: Sequence[Status], skip_unknown: bool = False):
        """Produce a clobbered representation of the statuses."""
        msgs = []
        for status in Status.sort(statuses):
            if skip_unknown and status.status == "unknown":
                continue
            msgs.append(self._fmt.format(status.tag, status.status, status.message))
        return self._sep.join(msgs)


class Condensed(Clobberer):
    """This clobberer provides a very compact, summarized view of all statuses.

    e.g. if the status pool has three statuses:
        relation_1 = ActiveStatus('✅')
        relation_2 = WaitingStatus('✅')
        relation_3 = BlockedStatus('✅')
        relation_... = ???
        relation_N = ActiveStatus('✅')
        relation_2 = WaitingStatus('𝌗: foo')
        workload = BlockedStatus('💔')

    The Condensed clobbered status will have as message:
        15 blocked; 43 waiting; 12 active

    If all are active the message will be empty.
    Priority will be ignored.
    """

    def __init__(self, fmt: str = "{0} {1}", sep: str = "; "):
        self._fmt = fmt
        self._sep = sep

    def clobber(self, statuses: Sequence[Status], skip_unknown: bool = False):
        """Produce a clobbered representation of the statuses."""
        ctr = Counter(s.status for s in statuses)

        if set(ctr) == {
            "active",
        }:  # only active statuses
            return ""

        msgs = []
        for status, count in sorted(
            ctr.items(), key=lambda v: Status.priority_key(v[0]), reverse=True
        ):
            if skip_unknown and status == "unknown":
                continue
            msgs.append(self._fmt.format(count, status))
        return self._sep.join(msgs)


class MasterStatus(Status):
    """The Master status of the pool.

    Parameters:
        - `tag`: the name to associate the master status with.

        - `fmt`: The format for each child status. Needs to contain three {}
            slots, will receive three arguments in this order:

            - the tag of the child status (a string)
            - the name of the child status (e.g. 'blocked', or 'active')
            - the message associated with the child status (another string)

        - `sep`: The separator used to join together the child statuses.
    """

    SKIP_UNKNOWN = False

    def __init__(
        self,
        tag: Optional[str] = "master",
        clobberer: Clobberer = WorstOnly(),
        priority: Optional[PositiveNumber] = None,
    ):
        super().__init__(tag, priority=priority)
        self.children = ()  # type: Tuple[Status, ...]  # gets populated by CompoundStatus
        self._owner = None  # type: CharmBase  # externally managed
        self._user_set = False
        self._clobberer = clobberer

        self._logger = log.getChild(tag)
        self._master = self  # lucky you
        self._attr = "*master*"

    def _add_child(self, status: Status):
        """Add a child status."""
        status._master = self
        status._logger = self._logger.getChild(status.tag)
        self.children = self.children + (status,)

    def _remove_child(self, status: Status):
        """Remove a child status."""
        if status not in self.children:
            raise ValueError(f"{status} not in {self}")

        status._master = None
        status._logger = None
        self.children = tuple(a for a in self.children if a is not status)

    @property
    def message(self) -> str:
        """Return the message associated with this status."""
        if self._user_set:
            return self._message
        return self._clobber_statuses(self.children, self.SKIP_UNKNOWN)

    def _clobber_statuses(
        self, statuses: Sequence[Status], skip_unknown: bool = False
    ) -> str:
        """Produce a message summarizing the child statuses."""
        return self._clobberer.clobber(statuses, skip_unknown)

    @property
    def status(self) -> str:
        """Return the status."""
        if self._user_set:
            return self._status
        return Status.sort(self.children)[0].status

    def coalesce(self) -> StatusBase:
        """Cast to an ops.model.StatusBase instance by clobbering statuses and messages."""
        if self.status == "unknown":
            raise ValueError("cannot coalesce unknown status")
        status_type = STATUS_NAME_TO_CLASS[self.status]
        status_msg = self.message
        return status_type(status_msg)

    def _set(self, status: StatusName, msg: str = ""):
        """Force-set this status and message.

        Should not be called by user code.
        """
        self._user_set = True
        super()._set(status, msg)

    def unset(self):
        """Unset all child statuses, as well as any user_set Master status."""
        super().unset()

        self._user_set = False
        for child in self.children:
            child.unset()

    def _snapshot(self) -> _StatusDict:
        """Serialize Status for storage."""
        dct = super()._snapshot()
        dct["type"] = "master"
        dct["user_set"] = self._user_set
        return dct

    def _restore(self, dct: _StatusDict):
        """Restore Status from stored state."""
        assert dct["type"] == "master", dct["type"]
        self._status = dct["status"]
        self._message = dct["message"]
        self._user_set = dct["user_set"]

    def __repr__(self):
        if not self.children:
            return "<MasterStatus -- empty>"
        if self.status == "unknown":
            return "unknown"
        return str(self.coalesce())


class StatusPool(Object):
    """Represents the pool of statuses available to an Object."""

    # whether unknown statuses should be omitted from the master message
    SKIP_UNKNOWN = False
    # whether the status should be committed automatically when the hook exits
    AUTO_COMMIT = True
    # key used to register handle
    KEY = "status_pool"

    if TYPE_CHECKING:
        _statuses = {}  # type: Dict[str, Status]
        _charm = {}  # type: CharmBase
        master = MasterStatus()  # type: MasterStatus
        _manual_priorities = False  # type: bool
        _priority_counter = 0  # type: int

    def __init__(self, charm: CharmBase, key: str = None):
        super().__init__(charm, key or self.KEY)
        # skip setattr
        self.__dict__["master"] = MasterStatus()
        self.__dict__["_statuses"] = {}
        self.__dict__["_manual_priorities"] = False
        self.__dict__["_priority_counter"] = 0

        stored_handle = Handle(self, StoredStateData.handle_kind, "_status_pool_state")
        charm.framework.register_type(
            StoredStateData, self, StoredStateData.handle_kind
        )
        try:
            self._state = charm.framework.load_snapshot(stored_handle)
        except NoSnapshotError:
            self._state = StoredStateData(self, "_status_pool_state")
            self._state["statuses"] = "{}"

        self._init_statuses(charm)
        self._load_from_stored_state()
        if self.AUTO_COMMIT:
            charm.framework.observe(
                charm.framework.on.commit, self._on_framework_commit
            )

    def get_status(self, attr: str) -> Status:
        """Retrieve a status by name. Equivalent to getattr(self, attr)."""
        return getattr(self, attr)

    def set_status(self, attr: str, status: StatusBase):
        """Set a status by name. Equivalent to setattr(self, attr, status)."""
        return setattr(self, attr, status)

    def add_status(self, status: Status, attr: Optional[str] = None):
        """Add status to this pool; under attr: `attr`.

        If attr is not provided, status.tag will be used instead if set.

        NB `attr` needs to be a valid Python identifier.
        """
        if not attr and not status.tag:
            raise ValueError(
                f"either give status {status} a tag, or pass `attr`" f"to add_status."
            )
        attr = attr or status.tag
        if not attr.isidentifier():
            raise ValueError(
                f"cannot set {attr!r}={status} on {self}: "
                f"attr needs to be a valid Python identifier."
            )

        # will check that attr is not in use already
        self._add_status(status, attr)

        setattr(self, attr, status)

    def remove_status(self, status: Status):
        """Remove the status and forget about it."""
        # some safety-first cleanup
        status.unset()
        self.master._remove_child(status)
        delattr(self, status._attr)

    def _add_status(self, status: Status, attr: str):
        if getattr(self, attr, None) not in {status, None}:
            raise ValueError(
                f"cannot set {attr!r} = {status}." f"attribute already set on {self}"
            )

        if status.priority is None:
            if self._manual_priorities:
                raise ValueError(
                    "Either pass a priority to all Statuses, "
                    "or leave it blank for all."
                )
        else:
            self._manual_priorities = True

        if not self._manual_priorities:
            self._priority_counter += 1
            status._priority = self._priority_counter

        if status.priority > 100:
            raise ValueError("Status priority cannot be > 100")

        status.tag = status.tag or attr
        self.master._add_child(status)

        status._attr = attr
        self._statuses[attr] = status

    def _init_statuses(self, charm: CharmBase):
        """Extract the statuses from the class namespace.

        And associate them with the master status.
        """

        def _is_child_status(obj):
            return isinstance(obj, Status) and not isinstance(obj, MasterStatus)

        statuses_ = inspect.getmembers(self, predicate=_is_child_status)
        statuses = sorted(statuses_, key=lambda s: s[1]._id)

        master = self.master
        # bind children to master, set tag if unset, init logger
        for attr, obj in statuses:
            self._add_status(obj, attr)

        master.SKIP_UNKNOWN = self.SKIP_UNKNOWN
        master.children = tuple(a[1] for a in statuses)

        # skip setattr
        self.__dict__["_statuses"] = dict(statuses)
        self.__dict__["_charm"] = charm

    def _load_from_stored_state(self):
        """Retrieve stored state snapshot of current statuses."""
        stored_statuses: Dict[str, _StatusDict] = json.loads(self._state["statuses"])
        for attr, status_dct in stored_statuses.items():

            if attr == "*master*":
                status = self.master
            else:
                if hasattr(self, attr):  # status was statically defined
                    status = getattr(self, attr)
                else:  # status was dynamically added
                    status = Status()
                    self.add_status(status, status_dct["attr"])

            status._restore(status_dct)  # noqa

    def _store(self):
        """Dump stored state."""
        all_statuses = chain(map(itemgetter(1), self._statuses.items()), (self.master,))
        statuses = {s._attr: s._snapshot() for s in all_statuses}
        self._state["statuses"] = json.dumps(statuses)

    def __setattr__(self, key: str, value: StatusBase):
        if isinstance(value, StatusBase):
            if key == "master":
                return self.master._set(value.name, value.message)  # noqa
            elif key in self._statuses:
                return self._statuses[key]._set(value.name, value.message)  # noqa
            else:
                raise AttributeError(key)
        return super().__setattr__(key, value)

    def _on_framework_commit(self, _event):
        log.debug("master status auto-committed")
        self.commit()

    def commit(self):
        """Store the current state and sync with juju."""
        assert isinstance(self.master, MasterStatus), type(self.master)

        # cannot coalesce in unknown status
        if self.master.status != "unknown":
            self._charm.unit.status = self.master.coalesce()
            self._store()

        self._charm.framework.save_snapshot(self._state)
        self._charm.framework._storage.commit()

    def unset(self):
        """Unsets master status (and all children)."""
        self.master.unset()

    def __repr__(self):
        return repr(self.master)

