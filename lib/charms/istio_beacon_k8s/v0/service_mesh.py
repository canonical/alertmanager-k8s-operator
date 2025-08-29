# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""# Service Mesh Library.

This library facilitates adding your charmed application to a service mesh, leveraging the
`service_mesh` and `cross_model_mesh` interfaces to provide secure, policy-driven traffic
management between applications.

## Overview

Service meshes provide capabilities for routing, controlling, and monitoring traffic between
applications. A key feature is the ability to restrict traffic between Pods. For example, you can define that Pod MetricsScraper can `GET` from Pod MetricsProducer
at `/metrics` on port `9090`, while preventing SomeOtherPod from accessing it.

## Consumer

The ServiceMeshConsumer object subscribes a charm and its workloads to a related service mesh.
Since application relations often indicate traffic flow patterns (e.g., DbConsumer requiring
DbProducer), ServiceMeshConsumer provides automated creation of traffic rules based on
application relations. \

The ServiceMeshConsumer implements the `requirer` side of the juju relation.

### Setup

First, add the required relations to your `charmcraft.yaml`:

```yaml
requires:
  service-mesh:
    limit: 1
    interface: service_mesh
    description: |
      Subscribe this charm into a service mesh to enforce authorization policies.
  require-cmr-mesh:
    interface: cross_model_mesh
    description: |
      Allow a cross-model application access to catalogue via the service mesh.
      This relation provides additional data required by the service mesh to enforce cross-model authorization policies.

provides:
  provide-cmr-mesh:
    interface: cross_model_mesh
    description: |
      Access a cross-model application from catalogue via the service mesh.
      This relation provides additional data required by the service mesh to enforce cross-model authorization policies.
```

Instantiate a ServiceMeshConsumer object in your charm's `__init__` method:

```python
from charms.istio_beacon_k8s.v0.service_mesh import Method, Endpoint, AppPolicy, UnitPolicy, ServiceMeshConsumer

class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self._mesh = ServiceMeshConsumer(
            self,
            policies=[
                AppPolicy(
                    relation="data",
                    endpoints=[
                        Endpoint(
                            ports=[HTTP_LISTEN_PORT],
                            methods=[Method.get],
                            paths=["/data"],
                        ),
                    ],
                ),
                UnitPolicy(
                    relation="metrics",
                    ports=[HTTP_LISTEN_PORT],
                ),
            ],
        )
```

This example creates two policies:
- An app policy - When related over the `data` relation, allow the related application to `GET` this application's `/data` endpoint on the specified port through the app's Kubernetes service.
- A unit policy - When related over the `metrics` relation, allow the related application to access this application's unit pods directly on the specified port without any other restriction. UnitPolicy does not support fine-grained access control on the methods and paths via `Endpoints`.

An AppPolicy can be used to control how the source application can communicate with the target application via the app address.
A UnitPolicy allows access to the specified port but only to the unit pods of the charm via individual unit addresses.

### Cross-Model Relations
To request service mesh policies for cross-model relations, additional information is required.

For any charm that wants to grant access to a related application (say, the above example
charm providing a `data` relation), these charms must also implement and relate over the
`cross_model_mesh` relation.  For `cross_model_mesh`, the charm granting access should be the
provider, and the charm trying to communicate should be the requirer.

### Joining the Mesh

For most charms, instantiating ServiceMeshConsumer automatically configures the charm
to join the mesh. For legacy "podspec" style charms or charms deploying custom
Kubernetes resources, you must manually apply the labels returned by
`ServiceMeshConsumer.labels()` to your pods.

## Provider

The ServiceMeshProvider implements the provider side of the juju relation. To provide a service mesh, instantiate ServiceMeshProvider in your charm's `__init__` method:

```python
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshProvider

class MyServiceMeshCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self._mesh = ServiceMeshProvider(
            charm=self,
            labels={"istio.io/dataplane-mode": "ambient"},
            mesh_relation_name="service-mesh",
        )
```

### Configuration

