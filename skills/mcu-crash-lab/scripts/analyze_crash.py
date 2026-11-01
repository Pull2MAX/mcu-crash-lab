#!/usr/bin/env python3
"""Decode Cortex-M fault registers and locate stacked PC/LR in an ELF image."""

import argparse
import json
from pathlib import Path
import re
import subprocess

MMFSR = {0: "IACCVIOL", 1: "DACCVIOL", 3: "MUNSTKERR", 4: "MSTKERR",
         5: "MLSPERR", 7: "MMARVALID"}
BFSR = {8: "IBUSERR", 9: "PRECISERR", 10: "IMPRECISERR", 11: "UNSTKERR",
        12: "STKERR", 13: "LSPERR", 15: "BFARVALID"}
UFSR = {16: "UNDEFINSTR", 17: "INVSTATE", 18: "INVPC", 19: "NOCP",
        20: "STKOF", 24: "UNALIGNED", 25: "DIVBYZERO"}
HFSR = {1: "VECTTBL", 30: "FORCED", 31: "DEBUGEVT"}
KEYS = "r0 r1 r2 r3 r12 lr pc xpsr exc_return cfsr hfsr mmfar bfar sp fpccr".split()
REQUIRED = "cfsr hfsr mmfar bfar pc lr".split()
CAUSES = {
    "IACCVIOL": "instruction_access_violation",
    "DACCVIOL": "mpu_violation",
    "MUNSTKERR": "memory_unstacking_error",
    "MSTKERR": "memory_stacking_error",
    "MLSPERR": "memory_lazy_fp_error",
    "IBUSERR": "instruction_bus_error",
    "PRECISERR": "precise_bus_error",
    "IMPRECISERR": "imprecise_bus_error",
    "UNSTKERR": "bus_unstacking_error",
    "STKERR": "bus_stacking_error",
    "LSPERR": "bus_lazy_fp_error",
    "UNDEFINSTR": "undefined_instruction",
    "INVSTATE": "invalid_state",
    "INVPC": "invalid_exception_return",
    "NOCP": "coprocessor_unavailable",
    "STKOF": "stack_overflow",
    "UNALIGNED": "unaligned_access",
    "DIVBYZERO": "divide_by_zero",
}
HINTS = {
    "IACCVIOL": "Check MPU execute permissions and the jump target.",
    "DACCVIOL": "Check the pointer and MPU data permissions.",
    "MUNSTKERR": "Check SP and stack corruption on exception return.",
    "MLSPERR": "Check stack access during lazy FP state preservation.",
    "IBUSERR": "Check the instruction address and function pointers.",
    "PRECISERR": "Check the load/store pointer and the board memory map.",
    "UNSTKERR": "Check SP and stack memory on exception return.",
    "LSPERR": "Check stack memory during lazy FP state preservation.",
    "UNDEFINSTR": "Check the instruction at PC and the build CPU flags.",
    "INVSTATE": "Check the Thumb bit in function pointers and stacked xPSR.",
    "INVPC": "Check EXC_RETURN and stack corruption on exception return.",
    "NOCP": "Check coprocessor instructions and FPU enable bits in CPACR.",
    "STKOF": "Check the stack limit and available stack space (Armv8-M).",
    "UNALIGNED": "Align the accessed data or use memcpy for packed data.",
    "DIVBYZERO": "Check the divisor before integer division; CCR.DIV_0_TRP is set.",
    "VECTTBL": "Check VTOR and the vector table memory.",
    "DEBUGEVT": "Check for a breakpoint or debug event without a debugger.",
}
CAVEATS = {
    "MSTKERR": "Stacked values may be incomplete; check stack space and MPU stack guards on exception entry.",
    "STKERR": "Stacked values may be incomplete; check for stack overflow or SP outside RAM on exception entry.",
    "IMPRECISERR": "PC may not be the faulting instruction; inspect earlier stores. On Cortex-M3/M4, try ACTLR.DISDEFWBUF.",
}


class AnalysisError(ValueError):
    pass


class RegisterDump(dict):
    def __init__(self):
        super().__init__()
        self.caveats = []


