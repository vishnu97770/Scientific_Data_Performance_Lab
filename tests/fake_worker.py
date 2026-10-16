"""A stand-in worker for fault-injection tests. Behaviour is chosen by the FAKE_MODE variable."""

import json
import os
import signal
import sys
import time

mode = os.environ.get("FAKE_MODE", "ok")
req = json.loads(sys.stdin.read())

if req.get("job") == "prepare":
    if mode == "prepare_mismatch":
        out = {"status": "mismatch", "problems": [{"variant": "csv", "aspect": "bytes"}]}
    elif mode == "prepare_garbage":
        sys.stdout.write("not json\n")
        sys.exit(0)
    else:
        out = {
            "status": "ok",
            "dataset": {"dtype": {"names": []}, "sha256": "a" * 8},
            "array_sha256": "a" * 8,
            "preprocess_digest": "b" * 8,
            "files": {v: 1 for v in req["variants"]},
            "problems": [],
        }
    sys.stdout.write(json.dumps(out) + "\n")
    sys.exit(0)

if mode == "exit1":
    sys.stderr.write("boom\n")
    sys.exit(1)
if mode == "kill":
    os.kill(os.getpid(), signal.SIGKILL)
if mode == "sleep":
    time.sleep(30)
if mode == "garbage":
    sys.stdout.write("this is not json\n")
    sys.exit(0)
if mode == "two_lines":
    sys.stdout.write('{"status": "ok"}\n{"status": "ok"}\n')
    sys.exit(0)
if mode == "no_status":
    sys.stdout.write('{"hello": 1}\n')
    sys.exit(0)
if mode == "reported_failure":
    sys.stdout.write(json.dumps({"status": "failed", "error": "ValueError: nope"}) + "\n")
    sys.exit(0)

out = {
    "status": "ok",
    "correct": mode != "incorrect",
    "correctness_check": "fake",
    "timing": {"elapsed_ns": 1000, "process_time_ns": 900},
    "resources": {
        "ru_maxrss_kib": 40000,
        "vm_hwm_kib": 39000,
        "vm_rss_baseline_kib": 30000,
        "vm_hwm_baseline_kib": 30000,
        "hwm_reset": True,
    },
    "sizes": {"logical_bytes": req["rows"] * 34, "file_bytes": 7},
    "thread_env": {"OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS")},
}
sys.stdout.write(json.dumps(out) + "\n")