The `labels` argument specifies the labels that indicate to the service mesh that a Pod
should be subscribed to the mesh. These labels are service-mesh specific, for eg.:
- For Istio ambient mesh: `{"istio.io/dataplane-mode": "ambient"}`
- For Istio sidecar mesh: `{"istio-injection": "enabled"}`

### Accessing Mesh Policies

The provider exposes the `mesh_info()` method that returns a list of MeshPolicy objects
for configuring the service mesh:

```python
for policy in self._mesh.mesh_info():
    configure_service_mesh_policy(policy)
```

## Data Models

- **Method**: Defines enum for HTTP methods (GET, POST, PUT, etc.)
- **Endpoint**: Defines traffic endpoints with hosts, ports, methods, and paths
- **AppPolicy**: Defines application level authorization policy for the consumer
- **UnitPolicy**: Defines unit level authorization policy for the consumer
- **MeshPolicy**: Contains complete policy information for mesh configuration
- **CMRData**: Contains cross-model relation metadata
"""

import enum
import json
import logging
import warnings
from typing import Dict, List, Literal, Optional, Union

import httpx
import pydantic
from lightkube import Client
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import ConfigMap, Service
from ops import CharmBase, Object, RelationMapping

LIBID = "3f40cb7e3569454a92ac2541c5ca0a0c"  # Never change this
LIBAPI = 0
LIBPATCH = 7

PYDEPS = ["lightkube", "pydantic"]

logger = logging.getLogger(__name__)

# Juju application names are limited to 63 characters, so we can use the app_name directly here and still keep under
# Kubernetes's 253 character limit.
label_configmap_name_template = "juju-service-mesh-{app_name}-labels"


class Method(str, enum.Enum):
    """HTTP method."""

    connect = "CONNECT"
    delete = "DELETE"
    get = "GET"
    head = "HEAD"
    options = "OPTIONS"
    patch = "PATCH"
    post = "POST"
    put = "PUT"
    trace = "TRACE"


class Endpoint(pydantic.BaseModel):
    """Data type for a policy endpoint."""

    hosts: Optional[List[str]] = None
    ports: Optional[List[int]] = None
    methods: Optional[List[Method]] = None
    paths: Optional[List[str]] = None


class PolicyTargetType(str, enum.Enum):
    """Target type for Policy classes."""

    app = "app"
    unit = "unit"


class Policy(pydantic.BaseModel):
    """Data type for defining a policy for your charm."""

    relation: str
    endpoints: List[Endpoint]
    service: Optional[str] = None

    def __init__(self, **data):
        warnings.warn(
            "Polcy is deprecated. Use AppPolicy for fine-grained application-level policies "
            "or UnitPolicy to allow access to charm units. For migration, Policy can be "
            "directly replaced with AppPolicy.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(**data)


class AppPolicy(pydantic.BaseModel):
    """Data type for defining a policy for your charm application."""

    relation: str
    endpoints: List[Endpoint]
    service: Optional[str] = None


class UnitPolicy(pydantic.BaseModel):
    """Data type for defining a policy for your charm unit."""

    relation: str
    # UnitPolicy at the moment only supports access control over ports.
    # This limitation stems from the currenlty supported upstream service meshes (Istio).
    # Since other attributes of Endpoints class are not supported, the easiest implementation was to use just the ports attribute in this class.
    ports: Optional[List[int]] = None


class MeshPolicy(pydantic.BaseModel):
    """Data type for storage service mesh policy information."""

    source_app_name: str
    source_namespace: str
    target_app_name: str
    target_namespace: str
    target_service: Optional[str] = None
    target_type: Literal[PolicyTargetType.app, PolicyTargetType.unit] = PolicyTargetType.app
    endpoints: List[Endpoint]


class CMRData(pydantic.BaseModel):
    """Data type containing the info required for cross-model relations."""

    app_name: str
    juju_model_name: str


class ServiceMeshConsumer(Object):
    """Class used for joining a service mesh."""

    def __init__(
        self,
        charm: CharmBase,
        mesh_relation_name: str = "service-mesh",
        cross_model_mesh_requires_name: str = "require-cmr-mesh",
        cross_model_mesh_provides_name: str = "provide-cmr-mesh",
        policies: Optional[List[Union[Policy, AppPolicy, UnitPolicy]]] = None,
        auto_join: bool = True,
    ):
        """Class used for joining a service mesh.

        Args:
            charm: The charm instantiating this object.
            mesh_relation_name: The relation name as defined in metadata.yaml or charmcraft.yaml
                for the relation which uses the service_mesh interface.
            cross_model_mesh_requires_name: The relation name as defined in metadata.yaml or
                charmcraft.yaml for the relation which requires the cross_model_mesh interface.
            cross_model_mesh_provides_name: The relation name as defined in metadata.yaml or
                charmcraft.yaml for the relation which provides the cross_model_mesh interface.
            policies: List of access policies this charm supports.
            auto_join: Automatically join the mesh by applying labels to charm pods.
        """
        super().__init__(charm, mesh_relation_name)
        self._charm = charm
        self._relation = self._charm.model.get_relation(mesh_relation_name)
        self._cmr_relations = self._charm.model.relations[cross_model_mesh_provides_name]
        self._policies = policies or []
        self._label_configmap_name = label_configmap_name_template.format(app_name=self._charm.app.name)
        self._lightkube_client = None
        if auto_join:
            self.framework.observe(
                self._charm.on[mesh_relation_name].relation_changed, self._update_labels
            )
            self.framework.observe(
                self._charm.on[mesh_relation_name].relation_broken, self._on_mesh_broken
            )
        self.framework.observe(
            self._charm.on[mesh_relation_name].relation_created, self._relations_changed
        )
        self.framework.observe(
            self._charm.on[cross_model_mesh_requires_name].relation_created, self._send_cmr_data
        )
        self.framework.observe(
            self._charm.on[cross_model_mesh_provides_name].relation_changed,
            self._relations_changed,
        )
        self.framework.observe(self._charm.on.upgrade_charm, self._relations_changed)
        relations = {policy.relation for policy in self._policies}
        for relation in relations:
            self.framework.observe(
                self._charm.on[relation].relation_created, self._relations_changed
            )
            self.framework.observe(
                self._charm.on[relation].relation_broken, self._relations_changed
            )

    def _send_cmr_data(self, event):
        """Send app and model information for CMR."""
        data = CMRData(
            app_name=self._charm.app.name, juju_model_name=self._charm.model.name
        ).model_dump()
        event.relation.data[self._charm.app]["cmr_data"] = json.dumps(data)

    def _relations_changed(self, _event):
        self.update_service_mesh()

    def update_service_mesh(self):
        """Update the service mesh.

        Gathers information from all relations of the charm and updates the mesh appropriately to
        allow communication.
        """
        if self._relation is None:
            return
        logger.debug("Updating service mesh policies.")

        # Collect the remote data from any fully established cross_model_relation integrations
        # {remote application name: cmr relation data}
        cmr_application_data = {
            cmr.app.name: CMRData.model_validate(json.loads(cmr.data[cmr.app]["cmr_data"]))
            for cmr in self._cmr_relations if "cmr_data" in cmr.data[cmr.app]
        }

        mesh_policies = build_mesh_policies(
            relation_mapping=self._charm.model.relations,
            target_app_name=self._charm.app.name,
            target_namespace=self._my_namespace(),
            policies=self._policies,
            cmr_application_data=cmr_application_data
        )
        self._relation.data[self._charm.app]["policies"] = json.dumps(mesh_policies)

    def _my_namespace(self):
        """Return the namespace of the running charm."""
        # This method currently assumes the namespace is the same as the model name. We
        # should consider if there is a better way to do this.
        return self._charm.model.name

    def labels(self) -> dict:
        """Labels required for a pod to join the mesh."""
        if self._relation is None or "labels" not in self._relation.data[self._relation.app]:
            return {}
        return json.loads(self._relation.data[self._relation.app]["labels"])

    def _on_mesh_broken(self, _event):
        self._set_labels({})
        self._delete_label_configmap()

    def _update_labels(self, _event):
        self._set_labels(self.labels())

    def _set_labels(self, labels: dict) -> None:
        """Add labels to the charm's Pods (via StatefulSet) and Service to put the charm on the mesh."""
        reconcile_charm_labels(
            client=self.lightkube_client,
            app_name=self._charm.app.name,
            namespace=self._charm.model.name,
            label_configmap_name=self._label_configmap_name,
            labels=labels
        )

    def _delete_label_configmap(self) -> None:
        client = self.lightkube_client
        client.delete(res=ConfigMap, name=self._label_configmap_name)

    @property
    def lightkube_client(self):
        """Returns a lightkube client configured for this library.

        This indirection is implemented to avoid complex mocking in integration tests, allowing the integration tests to
        do something equivalent to:
            ```python
           mesh_consumer = ServiceMeshConsumer(...)
           mesh_consumer._lightkube_client = mocked_lightkube_client
           ```
        """
        if self._lightkube_client is None:
            self._lightkube_client = Client(
                namespace=self._charm.model.name, field_manager=self._charm.app.name
            )
        return self._lightkube_client


