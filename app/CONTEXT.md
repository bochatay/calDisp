# CONTEXT — Mémoire de l'assistant (à compléter librement)

> Ce fichier sert de mémoire/notes de contexte pour l'assistant IA.
> Il est volontairement **hors du code applicatif** : c'est de la documentation
> de contexte, pas un module du projet. Complète-le quand tu veux ajouter des
> informations que je ne peux pas déduire tout seul.

## Environnement d'exécution (important)

- Je travaille dans un **conteneur Docker de dev dédié** (pas le conteneur de
  production décrit dans `docker/docker-compose.yaml`).
- Le dossier de l'application **`app` est monté dans le conteneur** ; c'est mon
  répertoire de travail `/workspace`. Tout ce que j'y écris persiste côté hôte
  (montage en lecture/écriture).
- Le fichier **`.env` est situé à l'extérieur de `app`** (au niveau hôte, à côté
  du dossier `app`). **Je ne le vois donc PAS** depuis le conteneur : les
  variables `CALDAV_*`, `S6_*`, etc. ne sont pas présentes dans mon
  environnement. À ne pas confondre avec une configuration absente.
- Le conteneur de dev démarre via `/entrypoint.sh` (génère les clés SSH puis
  lance `sshd`) : l'accès se fait donc par **SSH**. Hostname actuel : conteneur
  `26693102b03e`, utilisateur `dev` (home `/home/dev`).
- Docker est présent (présence de `/.dockerenv`), Python 3.12 disponible.

## Ce que je vois / ne vois pas

| Élément | Visible depuis mon conteneur ? |
|---|---|
| Code applicatif (`*.py`, `requirements.txt`, `docker/`, `output/`) | Oui, dans `/workspace` |
| `.env` (secrets CalDAV, chemins, options) | **Non** (hors de `app`) |
| `docker-compose.yaml` à la racine hôte | Non (seul `docker/docker-compose.yaml` est dans `app`) |

## Rappel d'analyse du projet (résumé)

Service FastAPI qui génère un calendrier e-paper (dalle Spectra 6, 1200x1600) :
CalDAV -> événements -> image PIL (mode P) -> `output/calendar.png` +
`output/calendar.s6` (4 bits/pixel pour ESP32). Rafraîchissement périodique via
`apscheduler`. Tramage *blue noise* pour les couleurs non natives.

Note : `docker/docker-compose.yaml` utilise `build.context: app`, donc il est
prévu pour être lancé depuis le niveau au-dessus de `app` (là où est aussi le
`.env`). C'est cohérent avec l'organisation décrite plus haut.

## Notes / ajouts

Les polices fonts-dejavu-core, fonts-noto et fonts-liberation sont installées sur le container de dev ainsi que sur celui du projet.

<!-- Ajoute ici les informations que tu veux me transmettre :
     - valeurs ou emplacement du .env
     - procédure de lancement / commandes utiles
     - URL et identifiants CalDAV si tu souhaites que je teste (attention secrets)
     - détails matériels ESP32 / dalle
     - conventions, contraintes, TODO
-->
- (à compléter)