def decode_bits(value, table):
    return [name for bit, name in sorted(table.items()) if value & (1 << bit)]


def decode_cfsr(value):
    return decode_bits(value, MMFSR | BFSR | UFSR)


def decode_hfsr(value):
    return decode_bits(value, HFSR)


def parse_dump(text):
    registers = RegisterDump()
    bare = set()
    for key, value in re.findall(
        r"\b([A-Za-z][A-Za-z0-9_]*)\s*[=:]\s*(0[xX][0-9a-fA-F]+|[0-9a-fA-F]+)\b",
        text,
    ):
        if key.lower() in KEYS:
            registers[key.lower()] = int(value, 16)
            if not value.lower().startswith("0x"):
                bare.add(key.upper())
    if bare:
        registers.caveats.append("Bare register values without 0x were assumed hexadecimal: "
                                + ", ".join(sorted(bare)) + ".")
    return registers


def symbolize(addr, elf, is_lr=False):
    location = {"addr": f"0x{addr:08x}", "function": None, "file": None, "line": None}
    if is_lr and addr >= 0xFFFFFF80:
        return location
    # LR points past the call; the preceding halfword belongs to that call.
    lookup = (addr & ~1) - (2 if is_lr and addr > 1 else 0)
    try:
        result = subprocess.run(
            ["arm-none-eabi-addr2line", "-f", "-C", "-i", "-e", str(elf), hex(lookup)],
            capture_output=True, text=True, timeout=10,
        )
    except OSError as error:
        raise AnalysisError(f"Cannot run arm-none-eabi-addr2line: {error}") from None
    except subprocess.TimeoutExpired:
        raise AnalysisError(f"addr2line timed out for {elf}") from None
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise AnalysisError(f"addr2line failed for {elf}: "
                            + (detail[0] if detail else f"exit status {result.returncode}"))
    lines = result.stdout.strip().splitlines()
    if not lines or len(lines) % 2:
        raise AnalysisError(f"Unexpected addr2line output for {elf}")
    frames = []
    for function, source in zip(lines[::2], lines[1::2]):
        match = re.fullmatch(r"(.+):(\d+|\?)(?: \(discriminator \d+\))?", source)
        if not function or not match:
            raise AnalysisError(f"Unexpected addr2line output for {elf}")
        filename, line = match.groups()
        frames.append({"function": None if function == "??" else function,
                       "file": None if filename == "??" else Path(filename).name,
                       "line": int(line) if line.isdigit() and int(line) else None})
    location.update(frames[0])
    if len(frames) > 1:
        location["inline_chain"] = frames
    return location


def classify(registers, cfsr_bits, hfsr_bits):
    cfsr = registers.get("cfsr", 0)
    causes = [name for mask, name in ((0x7F, "MemManage"), (0x7F00, "BusFault"),
                                     (0xFFFF0000, "UsageFault")) if cfsr & mask]
    fault_type = "HardFault" if hfsr_bits else "/".join(causes) or "Unknown"
    hints = [HINTS[bit] for bit in cfsr_bits + hfsr_bits if bit in HINTS]
    for valid, register in (("BFARVALID", "bfar"), ("MMARVALID", "mmfar")):
        if valid in cfsr_bits and registers.get(register, 0x1000) < 0x1000:
            hints.append(f"{register.upper()} is near zero; check for a NULL pointer plus a field offset.")
    if registers.get("lr", 0) >= 0xFFFFFF80:
        hints.append("Stacked LR is EXC_RETURN; the interrupted context's frame is higher "
                     "on the stack. Capture stack memory to unwind further.")
    return fault_type, " ".join(hints) or "Check the stacked frame and fault registers."


