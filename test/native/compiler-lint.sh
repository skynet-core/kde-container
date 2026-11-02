#!/usr/bin/env bash
# Run the same compiler checks with the SDK's real headers and merged build DB.
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"
artifacts=${1:-$root/test/.artifacts/lint}
mkdir -p "$artifacts"
[[ -f build/compile_commands.json ]] || {
    printf 'Build the native test SDK first; see test/native/README.md.\n' >&2
    exit 1
}
if (($# > 1)); then
    cpp_files=("${@:2}")
else
    mapfile -d '' -t cpp_files < <(python3 - <<'PY'
from pathlib import Path
import sys
for folder in ('native', 'compat', 'test'):
    for path in sorted(Path(folder).rglob('*.cpp')):
        if '.artifacts' not in path.parts:
            sys.stdout.write(str(path) + '\0')
PY
    )
fi
python3 - "${cpp_files[@]}" <<'PY'
import json
from pathlib import Path
import sys
commands = json.loads(Path('build/compile_commands.json').read_text())
compiled = {(Path(command['directory']) / command['file']).resolve() for command in commands}
for path in sys.argv[1:]:
    assert Path(path).resolve() in compiled, f'No real compile command for {path}'
PY
for file in "${cpp_files[@]}"; do
    log="$artifacts/$(basename -- "$file").clangd.log"
    if ! clangd --check="$file" --clang-tidy --tweaks= > "$log" 2>&1 || grep -q '^[EW]\[' "$log"; then
        cat "$log"
        exit 1
    fi
done
clang-tidy --quiet -p build native/*.cpp
clang-tidy --quiet -p build compat/*.cpp
printf 'PASS: clangd and clang-tidy with the actual native SDK compilation commands.\n'
