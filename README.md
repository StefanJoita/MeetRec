# MeetRec

MeetRec este un MVP pentru ingestie, procesare si transcriere de inregistrari audio.

Acest repository contine structura completa a proiectului, inclusiv directoarele goale necesare pentru dezvoltare. Directoarele goale sunt pastrate in Git cu fisiere `.gitkeep`.

## Stack

- PostgreSQL
- Redis
- Nginx
- Ingest service (Python)
- API service (schelet)
- Monitoring (Loki + Promtail)

## Structura proiect (snapshot)

```text
meeting-transcriber/
	.env.example
	docker-compose.yml
	Makefile
	README.md

	data/
		exports/.gitkeep
		inbox/.gitkeep
		processed/.gitkeep

	database/
		init.sql
		migrations/.gitkeep
		seeds/.gitkeep

	frontend/
		src/
			api/.gitkeep
			components/.gitkeep
			hooks/.gitkeep
			pages/.gitkeep

	monitoring/
		dashboards/.gitkeep
		grafana/.gitkeep
		loki/loki-config.yaml
		promtail/promtail-config.yaml

	nginx/
		nginx.conf
		conf.d/meeting.transcriber.conf
		ssl/.gitkeep

	services/
		api/
			requirements.txt
			tests/.gitkeep
			src/
				config.py
				middleware/.gitkeep
				models/
					base.py
					recording.py
				routers/.gitkeep
				services/.gitkeep

		audit-retention/
			src/.gitkeep

		ingest/
			Dockerfile
			requirements.txt
			src/
				config.py
				database.py
				logger.py
				main.py
				processor.py
				publisher.py
				storage.py
				validator.py
				watcher.py
			tests/
				test_validator.py

		search-indexer/
			src/.gitkeep

		stt-worker/
			models/.gitkeep
```

## Setup rapid

1. Clone repository.
2. Copiaza template-ul de env:

```powershell
Copy-Item .env.example .env
```

3. Completeaza valorile din `.env`.

## Rulare (stack minim pentru ingest)

```powershell
docker compose up -d postgres redis ingest
docker compose ps ingest redis postgres
docker compose logs -f ingest
```

## Smoke test ingest

Genereaza un fisier audio de test direct in inbox:

```powershell
docker compose exec -T ingest sh -lc "ffmpeg -f lavfi -i sine=frequency=440:duration=6 -ar 16000 -ac 1 /data/inbox/smoke_test.wav -y"
```

Verificari:

```powershell
docker compose logs --tail=120 ingest
docker compose exec -T redis redis-cli LLEN transcription_jobs
```

Semnale de succes in loguri:

- `validation_success`
- `recording_created`
- `job_published`
- `processing_completed`

## Comenzi utile (Makefile)

```powershell
make setup
make build
make start
make logs
make ps
```

## Status actual

- Ingest startup: functional
- Ingest smoke test (WAV -> storage + DB + Redis): functional
- API: schelet in lucru