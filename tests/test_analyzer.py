"""Check bit decoding, saved QEMU frames, and ELF source locations."""

import json
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(Path("skills/mcu-crash-lab/scripts").resolve()))
import analyze_crash as ac
import run_fixtures


class DecoderTests(unittest.TestCase):
    def test_precise_bus(self):
        self.assertEqual(ac.decode_cfsr(0x8200), ["PRECISERR", "BFARVALID"])

    def test_memmanage(self):
        self.assertEqual(ac.decode_cfsr(0x93),
                         ["IACCVIOL", "DACCVIOL", "MSTKERR", "MMARVALID"])

    def test_usage(self):
        self.assertEqual(ac.decode_cfsr(0x03030000),
                         ["UNDEFINSTR", "INVSTATE", "UNALIGNED", "DIVBYZERO"])

    def test_stacking_and_lazy_fp(self):
        self.assertEqual(ac.decode_cfsr(0x3838),
                         ["MUNSTKERR", "MSTKERR", "MLSPERR", "UNSTKERR", "STKERR", "LSPERR"])

    def test_instruction_bus_and_imprecise(self):
        self.assertEqual(ac.decode_cfsr(0x500), ["IBUSERR", "IMPRECISERR"])

    def test_invalid_return_coprocessor_stack_limit(self):
        self.assertEqual(ac.decode_cfsr(0x1C0000), ["INVPC", "NOCP", "STKOF"])

    def test_reserved_bits_ignored(self):
        self.assertEqual(ac.decode_cfsr(0xFCE04044), [])
        self.assertEqual(ac.decode_cfsr(0), [])

    def test_hfsr(self):
        self.assertEqual(ac.decode_hfsr(0x40000002), ["VECTTBL", "FORCED"])
        self.assertEqual(ac.decode_hfsr(0xC0000002), ["VECTTBL", "FORCED", "DEBUGEVT"])
        self.assertEqual(ac.decode_hfsr(1), [])

    def test_parse(self):
        registers = ac.parse_dump("PC=0x08001234\nlr: 0x8000001\nCFSR = 512\nEXC_RETURN=0xFFFFFFF9\nR4=7")
        self.assertEqual(registers, {"pc": 0x08001234, "lr": 0x8000001,
                                     "cfsr": 0x200, "exc_return": 0xFFFFFFF9})

    def test_frame_size_and_alignment(self):
        for exc_return in (0xFFFFFFF1, 0xFFFFFFF9, 0xFFFFFFFD,
                           0xFFFFFFE1, 0xFFFFFFE9, 0xFFFFFFED):
            for padding in (0, 4):
                with self.subTest(exc_return=hex(exc_return), padding=padding):
                    registers = {"pc": 0x40, "lr": 0x81, "sp": 0x20001000,
                                 "exc_return": exc_return,
                                 "xpsr": 0x01000200 if padding else 0x01000000}
                    with patch.object(ac, "symbolize", return_value={}):
                        result = ac.analyze(registers, "unused.elf")
                    basic = exc_return in (0xFFFFFFF1, 0xFFFFFFF9, 0xFFFFFFFD)
                    self.assertEqual(result["frame"], "basic" if basic else "extended")
                    self.assertEqual(result["pre_exception_sp"],
                                     0x20001000 + (0x20 if basic else 0x68) + padding)

    def test_null_hint(self):
        fault, hint = ac.classify({"cfsr": 0x8200, "bfar": 4}, ac.decode_cfsr(0x8200), [])
        self.assertEqual(fault, "BusFault")
        self.assertIn("NULL", hint)

    def test_invalid_address_does_not_hint_null(self):
        _, hint = ac.classify({"cfsr": 0x200, "bfar": 4}, ["PRECISERR"], [])
        self.assertNotIn("NULL", hint)

    def test_escalation(self):
        fault, hint = ac.classify({"cfsr": 0x2000000}, ["DIVBYZERO"], ["FORCED"])
        self.assertEqual(fault, "HardFault")
        self.assertIn("divisor", hint)
        self.assertIn("escalated", hint)
        _, hint = ac.classify({}, [], ["FORCED"])
        self.assertIn("CFSR is zero", hint)

    def test_memmanage_classification(self):
        fault, hint = ac.classify({"cfsr": 2}, ["DACCVIOL"], [])
        self.assertEqual(fault, "MemManage")
        self.assertIn("MPU", hint)

    def test_fault_classes(self):
        for cfsr, exc_return, xpsr, expected in (
            (0x82, 0xFFFFFFF9, 0, "mpu_violation"),
            (0x81, 0xFFFFFFF9, 0, "mpu_violation"),
            (0x82, 0xFFFFFFE1, 15, "mpu_violation"),
            (0x8200, 0xFFFFFFE9, 0, "fpu_frame_fault"),
            (0x8200, 0xFFFFFFE1, 15, "fpu_frame_fault"),
            (0x8200, 0xFFFFFFF1, 15, "fault_in_isr"),
            (0x80, 0xFFFFFFF9, 0, None),
            (0x02, 0xFFFFFFF9, 0, None),
        ):
            with self.subTest(cfsr=hex(cfsr), exc_return=hex(exc_return), xpsr=xpsr):
                registers = dict(cfsr=cfsr, exc_return=exc_return, xpsr=xpsr, sp=0, pc=0, lr=0)
                with patch.object(ac, "symbolize", return_value={}):
                    self.assertEqual(ac.analyze(registers, "unused.elf")["class"], expected)

    def test_exc_return_is_not_symbolized(self):
        with patch.object(ac.subprocess, "run") as run:
            location = ac.symbolize(0xFFFFFFF9, "unused.elf", is_lr=True)
        run.assert_not_called()
        self.assertEqual(location, {"addr": "0xfffffff9", "function": None,
                                    "file": None, "line": None})
        _, hint = ac.classify({"lr": 0xFFFFFFF9}, [], [])
        self.assertIn("stacked LR", hint)

    def test_symbolizer_strips_directories_and_lr_thumb_bit(self):
        result = subprocess.CompletedProcess([], 0, "caller\nnested/src/main.c:12 (discriminator 1)\n")
        with patch.object(ac.subprocess, "run", return_value=result) as run:
            location = ac.symbolize(0x105, "firmware.elf", is_lr=True)
        self.assertEqual(run.call_args.args[0][-1], "0x102")
        self.assertEqual(location, {"addr": "0x00000105", "function": "caller",
                                    "file": "main.c", "line": 12})


class SavedDumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folders = sorted(path.parent for path in Path("fixtures").glob("*/expected.json")
                             if json.loads(path.read_text()).get("status") != "not_reproduced")
        for folder in cls.folders:
            subprocess.run(["make", "--no-print-directory", "-s", "-C", str(folder)],
                           check=True, capture_output=True, text=True)

    def test_saved_source_locations_and_frame(self):
        for folder in self.folders:
            with self.subTest(fixture=folder.name):
                registers = ac.parse_dump((folder / "dump.txt").read_text())
                expected = json.loads((folder / "expected.json").read_text())
                self.assertEqual(set(registers), set(ac.KEYS))
                self.assertEqual(registers["exc_return"],
                                 int(expected.get("exc_return", "0xfffffff9"), 16))
                self.assertTrue(registers["xpsr"] & (1 << 24))
                self.assertEqual(registers["hfsr"], int(expected.get("hfsr", "0x0"), 16))
                result = run_fixtures.run_fixture(folder, None)
                self.assertEqual(result["status"], "static_only")
                self.assertEqual(result["mismatches"], [])
                self.assertFalse(result["passed"])
                self.assertEqual(result["dump"], str(folder / "dump.txt"))
                if expected.get("isr_number", 0):
                    self.assertIsNone(result["analysis"]["lr"]["function"])
                    continue
                self.assertEqual(result["analysis"]["lr"]["function"], "main")
                call_line = result["analysis"]["lr"]["line"]
                self.assertIn(result["analysis"]["pc"]["function"] + "()",
                              (folder / "main.c").read_text().splitlines()[call_line - 1])

    def test_json_shape(self):
        for folder in self.folders:
            with self.subTest(fixture=folder.name):
                run = subprocess.run([
                    "python3", run_fixtures.ANALYZER, str(folder / "dump.txt"),
                    "--elf", str(folder / "build/firmware.elf"), "--json",
                ], check=True, capture_output=True, text=True)
                result = json.loads(run.stdout)
                self.assertEqual(set(result), {"class", "fault_type", "cfsr_bits", "hfsr_bits",
                                               "pc", "lr", "bfar", "mmfar", "hint",
                                               "frame", "pre_exception_sp"})
                expected = json.loads((folder / "expected.json").read_text())
                self.assertEqual(result["frame"], expected["frame"])
                self.assertEqual(result["class"], expected.get("class"))
                self.assertIsInstance(result["pre_exception_sp"], int)
                for key in ("pc", "lr"):
                    self.assertEqual(set(result[key]), {"addr", "function", "file", "line"})
                    self.assertRegex(result[key]["addr"], r"^0x[0-9a-f]{8}$")
                    if key == "lr" and expected.get("isr_number", 0):
                        self.assertIsNone(result[key]["file"])
                        self.assertIsNone(result[key]["line"])
                    else:
                        self.assertEqual(result[key]["file"], "main.c")
                        self.assertIsInstance(result[key]["line"], int)
                self.assertIsInstance(result["cfsr_bits"], list)
                self.assertIsInstance(result["hfsr_bits"], list)
                self.assertIsInstance(result["hint"], str)

    def test_fault_address_validity(self):
        folder = Path("fixtures/unmapped_write_busfault")
        registers = ac.parse_dump((folder / "dump.txt").read_text())
        elf = folder / "build/firmware.elf"
        self.assertEqual(ac.analyze(registers, elf)["bfar"], 0x60000000)
        registers.update(cfsr=0x200, bfar=0xDEADBEEF, mmfar=0xBADF00D)
        result = ac.analyze(registers, elf)
        self.assertIsNone(result["bfar"])
        self.assertIsNone(result["mmfar"])
        registers.update(cfsr=0x82)
        self.assertEqual(ac.analyze(registers, elf)["mmfar"], 0xBADF00D)
        registers.update(cfsr=0x8282, bfar=0)
        result = ac.analyze(registers, elf)
        self.assertEqual(result["bfar"], 0)
        self.assertEqual(result["mmfar"], 0xBADF00D)

    def test_unknown_symbol(self):
        elf = Path("fixtures/div0_usagefault/build/firmware.elf")
        self.assertEqual(ac.symbolize(0x12345678, elf),
                         {"addr": "0x12345678", "function": None, "file": None, "line": None})

    def test_text_output(self):
        folder = Path("fixtures/div0_usagefault")
        run = subprocess.run([
            "python3", run_fixtures.ANALYZER, str(folder / "dump.txt"),
            "--elf", str(folder / "build/firmware.elf"),
        ], check=True, capture_output=True, text=True)
        self.assertIn("Fault: UsageFault", run.stdout)
        self.assertIn("Frame: basic", run.stdout)
        self.assertIn("Pre-exception SP: 0x203fffc8", run.stdout)
        self.assertIn("DIVBYZERO", run.stdout)
        self.assertIn("divide_by_zero (main.c:10)", run.stdout)
        self.assertIn("BFAR: invalid", run.stdout)


