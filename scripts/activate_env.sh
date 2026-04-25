# Source this file from a bash shell BEFORE running apr-agent / pytest.
#   source scripts/activate_env.sh
#
# Self-contained: every dep is under <project>/vendor/. The only thing this
# script touches outside the project is your shell's PATH (prepends entries).
# Project-relative so checking out the repo on another machine + bootstrapping
# vendor/ reproduces the same env.

# Resolve the project root from this script's own location, regardless of cwd.
__APR_AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export JAVA_HOME="${__APR_AGENT_ROOT}/vendor/jdk8"
export DEFECTS4J_HOME="${__APR_AGENT_ROOT}/vendor/defects4j"
export PERL5LIB="${__APR_AGENT_ROOT}/vendor/perl5/lib/perl5"
export TZ="America/Los_Angeles"

# Prepend each only if not already present. Order matters: defects4j first so
# `which defects4j` resolves to ours; jdk8 next so `java`/`javac` are 1.8.
for __dir in \
    "${DEFECTS4J_HOME}/framework/bin" \
    "${JAVA_HOME}/bin" \
    "${__APR_AGENT_ROOT}/vendor/perl5/bin" \
    "${__APR_AGENT_ROOT}/vendor/bin" ; do
  case ":$PATH:" in
    *":${__dir}:"*) ;;
    *) export PATH="${__dir}:$PATH" ;;
  esac
done
unset __dir

# Activate the project venv unless it's already active. We can't rely on
# `[ -z "$VIRTUAL_ENV" ]` because some terminal harnesses (VS Code remote,
# Cursor, etc.) inject a stale VIRTUAL_ENV pointing at a host-side python.
# Compare to the project's own venv path instead.
if [ -f "${__APR_AGENT_ROOT}/.venv/bin/activate" ] && \
   [ "${VIRTUAL_ENV:-}" != "${__APR_AGENT_ROOT}/.venv" ]; then
  # shellcheck disable=SC1091
  source "${__APR_AGENT_ROOT}/.venv/bin/activate"
fi

echo "[apr-agent env] root=${__APR_AGENT_ROOT}"
echo "                java=$(java -version 2>&1 | head -1)"
echo "                defects4j=$(command -v defects4j)  tz=$TZ"
unset __APR_AGENT_ROOT
