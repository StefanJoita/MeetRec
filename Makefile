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

.PHONY: help start start-core stop restart logs ps build clean setup \
        db-shell redis-cli redis-queue api-shell stt-shell audit-shell \
        test frontend-test clean-all ssl-self-signed create-admin

# Prima instalare completă (Ubuntu/Debian)
install:
	@bash install/install.sh

# Afișează ajutor (rulat și cu "make" fără argumente)
help:
	@echo ""
	@echo "  Meeting Transcriber — Comenzi disponibile:"
	@echo ""
	@echo "  Configurare & build:"
	@echo "  make install         → Installer complet pentru mediu fresh (Ubuntu/Debian)"
	@echo "  make setup           → Configurare rapidă (copiază .env, creează foldere)"
	@echo "  make build           → Reconstruiește imaginile Docker"
	@echo "  make ssl-self-signed → Generează certificate SSL self-signed"
	@echo "  make create-admin    → Creează utilizator administrator"
	@echo ""
	@echo "  Pornire & oprire:"
	@echo "  make start           → Pornește TOATE serviciile"
	@echo "  make start-core      → Pornește doar serviciile esențiale"
	@echo "  make stop            → Oprește toate serviciile"
	@echo "  make restart         → Repornește toate serviciile"
	@echo ""
	@echo "  Inspecție:"
	@echo "  make logs            → Afișează logurile în timp real"
	@echo "  make logs-<serviciu> → Loguri pentru un serviciu specific (ex: make logs-api)"
	@echo "  make ps              → Statusul serviciilor"
	@echo ""
	@echo "  Shell & debugging:"
	@echo "  make db-shell        → Intră în PostgreSQL"
	@echo "  make redis-cli       → Intră în Redis CLI"
	@echo "  make redis-queue     → Verifică lungimea cozii de transcripție"
	@echo "  make api-shell       → Shell în containerul API"
	@echo "  make stt-shell       → Shell în containerul STT Worker"
	@echo "  make audit-shell     → Shell în containerul Audit & Retention"
	@echo ""
	@echo "  Testare:"
	@echo "  make test            → Rulează testele backend (api, ingest, stt-worker)"
	@echo "  make frontend-test   → Rulează testele frontend (Vitest)"
	@echo ""
	@echo "  Curățare:"
	@echo "  make clean           → Oprește și șterge containerele (DATELE RĂMÂN)"
	@echo "  make clean-all       → Oprește și șterge TOT, inclusiv datele (ATENȚIE!)"
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
	@echo "🚀 Pornind toate serviciile..."
	docker compose up -d
	@echo ""
	@echo "✅ Servicii pornite!"
	@echo "   🌐 Aplicație:  https://localhost"
	@echo "   🔌 API:        http://localhost:8080/docs"

# Pornește doar serviciile esențiale
start-core:
	@echo "🚀 Pornind serviciile esențiale..."
	docker compose up -d postgres redis api ingest stt-worker nginx frontend
	@echo ""
	@echo "✅ Servicii pornite!"
	@echo "   🌐 Aplicație:  https://localhost"
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

# Intră în containerul STT Worker pentru debugging
stt-shell:
	docker compose exec stt-worker /bin/bash

# Intră în containerul Audit & Retention pentru debugging
audit-shell:
	docker compose exec audit-retention /bin/bash

# Rulează testele
test:
	docker compose exec api pytest tests/ -v
	docker compose exec ingest pytest tests/ -v
	docker compose exec stt-worker pytest tests/ -v

# Rulează testele frontend (Vitest)
frontend-test:
	docker compose exec frontend npm run test

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

# Generează certificate SSL self-signed (pentru LAN/intranet)
# Folosire: make ssl-self-signed  sau  make ssl-self-signed HOST=192.168.1.100
ssl-self-signed:
	@bash install/scripts/gen-self-signed.sh $(HOST)
	@echo ""
	@echo "  Repornește nginx pentru a aplica certificatele:"
	@echo "  docker compose restart nginx"

# Creează utilizator administrator interactiv
create-admin:
	@echo "Creare utilizator administrator..."
	@read -p "Username [admin]: " username; \
	username=$${username:-admin}; \
	read -p "Email: " email; \
	read -sp "Parolă: " password; \
	echo ""; \
	docker compose exec api python3 -c " \
import asyncio, sys, uuid; \
sys.path.insert(0, '/app'); \
from src.database import AsyncSessionLocal; \
from src.models.audit_log import User; \
from passlib.context import CryptContext; \
from sqlalchemy import select; \
pwd_ctx = CryptContext(schemes=['bcrypt']); \
async def run(): \
    async with AsyncSessionLocal() as db: \
        r = await db.execute(select(User).where(User.username == '$$username')); \
        if r.scalar_one_or_none(): print('EROARE: utilizatorul există deja'); return; \
        db.add(User(id=uuid.uuid4(), username='$$username', email='$$email', \
            hashed_password=pwd_ctx.hash('$$password'), role='admin', \
            is_active=True, force_password_change=True)); \
        await db.commit(); \
        print('Administrator creat cu succes!'); \
asyncio.run(run())"