#!/usr/bin/env python3
"""Build each fixture, compare its crash with expected.json, and save results."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
ANALYZER = "skills/mcu-crash-lab/scripts/analyze_crash.py"
REGISTER_NAMES = set("R0 R1 R2 R3 R12 LR PC xPSR EXC_RETURN SP CFSR HFSR MMFAR BFAR".split())


def run_fixture(folder, qemu_version):
    expected = json.loads((folder / "expected.json").read_text())
    subprocess.run(["make", "--no-print-directory", "-s", "-C", str(folder)],
                   check=True, capture_output=True, text=True)
    machine = subprocess.check_output(
        ["make", "--no-print-directory", "-s", "-C", str(folder), "print-machine"], text=True,
    ).strip()
    assert machine == expected["machine"], f"machine: {machine} != {expected['machine']}"
    elf = folder / "build/firmware.elf"
    dump = folder / "dump.txt"
    if qemu_version:
        run = subprocess.run(
            ["qemu-system-arm", "-M", machine, "-nographic", "-monitor", "none",
             "-serial", "none", "-semihosting-config", "enable=on,target=native",
             "-kernel", str(elf)],
            check=True, capture_output=True, text=True, timeout=10,
        )
        lines = [line for line in (run.stdout + run.stderr).splitlines()
                 if re.fullmatch(r"[A-Za-z0-9_]+=0x[0-9a-fA-F]{8}", line)]
        assert len(lines) == len(REGISTER_NAMES) and {
            line.split("=", 1)[0] for line in lines
        } == REGISTER_NAMES, "missing or duplicate dump registers"
        dump = folder / "build/dump.txt"
        dump.write_text("\n".join(lines) + "\n")
    result = subprocess.run(
        ["python3", ANALYZER, str(dump), "--elf", str(elf), "--json"],
        check=True, capture_output=True, text=True,
    )
    analysis = json.loads(result.stdout)
    registers = dict(re.findall(r"^(\w+)=0x([0-9a-fA-F]{8})$", dump.read_text(), re.MULTILINE))
    for key in ("exc_return", "cfsr", "hfsr", "bfar"):
        if key in expected:
            actual = int(registers[key.upper()], 16)
            assert actual == int(expected[key], 16), f"{key}: 0x{actual:08x} != {expected[key]}"
    for key in ("fault_type", "cfsr_bits", "frame"):
        assert analysis[key] == expected[key], f"{key}: {analysis[key]} != {expected[key]}"
    for key in ("function", "file", "line"):
        actual = analysis["pc"][key]
        assert actual == expected[key], f"PC {key}: {actual} != {expected[key]}"
    assert analysis["hfsr_bits"] == [], "fault escalated to HardFault"
    markers = [n for n, line in enumerate((folder / "main.c").read_text().splitlines(), 1)
               if "/* FAULT HERE */" in line]
    assert markers == [expected["line"]], f"FAULT HERE lines: {markers} != {[expected['line']]}"
    status = (f"verified in qemu-system-arm {qemu_version} ({machine})"
              if qemu_version else "static analysis only")
    return {"name": folder.name, "machine": machine, "passed": True, "status": status,
            "elf": str(elf), "dump": str(dump), "analysis": analysis}


def main():
    os.chdir(ROOT)
    qemu_version = None
    if shutil.which("qemu-system-arm"):
        version = subprocess.check_output(["qemu-system-arm", "--version"], text=True)
        qemu_version = version.splitlines()[0].split("version ", 1)[1].split()[0]
    results = []
    for expected_file in sorted(Path("fixtures").glob("*/expected.json")):
        folder = expected_file.parent
        try:
            result = run_fixture(folder, qemu_version)
        except (AssertionError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            detail = str(error)
            if isinstance(error, subprocess.CalledProcessError):
                detail += "\n" + (error.stdout or "") + (error.stderr or "")
            result = {"name": folder.name, "passed": False, "status": "not reproduced",
                      "error": detail.strip()}
        results.append(result)
        label = "PASS" if result["passed"] else "FAIL"
        print(f"{label} {folder.name}: {result['status']}")
        if not result["passed"]:
            print(result["error"])
    verified_count = sum(r["passed"] and r["status"].startswith("verified in ") for r in results)
    failed_count = sum(not r["passed"] for r in results)
    summary = {"verified_count": verified_count, "passed_count": len(results) - failed_count,
               "failed_count": failed_count, "fixtures": results}
    Path("tests/results.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"verified_count: {verified_count}; passed: {summary['passed_count']}; failed: {failed_count}")
    return int(bool(failed_count) or not results)


if __name__ == "__main__":
    raise SystemExit(main())
