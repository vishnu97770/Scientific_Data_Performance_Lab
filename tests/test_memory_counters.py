"""Reproduce the parent-peak inheritance effect that motivated ADR-005 (Linux only)."""

import subprocess
import sys

import pytest

CHILD = (
    "import json,re,resource;"
    "t=open('/proc/self/status').read();"
    "g=lambda k:int(re.search(k+r':\\s+(\\d+) kB',t).group(1));"
    "print(json.dumps({'ru':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'hwm':g('VmHWM')}))"
)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc and ru_maxrss in KiB")
def test_child_ru_maxrss_can_inherit_the_parent_peak_while_vm_hwm_stays_independent():
    import json

    block = bytearray(300 * 1024 * 1024)  # touch ~300 MiB in the parent, then release it
    for i in range(0, len(block), 4096):
        block[i] = 1
    del block
    out = subprocess.run(
        [sys.executable, "-I", "-c", CHILD], capture_output=True, text=True, check=True
    ).stdout
    child = json.loads(out)
    # Large margins on purpose: the point is the effect, not exact numbers.
    assert child["hwm"] < 100 * 1024, "VmHWM must reflect only the child's own memory"
    assert child["ru"] > 200 * 1024, "ru_maxrss is floored by the parent's peak at launch"