class ServiceMeshProvider(Object):
    """Provide a service mesh to applications."""

    def __init__(
        self, charm: CharmBase, labels: Dict[str, str], mesh_relation_name: str = "service-mesh"
    ):
        """Class used to provide information needed to join the service mesh.

        Args:
            charm: The charm instantiating this object.
            mesh_relation_name: The relation name as defined in metadata.yaml or charmcraft.yaml
                for the relation which uses the service_mesh interface.
            labels: The labels which related applications need to apply to use the mesh.
        """
        super().__init__(charm, mesh_relation_name)
        self._charm = charm
        self._relation_name = mesh_relation_name
        self._labels = labels
        self.framework.observe(
            self._charm.on[mesh_relation_name].relation_created, self._relation_created
        )

    def _relation_created(self, _event):
        self.update_relations()

    def update_relations(self):
        """Update all relations with the labels needed to use the mesh."""
        # Only the leader unit can update the application data bag
        if self._charm.unit.is_leader():
            rel_data = json.dumps(self._labels)
            for relation in self._charm.model.relations[self._relation_name]:
                relation.data[self._charm.app]["labels"] = rel_data

    def mesh_info(self) -> List[MeshPolicy]:
        """Return the relation data that defines Policies requested by the related applications."""
        mesh_info = []
        for relation in self._charm.model.relations[self._relation_name]:
            policies_data = json.loads(relation.data[relation.app]["policies"])
            policies = [MeshPolicy.model_validate(policy) for policy in policies_data]
            mesh_info.extend(policies)
        return mesh_info


