#!/usr/bin/env bash
set -euo pipefail
export NATIVE_TEST_DISPLAY=${DISPLAY:?Private Xvfb display is required}
mkdir -p /results
ctest --test-dir /source/build --show-only=json-v1 > /results/native-plan.json
ctest --test-dir /source/build --output-on-failure --parallel 2 \
    --output-junit /results/native-junit.xml 2>&1 | tee /results/native.log
python3 - <<'PY'
import json
from pathlib import Path
import xml.etree.ElementTree as ET

plan = json.loads(Path('/results/native-plan.json').read_text())
cases = ET.parse('/results/native-junit.xml').getroot().findall('.//testcase')
assert cases, 'No native tests executed'
assert {case.attrib['name'] for case in cases} == {test['name'] for test in plan['tests']}
assert not any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped'))
print(f'PASS: all {len(cases)} native tests executed without failures or skips')
PY
