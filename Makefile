# ============================================
# NÉRON AI — MAKEFILE DEV
# ============================================

.PHONY: help test status submodules clean install-dev install install-check update ollama health

help:
	@echo "NÉRON DEV"
	@echo ""
	@echo "Commandes disponibles :"
	@echo "  make test              Lance les tests"
	@echo "  make status            Affiche l'état Git et des submodules"
	@echo "  make health            Vérifie l'environnement NéronOS"
	@echo "  make submodules        Initialise/met à jour les submodules"
	@echo "  make clean             Nettoie les caches Python/Pytest"
	@echo "  make update            Met à jour les paquets venv"
	@echo "  make install-dev       Installe les dépendances"
	@echo "  make install-check     Compare la config déployée au dépôt"
	@echo "  make install           Installe la config de déploiement (sudo)"

test:
	pytest

status:
	git status
	@echo ""
	git submodule status

submodules:
	git submodule update --init --recursive

clean:
	@neron clean

update:
	python -m pip install --upgrade pip

ollama:
	curl -fsSL https://ollama.com/install.sh | sh

install-dev:
	pip install -r system/requirements/dev.txt \
		--constraint system/requirements/constraints.txt --prefer-binary

install-check:
	@./system/deploy/install.sh check

install:
	sudo ./system/deploy/install.sh install

health:
	@status=0; \
	echo "┌─────────────────────────────────────┐"; \
	echo "│          NÉRONOS ENVIRONMENT        │"; \
	echo "├─────────────────────────────────────┤"; \
	node_v="$$(node -v | sed 's/^v//')"; \
	npm_v="$$(npm -v)"; \
	pnpm_v="$$(pnpm -v)"; \
	python_v="$$(python3 --version | awk '{print $$2}')"; \
	pip_v="$$(/etc/neronOS/venv/bin/python -m pip --version | awk '{print $$2}')"; \
	printf "│ Node.js       %-14s %-7s│\n" "$$node_v" "OK"; \
	printf "│ npm           %-14s %-7s│\n" "$$npm_v" "OK"; \
	printf "│ pnpm          %-14s %-7s│\n" "$$pnpm_v" "OK"; \
	printf "│ Python        %-14s %-7s│\n" "$$python_v" "OK"; \
	printf "│ pip           %-14s %-7s│\n" "$$pip_v" "OK"; \
	printf "│ Python venv   %-14s %-7s│\n" "/etc/neronOS" "OK"; \
	if /etc/neronOS/venv/bin/python -m pip check >/dev/null 2>&1; then dep="OK"; else dep="FAILED"; status=1; fi; \
	printf "│ Dependencies  %-14s %-7s│\n" "pip check" "$$dep"; \
	http="$$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:4400/)"; \
	if [ "$$http" = "200" ] || [ "$$http" = "301" ] || [ "$$http" = "302" ]; then dash="OK"; else dash="FAILED"; status=1; fi; \
	printf "│ Dashboard     %-14s %-7s│\n" "HTTP $$http" "$$dash"; \
	if curl -sf --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then ollama="OK"; else ollama="FAILED"; status=1; fi; \
	printf "│ Ollama        %-14s %-7s│\n" "api/tags" "$$ollama"; \
	for svc in core llm memory goal doctor voice print gateways; do \
		state="$$(systemctl is-active neron@$$svc.service)"; \
		if [ "$$state" = "active" ]; then result="OK"; else result="FAILED"; status=1; fi; \
		printf "│ %-13s %-14s %-7s│\n" "$$(echo $$svc | sed 's/.*/\u&/')" "$$state" "$$result"; \
	done; \
	for svc in cognitive-loop world-model-loop homeassistant-registry; do \
		state="$$(systemctl is-active neron-$$svc.service)"; \
		if [ "$$state" = "active" ]; then result="OK"; else result="FAILED"; status=1; fi; \
		case "$$svc" in \
			cognitive-loop) name="Cognitive" ;; \
			world-model-loop) name="World Model" ;; \
			homeassistant-registry) name="HA Registry" ;; \
		esac; \
		printf "│ %-13s %-14s %-7s│\n" "$$name" "$$state" "$$result"; \
	done; \
	echo "└─────────────────────────────────────┘"; \
	exit $$status
