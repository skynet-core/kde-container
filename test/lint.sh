#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
artifacts="$root/test/.artifacts/lint"
mkdir -p "$artifacts"
shell_files=()
cpp_files=()
dockerfiles=()
while IFS= read -r -d '' file; do
    [[ -f $file ]] || continue
    case $file in
        *.sh | bin/* | libexec/* | build/*)
            IFS= read -r first_line < "$file" || true
            if [[ $first_line == '#!'*bash* ]]; then shell_files+=("$file"); fi
            ;;
        *.cpp) cpp_files+=("$file") ;;
        Dockerfile.* | */Dockerfile.*) dockerfiles+=("$file") ;;
    esac
done < <(git ls-files --cached --others --exclude-standard -z)

shellcheck --severity=style "${shell_files[@]}"
ruff check .
ruff format --check .
python3 build/render-dockerfiles.py --check
hadolint --failure-threshold info "${dockerfiles[@]}"
actionlint
clang-format --dry-run --Werror "${cpp_files[@]}"
[[ -f build/compile_commands.json ]] || {
    printf 'Configure and build native/ first; see README.md#linting.\n' >&2
    exit 1
}
for file in "${cpp_files[@]}"; do
    log="$artifacts/$(basename -- "$file").clangd.log"
    # Refactoring self-tests are separate from compiler, include and tidy diagnostics.
    if ! clangd --check="$file" --clang-tidy --tweaks= > "$log" 2>&1 || rg -q '^[EW]\[' "$log"; then
        cat "$log"
        exit 1
    fi
done
clang-tidy --quiet -p build native/*.cpp
clang-tidy --quiet compat/*.cpp -- -std=c++17
xmllint --noout --dtdvalid /usr/share/wayland/wayland.dtd native/fake-input.xml
xmllint --noout docs/diagrams/*.svg
python3 -m json.tool docs/diagrams/config.json > /dev/null
printf 'PASS: ShellCheck, Ruff, Hadolint, actionlint, clang-format, clangd, clang-tidy, XML and JSON.\n'
printf 'Clangd logs: %s\n' "$artifacts"
