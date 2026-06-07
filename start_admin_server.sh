#!/bin/bash

cd "$(dirname "$0")/photos" || exit 1

python3 admin_server.py
