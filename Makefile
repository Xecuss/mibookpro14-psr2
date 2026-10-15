.PHONY: check

check:
	python3 scripts/verify-data.py
	python3 -m unittest discover -s tests -p 'test_*.py'
	@set -e; check_bin=$$(mktemp /tmp/psr2-alignment-check.XXXXXX); \
	trap 'rm -f "$$check_bin"' EXIT; \
	$(CC) -O2 -Wall -Wextra tests/alignment-check.c -o "$$check_bin"; \
	"$$check_bin"