def build_mesh_policies(
        relation_mapping: RelationMapping,
        target_app_name: str,
        target_namespace: str,
        policies: List[Union[Policy, AppPolicy, UnitPolicy]],
        cmr_application_data: Dict[str, CMRData]
) -> List[MeshPolicy]:
    """Generate MeshPolicy that implement the given policies for the currently related applications.

    Args:
        relation_mapping: Charm's RelatioMapping object, for example self.model.relations.
        target_app_name: The name of the target application, for example self.app.name.
        target_namespace: The namespace of the target application, for example self.model.name.
        policies: List of AppPolicy, or UnitPolicy objects defining the access rules.
        cmr_application_data: Data for cross-model relations, mapping app names to CMRData.
    """
    mesh_policies = []
    for policy in policies:
        for relation in relation_mapping[policy.relation]:
            if relation.app.name in cmr_application_data:
                logger.debug(f"Found cross model relation: {relation.name}. Creating policy.")
                source_app_name = cmr_application_data[relation.app.name].app_name
                source_namespace = cmr_application_data[relation.app.name].juju_model_name
            else:
                logger.debug(f"Found in-model relation: {relation.name}. Creating policy.")
                source_app_name = relation.app.name
                source_namespace = target_namespace

            if isinstance(policy, UnitPolicy):
                mesh_policies.append(
                    MeshPolicy(
                        source_app_name=source_app_name,
                        source_namespace=source_namespace,
                        target_app_name=target_app_name,
                        target_namespace=target_namespace,
                        target_service=None,
                        target_type=PolicyTargetType.unit,
                        endpoints=[
                            Endpoint(
                                ports=policy.ports,
                            )
                        ]
                        if policy.ports
                        else [],
                    ).model_dump()
                )
            else:
               mesh_policies.append(
                    MeshPolicy(
                        source_app_name=source_app_name,
                        source_namespace=source_namespace,
                        target_app_name=target_app_name,
                        target_namespace=target_namespace,
                        target_service=policy.service,
                        target_type=PolicyTargetType.app,
                        endpoints=policy.endpoints,
                    ).model_dump()
                )
    return mesh_policies


