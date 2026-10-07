"""Chargement et validation de la configuration depuis l'environnement."""

import logging
import os
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)

# Couleur par defaut : nom de la palette logique (voir ``s6.LOGICAL_PALETTE``).
DEFAULT_COLOR = "BLACK"

# Fond des colonnes : une variable par jour de la semaine (MONDAY..SUNDAY). Une
# valeur absente ou vide retombe sur ``DEFAULT_COLUMN_COLOR`` (blanc). L'ordre
# suit ``datetime.weekday`` (lundi = 0).
DEFAULT_COLUMN_COLOR = "WHITE"
DAY_NAMES = (
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY",
)
_DEFAULT_COLUMN_COLORS = (DEFAULT_COLUMN_COLOR,) * len(DAY_NAMES)

# Largeur de la 1re colonne (celle du jour) par rapport aux autres : 1.5 = +50 %.
DEFAULT_FIRST_COLUMN_SCALE = 1.5

# Plage horaire (heure locale) pendant laquelle le rafraichissement planifie
# s'execute : de START_HOUR (inclus) a END_HOUR (exclu). Hors plage, aucun appel
# CalDAV ni generation : l'ecran et le NAS se reposent.
DEFAULT_START_HOUR = 6
DEFAULT_END_HOUR = 23

# Emplacement par defaut des fichiers produits (volume monte dans le conteneur).
DEFAULT_OUTPUT_DIR = "/opt/calendar-output"
DEFAULT_IMAGE_PATH = os.path.join(DEFAULT_OUTPUT_DIR, "calendar.png")
DEFAULT_S6_PATH = os.path.join(DEFAULT_OUTPUT_DIR, "calendar.s6")


@dataclass
class CalendarConfig:
    """Un calendrier a afficher : nom d'affichage + couleur.

    La couleur est un nom de la palette logique (voir ``s6.LOGICAL_PALETTE``) :
    soit une couleur native de l'ecran (BLACK, WHITE, RED, YELLOW, GREEN, BLUE,
    rendues en aplat), soit un melange de deux natives (``orange``, ``cyan``,
    ``gray``, ``pink``... rendus par tramage blue noise). Les codes hexadecimaux
    ne sont plus acceptes : une valeur inconnue retombe sur du noir, avec un
    avertissement dans les journaux.

    Un *motif* est aussi accepte : ``ENCRE_motifs[_parametre]_espacement``, par
    exemple ``YELLOW_45_3`` (lignes a 45 degres), ``RED_p_10`` (pointille),
    ``GREEN_t_3_10`` (tirets), ``BLUE_b_4_16`` (bandes) ou ``BLACK_d_8``
    (damier). Un suffixe ``h``/``v`` limite pointilles, tirets et bandes a un
    seul sens (ex. ``RED_pv_10``). Voir ``s6`` pour la syntaxe complete.
    """

    name: str
    color: str = DEFAULT_COLOR


@dataclass
class Config:
    """Configuration complete du service."""

    caldav_url: str
    caldav_username: str
    caldav_password: str
    calendars: List[CalendarConfig] = field(default_factory=list)
    refresh_interval_minutes: int = 60
    display_timezone: str = "Europe/Paris"
    days_ahead: int = 7
    image_path: str = DEFAULT_IMAGE_PATH
    s6_path: str = DEFAULT_S6_PATH
    s6_rotation: int = 90
    column_colors: List[str] = field(
        default_factory=lambda: list(_DEFAULT_COLUMN_COLORS)
    )
    first_column_scale: float = DEFAULT_FIRST_COLUMN_SCALE
    start_hour: int = DEFAULT_START_HOUR
    end_hour: int = DEFAULT_END_HOUR


def _parse_calendars(raw: str) -> List[CalendarConfig]:
    """Parse ``CALDAV_CALENDARS`` = "Nom:#couleur,Autre:#couleur".

    La couleur est optionnelle (defaut noir). Le nom est separe de la
    couleur par le premier ``:``.
    """
    calendars: List[CalendarConfig] = []

    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue

        name, _, color = entry.partition(":")
        name = name.strip()
        color = color.strip() or DEFAULT_COLOR

        if name:
            calendars.append(CalendarConfig(name=name, color=color))

    return calendars


def _parse_column_colors() -> List[str]:
    """Couleur de fond de chaque colonne, lue dans MONDAY..SUNDAY.

    Une variable absente ou vide retombe sur ``DEFAULT_COLUMN_COLOR`` (blanc).
    L'ordre suit ``DAY_NAMES`` (lundi en premier, comme ``datetime.weekday``).
    """
    colors: List[str] = []

    for name in DAY_NAMES:
        value = os.environ.get(name, "").strip()
        colors.append(value or DEFAULT_COLUMN_COLOR)

    return colors


