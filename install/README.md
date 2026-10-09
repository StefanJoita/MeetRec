# install/ — scripturi de instalare MeetRec

## Ce variantă alegi?

| Situație | Rulezi | Ghid complet |
|----------|--------|--------------|
| Server **Linux cu internet** | `bash install/online/install.sh` | [docs/INSTALL-ONLINE.md](../docs/INSTALL-ONLINE.md) · [EN](../docs/INSTALL-ONLINE.en.md) |
| **Windows** cu Docker Desktop | `.\install\online\install.ps1` | [docs/INSTALL-ONLINE.md](../docs/INSTALL-ONLINE.md) · [EN](../docs/INSTALL-ONLINE.en.md) |
| Server **fără internet** (air-gapped) | pe o mașină cu internet: `bash install/offline/build-bundle.sh`<br>pe server: `sudo ./install-offline.sh` (din pachet) | [docs/INSTALL-OFFLINE.md](../docs/INSTALL-OFFLINE.md) |

Toate comenzile se rulează din **rădăcina repo-ului**.

## Structură

```
install/
├── online/                       instalare directă pe un server cu internet
│   ├── install.sh                  Linux (Ubuntu/Debian): Docker, .env, certificate, build, admin
│   └── install.ps1                 Windows (Docker Desktop)
│
├── offline/                      instalare pe un server fără internet
│   ├── build-bundle.sh             [mașina cu internet] construiește dist/meetrec-offline-<ver>.tar
│   ├── download-docker-packages.sh [mașina cu internet] Docker Engine (.deb + binare statice); apelat de build-bundle.sh
│   ├── download-system-packages.sh [mașina cu internet] iptables, nftables, openssl + dependențe (.deb); apelat de build-bundle.sh
│   └── install-offline.sh          [serverul offline] installerul inclus în pachet
│
├── models/                       modelele ML incluse în imagini (folosite de ambele variante)
│   ├── download-models.py          descarcă Whisper, aliniere, diarizare, embeddings în services/*/models/
│   └── download-models-docker.sh   rulează scriptul de mai sus într-un container (fără Python pe host)
│
└── certs/                        certificate HTTPS → nginx/ssl/
    ├── gen-local-ca.sh             CA locală + certificat server (recomandat pentru LAN/offline)
    ├── gen-self-signed.sh          certificat self-signed (test / intern)
    └── gen-letsencrypt.sh          Let's Encrypt (doar server public, cu internet)
```

Pachetul offline generat ajunge în `dist/` (ignorat de git).
