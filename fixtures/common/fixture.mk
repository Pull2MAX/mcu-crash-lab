CC = arm-none-eabi-gcc
TOOLCHAIN_ROOT := $(realpath $(dir $(shell command -v $(CC)))/..)
CFLAGS = -mcpu=$(CPU) -mthumb -O0 -g -ffreestanding -fno-builtin \
         -Wall -Wextra -Werror -fno-unwind-tables -fno-asynchronous-unwind-tables \
         -ffile-prefix-map=$(CURDIR)=. -ffile-prefix-map=$(TOOLCHAIN_ROOT)=toolchain

.PHONY: all clean print-machine
all: build/firmware.elf

build/firmware.elf: build/main.o build/startup.o link.ld ../common/fixture.mk
	@echo "LD build/firmware.elf"
	@$(CC) $(CFLAGS) -nostdlib -T link.ld -Wl,--build-id=none,-Map,build/firmware.map build/main.o build/startup.o -o $@

build/%.o: %.c Makefile ../common/fixture.mk
	@mkdir -p build
	@echo "CC $<"
	@$(CC) $(CFLAGS) -c $< -o $@

build/startup.o: ../common/startup.c

print-machine:
	@echo $(QEMU_MACHINE)

clean:
	$(RM) build/main.o build/startup.o build/firmware.elf build/firmware.map build/dump.txt
