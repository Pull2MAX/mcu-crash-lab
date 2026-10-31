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


def run_qemu(elf, machine):
    run = subprocess.run(
        ["qemu-system-arm", "-M", machine, "-nographic", "-monitor", "none",
         "-serial", "none", "-semihosting-config", "enable=on,target=native",
         "-kernel", str(elf)],
        check=True, capture_output=True, text=True, timeout=10,
    )
    return run.stdout + run.stderr


def run_fixture(folder, qemu_version):
    expected = json.loads((folder / "expected.json").read_text())
    make = ["make", "--no-print-directory", "-s", "-C", str(folder)]
    subprocess.run(make, check=True, capture_output=True, text=True)
    machine = subprocess.check_output(make + ["print-machine"], text=True).strip()
    assert machine == expected["machine"], f"machine: {machine} != {expected['machine']}"
    elf = folder / "build/firmware.elf"
    dump = folder / ("build/dump.txt" if qemu_version else "dump.txt")
    if qemu_version:
        dump.write_text(run_qemu(elf, machine))
    output = dump.read_text()
    lines = re.findall(r"^(\w+)=0x([0-9a-fA-F]{8})$", output, re.MULTILINE)
    registers = {key: int(value, 16) for key, value in lines}
    analysis = None
    if "EXC_RETURN" in registers:
        assert len(lines) == len(REGISTER_NAMES) and set(registers) == REGISTER_NAMES, \
            "missing or duplicate dump registers"
        run = subprocess.run(
            ["python3", ANALYZER, str(dump), "--elf", str(elf), "--json"],
            check=True, capture_output=True, text=True,
        )
        analysis = json.loads(run.stdout)
        checks = [(key, analysis[key], expected[key])
                  for key in ("fault_type", "cfsr_bits", "frame", "class") if key in expected]
        checks += [(f"PC {key}", analysis["pc"][key], expected[key])
                   for key in ("function", "file", "line")]
        checks.append(("hfsr_bits", analysis["hfsr_bits"], expected.get("hfsr_bits", [])))
        for key in ("exc_return", "cfsr", "hfsr", "mmfar", "bfar"):
            if key in expected:
                checks.append((key, registers[key.upper()], int(expected[key], 16)))
        if "isr_number" in expected:
            checks.append(("isr_number", registers["xPSR"] & 0x1FF, expected["isr_number"]))
        if "mmfar_symbol" in expected or "bfar_symbol" in expected:
            nm = subprocess.check_output(["arm-none-eabi-nm", "--defined-only", str(elf)], text=True)
            symbols = {name: int(address, 16) for address, _, name in
                       (line.split() for line in nm.splitlines())}
            for key in ("mmfar", "bfar"):
                if key + "_symbol" in expected:
                    checks.append((key, registers[key.upper()], symbols[expected[key + "_symbol"]]))
        mismatches = [f"{key}: {actual!r} != {wanted!r}"
                      for key, actual, wanted in checks if actual != wanted]
    else:
        assert "DONE" in output.splitlines(), "no fault frame or DONE marker"
        mismatches = ["no fault frame; reached DONE"]
    markers = [n for n, line in enumerate((folder / "main.c").read_text().splitlines(), 1)
               if "/* FAULT HERE */" in line]
    assert markers == [expected["line"]], f"FAULT HERE lines: {markers} != {[expected['line']]}"
    fixed = None
    if (folder / "fixed/main.c").exists():
        subprocess.run(make + ["MAIN=fixed/main.c", "BUILD=build/fixed"],
                       check=True, capture_output=True, text=True)
        fixed = "static_only"
        if qemu_version:
            fixed_output = run_qemu(folder / "build/fixed/firmware.elf", machine)
            assert fixed_output.splitlines() == ["DONE"], f"fixed: {fixed_output!r}"
            fixed = "DONE"
    documented = expected.get("status", "verified")
    status = (documented if documented in ("not_reproduced", "static_only") else
              "failed" if mismatches else "verified" if qemu_version else "static_only")
    return {"name": folder.name, "machine": machine, "passed": status == "verified",
            "status": status, "reason": expected.get("reason"), "mismatches": mismatches,
            "qemu_version": qemu_version, "fixed": fixed,
            "elf": str(elf), "dump": str(dump), "analysis": analysis,
            "registers": {key: f"0x{value:08x}" for key, value in registers.items()}}


def main():
    os.chdir(ROOT)
    qemu_version = None
    if shutil.which("qemu-system-arm"):
        version = subprocess.check_output(["qemu-system-arm", "--version"], text=True)
        qemu_version = version.splitlines()[0].split("version ", 1)[1].split()[0]
    results = []
    labels = {"verified": "PASS", "failed": "FAIL", "not_reproduced": "NOT REPRODUCED",
              "static_only": "STATIC ONLY"}
    for expected_file in sorted(Path("fixtures").glob("*/expected.json")):
        folder = expected_file.parent
        try:
            result = run_fixture(folder, qemu_version)
        except (AssertionError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            detail = str(error)
            if isinstance(error, subprocess.CalledProcessError):
                detail += "\n" + (error.stdout or "") + (error.stderr or "")
            result = {"name": folder.name, "passed": False, "status": "failed",
                      "error": detail.strip()}
        results.append(result)
        detail = result.get("error") or result.get("reason") or result["status"]
        if result.get("fixed"):
            detail += f"; fixed: {result['fixed']}"
        print(f"{labels[result['status']]} {folder.name}: {detail}")
        if result["status"] == "failed":
            for mismatch in result.get("mismatches", []):
                print(mismatch)
    summary = {"verified_count": sum(r["status"] == "verified" for r in results),
               "passed_count": sum(r["passed"] for r in results),
               "failed_count": sum(r["status"] == "failed" for r in results),
               "not_reproduced_count": sum(r["status"] == "not_reproduced" for r in results),
               "static_only_count": sum(r["status"] == "static_only" for r in results),
               "fixtures": results}
    Path("tests/results.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"verified_count: {summary['verified_count']}; passed: {summary['passed_count']}; "
          f"not_reproduced: {summary['not_reproduced_count']}; "
          f"static_only: {summary['static_only_count']}; failed: {summary['failed_count']}")
    return int(bool(summary["failed_count"]) or not results)


if __name__ == "__main__":
    raise SystemExit(main())
