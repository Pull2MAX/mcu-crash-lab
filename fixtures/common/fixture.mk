CC = arm-none-eabi-gcc
MAIN ?= main.c
STARTUP ?= startup.c
LINKER ?= link.ld
BUILD ?= build
TOOLCHAIN_ROOT := $(realpath $(dir $(shell command -v $(CC)))/..)
CFLAGS = -mcpu=$(CPU) -mthumb -O0 -g -ffreestanding -fno-builtin \
         -Wall -Wextra -Werror -fno-unwind-tables -fno-asynchronous-unwind-tables \
         -ffile-prefix-map=$(CURDIR)=. -ffile-prefix-map=$(TOOLCHAIN_ROOT)=toolchain

.PHONY: all clean print-machine
all: $(BUILD)/firmware.elf

$(BUILD)/firmware.elf: $(BUILD)/main.o $(BUILD)/startup.o $(LINKER) ../common/fixture.mk
	@echo "LD $@"
	@$(CC) $(CFLAGS) -nostdlib -T $(LINKER) -Wl,--build-id=none,-Map,$(BUILD)/firmware.map $(BUILD)/main.o $(BUILD)/startup.o -o $@

$(BUILD)/main.o: $(MAIN) Makefile ../common/fixture.mk $(wildcard ../common/*.h)
	@mkdir -p $(BUILD)
	@echo "CC $<"
	@$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/startup.o: $(STARTUP) ../common/startup.c Makefile ../common/fixture.mk ../common/fixture.h
	@mkdir -p $(BUILD)
	@echo "CC $<"
	@$(CC) $(CFLAGS) -c $< -o $@

print-machine:
	@echo $(QEMU_MACHINE)

clean:
	$(RM) build/main.o build/startup.o build/firmware.elf build/firmware.map build/dump.txt
	$(RM) build/fixed/main.o build/fixed/startup.o build/fixed/firmware.elf build/fixed/firmware.map
