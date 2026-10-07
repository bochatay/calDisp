"""Empreinte du contenu affiche et numero de version persistant.

Le but : ne regenerer l'image (et donc ne faire rafraichir l'ecran e-ink) que
lorsque le *contenu* change reellement. L'empreinte porte sur les evenements, la
date de reference (le jour affiche) et la mise en page -- **jamais** sur l'heure
de generation, qui change pourtant a chaque fois.
"""

import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

# Etat par defaut : aucune version encore produite.
DEFAULT_STATE = {"version": 0, "signature": None, "generated_at": None}


def state_path(s6_path: str) -> str:
    """Chemin du fichier d'etat, deduit du chemin du binaire ``.s6``.

    ``output/calendar.s6`` -> ``output/calendar.version.json`` : le fichier vit a
    cote de l'image, dans le volume monte, et survit donc aux redemarrages.
    """
    return os.path.splitext(s6_path)[0] + ".version.json"


def _stamp(value) -> str:
    """Representation stable d'une date, d'une heure ou d'une chaine."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def content_signature(events, config, reference) -> str:
    """Empreinte (SHA-256) du contenu affiche, hors horodatage.

    ``reference`` est le jour affiche en premiere colonne (aujourd'hui) : il
    entre dans l'empreinte pour qu'au passage de minuit -- quand le nom du jour
    de la 1re colonne change -- une nouvelle version soit produite.
    """
    payload = {
        "reference": _stamp(reference),
        "days_ahead": config.days_ahead,
        "timezone": config.display_timezone,
        "column_colors": list(config.column_colors),
        "first_column_scale": config.first_column_scale,
        "calendars": [
            [calendar.name, calendar.color] for calendar in config.calendars
        ],
        "events": [
            [
                _stamp(event["start"]),
                _stamp(event["end"]),
                event["summary"],
                event["location"],
                event["description"],
                bool(event["all_day"]),
                event["calendar"],
                event["color"],
            ]
            for event in events
        ],
    }

    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_state(path: str) -> dict:
    """Charge l'etat persistant ; valeurs par defaut si le fichier est absent."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return dict(DEFAULT_STATE)

    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0

    return {
        "version": version,
        "signature": data.get("signature"),
        "generated_at": data.get("generated_at"),
    }


def save_state(path: str, state: dict) -> None:
    """Ecrit l'etat persistant (cree le dossier au besoin)."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
