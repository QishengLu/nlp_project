# Source this file from a bash shell BEFORE running apr-agent / pytest.
#   source scripts/activate_env.sh
# Adds: JDK 8, defects4j on PATH, Perl modules for D4J, project venv, TZ lock.

export JAVA_HOME="/home/nn/.local/opt/jdk8u422-b05"
export DEFECTS4J_HOME="/home/nn/defects4j"
export PERL5LIB="/home/nn/perl5/lib/perl5"
export TZ="America/Los_Angeles"

# Prepend each only if not already present.
case ":$PATH:" in
  *":$DEFECTS4J_HOME/framework/bin:"*) ;;
  *) export PATH="$DEFECTS4J_HOME/framework/bin:$PATH" ;;
esac
case ":$PATH:" in
  *":$JAVA_HOME/bin:"*) ;;
  *) export PATH="$JAVA_HOME/bin:$PATH" ;;
esac
case ":$PATH:" in
  *":/home/nn/perl5/bin:"*) ;;
  *) export PATH="/home/nn/perl5/bin:$PATH" ;;
esac

# Activate the project venv if not already active.
if [ -z "${VIRTUAL_ENV:-}" ] && [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "[apr-agent env] java=$(java -version 2>&1 | head -1) defects4j=$(which defects4j) tz=$TZ"
