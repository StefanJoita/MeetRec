# ============================================================
# Makefile — Comenzi rapide pentru proiect
# ============================================================
# Folosire: make <comandă>
# Exemplu:  make start
#
# De ce Makefile și nu scripturi bash?
# → O singură locație pentru toate comenzile
# → Auto-documentare (make help)
# → Standard în lumea open-source

.PHONY: help start stop restart logs ps build clean setup

# Afișează ajutor (rulat și cu "make" fără argumente)
help:
	@echo ""
	@echo "  Meeting Transcriber — Comenzi disponibile:"
	@echo ""
	@echo "  make setup      → Prima configurare (copiază .env, creează foldere)"
	@echo "  make start      → Pornește toate serviciile"
	@echo "  make stop       → Oprește toate serviciile"
	@echo "  make restart    → Repornește toate serviciile"
	@echo "  make build      → Reconstruiește imaginile Docker"
	@echo "  make logs       → Afișează logurile în timp real"
	@echo "  make ps         → Statusul serviciilor"
	@echo "  make db-shell   → Intră în PostgreSQL"
	@echo "  make redis-cli  → Intră în Redis CLI"
	@echo "  make clean      → Oprește și șterge containerele (DATELE RĂMÂN)"
	@echo "  make clean-all  → Oprește și șterge TOT, inclusiv datele (ATENȚIE!)"
	@echo ""

# Prima configurare
setup:
	@echo "⚙️  Configurare inițială..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ Creat .env din .env.example — editează-l cu valorile tale!"; \
	else \
		echo "ℹ️  .env există deja"; \
	fi
	@mkdir -p data/inbox data/processed data/exports
	@touch data/inbox/.gitkeep data/processed/.gitkeep data/exports/.gitkeep
	@echo "✅ Foldere create"
	@echo ""
	@echo "📋 Pași următori:"
	@echo "   1. Editează .env cu valorile corecte"
	@echo "   2. Rulează: make build"
	@echo "   3. Rulează: make start"

# Pornește serviciile
start:
	@echo "🚀 Pornind serviciile..."
	docker compose up -d
	@echo ""
	@echo "✅ Servicii pornite!"
	@echo "   🌐 Aplicație:  https://localhost"
	@echo "   📊 Grafana:    http://localhost:3000"
	@echo "   🔌 API:        http://localhost:8080/docs"

# Oprește serviciile
stop:
	@echo "🛑 Oprind serviciile..."
	docker compose stop

# Repornește
restart:
	@echo "🔄 Repornind serviciile..."
	docker compose restart

# Construiește imaginile
build:
	@echo "🔨 Construind imaginile Docker..."
	docker compose build --no-cache

# Loguri în timp real
logs:
	docker compose logs -f --tail=100

# Loguri pentru un serviciu specific
logs-%:
	docker compose logs -f --tail=100 $*
# Folosire: make logs-api, make logs-stt-worker

# Status servicii
ps:
	docker compose ps

# Shell în PostgreSQL
db-shell:
	docker compose exec postgres psql -U $${POSTGRES_USER} -d $${POSTGRES_DB}

# Redis CLI
redis-cli:
	docker compose exec redis redis-cli

# Verifică job-urile din coadă Redis
redis-queue:
	docker compose exec redis redis-cli LLEN transcription_jobs

# Intră în containerul API pentru debugging
api-shell:
	docker compose exec api /bin/bash

# Rulează testele
test:
	docker compose exec api pytest tests/ -v
	docker compose exec ingest pytest tests/ -v

# Oprește și șterge containerele (volumele cu date rămân!)
clean:
	@echo "🧹 Ștergând containerele (datele rămân)..."
	docker compose down

# Oprește și șterge TOT (inclusiv datele din volume!)
clean-all:
	@echo "⚠️  ATENȚIE: Aceasta șterge TOATE datele!"
	@read -p "Ești sigur? (tastează 'da'): " confirm; \
	if [ "$$confirm" = "da" ]; then \
		docker compose down -v; \
		echo "✅ Tot a fost șters"; \
	else \
		echo "❌ Anulat"; \
	fi