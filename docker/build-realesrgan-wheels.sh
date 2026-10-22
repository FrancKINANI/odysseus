#!/usr/bin/env bash
# Build patched wheels for Real-ESRGAN's unmaintained dependencies.
#
# basicsr / gfpgan / facexlib (xinntao, last released 2022) read their version
# in setup.py with:
#
#     exec(compile(f.read(), version_file, 'exec'))
#     return locals()['__version__']
#
# Python 3.13+ implements PEP 667: locals() inside a function returns an
# independent snapshot that exec() can no longer mutate, so the read raises
# `KeyError: '__version__'` and the sdist build fails. That is why the Cookbook
# "install realesrgan" button dies on the python:3.14 image. The packages have
# no fixed release, so we patch get_version() to exec into an explicit namespace
# dict (works on every Python) and build wheels from the patched source.
#
# Those same setup.py files declare setup_requires, which PEP 517 turns into
# build requirements and pip therefore resolves in the isolated build env — see
# the note at the patch site below.
#
# Usage: build-realesrgan-wheels.sh [OUTPUT_DIR]   (default: /wheels)
set -euo pipefail

OUT="${1:-/wheels}"
mkdir -p "$OUT"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

# Pinned to the versions Real-ESRGAN 0.3.0 resolves to.
SPECS="basicsr==1.4.2 gfpgan==1.3.8 facexlib==0.3.0"

for spec in $SPECS; do
  name="${spec%%==*}"
  ver="${spec##*==}"
  # pip download builds metadata (and trips the same bug), so fetch the raw
  # sdist URL from the PyPI JSON API instead.
  url="$(python - "$name" "$ver" <<'PY'
import json, sys, urllib.request
name, ver = sys.argv[1], sys.argv[2]
data = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json"))
for f in data["urls"]:
    if f["packagetype"] == "sdist":
        print(f["url"]); break
else:
    sys.exit(f"no sdist found for {name}=={ver}")
PY
)"
  echo ">> fetching ${name} ${ver}: ${url}"
  curl -fsSL "$url" -o "${name}.tar.gz"
  tar xzf "${name}.tar.gz"
done

echo ">> patching get_version() and dropping setup_requires"
python - <<'PY'
import pathlib
import re

old_exec = "exec(compile(f.read(), version_file, 'exec'))"
new_exec = "_ver_ns = {}\n        exec(compile(f.read(), version_file, 'exec'), _ver_ns)"
old_ret = "return locals()['__version__']"
new_ret = "return _ver_ns['__version__']"

# setup_requires is not a runtime hint: setuptools reports it through
# get_requires_for_build_wheel, so pip installs it into the throwaway PEP 517
# build env — and `pip wheel --no-deps` does not exempt it. basicsr asks for
# ['cython', 'numpy', 'torch'] and gfpgan/facexlib for ['cython', 'numpy'],
# which on Python 3.14 dies with `No matching distribution found for torch`
# (torch ships no cp314 wheels) or for numpy when the index cannot resolve it.
# Dropping the keyword changes nothing about the built wheel: no extension is
# compiled here (basicsr only builds its CUDA exts when BASICSR_EXT=True) and
# install_requires — the metadata the Cookbook and runtime actually read — is
# left intact.
setup_requires_re = re.compile(r"^[ \t]*setup_requires=\[[^\]]*\],\n", re.M)

version_patched = requires_dropped = 0
for setup in sorted(pathlib.Path(".").glob("*/setup.py")):
    s = setup.read_text()
    if old_exec in s and old_ret in s:
        s = s.replace(old_exec, new_exec).replace(old_ret, new_ret)
        version_patched += 1
        print("   patched get_version()", setup)
    s, n = setup_requires_re.subn("", s)
    if n:
        requires_dropped += 1
        print("   dropped setup_requires", setup)
    setup.write_text(s)
assert version_patched == 3, f"expected to patch 3 get_version() bodies, patched {version_patched}"
assert requires_dropped == 3, f"expected to drop setup_requires from 3 setup.py files, dropped {requires_dropped}"
PY

echo ">> building wheels into ${OUT}"
pip wheel --no-deps -w "$OUT" ./basicsr-* ./gfpgan-* ./facexlib-*
ls -l "$OUT"