def reconcile_charm_labels(client: Client, app_name: str, namespace: str,  label_configmap_name: str, labels: Dict[str, str]) -> None:
    """Reconciles zero or more user-defined additional Kubernetes labels that are put on a Charm's Kubernetes objects.

    This function manages a group of user-defined labels that are added to a Charm's Kubernetes objects (the charm Pods
    (via editing the StatefulSet) and Service).  Its primary uses are:
    * adding labels to a Charm's objects
    * updating or removing labels on a Charm's Kubernetes objects that were previously set by this method

    To enable removal of labels, we also create a ConfigMap that stores the labels we last set.  This way the function
    itself can be stateless.

    This function takes a little care to avoid removing labels added by other means, but it does not provide exhaustive
    guarantees for safety.  It is up to the caller to ensure that the labels they pass in are not already in use.

    Args:
        client: The lightkube Client to use for Kubernetes API calls.
        app_name: The name of the application (Charm) to reconcile labels for.
        namespace: The namespace in which the application is running.
        label_configmap_name: The name of the ConfigMap that stores the labels.
        labels: A dictionary of labels to set on the Charm's Kubernetes objects. Any labels that were previously created
                by this method but omitted in `labels` now will be removed from the Kubernetes objects.
    """
    patch_labels = {}
    patch_labels.update(labels)
    stateful_set = client.get(res=StatefulSet, name=app_name)
    service = client.get(res=Service, name=app_name)
    try:
        config_map = client.get(ConfigMap, label_configmap_name)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            config_map = _init_label_configmap(client, label_configmap_name, namespace)
        else:
            raise
    if config_map.data:
        config_map_labels = json.loads(config_map.data["labels"])
        for label in config_map_labels:
            if label not in patch_labels:
                # The label was previously set. Setting it to None will delete it.
                patch_labels[label] = None
    if stateful_set.spec:
        stateful_set.spec.template.metadata.labels.update(patch_labels)  # type: ignore
    if service.metadata:
        service.metadata.labels = service.metadata.labels or {}
        service.metadata.labels.update(patch_labels)

    # Store our actively managed labels in a ConfigMap so next call we know which we might need to delete.
    # This should not include any labels that are nulled out as they're now out of scope.
    config_map_labels = {k: v for k, v in patch_labels.items() if v is not None}
    config_map.data = {"labels": json.dumps(config_map_labels)}
    client.patch(res=ConfigMap, name=label_configmap_name, obj=config_map)
    client.patch(res=StatefulSet, name=app_name, obj=stateful_set)
    client.patch(res=Service, name=app_name, obj=service)


def _init_label_configmap(client, name, namespace) -> ConfigMap:
    """Create a ConfigMap with data of {labels: {}}, returning the lightkube ConfigMap object."""
    obj = ConfigMap(
        data={"labels": "{}"},
        metadata=ObjectMeta(
            name=name,
            namespace=namespace,
        ),
    )
    client.create(obj=obj)
    return obj
