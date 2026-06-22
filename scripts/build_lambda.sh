#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build"
PACKAGE_DIR="$BUILD_DIR/package"
ZIP_PATH="$BUILD_DIR/lambda.zip"

rm -rf "$BUILD_DIR"
mkdir -p "$PACKAGE_DIR"

docker run --rm \
  -v "$ROOT_DIR":/var/task \
  -w /var/task \
  public.ecr.aws/sam/build-python3.12:latest \
  /bin/bash -lc "python -m pip install --upgrade pip && pip install -r requirements.txt -t build/package"

cp -R "$ROOT_DIR/src/"* "$PACKAGE_DIR/"

cd "$PACKAGE_DIR"
zip -qr "$ZIP_PATH" .

echo "Built $ZIP_PATH"