class RunnerTests(unittest.TestCase):
    def test_exact_expectation_mismatches_fail(self):
        loads = json.loads
        for name, changes in (
            ("mpu_violation", {"exc_return": "0xfffffff1"}),
            ("mpu_violation", {"cfsr": "0x80"}),
            ("mpu_violation", {"hfsr": "0x1"}),
            ("mpu_violation", {"mmfar": "0x0"}),
            ("mpu_violation", {"mmfar_symbol": "_estack"}),
            ("mpu_violation", {"isr_number": 15}),
            ("mpu_violation", {"class": None}),
            ("fault_in_isr_unmapped", {"bfar": "0x0"}),
            ("fault_in_isr_unmapped", {"bfar_symbol": "_estack"}),
        ):
            with self.subTest(fixture=name, changes=changes):
                folder = Path("fixtures") / name
                expected_text = (folder / "expected.json").read_text()

                def load(text):
                    value = loads(text)
                    if text == expected_text:
                        value.update(changes)
                    return value

                with patch.object(run_fixtures.json, "loads", side_effect=load):
                    result = run_fixtures.run_fixture(folder, None)
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["passed"])
                self.assertTrue(result["mismatches"])

    def test_no_fault_is_not_reproduced_and_fixed_must_finish(self):
        folder = Path("fixtures/fault_in_isr")
        output = (folder / "dump.txt").read_text()
        with patch.object(run_fixtures, "run_qemu", side_effect=[output, "DONE\n"]):
            result = run_fixtures.run_fixture(folder, "test")
        self.assertEqual(result["status"], "not_reproduced")
        self.assertFalse(result["passed"])
        self.assertIsNone(result["analysis"])
        self.assertNotIn("EXC_RETURN", result["registers"])
        self.assertEqual(result["fixed"], "DONE")
        with patch.object(run_fixtures, "run_qemu", side_effect=[output, "crashed\n"]):
            with self.assertRaisesRegex(AssertionError, "fixed"):
                run_fixtures.run_fixture(folder, "test")

    def test_summary_excludes_not_reproduced_and_fails_verified_mismatch(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                def result(folder, version):
                    status = ("not_reproduced" if folder.name == "fault_in_isr" else
                              "failed" if fail and folder.name == "mpu_violation" else "verified")
                    return {"name": folder.name, "status": status, "passed": status == "verified"}

                output = StringIO()
                with patch.object(run_fixtures, "run_fixture", side_effect=result), \
                     patch.object(run_fixtures.shutil, "which", return_value=None), \
                     patch.object(Path, "write_text") as write, redirect_stdout(output):
                    self.assertEqual(run_fixtures.main(), int(fail))
                summary = json.loads(write.call_args.args[0])
                count = len(summary["fixtures"])
                self.assertEqual(summary["verified_count"], count - 1 - int(fail))
                self.assertEqual(summary["passed_count"], summary["verified_count"])
                self.assertEqual(summary["not_reproduced_count"], 1)
                self.assertEqual(summary["failed_count"], int(fail))
                self.assertIn("NOT REPRODUCED fault_in_isr:", output.getvalue())
                self.assertNotIn("PASS fault_in_isr:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
