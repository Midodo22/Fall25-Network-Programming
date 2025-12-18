PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

main: install-deps
	make clean
	mkdir -p games-dev1
	cp games/rps.py games-dev1/rps.py
	mkdir -p games-dev2
	cp games/tetris.py games-dev2/tetris.py
	@echo "Starting database server..."
	@/bin/sh -c ' \
		$(PYTHON) database.py > db.log 2>&1 & \
		DB_PID=$$!; \
		echo "Database PID: $$DB_PID"; \
		trap "kill $$DB_PID 2>/dev/null || true" EXIT; \
		$(PYTHON) server.py; \
		kill $$DB_PID 2>/dev/null || true; \
		wait $$DB_PID 2>/dev/null || true \
	'

install-deps:
	$(PIP) install -r requirements.txt

clean:
	rm -f *.log
	rm -rf games-*
	rm -rf __pycache__
