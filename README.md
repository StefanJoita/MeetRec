# MeetRec

MeetRec este un MVP pentru ingestie, procesare si transcriere de inregistrari de sedinte.

## Ce include acum

- Ingest service: monitorizeaza inbox-ul, valideaza audio, stocheaza fisierul si publica job in Redis.
- API service (schelet): configurare + modele SQLAlchemy de baza.
- PostgreSQL schema initiala.
- Nginx reverse proxy config.
- Stack de observabilitate Loki + Promtail.

## Structura proiect

```text
meeting-transcriber/
	database/
		init.sql
	monitoring/
		loki/loki-config.yaml
		promtail/promtail-config.yaml
	nginx/
		nginx.conf
		conf.d/meeting.transcriber.conf
	services/
		api/
			requirements.txt
			src/
		ingest/
			Dockerfile
			requirements.txt
			src/
```

## Prerequisites

- Docker Desktop
- Git
- Windows PowerShell (comenzile de mai jos sunt pentru PowerShell)

## Cum rulezi local

In workspace-ul curent, fisierul `docker-compose.yml` este in folderul parinte (`d:/MeetRec_MVP`).

1. Creeaza `.env` in `d:/MeetRec_MVP` (daca nu exista deja), pornind de la template-ul tau local.
2. Ruleaza stack-ul minim pentru ingest:

```powershell
docker compose --project-directory "d:\MeetRec_MVP\meeting-transcriber" --env-file "d:\MeetRec_MVP\.env" -f "d:\MeetRec_MVP\docker-compose.yml" up -d postgres redis ingest
```

3. Verifica status:

```powershell
docker compose --project-directory "d:\MeetRec_MVP\meeting-transcriber" --env-file "d:\MeetRec_MVP\.env" -f "d:\MeetRec_MVP\docker-compose.yml" ps ingest redis postgres
```

4. Verifica loguri ingest:

```powershell
docker compose --project-directory "d:\MeetRec_MVP\meeting-transcriber" --env-file "d:\MeetRec_MVP\.env" -f "d:\MeetRec_MVP\docker-compose.yml" logs -f ingest
```

## Smoke test pentru ingest

Genereaza un WAV valid direct in inbox:

```powershell
docker compose --project-directory "d:\MeetRec_MVP\meeting-transcriber" --env-file "d:\MeetRec_MVP\.env" -f "d:\MeetRec_MVP\docker-compose.yml" exec -T ingest sh -lc "ffmpeg -f lavfi -i sine=frequency=440:duration=6 -ar 16000 -ac 1 /data/inbox/smoke_test.wav -y"
```

Verifica rezultatul:

```powershell
docker compose --project-directory "d:\MeetRec_MVP\meeting-transcriber" --env-file "d:\MeetRec_MVP\.env" -f "d:\MeetRec_MVP\docker-compose.yml" logs --tail=120 ingest
docker compose --project-directory "d:\MeetRec_MVP\meeting-transcriber" --env-file "d:\MeetRec_MVP\.env" -f "d:\MeetRec_MVP\docker-compose.yml" exec -T redis redis-cli LLEN transcription_jobs
```

Semnale de succes in logs:

- `validation_success`
- `recording_created`
- `job_published`
- `processing_completed`

## Fisiere cheie

- `database/init.sql`: schema initiala (recordings, transcripts, audit_logs).
- `services/ingest/src/main.py`: bootstrapping ingest.
- `services/ingest/src/watcher.py`: monitorizare inbox + dispatch procesare.
- `services/ingest/src/processor.py`: orchestrare validator/storage/db/publisher.
- `services/ingest/src/database.py`: operatii DB pentru ingest.
- `services/ingest/src/publisher.py`: publicare joburi in Redis.

## Troubleshooting rapid

- Daca `ingest` este in restart loop: verifica `docker compose ... logs --tail=200 ingest`.
- Daca push-ul in GitHub este respins cu `fetch first`: fa `git pull origin main --allow-unrelated-histories`, apoi `git push`.
- Daca lipsesc variabile in compose: completeaza `.env` in `d:/MeetRec_MVP`.

## Status curent

- Ingest startup: functional.
- Ingest smoke test (WAV -> DB + Redis queue): functional.
- API: schelet in lucru (necesita completari pentru runtime complet).