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
KEYS = "r0 r1 r2 r3 r12 lr pc xpsr exc_return cfsr hfsr mmfar bfar sp".split()
HINTS = {
    "IACCVIOL": "Check MPU execute permissions and the jump target.",
    "DACCVIOL": "Check the pointer and MPU data permissions.",
    "MUNSTKERR": "Check SP and stack corruption on exception return.",
    "MSTKERR": "Check stack space and MPU stack guards on exception entry.",
    "MLSPERR": "Check stack access during lazy FP state preservation.",
    "IBUSERR": "Check the instruction address and function pointers.",
    "PRECISERR": "Check the load/store pointer and the board memory map.",
    "IMPRECISERR": "The failed store may precede PC; inspect earlier stores. On Cortex-M3/M4, try ACTLR.DISDEFWBUF.",
    "UNSTKERR": "Check SP and stack memory on exception return.",
    "STKERR": "Check for stack overflow or SP outside RAM on exception entry.",
    "LSPERR": "Check stack memory during lazy FP state preservation.",
    "UNDEFINSTR": "Check the instruction at PC and the build CPU flags.",
    "INVSTATE": "Check the Thumb bit in function pointers and stacked xPSR.",
    "INVPC": "Check EXC_RETURN and stack corruption on exception return.",
    "NOCP": "Check coprocessor instructions and FPU enable bits in CPACR.",
    "STKOF": "Check the stack limit and available stack space (Armv8-M).",
    "UNALIGNED": "Align the accessed data or use memcpy for packed data.",
    "DIVBYZERO": "Check the divisor before integer division; CCR.DIV_0_TRP is set.",
    "VECTTBL": "Check VTOR and the vector table memory.",
    "FORCED": "A configurable fault escalated to HardFault; inspect CFSR and SHCSR.",
    "DEBUGEVT": "Check for a breakpoint or debug event without a debugger.",
}


def decode_bits(value, table):
    return [name for bit, name in sorted(table.items()) if value & (1 << bit)]


def decode_cfsr(value):
    return decode_bits(value, MMFSR | BFSR | UFSR)


def decode_hfsr(value):
    return decode_bits(value, HFSR)


def parse_dump(text):
    registers = {}
    for key, value in re.findall(
        r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*[=:]\s*(0[xX][0-9a-fA-F]+|[0-9]+)\s*$",
        text, re.MULTILINE,
    ):
        if key.lower() in KEYS:
            registers[key.lower()] = int(value, 16 if value.lower().startswith("0x") else 10)
    return registers


def symbolize(addr, elf, is_lr=False):
    location = {"addr": f"0x{addr:08x}", "function": None, "file": None, "line": None}
    if is_lr and addr >= 0xFFFFFF80:
        return location
    # LR points past the call; the preceding halfword belongs to that call.
    lookup = (addr & ~1) - (2 if is_lr and addr > 1 else 0)
    result = subprocess.run(
        ["arm-none-eabi-addr2line", "-f", "-e", str(elf), hex(lookup)],
        check=True, capture_output=True, text=True,
    )
    function, source = result.stdout.strip().splitlines()
    filename, line = source.rsplit(":", 1)
    line = line.split()[0]
    location.update(function=None if function == "??" else function,
                    file=None if filename == "??" else Path(filename).name,
                    line=int(line) if line.isdigit() and int(line) else None)
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
    if "FORCED" in hfsr_bits and not cfsr_bits:
        hints.append("FORCED is set but CFSR is zero; capture CFSR before clearing it.")
    if registers.get("lr", 0) >= 0xFFFFFF80:
        hints.append("LR is EXC_RETURN; supply the stacked LR for the caller location.")
    return fault_type, " ".join(hints) or "Check the stacked frame and fault registers."


def analyze(registers, elf):
    cfsr_bits = decode_cfsr(registers.get("cfsr", 0))
    hfsr_bits = decode_hfsr(registers.get("hfsr", 0))
    fault_type, hint = classify(registers, cfsr_bits, hfsr_bits)
    return {
        "fault_type": fault_type,
        "cfsr_bits": cfsr_bits,
        "hfsr_bits": hfsr_bits,
        "pc": symbolize(registers["pc"], elf),
        "lr": symbolize(registers["lr"], elf, is_lr=True),
        "bfar": registers.get("bfar") if "BFARVALID" in cfsr_bits else None,
        "mmfar": registers.get("mmfar") if "MMARVALID" in cfsr_bits else None,
        "hint": hint,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="text file with key=value registers")
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    result = analyze(parse_dump(args.dump.read_text()), args.elf)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"Fault: {result['fault_type']}")
    for key in ("cfsr_bits", "hfsr_bits"):
        print(f"{key.split('_')[0].upper()}: {', '.join(result[key]) or 'none'}")
    for key in ("pc", "lr"):
        loc = result[key]
        print(f"{key.upper()} {loc['addr']}: {loc['function'] or '??'} "
              f"({loc['file'] or '??'}:{loc['line'] or 0})")
    for key in ("bfar", "mmfar"):
        value = result[key]
        print(f"{key.upper()}: {'invalid' if value is None else f'0x{value:08x}'}")
    print(f"Hint: {result['hint']}")


if __name__ == "__main__":
    main()
