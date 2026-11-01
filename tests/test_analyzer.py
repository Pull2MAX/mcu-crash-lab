"""Check bit decoding, saved QEMU frames, and ELF source locations."""

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(Path("skills/mcu-crash-lab/scripts").resolve()))
import analyze_crash as ac
import run_fixtures


class DecoderTests(unittest.TestCase):
    def analyze(self, **registers):
        values = dict.fromkeys(ac.REQUIRED, 0)
        values.update(registers)
        with patch.object(ac, "symbolize", return_value={}):
            return ac.analyze(values, "unused.elf")

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
        registers = ac.parse_dump("PC=0x08001234\nlr: 0x8000001\nCFSR = 512\nEXC_RETURN=0xFFFFFFF9\nFPCCR=0xC0000001\nR4=7")
        self.assertEqual(registers, {"pc": 0x08001234, "lr": 0x8000001,
                                     "cfsr": 0x512, "exc_return": 0xFFFFFFF9,
                                     "fpccr": 0xC0000001})
        self.assertIn("assumed hexadecimal: CFSR", registers.caveats[0])

    def test_parse_multiple_pairs_and_annotations(self):
        registers = ac.parse_dump("PC: 0x50  LR: 0x65\n"
                                  "CFSR = 0x8200 (PRECISERR) HFSR: 0x40000000\n"
                                  "BFAR: 0x60000000; MMFAR=0x0 # unused")
        self.assertEqual(registers, {"pc": 0x50, "lr": 0x65, "cfsr": 0x8200,
                                     "hfsr": 0x40000000, "bfar": 0x60000000, "mmfar": 0})
        self.assertEqual(registers.caveats, [])

    def test_bare_hex_registers(self):
        text = ("CFSR=00008200 HFSR=40000000 MMFAR=deadbeef BFAR=60000000\n"
                "PC=00000050 LR=00000065 SP=203fffb0 xPSR=21000000 EXC_RETURN=fffffff9")
        registers = ac.parse_dump(text)
        self.assertEqual(registers, {"cfsr": 0x8200, "hfsr": 0x40000000,
                                     "mmfar": 0xDEADBEEF, "bfar": 0x60000000,
                                     "pc": 0x50, "lr": 0x65, "sp": 0x203FFFB0,
                                     "xpsr": 0x21000000, "exc_return": 0xFFFFFFF9})
        with patch.object(ac, "symbolize", return_value={}):
            result = ac.analyze(registers, "unused.elf")
        self.assertEqual(result["cause"], "precise_bus_error")
        for key in registers:
            self.assertIn(key.upper(), result["caveats"][0])
        self.assertIn("assumed hexadecimal", result["caveats"][0])

    def test_optional_registers(self):
        optional = dict(exc_return=0xFFFFFFE1, xpsr=0x0100020B, sp=0x20001000)
        for mask in range(8):
            present = {key: value for n, (key, value) in enumerate(optional.items())
                       if mask & (1 << n)}
            with self.subTest(present=present):
                result = self.analyze(cfsr=0x8200, **present)
                self.assertEqual(result["cause"], "precise_bus_error")
                self.assertEqual(result["frame"], "extended" if "exc_return" in present else None)
                self.assertEqual(result["context"], {"mode": "isr", "exception_number": 11}
                                 if "xpsr" in present else None)
                self.assertEqual(result["pre_exception_sp"], 0x2000106C if mask == 7 else None)
                caveats = " ".join(result["caveats"])
                for key in optional.keys() - present.keys():
                    self.assertIn(key.upper(), caveats.upper())
                if mask != 7:
                    self.assertIn("cannot be determined", caveats)

    def test_required_registers(self):
        for key in ac.REQUIRED:
            with self.subTest(missing=key):
                registers = dict.fromkeys(ac.REQUIRED, 0)
                del registers[key]
                with self.assertRaisesRegex(ac.AnalysisError, f"Missing required registers: {key.upper()}"):
                    ac.analyze(registers, "unused.elf")

    def test_caveats(self):
        for cfsr, hfsr, message in (
            (0x10, 0, "Stacked values may be incomplete"),
            (0x1000, 0, "Stacked values may be incomplete"),
            (0x400, 0, "PC may not be the faulting instruction"),
            (0x2000000, 0x40000000, "inspect CFSR and SHCSR"),
            (0, 0x40000000, "CFSR has no fault bits"),
        ):
            with self.subTest(cfsr=hex(cfsr), hfsr=hex(hfsr)):
                registers = dict(cfsr=cfsr, hfsr=hfsr, pc=0, lr=0, sp=0,
                                 exc_return=0xFFFFFFF9, xpsr=0x01000000)
                result = self.analyze(**registers)
                self.assertIn(message, " ".join(result["caveats"]))
                self.assertNotIn(message, result["hint"])
                for caveat in result["caveats"]:
                    self.assertNotIn(caveat, result["hint"])

    def test_forced_without_cfsr_fault(self):
        result = self.analyze(cfsr=0, hfsr=0x40000000,
                              exc_return=0xFFFFFFF9, xpsr=0x01000000, sp=0)
        self.assertIsNone(result["cause"])
        self.assertEqual(len(result["caveats"]), 1)
        caveat = result["caveats"][0]
        self.assertIn("SVC/BKPT at too-low priority", caveat)
        self.assertIn("CFSR was already cleared", caveat)
        self.assertNotIn("the cause is in CFSR", caveat)
        self.assertNotIn("capture CFSR before clearing", caveat)

    def test_lazy_fp_caveat_requires_extended_frame_and_lspact(self):
        for exc_return in (0xFFFFFFF9, 0xFFFFFFE9):
            for fpccr in (None, 0, 0xC0000000, 0xC0000001):
                with self.subTest(exc_return=hex(exc_return), fpccr=fpccr):
                    registers = dict(pc=0, lr=0, sp=0, xpsr=0, exc_return=exc_return)
                    if fpccr is not None:
                        registers["fpccr"] = fpccr
                    result = self.analyze(**registers)
                    if exc_return == 0xFFFFFFE9 and fpccr == 0xC0000001:
                        self.assertIn("FP registers were not saved yet", result["caveats"][0])
                    else:
                        self.assertEqual(result["caveats"], [])

    def test_frame_size_and_alignment(self):
        for exc_return in (0xFFFFFFF1, 0xFFFFFFF9, 0xFFFFFFFD,
                           0xFFFFFFE1, 0xFFFFFFE9, 0xFFFFFFED):
            for padding in (0, 4):
                with self.subTest(exc_return=hex(exc_return), padding=padding):
                    registers = {"pc": 0x40, "lr": 0x81, "sp": 0x20001000,
                                 "exc_return": exc_return,
                                 "xpsr": 0x01000200 if padding else 0x01000000}
                    result = self.analyze(**registers)
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
        self.assertNotIn("escalated", hint)
        _, hint = ac.classify({}, [], ["FORCED"])
        self.assertNotIn("CFSR is zero", hint)

    def test_memmanage_classification(self):
        fault, hint = ac.classify({"cfsr": 2}, ["DACCVIOL"], [])
        self.assertEqual(fault, "MemManage")
        self.assertIn("MPU", hint)

    def test_cause_frame_and_context(self):
        for cfsr, cause in (
            (0x82, "mpu_violation"),
            (0x01, "instruction_access_violation"),
            (0x02, "mpu_violation"),
            (0x8200, "precise_bus_error"),
            (0x400, "imprecise_bus_error"),
            (0x10000, "undefined_instruction"),
            (0x2000000, "divide_by_zero"),
            (0x80, None),
        ):
            for exc_return, frame, number in ((0xFFFFFFF9, "basic", 0),
                                             (0xFFFFFFF1, "basic", 15),
                                             (0xFFFFFFE9, "extended", 0),
                                             (0xFFFFFFE1, "extended", 11)):
                with self.subTest(cfsr=hex(cfsr), exc_return=hex(exc_return), exception=number):
                    result = self.analyze(cfsr=cfsr, exc_return=exc_return,
                                          xpsr=0x01000000 | number, sp=0)
                    self.assertEqual(result["cause"], cause)
                    self.assertEqual(result["frame"], frame)
                    self.assertEqual(result["context"], {"mode": "isr" if number else "thread",
                                                         "exception_number": number})
                    self.assertNotIn("class", result)
                    if cfsr == 1:
                        self.assertIsNone(result["mmfar"])

    def test_extended_frame_in_isr_keeps_null_bus_cause(self):
        result = self.analyze(cfsr=0x8200, bfar=0, exc_return=0xFFFFFFE1,
                              xpsr=0x0100000B, sp=0)
        self.assertEqual(result["cause"], "precise_bus_error")
        self.assertEqual(result["frame"], "extended")
        self.assertEqual(result["context"], {"mode": "isr", "exception_number": 11})
        self.assertIn("NULL", result["hint"])

    def test_multiple_causes(self):
        result = self.analyze(cfsr=0x3000000)
        self.assertEqual(result["cause"], "multiple_faults")
        self.assertEqual(result["cfsr_bits"], ["UNALIGNED", "DIVBYZERO"])

    def test_exc_return_is_not_symbolized(self):
        with patch.object(ac.subprocess, "run") as run:
            location = ac.symbolize(0xFFFFFFF9, "unused.elf", is_lr=True)
        run.assert_not_called()
        self.assertEqual(location, {"addr": "0xfffffff9", "function": None,
                                    "file": None, "line": None})
        _, hint = ac.classify({"lr": 0xFFFFFFF9}, [], [])
        self.assertIn("Stacked LR is EXC_RETURN", hint)
        self.assertIn("Capture stack memory", hint)

    def test_symbolizer_strips_directories_and_lr_thumb_bit(self):
        result = subprocess.CompletedProcess([], 0, "caller\nnested/src/main.c:12 (discriminator 1)\n")
        with patch.object(ac.subprocess, "run", return_value=result) as run:
            location = ac.symbolize(0x105, "firmware.elf", is_lr=True)
        self.assertEqual(run.call_args.args[0][-1], "0x102")
        self.assertEqual(location, {"addr": "0x00000105", "function": "caller",
                                    "file": "main.c", "line": 12})

    def test_symbolizer_demangles_and_keeps_inline_chain(self):
        output = "Widget::read()\nsrc/widget.h:12\nmain\nsrc/main.cpp:40 (discriminator 1)\n"
        result = subprocess.CompletedProcess([], 0, output)
        with patch.object(ac.subprocess, "run", return_value=result) as run:
            location = ac.symbolize(0x100, "firmware.elf")
        self.assertIn("-C", run.call_args.args[0])
        self.assertIn("-i", run.call_args.args[0])
        self.assertEqual(location["function"], "Widget::read()")
        self.assertEqual(location["file"], "widget.h")
        self.assertEqual(location["line"], 12)
        self.assertEqual(location["inline_chain"], [
            {"function": "Widget::read()", "file": "widget.h", "line": 12},
            {"function": "main", "file": "main.cpp", "line": 40},
        ])


