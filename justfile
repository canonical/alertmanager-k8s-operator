set quiet  # Recipes are silent by default
set export  # Just variables are exported to the environment

terraform := `which terraform || which tofu || echo ""` # require 'terraform' or 'opentofu'

[private]
default:
  just --list

# Lint everything
[group("Lint")]
lint: lint-terraform lint-terraform-docs validate-terraform lint-terraform-endpoints

# Format everything 
[group("Format")]
fmt: format-terraform format-terraform-docs

# Lint the Terraform modules
[group("Lint")]
[working-directory("./terraform")]
lint-terraform:
  if [ -z "${terraform}" ]; then echo "ERROR: please install terraform or opentofu"; exit 1; fi
  $terraform init -upgrade -reconfigure && $terraform fmt -check -recursive -diff

# Lint the Terraform documentation
[group("Lint")]
[working-directory("./terraform")]
lint-terraform-docs:
  terraform-docs --config .tfdocs-config.yml .

# Validate the Terraform modules
[group("Lint")]
[working-directory("./terraform")]
validate-terraform:
  if [ -z "${terraform}" ]; then echo "ERROR: please install terraform or opentofu"; exit 1; fi
  terraform init -upgrade -reconfigure && $terraform validate

# Lint the endpoints in outputs.tf compared to the charmcraft.yaml
[group("Lint")]
lint-terraform-endpoints:
  #!/usr/bin/env bash
  if [ -z "${terraform}" ]; then echo "ERROR: please install terraform or opentofu"; exit 1; fi
  requires_keys=$(yq eval '.requires | keys | .[]' charmcraft.yaml)
  provides_keys=$(yq eval '.provides | keys | .[]' charmcraft.yaml)
  endpoints_keys=$(grep -oP '^\s*\w+\s*=\s*"\K[^"]+' terraform/outputs.tf)

  missing_keys=0

  # Check requires keys
  for key in $requires_keys; do
    if ! echo "$endpoints_keys" | grep -q "^$key$"; then
        echo "$key is missing from endpoints"
        missing_keys=1
    fi
  done

  # Check provides keys
  for key in $provides_keys; do
    if ! echo "$endpoints_keys" | grep -q "^$key$"; then
        echo "$key is missing from endpoints"
        missing_keys=1
    fi
  done

  # Exit with a non-zero code if any keys are missing
  if [ $missing_keys -ne 0 ]; then
    exit 1
  fi

# Format the Terraform modules
[group("Format")]
[working-directory("./terraform")]
format-terraform:
  if [ -z "${terraform}" ]; then echo "ERROR: please install terraform or opentofu"; exit 1; fi
  terraform init -upgrade -reconfigure && $terraform fmt -recursive -diff

# Format the Terraform documentation
[group("Format")]
[working-directory("./terraform")]
format-terraform-docs:
  terraform-docs --config .tfdocs-config.yml .
