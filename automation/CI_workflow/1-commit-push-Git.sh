#!/usr/bin/env bash
set -euo pipefail

MESSAGE="${1:-commit code changes}"

# stage files using git add
git status
git add .

# create a snapshot with git commit, then upload it to the remote repository
git commit -m "$MESSAGE"
git push origin master

echo "Git push Done - $MESSAGE"