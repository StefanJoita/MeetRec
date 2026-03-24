# Cerințe client — Upload segmente audio

Acest document descrie exact ce trimite clientul desktop (Electron) la server,
pentru a ghida implementarea și testarea logicii de reconstrucție a sesiunilor.

## Endpoint

```
POST /api/v1/inbox/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

## Câmpuri FormData

| Câmp | Tip | Exemplu | Note |
|---|---|---|---|
| `file` | binary (WAV) | `sala-sedinte-2026-03-24T10-00-00.wav` | PCM 16-bit mono, sample rate variabil (48000 Hz tipic) |
| `title` | string | `"Ședință board"` | introdus de utilizator la Start |
| `meeting_date` | string | `"2026-03-24"` | introdus de utilizator |
| `location` | string | `"Sediu principal"` | din setări |
| `participants` | string | `"Ion, Maria"` | **opțional** — poate lipsi complet din FormData |
| `description` | string | `"Inregistrare automata — Sala de sedinte"` | generat automat |
| `session_id` | UUID v4 | `"550e8400-e29b-41d4-a716-446655440000"` | același pentru toate segmentele dintr-o sesiune |
| `segment_index` | integer ≥ 0 | `0`, `1`, `2`, ... | ordinea strictă în sesiune, începe de la 0 |

## Comportamentul clientului

**La `start()`:** se generează un `session_id` nou (`crypto.randomUUID()`).
`segment_index` se resetează la 0.

**La fiecare interval** (configurat de utilizator, 30s–3600s, default 300s):
se codifică PCM-ul acumulat în WAV și se trimite cu `session_id` curent și
`segment_index` incrementat.

**La `stop()`:** se face un flush final cu restul de PCM.
Acesta poate fi considerabil mai scurt decât durata configurată.

**Exemplu concret — ședință 1 oră, segmente 10 min:**

```
session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"  (fix pentru toată sesiunea)

segment_index=0  →  WAV ~10 min, ~27 MB
segment_index=1  →  WAV ~10 min, ~27 MB
segment_index=2  →  WAV ~10 min, ~27 MB
segment_index=3  →  WAV ~10 min, ~27 MB
segment_index=4  →  WAV ~10 min, ~27 MB
segment_index=5  →  WAV ~2 min  (flush final la stop — durată variabilă)
```

Toate 6 request-uri au același `session_id`. `segment_index` este strict
crescător, fără gaps în condiții normale.

## Ce trebuie să implementeze serverul

1. **Acceptă segmente individuale** — fiecare request este valid și complet
   independent (are `title`, `meeting_date` etc. repetate pe fiecare segment).

2. **Grupează după `session_id`** — toate segmentele cu același `session_id`
   aparțin aceleiași înregistrări.

3. **Ordonează după `segment_index`** — pentru reconstrucția audio și
   transcriere. Nu presupune că sosesc în ordine — coada are retry logic și
   în scenarii de reconectare ordinea de sosire poate diferi.

4. **Detectează completitudinea sesiunii** — clientul nu trimite un semnal
   explicit de "sesiune terminată". Serverul trebuie să decidă singur când să
   proceseze (ex: timeout după ultimul segment primit, sau trigger manual).

5. **Transcrierea** — pe audio-ul concatenat în ordine `segment_index`, nu pe
   segmente individuale. Dacă transcrierea se face per segment, apar artefacte
   la joncțiuni (cuvinte tăiate, context pierdut).

## Scenarii de testat

| Scenariu | Detalii |
|---|---|
| Ordine normală | Segmentele sosesc în ordine: 0, 1, 2, ... |
| Dezordine | Segmentele sosesc în ordine aleatorie din cauza retry-ului |
| Cel mai defavorabil | `segment_index=0` sosit ultimul |
| Ședință scurtă | Un singur segment cu `segment_index=0` (oprită înainte de primul interval) |
| Segment final scurt | Ultimul flush poate fi câteva secunde, nu durata configurată |
| `participants` lipsă | Câmpul nu apare deloc în FormData |
| Sesiuni simultane | Două instanțe client de la același user, `session_id` diferit |
| Segment duplicat | Același `session_id` + `segment_index` trimis de două ori (retry după upload parțial) — serverul trebuie să fie idempotent sau să dedupliceze |