class CliTests(unittest.TestCase):
    def invoke(self, directory, text, json_output=False):
        dump = Path(directory, "dump.txt")
        elf = Path(directory, "firmware.elf")
        dump.write_text(text)
        args = ["analyze_crash.py", str(dump), "--elf", str(elf)]
        if json_output:
            args.append("--json")
        stdout, stderr = StringIO(), StringIO()
        with patch.object(sys, "argv", args), redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                ac.main()
            except SystemExit as error:
                code = error.code
            else:
                code = 0
        return code, stdout.getvalue(), stderr.getvalue()

    def test_minimal_dump_json_and_text(self):
        text = "CFSR=0x8200 HFSR=0x0 MMFAR=0x0 BFAR=0x60000000 PC=0x50 LR=0x65"
        symbol = subprocess.CompletedProcess([], 0, "write_unmapped\nmain.c:7\n")
        with TemporaryDirectory() as directory:
            Path(directory, "firmware.elf").touch()
            for json_output in (False, True):
                with self.subTest(json=json_output), \
                     patch.object(ac.subprocess, "run", return_value=symbol):
                    code, stdout, stderr = self.invoke(directory, text, json_output)
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                if json_output:
                    result = json.loads(stdout)
                    self.assertEqual(result["cause"], "precise_bus_error")
                    for key in ("frame", "context", "pre_exception_sp"):
                        self.assertIsNone(result[key])
                    self.assertEqual(len(result["caveats"]), 3)
                else:
                    self.assertIn("Frame: unknown", stdout)
                    self.assertIn("Context: unknown", stdout)
                    self.assertIn("Pre-exception SP: unknown", stdout)

    def test_errors_are_one_message_without_traceback(self):
        text = "CFSR=0x8200 HFSR=0x0 MMFAR=0x0 BFAR=0x60000000 PC=0x50 LR=0x65"
        cases = [
            (None, "ELF file not found"),
            (subprocess.CompletedProcess([], 1, "", "bad ELF\nextra detail\n"), "addr2line failed"),
            (FileNotFoundError("tool missing"), "Cannot run arm-none-eabi-addr2line"),
            (subprocess.TimeoutExpired("addr2line", 10), "addr2line timed out"),
        ]
        for output in ("", "function\n", "function\ninvalid source\n",
                       "function\nmain.c:not-a-line\n", "function\nmain.c:1\nextra\n",
                       "function\nmain.c:1\ncaller\nbroken\n"):
            cases.append((subprocess.CompletedProcess([], 0, output, ""), "Unexpected addr2line output"))
        for response, message in cases:
            with self.subTest(message=message, response=response), TemporaryDirectory() as directory:
                if response is not None:
                    Path(directory, "firmware.elf").touch()
                kwargs = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
                with patch.object(ac.subprocess, "run", **kwargs):
                    code, stdout, stderr = self.invoke(directory, text, json_output=True)
                self.assertNotEqual(code, 0)
                self.assertEqual(stdout, "")
                self.assertEqual(len(stderr.splitlines()), 1)
                self.assertIn(message, stderr)
                self.assertNotIn("Traceback", stderr)

    def test_missing_required_register_is_reported(self):
        with TemporaryDirectory() as directory:
            Path(directory, "firmware.elf").touch()
            code, stdout, stderr = self.invoke(directory, "PC=0x50 LR=0x65")
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "error: Missing required registers: CFSR, HFSR, MMFAR, BFAR\n")


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
                self.assertEqual(set(registers), set(ac.KEYS) - {"fpccr"})
                self.assertEqual(registers["exc_return"],
                                 int(expected.get("exc_return", "0xfffffff9"), 16))
                self.assertTrue(registers["xpsr"] & (1 << 24))
                self.assertEqual(registers["hfsr"], int(expected.get("hfsr", "0x0"), 16))
                result = run_fixtures.run_fixture(folder, None)
                self.assertEqual(result["status"], "static_only")
                self.assertEqual(result["mismatches"], [])
                self.assertFalse(result["passed"])
                self.assertEqual(result["dump"], str(folder / "dump.txt"))
                if expected.get("context", {}).get("exception_number", 0):
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
                self.assertEqual(set(result), {"cause", "context", "fault_type", "cfsr_bits", "hfsr_bits",
                                               "pc", "lr", "bfar", "mmfar", "hint",
                                               "frame", "pre_exception_sp", "caveats"})
                expected = json.loads((folder / "expected.json").read_text())
                self.assertEqual(result["frame"], expected["frame"])
                if "cause" in expected:
                    self.assertEqual(result["cause"], expected["cause"])
                self.assertEqual(result["context"], expected.get("context", {"mode": "thread",
                                                                           "exception_number": 0}))
                self.assertIsInstance(result["pre_exception_sp"], int)
                for key in ("pc", "lr"):
                    self.assertEqual(set(result[key]), {"addr", "function", "file", "line"})
                    self.assertRegex(result[key]["addr"], r"^0x[0-9a-f]{8}$")
                    if key == "lr" and expected.get("context", {}).get("exception_number", 0):
                        self.assertIsNone(result[key]["file"])
                        self.assertIsNone(result[key]["line"])
                    else:
                        self.assertEqual(result[key]["file"], "main.c")
                        self.assertIsInstance(result[key]["line"], int)
                self.assertIsInstance(result["cfsr_bits"], list)
                self.assertIsInstance(result["hfsr_bits"], list)
                self.assertIsInstance(result["hint"], str)
                self.assertIsInstance(result["caveats"], list)
                self.assertEqual(bool(result["caveats"]), "FORCED" in result["hfsr_bits"])

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
        self.assertIsNone(ac.analyze(registers, elf)["bfar"])
        registers.update(cfsr=0x8200, bfar=0)
        result = ac.analyze(registers, elf)
        self.assertEqual(result["bfar"], 0)
        self.assertIsNone(result["mmfar"])

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


