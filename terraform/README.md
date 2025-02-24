# Terraform module for alertmanager-k8s

Terraform module for Alertmanager K8s charmed operator

This is a Terraform module facilitating the deployment of Alertmanager, using the [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs).


## Requirements
This module requires a `juju` model to be available. Refer to the [usage section](#usage) below for more details.

## API

### Inputs
The module offers the following configurable inputs:

| Name | Type | Description | Default value |
| - | - | - | - |
| `app_name`|  string | Application name | Alertmanager |
| `channel` | string | Channel that the charms are deployed from | latest/stable |
| `constraints` | string | Constraints to be applied | "" |
| `model_name` | string | Name of the model that the charm is deployed on | ""  |
| `revision` | number | Charm revision | null |


### Outputs
Upon application, the module exports the following outputs:

| Name | Description |
| - | - |
| `app_name`|  Application name |
| `endpoints`| Map of endpoints |


## Usage


### Basic usage

Users should ensure that Terraform is aware of the `juju_model` dependency of the charm module.

To deploy this module with its needed dependency, you can run `terraform apply -var="model_name=<MODEL_NAME>" -auto-approve`. This would deploy all COS HA solution modules in the same model.
