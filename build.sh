#!/bin/sh
# Assemble the static site in dist/ for Cloudflare Pages.
set -e
cd "$(dirname "$0")"
rm -rf dist
mkdir -p dist/py
cp index.html dist/
cp -R static dist/static
for f in *.py; do
    case "$f" in test_*) continue ;; esac
    cp "$f" dist/py/
done
ls dist/py | grep '\.py$' | python3 -c "import json,sys; print(json.dumps([l.strip() for l in sys.stdin]))" > dist/py/manifest.json
cat > dist/_headers <<'H'
/py/*
  Cache-Control: public, max-age=300
/static/*
  Cache-Control: public, max-age=300
H