class OfflineDemoTests(unittest.TestCase):
    def test_full_and_thin_dumps(self):
        folder = Path("examples/offline")
        full = ac.parse_dump((folder / "crash_full.txt").read_text())
        thin = ac.parse_dump((folder / "crash_thin.txt").read_text())
        self.assertEqual(set(full), set(ac.KEYS) - {"fpccr"})
        self.assertEqual(thin["bfar"], full["bfar"])
        self.assertEqual(thin["cfsr"], 0x400)
        self.assertGreater(thin["pc"], full["pc"])
        result = ac.analyze(full, folder / "firmware.elf")
        self.assertEqual(result["pc"]["function"], "write_unmapped")
        self.assertEqual(result["bfar"], 0x60000000)
        self.assertEqual(result["caveats"], [])
        result = ac.analyze(thin, folder / "firmware.elf")
        self.assertIsNone(result["bfar"])
        self.assertEqual(result["cause"], "imprecise_bus_error")
        self.assertIn("PC may not be the faulting instruction", result["caveats"][0])
        self.assertNotIn("load/store pointer", result["hint"])

    def test_demo_without_qemu_or_compiler(self):
        with TemporaryDirectory() as directory:
            for name in ("make", "python3", "arm-none-eabi-addr2line"):
                Path(directory, name).symlink_to(shutil.which(name))
            env = dict(os.environ, PATH=directory)
            self.assertIsNone(shutil.which("qemu-system-arm", path=directory))
            self.assertIsNone(shutil.which("arm-none-eabi-gcc", path=directory))
            run = subprocess.run(["make", "demo"], env=env, check=True,
                                 capture_output=True, text=True)
        self.assertIn("CFSR: PRECISERR, BFARVALID", run.stdout)
        self.assertIn("CFSR: IMPRECISERR", run.stdout)
        self.assertIn("Caveat: PC may not be the faulting instruction", run.stdout)