def _default_s6_path(image_path: str) -> str:
    """Chemin du binaire : meme racine que le PNG, extension ``.s6``."""
    return os.path.splitext(image_path)[0] + ".s6"


def _parse_rotation(raw: str) -> int:
    """Sens de rotation paysage -> portrait : 90 (horaire) ou 270 degres.

    Une valeur illisible est ignoree avec un avertissement : mieux vaut un
    affichage retourne qu'un service qui refuse de demarrer.
    """
    try:
        rotation = int(raw)
    except (TypeError, ValueError):
        rotation = -1

    if rotation not in (90, 270):
        logger.warning(
            "S6_ROTATION=%r invalide (90 ou 270 attendus) : 90 degres utilise", raw
        )
        return 90

    return rotation


def _parse_first_column_scale(raw: str) -> float:
    """Ratio de largeur de la 1re colonne (aujourd'hui), lue dans FIRST_COLUMN_SCALE.

    Une valeur illisible ou hors bornes (1.0 a 10.0) est ignoree avec un
    avertissement : le defaut ``DEFAULT_FIRST_COLUMN_SCALE`` est alors utilise.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = -1.0

    if not 1.0 <= value <= 10.0:
        logger.warning(
            "FIRST_COLUMN_SCALE=%r invalide (1.0 a 10.0 attendu) : %s utilise",
            raw,
            DEFAULT_FIRST_COLUMN_SCALE,
        )
        return DEFAULT_FIRST_COLUMN_SCALE

    return value


def _parse_hour(raw: str, default: int) -> int:
    """Heure entiere 0..23 ; valeur illisible remplacee par ``default``."""
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        hour = -1

    if not 0 <= hour <= 23:
        logger.warning("Heure %r invalide (0 a 23 attendu) : %d utilise", raw, default)
        return default

    return hour


def _warn_relative_paths(*paths: str) -> None:
    """Avertit si un chemin de sortie est relatif (il depend du repertoire courant)."""
    for path in paths:
        if not os.path.isabs(path):
            logger.warning(
                "Chemin de sortie relatif %r : resolu depuis %s, pas depuis le "
                "volume de sortie. Utilisez un chemin absolu (ex. sous %s).",
                path, os.getcwd(), DEFAULT_OUTPUT_DIR,
            )


def _env(name: str, default: str = "") -> str:
    """Valeur d'environnement, ou ``default`` si la variable est absente OU vide.

    Reproduit ``${VAR:-defaut}`` de Docker Compose : le service demarre avec ses
    valeurs par defaut meme sans ``.env`` complet, que le compose soit utilise ou non.
    """
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _parse_int(name: str, default: int, minimum: int = 1) -> int:
    """Entier lu dans ``name`` (>= ``minimum``) ; sinon ``default`` + avertissement."""
    raw = _env(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = -1
    if value < minimum:
        logger.warning(
            "%s=%r invalide (>= %d attendu) : %d utilise", name, raw, minimum, default
        )
        return default
    return value


def load_config() -> Config:
    """Construit la configuration a partir des variables d'environnement.

    Seuls les identifiants CalDAV sont obligatoires ; **toutes** les autres ont
    une valeur par defaut definie ici, donc le service tourne meme sans le
    ``docker-compose``. Une variable absente ou vide retombe sur son defaut.
    """
    image_path = _env("IMAGE_PATH", DEFAULT_IMAGE_PATH)
    s6_path = _env("S6_PATH") or _default_s6_path(image_path)
    _warn_relative_paths(image_path, s6_path)

    return Config(
        caldav_url=os.environ["CALDAV_URL"],
        caldav_username=os.environ["CALDAV_USERNAME"],
        caldav_password=os.environ["CALDAV_PASSWORD"],
        calendars=_parse_calendars(_env("CALDAV_CALENDARS")),
        refresh_interval_minutes=_parse_int("REFRESH_INTERVAL_MINUTES", 60),
        display_timezone=_env("DISPLAY_TIMEZONE", "Europe/Paris"),
        days_ahead=_parse_int("DAYS_AHEAD", 7),
        image_path=image_path,
        s6_path=s6_path,
        s6_rotation=_parse_rotation(_env("S6_ROTATION", "90")),
        column_colors=_parse_column_colors(),
        first_column_scale=_parse_first_column_scale(
            _env("FIRST_COLUMN_SCALE", str(DEFAULT_FIRST_COLUMN_SCALE))
        ),
        start_hour=_parse_hour(
            _env("START_HOUR", str(DEFAULT_START_HOUR)), DEFAULT_START_HOUR
        ),
        end_hour=_parse_hour(
            _env("END_HOUR", str(DEFAULT_END_HOUR)), DEFAULT_END_HOUR
        ),
    )
