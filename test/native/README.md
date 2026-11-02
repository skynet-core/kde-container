# Native regression tests

These tests compile the maintained native and compatibility sources. The
Wayland harness checks the real pointer callbacks and protocol messages; Qt
events drive the fixture and clipboard code. The tests link the patched
TigerVNC viewer objects and KRFB PipeWire framebuffer objects used by the image,
including the actual KRFB damage method and LibVNCServer modified regions.

The regressions cover pointer entry with one event, scaled and offset outputs,
caller preload restoration, XTest calibration flushing, full SHA1/AES buffers,
first framebuffer allocation, RGBX channel layout, padded rows and resize/null
frames, inclusive/exclusive damage edges, and clipboard transport metadata.
The pinned KPipeWire private cleanup declaration retains its original license
and is checksum-checked before the frame callback test is compiled.

Build the isolated SDK from the maintained Fedora build stages:

```sh
mkdir -p test/.artifacts/native
cat Dockerfile.fedora-44 test/native/Dockerfile.fragment > test/.artifacts/native/Dockerfile
docker build --target native-tests -f test/.artifacts/native/Dockerfile -t plasma6:native-tests .
docker run --rm --network none \
  --mount "type=bind,source=$PWD/test/.artifacts/native,target=/results" plasma6:native-tests
```

The entrypoint creates a private Xvfb and runs every configured CTest case.
JUnit, the test plan and full output are retained in the mounted directory.
Failed, missing or skipped cases fail the run. The image includes a combined
`/source/build/compile_commands.json` for production sources, these tests and
the actual TigerVNC/KRFB test targets, so `clangd --check` can use the matching
SDK headers and flags. No native test binaries or test dependencies enter a
production stage.

The same image contains `clangd` and `clang-tidy` only in its test SDK. Run the
complete standard lint entrypoint after building it:

```sh
NATIVE_TEST_IMAGE=plasma6:native-tests ./test/lint.sh
```

This mode compares the checkout's native, compatibility, test/CMake, patch,
Fedora build/package and compiler-configuration hashes against files inside
the image before any compiler check runs. The verifier is mounted from the
checkout, so a stale image cannot bypass the comparison. Missing or changed
inputs fail and require rebuilding the SDK. The exact manifest and compiler
logs are retained under `test/.artifacts/lint`.

Without `NATIVE_TEST_IMAGE`, `test/lint.sh` retains its host compiler mode and
requires the complete merged native test compilation DB on the host. Host-side
ShellCheck, Ruff, generated Dockerfile, Hadolint, actionlint, clang-format and
XML/JSON checks retain their existing scope. Every maintained C++ source must
have a real compilation command; the script fails rather than using fallback
flags for an unconfigured file.
