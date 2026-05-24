#!/usr/bin/env bash
set -euo pipefail

MESSAGE="${1:-commit code changes}"

git status
git add .                   # stage files using git add

git commit -m "$MESSAGE"    # create a snapshot with git commit
git push origin master      # upload it to the remote repository

echo "Git push Done - $MESSAGE"