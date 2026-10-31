PYTHON = python3
export PYTHONDONTWRITEBYTECODE = 1
FIXTURES = $(patsubst fixtures/%/expected.json,%,$(wildcard fixtures/*/expected.json))

.PHONY: test clean demo
test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'
	$(PYTHON) tests/run_fixtures.py

demo:
	$(PYTHON) skills/mcu-crash-lab/scripts/analyze_crash.py examples/offline/crash_full.txt --elf examples/offline/firmware.elf
	$(PYTHON) skills/mcu-crash-lab/scripts/analyze_crash.py examples/offline/crash_thin.txt --elf examples/offline/firmware.elf

clean:
	@for fixture in $(FIXTURES); do $(MAKE) --no-print-directory -C fixtures/$$fixture clean || exit $$?; done
	$(RM) tests/results.json
	@find skills/mcu-crash-lab/scripts tests -type f -name '*.pyc' -delete
	@find skills/mcu-crash-lab/scripts tests -type d -name __pycache__ -empty -delete
