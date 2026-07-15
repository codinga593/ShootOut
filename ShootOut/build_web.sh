#!/usr/bin/env sh
set -eu

pygbag \
  --build \
  --archive \
  --title ShootOut \
  --app_name ShootOut \
  --ume_block 0 \
  --width 1280 \
  --height 800 \
  .

python3 prepare_web_runtime.py

printf '%s\n' 'Browser build created in build/web and build/web.zip'
