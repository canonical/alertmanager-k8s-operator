set quiet  # Recipes are silent by default
set export  # Just variables are exported to the environment

terraform := `which terraform || which tofu || echo ""` # require 'terraform' or 'opentofu'

[private]
default:
  just --list

# Lint everything
[group("Lint")]
lint: lint-terraform lint-terraform-docs

# Format everything 
[group("Format")]
fmt: format-terraform

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

# Format the Terraform modules
[group("Format")]
[working-directory("./terraform")]
format-terraform:
  if [ -z "${terraform}" ]; then echo "ERROR: please install terraform or opentofu"; exit 1; fi
  terraform init -upgrade -reconfigure && $terraform fmt -recursive -diff

# Validate the Terraform modules
[working-directory("./terraform")]
validate-terraform:
  if [ -z "${terraform}" ]; then echo "ERROR: please install terraform or opentofu"; exit 1; fi
  terraform init -upgrade -reconfigure && $terraform validate

# Format the Terraform documentation
[group("Format")]
[working-directory("./terraform")]
format-terraform-docs:
  terraform-docs --config .tfdocs-config.yml .
