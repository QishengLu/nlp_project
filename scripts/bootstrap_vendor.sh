#!/usr/bin/env bash
# Bootstrap the project's vendored toolchain into <project>/vendor/.
# Idempotent: re-runs are safe; existing components are skipped.
#
# Installs (all user-local, no sudo, no system pollution):
#   vendor/jdk8/        Temurin OpenJDK 1.8.0_422  (Defects4J 2.x requires JDK 8)
#   vendor/defects4j/   Defects4J v2.0.1 (commit a83e479)
#   vendor/perl5/       D4J's Perl module deps (DBI, JSON, etc.)
#   vendor/bin/cpanm    cpanminus, used to install the Perl modules above
#
# Usage:
#   bash scripts/bootstrap_vendor.sh
#   source scripts/activate_env.sh   # then this every shell

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/vendor"
mkdir -p "$VENDOR/bin"

JDK_TARBALL="OpenJDK8U-jdk_x64_linux_hotspot_8u422b05.tar.gz"
JDK_URL="https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u422-b05/${JDK_TARBALL}"
JDK_DIR="$VENDOR/jdk8"

D4J_TAG="v2.0.1"
D4J_DIR="$VENDOR/defects4j"
PERL_DIR="$VENDOR/perl5"
CPANM_BIN="$VENDOR/bin/cpanm"

# 1. JDK 8 -------------------------------------------------------------------
if [ -x "$JDK_DIR/bin/java" ]; then
  echo "[1/4] JDK 8 already present at $JDK_DIR — skip"
else
  echo "[1/4] Downloading Temurin JDK 8 (~99MB)..."
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl -sSL -o "$tmp/jdk8.tar.gz" "$JDK_URL"
  mkdir -p "$JDK_DIR"
  tar xzf "$tmp/jdk8.tar.gz" -C "$tmp"
  # Adoptium tarball unpacks as jdk8uXXX-bYY/; flatten into JDK_DIR.
  inner=$(find "$tmp" -maxdepth 1 -type d -name 'jdk8u*' | head -1)
  cp -a "$inner/." "$JDK_DIR/"
  trap - EXIT
  rm -rf "$tmp"
  "$JDK_DIR/bin/java" -version 2>&1 | head -1
fi

# 2. cpanm -------------------------------------------------------------------
if [ -x "$CPANM_BIN" ]; then
  echo "[2/4] cpanm already present — skip"
else
  echo "[2/4] Installing cpanm to $CPANM_BIN"
  curl -sSL https://cpanmin.us -o "$CPANM_BIN"
  chmod +x "$CPANM_BIN"
fi

# 3. Perl modules required by Defects4J -------------------------------------
PERL_DEPS=(DBI DBD::CSV JSON IPC::System::Simple JSON::Parse IO::CaptureOutput)
if [ -d "$PERL_DIR/lib/perl5" ] && \
   PERL5LIB="$PERL_DIR/lib/perl5" perl -e 'use DBI; use JSON; use IPC::System::Simple; use JSON::Parse; use IO::CaptureOutput; 1' 2>/dev/null; then
  echo "[3/4] Perl deps already installed at $PERL_DIR — skip"
else
  echo "[3/4] Installing Perl deps to $PERL_DIR (cpanm, ~1 minute)"
  "$CPANM_BIN" --notest -l "$PERL_DIR" "${PERL_DEPS[@]}" >/tmp/cpanm-bootstrap.log 2>&1 || {
    echo "  cpanm failed; tail of log:"
    tail -30 /tmp/cpanm-bootstrap.log
    exit 1
  }
fi

# 4. Defects4J --------------------------------------------------------------
if [ -x "$D4J_DIR/framework/bin/defects4j" ] && [ -d "$D4J_DIR/major" ]; then
  echo "[4/4] Defects4J already initialized at $D4J_DIR — skip"
else
  if [ ! -d "$D4J_DIR" ]; then
    echo "[4/4a] Cloning rjust/defects4j @ $D4J_TAG"
    git clone --depth 1 --branch "$D4J_TAG" \
        https://github.com/rjust/defects4j.git "$D4J_DIR"
  fi
  echo "[4/4b] Running defects4j init.sh (~3GB downloads, several minutes)"
  (
    cd "$D4J_DIR"
    JAVA_HOME="$JDK_DIR" \
    PATH="$VENDOR/bin:$PERL_DIR/bin:$JDK_DIR/bin:$D4J_DIR/framework/bin:$PATH" \
    PERL5LIB="$PERL_DIR/lib/perl5" \
    ./init.sh
  )
fi

echo
echo "Bootstrap complete. Next:"
echo "  source scripts/activate_env.sh"
echo "  python -m pytest"
