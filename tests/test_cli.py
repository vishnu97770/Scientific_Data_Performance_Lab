import json
import subprocess
import sys
from pathlib import Path

import pytest

from sdplab.cli import EXIT_CODES_HELP, main


def toml(tmp_path, *, sizes="[600]", extra=""):
    path = tmp_path / "c.toml"
    path.write_text(
        "config_schema_version = 1\n"
        f"[dataset]\nsizes = {sizes}\ndata_dir = '{tmp_path}/data'\n"
        "[trials]\nwarmup_rounds = 1\nmeasured_rounds = 2\ntimeout_s = 60\n"
        f"[output]\nresults_dir = '{tmp_path}/results'\n{extra}",
        encoding="utf-8",
    )
    return str(path)


def test_help_exits_zero_and_documents_the_exit_codes(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage: sdplab" in out
    for command in ("info", "prepare", "validate", "run", "report"):
        assert command in out
    assert " ".join(EXIT_CODES_HELP.split()) in " ".join(out.split())


def test_a_missing_command_and_an_unknown_option_are_usage_errors():
    for argv in ([], ["--no-such-option"], ["run"], ["report"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 2


def test_module_entry_point_and_version_in_a_fresh_interpreter():
    for argv, needle in ((["--help"], "usage: sdplab"), (["--version"], "sdplab ")):
        proc = subprocess.run(
            [sys.executable, "-I", "-m", "sdplab", *argv],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert needle in proc.stdout


def test_importing_the_run_path_never_loads_matplotlib():
    code = (
        "import sys; import sdplab.cli, sdplab.runner, sdplab.worker, sdplab.results; "
        "sys.exit(1 if 'matplotlib' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0


def test_info_prints_the_environment_as_json(capsys, tmp_path):
    assert main(["info", "--config", toml(tmp_path)]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["environment"]["numpy"]
    assert info["config_schema_version"] == 1


def test_configuration_errors_exit_2_and_name_the_key(capsys, tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("config_schema_version = 1\n[trials]\ntimeout_s = -1\n", encoding="utf-8")
    assert main(["run", "--config", str(bad)]) == 2
    assert "trials.timeout_s" in capsys.readouterr().err
    assert main(["run", "--config", str(tmp_path / "absent.toml")]) == 2
    assert main(["prepare", "--config", str(bad)]) == 2


def test_preflight_refusal_exits_5(capsys, tmp_path):
    path = toml(tmp_path)
    cfg_file = Path(path)
    cfg_file.write_text(
        cfg_file.read_text(encoding="utf-8").replace("[trials]\n", "[trials]\nfsync = true\n"),
        encoding="utf-8",
    )
    assert main(["run", "--config", path]) == 5
    assert "fsync" in capsys.readouterr().err


def test_prepare_validate_run_report_end_to_end(capsys, tmp_path):
    cfg = toml(tmp_path)
    assert main(["prepare", "--config", cfg]) == 0
    assert "all variants bit-exact" in capsys.readouterr().out
    assert main(["validate", "--config", cfg]) == 0
    assert main(["run", "--config", cfg]) == 0
    runs = list((tmp_path / "results" / "raw").iterdir())
    assert len(runs) == 1
    assert main(["report", "--run", str(runs[0])]) == 0
    assert (runs[0] / "summary.csv").is_file()
    assert any((tmp_path / "results" / "plots" / runs[0].name).glob("*.png"))
    assert (tmp_path / "results" / "reports" / f"{runs[0].name}.md").is_file()


def test_validate_exits_3_when_a_prepared_file_is_corrupted(capsys, tmp_path):
    cfg = toml(tmp_path)
    assert main(["prepare", "--config", cfg]) == 0
    target = tmp_path / "data" / "events_600_npy.npy"
    data = bytearray(target.read_bytes())
    data[-1] ^= 0x01
    target.write_bytes(bytes(data))
    capsys.readouterr()
    assert main(["validate", "--config", cfg]) == 3
    assert "correctness gate failed" in capsys.readouterr().err


def test_validate_reports_missing_files_as_a_gate_failure(capsys, tmp_path):
    assert main(["validate", "--config", toml(tmp_path)]) == 3
    assert "missing" in capsys.readouterr().err


def test_report_on_a_bad_directory_is_a_usage_error(capsys, tmp_path):
    assert main(["report", "--run", str(tmp_path / "nope")]) == 2
    assert "error:" in capsys.readouterr().err


def test_an_unexpected_exception_is_an_internal_error_exit_1(monkeypatch, capsys, tmp_path):
    from sdplab import cli

    def boom(_args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "_cmd_info", boom)
    assert main(["info", "--config", toml(tmp_path)]) == 1
    assert "internal error: RuntimeError: kaboom" in capsys.readouterr().err


def _finished_run(tmp_path):
    cfg = toml(tmp_path)
    assert main(["run", "--config", cfg]) == 0
    return next((tmp_path / "results" / "raw").iterdir())


def test_check_run_accepts_a_real_run_and_rejects_tampering(capsys, tmp_path):
    run = _finished_run(tmp_path)
    capsys.readouterr()
    assert main(["check-run", "--run", str(run)]) == 0
    assert "consistent" in capsys.readouterr().out

    trials = run / "trials.jsonl"
    original = trials.read_text(encoding="utf-8")
    lines = original.splitlines()

    trials.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")  # a trial went missing
    assert main(["check-run", "--run", str(run)]) == 3
    err = capsys.readouterr().err
    assert "expected" in err
    assert "counts" in err

    tampered = json.loads(lines[0])
    tampered["dataset"]["sha256"] = "0" * 64
    trials.write_text("\n".join([json.dumps(tampered), *lines[1:]]) + "\n", encoding="utf-8")
    assert main(["check-run", "--run", str(run)]) == 3
    assert "dataset hash differs" in capsys.readouterr().err

    trials.write_text(original + '{"results_schema_version": 1, "run_', encoding="utf-8")
    assert main(["check-run", "--run", str(run)]) == 3
    assert "truncated" in capsys.readouterr().err


def test_check_run_flags_an_unfinished_run_and_a_bad_directory(capsys, tmp_path):
    run = _finished_run(tmp_path)
    run_json = run / "run.json"
    data = json.loads(run_json.read_text(encoding="utf-8"))
    data["status"] = "running"
    run_json.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert main(["check-run", "--run", str(run)]) == 3
    assert "did not finish" in capsys.readouterr().err
    assert main(["check-run", "--run", str(tmp_path / "nope")]) == 3
    assert "run.json" in capsys.readouterr().err
