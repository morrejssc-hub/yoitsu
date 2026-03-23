#!/bin/sh
set -eu

python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8100/control/status", timeout=5).read()'
