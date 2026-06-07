#!/bin/bash

# Single unified server on port 8765
# Serves:
#   - Public site on /
#   - Photos on /photos/
#   - Admin interface on /admin/

cd "$(dirname "$0")/photos" || exit 1

python3 admin_server.py
