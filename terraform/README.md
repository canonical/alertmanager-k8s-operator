# Alertmanager Operator (k8s) Terraform Module

This folder contains a base [Terraform][Terraform] module for the alertmanager-k8s charm.

The module uses the [Terraform Juju provider][Terraform Juju provider] to model the charm
deployment onto any Kubernetes environment managed by [Juju][Juju].

The module can be used to deploy the Alertmanager to a Kubernetes cluster separately 
as well as a part of a higher level Terraform module, depending on the deployment architecture.

## Module structure

- **main.tf** - Defines the Juju application to be deployed.
- **variables.tf** - Allows customization of the deployment. Except for exposing the deployment
  options (Juju model name, channel or application name) also allows overwriting charm's default
  configuration.
- **output.tf** - Responsible for integrating the module with other Terraform modules, primarily
  by defining potential integration endpoints (charm integrations), but also by exposing
  the application name.
- **terraform.tf** - Defines the Terraform provider.

## Deploying alertmanager-k8s base module separately

### Pre-requisites

- A Kubernetes cluster
- Juju 3.x
- Juju controller bootstrapped onto the K8s cluster
- Terraform

### Deploying Alertmanager with Terraform

Clone the [alertmanager-k8s-operator][alertmanager-repo] Git repository.

From inside the `terraform` folder, initialize the provider:

```shell
terraform init
```

Create Terraform plan:

```shell
terraform plan
```

While creating the plan, the default configuration can be overwritten with `-var-file`. To do that,
Terraform `tfvars` file should be prepared prior to the plan creation.

Deploy UPF:

```console
terraform apply -auto-approve 
```

### Cleaning up

Destroy the deployment:

```shell
terraform destroy -auto-approve
```

## Using alertmanager-k8s base module in higher level modules

If you want to use `alertmanager-k8s` base module as part of your Terraform module, import it
like shown below:

```text
module "alertmanager" {
  source = "git::https://github.com/canonical/alertmanager-k8s-operator//terraform"
  
  model_name = "juju_model_name"
  config = Optional config map
}
```

Create integrations, for instance:

```text
resource "juju_integration" "metrics" {
  model = var.model_name
  application {
    name     = module.alertmanager.app_name
    endpoint = module.alertmanager.metrics_endpoint
  }
  application {
    name     = module.prometheus.app_name
    endpoint = module.prometheus.metrics_endpoint
  }
}
```

The complete list of available integrations can be found [here][alertmanager-integrations].

[Terraform]: https://www.terraform.io/
[Terraform Juju provider]: https://registry.terraform.io/providers/juju/juju/latest
[Juju]: https://juju.is
[alertmanager-repo]: https://github.com/canonical/alertmanager-k8s-operator
[alertmanager-integrations]: https://charmhub.io/alertmanager-k8s/integrations
