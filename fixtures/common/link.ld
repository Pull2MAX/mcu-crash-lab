ENTRY(Reset_Handler)

MEMORY {
    CODE (rx) : ORIGIN = 0x00000000, LENGTH = 4M
    RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 4M
}
_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS {
    .text : {
        KEEP(*(.isr_vector))
        *(.text*) *(.rodata*)
        . = ALIGN(4);
    } > CODE
    .ARM.exidx : { *(.ARM.exidx*) } > CODE
    _sidata = LOADADDR(.data);
    .data : {
        . = ALIGN(4);
        _sdata = .;
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > RAM AT > CODE
    .bss (NOLOAD) : {
        . = ALIGN(4);
        _sbss = .;
        *(.bss*) *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > RAM
}