class RunnerTests(unittest.TestCase):
    def test_fixture_sources(self):
        for path in Path("fixtures").glob("*/expected.json"):
            expected = json.loads(path.read_text())
            self.assertIn(expected["source"], ("qemu_measured", "hand_built", "real_device"))
            if path.parent.name == "fault_in_isr":
                self.assertEqual(expected["source"], "hand_built")
                self.assertEqual(expected["status"], "not_reproduced")
            else:
                self.assertEqual(expected["source"], "qemu_measured")

    def test_only_qemu_measured_sources_can_be_verified(self):
        folder = Path("fixtures/unmapped_write_busfault")
        expected_text = (folder / "expected.json").read_text()
        output = (folder / "dump.txt").read_text()
        loads = json.loads
        for source in ("qemu_measured", "hand_built", "real_device"):
            for version in (None, "test"):
                with self.subTest(source=source, version=version):
                    def load(text):
                        value = loads(text)
                        if text == expected_text:
                            value["source"] = source
                        return value

                    with patch.object(run_fixtures.json, "loads", side_effect=load), \
                         patch.object(run_fixtures, "run_qemu", return_value=output):
                        result = run_fixtures.run_fixture(folder, version)
                    verified = source == "qemu_measured" and version is not None
                    self.assertEqual(result["source"], source)
                    self.assertEqual(result["status"], "verified" if verified else "static_only")
                    self.assertEqual(result["passed"], verified)

    def test_exact_expectation_mismatches_fail(self):
        loads = json.loads
        for name, changes in (
            ("mpu_violation", {"exc_return": "0xfffffff1"}),
            ("mpu_violation", {"cfsr": "0x80"}),
            ("mpu_violation", {"hfsr": "0x1"}),
            ("mpu_violation", {"mmfar": "0x0"}),
            ("mpu_violation", {"mmfar_symbol": "_estack"}),
            ("mpu_violation", {"context": {"mode": "isr", "exception_number": 15}}),
            ("mpu_violation", {"cause": None}),
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