def analyze(registers, elf):
    missing = [key.upper() for key in REQUIRED if key not in registers]
    if missing:
        raise AnalysisError("Missing required registers: " + ", ".join(missing))
    cfsr_bits = decode_cfsr(registers["cfsr"])
    hfsr_bits = decode_hfsr(registers["hfsr"])
    fault_type, hint = classify(registers, cfsr_bits, hfsr_bits)
    caveats = list(getattr(registers, "caveats", []))
    caveats += [CAVEATS[bit] for bit in cfsr_bits if bit in CAVEATS]
    if "FORCED" in hfsr_bits:
        caveats.append(
            "CFSR has no fault bits; escalation came from something other than a CFSR fault "
            "(e.g. SVC/BKPT at too-low priority), or CFSR was already cleared."
            if registers["cfsr"] == 0 else
            "HFSR.FORCED indicates escalation to HardFault; inspect CFSR and SHCSR."
        )
    frame = None
    context = None
    pre_exception_sp = None
    if "exc_return" in registers:
        frame = "basic" if registers["exc_return"] & (1 << 4) else "extended"
    else:
        caveats.append("EXC_RETURN is missing; frame type and pre-exception SP cannot be determined.")
    if "xpsr" in registers:
        number = registers["xpsr"] & 0x1FF
        context = {"mode": "isr" if number else "thread", "exception_number": number}
    else:
        caveats.append("xPSR is missing; execution context and pre-exception SP cannot be determined.")
    if "sp" not in registers:
        caveats.append("SP is missing; pre-exception SP cannot be determined.")
    if all(key in registers for key in ("exc_return", "xpsr", "sp")):
        frame_size = 0x20 if frame == "basic" else 0x68
        padding = 4 if registers["xpsr"] & (1 << 9) else 0
        pre_exception_sp = registers["sp"] + frame_size + padding
    if frame == "extended" and registers.get("fpccr", 0) & 1:
        caveats.append("FPCCR.LSPACT is set; FP registers were not saved yet (lazy stacking).")
    causes = [CAUSES[bit] for bit in cfsr_bits if bit in CAUSES]
    return {
        "cause": causes[0] if len(causes) == 1 else "multiple_faults" if causes else None,
        "fault_type": fault_type,
        "frame": frame,
        "context": context,
        "pre_exception_sp": pre_exception_sp,
        "cfsr_bits": cfsr_bits,
        "hfsr_bits": hfsr_bits,
        "pc": symbolize(registers["pc"], elf),
        "lr": symbolize(registers["lr"], elf, is_lr=True),
        "bfar": registers.get("bfar") if "BFARVALID" in cfsr_bits else None,
        "mmfar": registers.get("mmfar") if "MMARVALID" in cfsr_bits else None,
        "hint": hint,
        "caveats": caveats,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="text file with key=value registers")
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    if not args.elf.is_file():
        parser.exit(1, f"error: ELF file not found: {args.elf}\n")
    try:
        dump = args.dump.read_text()
    except OSError as error:
        parser.exit(1, f"error: Cannot read dump: {error}\n")
    try:
        result = analyze(parse_dump(dump), args.elf)
    except AnalysisError as error:
        parser.exit(1, f"error: {error}\n")
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"Fault: {result['fault_type']}")
    print(f"Cause: {result['cause'] or 'unknown'}")
    print(f"Frame: {result['frame'] or 'unknown'}")
    context = result["context"]
    print("Context: " + (f"{context['mode']} (exception {context['exception_number']})"
                         if context else "unknown"))
    sp = result["pre_exception_sp"]
    print("Pre-exception SP: " + (f"0x{sp:08x}" if sp is not None else "unknown"))
    for key in ("cfsr_bits", "hfsr_bits"):
        print(f"{key.split('_')[0].upper()}: {', '.join(result[key]) or 'none'}")
    for key in ("pc", "lr"):
        loc = result[key]
        print(f"{key.upper()} {loc['addr']}: {loc['function'] or '??'} "
              f"({loc['file'] or '??'}:{loc['line'] or 0})")
        for caller in loc.get("inline_chain", [])[1:]:
            print(f"  Inline caller: {caller['function'] or '??'} "
                  f"({caller['file'] or '??'}:{caller['line'] or 0})")
    for key in ("bfar", "mmfar"):
        value = result[key]
        print(f"{key.upper()}: {'invalid' if value is None else f'0x{value:08x}'}")
    print(f"Hint: {result['hint']}")
    for caveat in result["caveats"]:
        print(f"Caveat: {caveat}")


if __name__ == "__main__":
    main()
