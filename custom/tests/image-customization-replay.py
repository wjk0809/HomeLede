#!/usr/bin/env python3
"""Exercise owned GPT patch replay in an isolated tree; no images or builds."""
import pathlib
import shutil
import subprocess
import sys
import tempfile

root = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="homelede-gpt-replay-") as directory:
    sandbox = pathlib.Path(directory)
    files = (
        "scripts/gen_image_generic.sh",
        "custom/apply-image-customizations.sh",
        "custom/patches/001-x86-complete-gpt.patch",
    )
    for name in files:
        target = sandbox / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    subprocess.run(["git", "init", "-q", str(sandbox)], check=True)
    script = sandbox / files[0]
    original = script.read_bytes()
    def run(*args, check=True):
        return subprocess.run(args, cwd=sandbox, check=check, capture_output=True)
    assert run("sh", files[1], "--check", check=False).returncode != 0
    first = run("sh", files[1])
    patched = script.read_bytes()
    assert patched != original
    assert b"GPT_ALT=1" in patched and b"${GPT_ALT:+-d 0}" in patched
    run("sh", "-n", files[0])
    run("sh", files[1])
    assert script.read_bytes() == patched, "second replay changed bytes"
    run("sh", files[1], "--check")
    run("git", "apply", "--reverse", "--check", files[2])
    run("git", "apply", "--reverse", files[2])
    assert script.read_bytes() == original, "reverse lost upstream options"
    script.write_bytes(original.replace(b"# create partition table", b"# incompatible partition context"))
    incompatible = script.read_bytes()
    assert run("sh", files[1], check=False).returncode != 0
    assert script.read_bytes() == incompatible, "failed replay changed source"
print("PASS: GPT replay, idempotency, reverse preservation and fail-closed mismatch")
