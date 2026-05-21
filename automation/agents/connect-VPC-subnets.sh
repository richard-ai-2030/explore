#!/usr/bin/env bash
set -euo pipefail

echo "connecting subnets ..."

# unplug
for node in staging-worker2 staging-worker staging-control-plane; do docker stop $node; done
for d in kafka redis postgres; do docker network disconnect kind $d; done

# replug
for node in staging-worker2 staging-worker staging-control-plane; do docker start $node; done
for c in postgres redis kafka; do docker network connect kind $c; done

docker network ls
docker network inspect kind

echo "subnets connected."