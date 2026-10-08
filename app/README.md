# Calendrier e-paper Spectra 6 — configuration `.env`

Service FastAPI qui récupère les événements d'un agenda **CalDAV** (Radicale, etc.)
et génère l'image d'un calendrier 7 jours pour une dalle **Waveshare Spectra 6**
(1200×1600, 6 couleurs). À chaque rafraîchissement, deux fichiers sont produits :
`calendar.png` (aperçu) et `calendar.s6` (binaire 4 bits/pixel à envoyer à l'ESP32).

Un **bandeau en bas de l'image** récapitule les calendriers affichés (pastille de
couleur + nom, dans l'ordre de `CALDAV_CALENDARS`) et affiche à droite l'**heure
de génération** au format local (`JJ/MM/AAAA HH:MM`).

## Démarrage rapide

Le fichier `.env` se place **à côté du dossier `app`** (pas dedans). Contenu minimal :

```env
CALDAV_URL=https://cal.example.net/radicale/user/
CALDAV_USERNAME=user
CALDAV_PASSWORD=secret
```

Lancement (depuis le dossier parent de `app`) :

```bash
docker compose -f app/docker/docker-compose.yaml up -d
```

## Exemple `.env` complet

```env
# --- Connexion CalDAV (obligatoire) ---
CALDAV_URL=https://cal.example.net/radicale/user/
CALDAV_USERNAME=user
CALDAV_PASSWORD=secret

# --- Calendriers à afficher : "Nom:Couleur" séparés par des virgules ---
CALDAV_CALENDARS=Perso:YELLOW_45_3,Travail:RED_0_90_4,Famille:GREEN,Todo:light_blue

# --- Rafraîchissement et affichage ---
REFRESH_INTERVAL_MINUTES=60
DISPLAY_TIMEZONE=Europe/Paris
DAYS_AHEAD=7
FIRST_COLUMN_SCALE=1.5
START_HOUR=6
END_HOUR=23

# --- Fichiers produits (fixes par le docker-compose ; ne surcharger que si besoin) ---
# IMAGE_PATH=/opt/calendar-output/calendar.png
# S6_PATH=/opt/calendar-output/calendar.s6
S6_ROTATION=90

# --- Fonds des colonnes (une variable par jour, vide = blanc) ---
MONDAY=WHITE
TUESDAY=BLUE_45_5
WEDNESDAY=
THURSDAY=purple
FRIDAY=blue_cyan
SATURDAY=YELLOW_0_90_8
SUNDAY=GREEN

# --- Optionnel ---
DITHER_NOISE_SIZE=64
# FONT_PATH=/app/fonts/NotoSans-Regular.ttf
# FONT_BOLD_PATH=/app/fonts/NotoSans-Bold.ttf
```

## Référence des variables

| Variable | Défaut | Description |
|---|---|---|
| `CALDAV_URL` | — (**obligatoire**) | URL du serveur CalDAV |
| `CALDAV_USERNAME` | — (**obligatoire**) | Utilisateur CalDAV |
| `CALDAV_PASSWORD` | — (**obligatoire**) | Mot de passe CalDAV |
| `CALDAV_CALENDARS` | *(vide)* | Calendriers affichés, `Nom:Couleur` séparés par `,`. Vide = **tous** les calendriers (noir). |
| `REFRESH_INTERVAL_MINUTES` | `60` | Intervalle de régénération, en minutes |
| `DISPLAY_TIMEZONE` | `Europe/Paris` | Fuseau d'affichage |
| `DAYS_AHEAD` | `7` | Nombre de jours affichés (colonnes) |
| `FIRST_COLUMN_SCALE` | `1.5` | Largeur de la 1ʳᵉ colonne (aujourd'hui) par rapport aux autres (`1.5` = +50 %) |
| `START_HOUR` | `6` | Debut (heure locale, incluse) de la plage de rafraichissement |
| `END_HOUR` | `23` | Fin (heure locale, exclue) de la plage ; hors plage, aucun appel CalDAV |
| `IMAGE_PATH` | `/opt/calendar-output/calendar.png` | Chemin du PNG de prévisualisation |
| `S6_PATH` | *(déduit de `IMAGE_PATH`)* | Chemin du binaire `.s6` |
| `S6_ROTATION` | `90` | Rotation paysage→portrait de la dalle : `90` ou `270` |
| `MONDAY` … `SUNDAY` | `WHITE` | Couleur/motif de fond de chaque colonne (vide = blanc) |
| `DITHER_NOISE_SIZE` | `64` | Taille du masque *blue noise* : `32` ou `64` |
| `FONT_PATH` | *(auto)* | Police TrueType normale forcée (Noto Sans par défaut) |
| `FONT_BOLD_PATH` | *(auto)* | Police TrueType grasse forcée |

## Les couleurs

Partout où une couleur est attendue (`CALDAV_CALENDARS`, `MONDAY`…`SUNDAY`), on peut mettre :

- une **couleur native** (rendue en aplat uni) : `BLACK`, `WHITE`, `RED`, `YELLOW`, `GREEN`, `BLUE` ;
- une **couleur logique** (mélange de deux natives, rendu par tramage) ;
- un **motif** (hachures, pointillés, tirets, bandes, damier).

La casse n'est pas significative : `yellow`, `YELLOW` et `Yellow` sont équivalents.

### Couleurs logiques (mélanges tramés)

`orange`, `red_orange`, `yellow_orange`,
`purple`, `red_purple`, `blue_purple`,
`lime`, `green_yellow`, `yellow_green`,
`cyan`, `green_cyan`, `blue_cyan`,
`brown`, `red_brown`, `green_brown`,
`gray`, `dark_gray`, `light_gray`,
`pink`, `light_red`, `light_yellow`, `light_green`, `light_blue`,
`dark_red`, `dark_yellow`, `dark_green`, `dark_blue`.

## Les motifs

Syntaxe : `ENCRE_motif[_paramètre]_espacement`. L'**encre** est l'une des **6 couleurs natives** (les autres noms ne sont pas acceptés ici). Le fond d'un motif est toujours **blanc**.

### Lignes — `ENCRE_angle1[_angle2]_N`

`N` = espacement en pixels (2 à 100). Angles : `0` = horizontale, `90` = verticale,
`45`/`135` = diagonales (tout angle entier est accepté). Le 2ᵉ angle est optionnel.

| Exemple | Rendu |
|---|---|
| `YELLOW_45_3` | lignes jaunes à 45°, une tous les 3 px |
| `YELLOW_135_4` | idem à 135° (sens inverse) |
| `RED_0_90_4` | grille rouge (horizontales + verticales), une tous les 4 px |
| `BLUE_45_135_5` | croix bleue (les deux diagonales), une tous les 5 px |

### Pointillés — `ENCRE_p[taille][h|v]_pas[_pas2]`

`taille` = taille des points, de 2 à 9 px (défaut 1). `h`/`v` = sens seul (sinon les deux).

| Exemple | Rendu |
|---|---|
| `RED_p_10` | un point tous les 10 px en V et H |
| `RED_p_3_12` | points tous les 3 px, lignes tous les 12 px (deux sens) |
| `RED_ph_3_12` | pointillés **horizontaux** seulement |
| `RED_pv_3_12` | pointillés **verticaux** seulement |
| `BLUE_p2_8` | gros points 2×2 px tous les 8 px |
| `BLUE_p2v_8` | idem, verticaux seulement |

### Tirets — `ENCRE_t[h|v]_longueur_période`

| Exemple | Rendu |
|---|---|
| `GREEN_t_3_10` | tirets de 3 px tous les 10 px (deux sens) |
| `GREEN_th_3_10` | tirets **horizontaux** seulement |
| `GREEN_tv_3_10` | tirets **verticaux** seulement |

### Bandes — `ENCRE_b[h|v]_largeur_période`

| Exemple | Rendu |
|---|---|
| `BLUE_b_4_16` | bandes pleines de 4 px tous les 16 px (deux sens) |
| `BLUE_bh_4_16` | bandes **horizontales** seulement |
| `BLUE_bv_4_16` | bandes **verticales** seulement |

### Damier — `ENCRE_d_cellule`

| Exemple | Rendu |
|---|---|
| `BLACK_d_8` | damier de cases 8×8 px |

> Une valeur de couleur ou de motif inconnue fait tomber la couleur sur **noir**, avec un avertissement dans les journaux (`POST /generate` indique aussi `color_valid: false`).

## Endpoints HTTP

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/calendar.png` | PNG de prévisualisation |
| `GET` | `/calendar.s6` | binaire Spectra 6 (4 bits/pixel) pour l'ESP32 (+ tension batterie, v. plus bas) |
| `POST` | `/generate` | régénère à la demande + rapport par calendrier |
| `GET` | `/status` | état du planificateur : intervalle **réel**, prochaine exécution, dernier résultat, dernière tension reçue |
| `GET` | `/version` | numéro de version de l'image courante |
| `GET` | `/health` | sonde de santé |

## Format du fichier `.s6`

Binaire « version 1 » destiné à l'ESP32 : un **en-tête de 17 octets** (little-endian)
suivi des pixels, **4 bits par pixel**. Taille totale : `17 + 600 × 1600 = 960017` octets.

### En-tête (17 octets)

| Offset | Taille | Champ | Valeur |
|---|---|---|---|
| 0 | 8 | nom du format (ASCII, non terminé) | `SPECTRA6` |
| 8 | 1 | version du format | `1` |
| 9 | 2 | largeur de la dalle, `uint16` | `1200` |
| 11 | 2 | hauteur de la dalle, `uint16` | `1600` |
| 13 | 1 | bits par pixel | `4` |
| 14 | 1 | nombre de couleurs de la palette | `6` |
| 15 | 2 | offset des données pixels | `17` |

### Disposition mémoire

La dalle est native en **portrait (1200×1600)** et se divise en **deux moitiés de
600×1600**, envoyées l'une après l'autre :

```
 en-tête (17 o) │ moitié GAUCHE (600×1600) │ moitié DROITE (600×1600)
```

Dans chaque moitié : les lignes vont de haut en bas, les pixels de gauche à
droite, **4 bits par pixel** (2 pixels par octet). Le pixel **pair (le plus à
gauche)** occupe le quartet de **poids fort** (bits 7-4), le suivant le poids
faible (bits 3-0). Chaque ligne fait donc **300 octets** (600 px ÷ 2).

```
octet :  [ px0 ][ px1 ]   ->  px0 dans 7..4, px1 dans 3..0
```

### Numérotation des couleurs

Les indices suivent la **numérotation de la dalle** (Spectra 6) — c'est aussi
l'ordre de la palette interne. Les indices 4 et 7 sont **réservés** par l'écran
et ne sont jamais utilisés.

| Couleur | Indice |
|---|---|
| noir | 0 |
| blanc | 1 |
| jaune | 2 |
| rouge | 3 |
| *(réservé)* | 4 |
| bleu | 5 |
| vert | 6 |
| *(réservé)* | 7 |

### Orientation

Le dessin est produit en **paysage (1600×1200)**, puis tourné vers le **portrait
natif (1200×1600)** selon `S6_ROTATION` (`90` ou `270`) avant l'encodage.

### Vérifier un fichier produit

```bash
python decode_s6.py /opt/calendar-output/calendar.s6 /tmp/apercu.png   # relit le .s6 -> PNG
```

## Version de l'image et rafraichissement à la demande

Pour économiser la dalle, l'image n'est régénérée que lorsque son **contenu** change (événements, jour affiché, mise en page) — l'heure de génération du pied de page n'est **pas** un motif de régénération. Un **numéro de version** est persisté dans `/opt/calendar-output/calendar.version.json` et exposé :

- `GET /version` → `{"version": N, "generated_at": "..."}`.
- `GET /calendar.s6` (et `/calendar.png`) renvoient l'en-tête **`X-Image-Version: N`** (+ `ETag: "N"`). Un `GET /calendar.s6` avec `If-None-Match: "N"` répond **`304`** (corps vide) si la version n'a pas changé.

Côté ESP32 : au réveil, appeler `/version` (ou lire l'en-tête `X-Image-Version` du `.s6`) ; ne reflasher la dalle que si la version diffère de la dernière connue. Le binaire peut en plus porter la **tension batterie** (section suivante) sans que cela change cette version.

Hors de la plage `START_HOUR`→`END_HOUR` (heure locale), le service **n'appelle pas CalDAV et ne génère rien** (le NAS se repose la nuit). La première génération après `START_HOUR` produit une nouvelle version (le nom du jour de la 1ʳᵉ colonne a changé).

## Tension de la batterie (`X-Battery-Voltage`)

L'ESP32 mesure sa batterie mais **ne dessine pas** (pour l'économiser) : c'est le
serveur qui compose l'image. L'ESP32 transmet donc sa tension dans l'en-tête
`X-Battery-Voltage` (format `3.85` ; `3,85` et `3.85V` sont aussi acceptés) avec
son `GET /calendar.s6` :

```bash
curl -H 'X-Battery-Voltage: 3.85' http://<hôte>:8000/calendar.s6 -o calendar.s6
```

- La valeur est **incrustée en bas à droite** du pied de page (`3.85V`) : la date
  et l'heure de génération sont **décalées vers la gauche** pour lui laisser la
  place, et les entrées de légende qui ne tiennent plus sont retirées.
- L'ajout se fait **à la volée dans le binaire déjà généré** : l'image n'est
  **pas** régénérée (aucun appel CalDAV, aucun re-rendu) et seuls les ~33 Ko de
  la bande du pied de page sont relus puis réécrits. C'est `S6_ROTATION` qui
  désigne la moitié concernée du binaire (`90` → moitié gauche, `270` → droite).
- Le **fichier `calendar.s6` sur disque n'est jamais modifié** ; sa taille
  (960 017 o) est conservée, et **ni le numéro de version ni l'`ETag` ne
  changent**.
- La réponse renvoie la valeur normalisée dans `X-Battery-Voltage` (ex. `3.85V`)
  et `GET /status` expose `last_battery` (`label` + horodatage UTC).
- Valeur absente ou illisible (`abc`, hors de `0,5`–`12 V`) : l'image est servie
  **telle quelle**, avec un avertissement dans les journaux.
- Une réponse **`304`** n'ayant pas de corps, il n'y a rien à incruster :
  l'ESP32 doit faire un `GET` complet (sans `If-None-Match`) pour récupérer une
  image portant la tension à jour.

## Notes

- Le `.env` est lu par Docker Compose : les variables utilisées sont listées dans `docker/docker-compose.yaml`, à compléter si vous en ajoutez.
- **Toutes les valeurs par défaut sont aussi dans le code Python** (`config.py`, `dither.py`) : le service démarre avec ces défauts même sans `docker-compose` ni `.env`. Seuls les identifiants CalDAV (`CALDAV_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD`) sont obligatoires ; les défauts du compose ne font que les refléter. Une variable **absente ou vide** retombe sur son défaut, et une valeur invalide est ignorée avec un avertissement.
- **Après avoir modifié le `.env`, il faut *recréer* le conteneur** (`docker compose up -d`), pas seulement le redémarrer (`docker compose restart` conserve l'environnement d'origine). Pour vérifier l'intervalle réellement utilisé : `curl http://<hôte>:8000/status` (champ `refresh_interval_minutes`).
- `DITHER_NOISE_SIZE` ne concerne que les **couleurs logiques** (tramage), pas les motifs.
- `S6_ROTATION` doit correspondre au sens de montage de la dalle ; `decode_s6.py` permet de vérifier un `.s6` produit (`python decode_s6.py /opt/calendar-output/calendar.s6 /tmp/apercu.png`).

