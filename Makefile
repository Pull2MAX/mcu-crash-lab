PYTHON = python3
export PYTHONDONTWRITEBYTECODE = 1
FIXTURES = div0_usagefault undefined_instruction_usagefault unmapped_write_busfault fpu_frame_fault

.PHONY: test clean
test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'
	$(PYTHON) tests/run_fixtures.py

clean:
	@for fixture in $(FIXTURES); do $(MAKE) --no-print-directory -C fixtures/$$fixture clean || exit $$?; done
	$(RM) tests/results.json
	@find skills/mcu-crash-lab/scripts tests -type f -name '*.pyc' -delete
	@find skills/mcu-crash-lab/scripts tests -type d -name __pycache__ -empty -delete
