#!/bin/bash
# Copy the NS-3 sources into ns-3/scratch and build the simulation.
set -e
NS3_DIR="${NS3_DIR:-$HOME/ns-3}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${NS3_DIR:?}/scratch/tcp-predictor"
if command -v rsync > /dev/null; then
  mkdir -p "$TARGET"
  rsync -a --delete "$PROJECT_DIR/ns3/" "$TARGET/"
else
  # rsync is not installed on every Linux system: replace the folder with a plain copy
  rm -rf "$TARGET"
  mkdir -p "$TARGET"
  cp -R "$PROJECT_DIR/ns3/." "$TARGET/"
fi
cd "$NS3_DIR"
./ns3 build tcp-predictor
