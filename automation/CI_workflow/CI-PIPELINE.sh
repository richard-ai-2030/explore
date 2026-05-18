#!/usr/bin/env bash
set -euo pipefail

# CI PIPELINE AUTOMATION

# developers commit code changes
./automation/CI_workflow/1-commit-push-Git.sh "improve codes"

# auto build images for each Git push 
./automation/CI_workflow/2-build-domain-services.sh

# auto push to Containers Registry for each image built
./automation/CI_workflow/3-staging-services-Kubernetes.sh

# auto TEST with a Docker container node
./automation/CI_workflow/4-staging-smoke-test.sh

