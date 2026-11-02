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
if [[ -n ${NATIVE_TEST_IMAGE:-} ]]; then
    python3 test/native/sdk-inputs.py "$NATIVE_TEST_IMAGE" "$artifacts" "${cpp_files[@]}"
else
    bash test/native/compiler-lint.sh "$artifacts" "${cpp_files[@]}"
fi
xmllint --noout --dtdvalid /usr/share/wayland/wayland.dtd native/*.xml
xmllint --noout docs/diagrams/*.svg
python3 -m json.tool docs/diagrams/config.json > /dev/null
printf 'PASS: ShellCheck, Ruff, Hadolint, actionlint, clang-format, clangd, clang-tidy, XML and JSON.\n'
printf 'Clangd logs: %s\n' "$artifacts"
