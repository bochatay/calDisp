"""Connexion CalDAV (Radicale) et recuperation des evenements a afficher."""

import logging
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import caldav

from config import DEFAULT_COLOR, CalendarConfig, Config

logger = logging.getLogger(__name__)


def _norm(value: str) -> str:
    """Normalise un nom de calendrier pour comparaison sans ambiguite.

    NFC (recompose les accents), suppression des espaces de bord et minuscules,
    afin que "Général", "general" ou "Ge\u0301ne\u0301ral" (NFD) soient equivalents.
    """
    return unicodedata.normalize("NFC", value or "").strip().casefold()


def _window(tz: ZoneInfo, days_ahead: int):
    """Fenetre [aujourd'hui 00:00 ; +days_ahead jours) dans le fuseau donne."""
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days_ahead)
    return start, end


def _to_local(value, tz: ZoneInfo) -> datetime:
    """Convertit une datetime/date d'evenement en datetime dans le fuseau local."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)
    return datetime(value.year, value.month, value.day, tzinfo=tz)


def _property_text(property_) -> str:
    """Valeur texte d'une propriete vobject (``location``, ``description``...).

    Renvoie une chaine vide quand la propriete est absente ou vide, ce qui
    simplifie le rendu : un evenement sans lieu ni description est traite comme
    les autres.
    """
    value = getattr(property_, "value", None)
    if value is None:
        return ""
    return str(value).strip()


def _display_name(calendar) -> str:
    """Nom d'affichage (propriete DAV ``displayname``) d'un calendrier."""
    try:
        return (calendar.get_display_name() or "").strip()
    except Exception:  # pragma: no cover - depend du serveur
        return ""


def _calendar_id(calendar) -> str:
    """Identifiant interne (segment d'URL) du calendrier."""
    try:
        return (getattr(calendar, "name", "") or "").strip()
    except Exception:  # pragma: no cover
        return ""


def _describe(calendar) -> dict:
    """Identifiants exploitables pour le debogage d'un calendrier distant."""
    return {
        "display_name": _display_name(calendar),
        "id": _calendar_id(calendar),
        "url": str(getattr(calendar, "url", "")),
    }


def fetch(config: Config):
    """Recupere les evenements et un rapport de debogage par calendrier.

    Retourne ``(events, report)``. Le rapport contient la liste des calendriers
    presents cote serveur (nom d'affichage + identifiant) ainsi que, pour chaque
    calendrier demande, s'il a ete trouve et combien d'objets il contient.
    """
    client = caldav.DAVClient(
        url=config.caldav_url,
        username=config.caldav_username,
        password=config.caldav_password,
    )

    principal = client.principal()
    tz = ZoneInfo(config.display_timezone)
    start, end = _window(tz, config.days_ahead)

    remote = list(principal.calendars())

    report = {
        "timezone": config.display_timezone,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "available_calendars": [_describe(c) for c in remote],
        "requested_calendars": [],
        "total_events": 0,
    }

    # Index des calendriers distants par nom d'affichage ET identifiant interne.
    by_key = {}
    for calendar in remote:
        for key in (_norm(_display_name(calendar)), _norm(_calendar_id(calendar))):
            if key and key not in by_key:
                by_key[key] = calendar

    # Selection : les calendriers demandes, ou tous si aucun n'est configure.
    if config.calendars:
        wanted = list(config.calendars)
    else:
        wanted = [
            CalendarConfig(name=_display_name(c) or _calendar_id(c) or "Calendrier",
                           color=DEFAULT_COLOR)
            for c in remote
        ]

    events = []

    for want in wanted:
        calendar = by_key.get(_norm(want.name))

        if calendar is None:
            logger.warning("Calendrier introuvable (ignore) : %s", want.name)
            report["requested_calendars"].append({
                "requested": want.name,
                "color": want.color,
                "matched": False,
                "error": None,
                "event_count": 0,
            })
            continue

        entry = {
            "requested": want.name,
            "color": want.color,
            "matched": True,
            "display_name": _display_name(calendar),
            "id": _calendar_id(calendar),
            "error": None,
            "event_count": 0,
        }

        try:
            found = calendar.search(start=start, end=end, event=True, expand=True)
        except Exception as exc:  # pragma: no cover - depend du serveur
            logger.exception("Echec de lecture du calendrier '%s'", want.name)
            entry["error"] = str(exc)
            report["requested_calendars"].append(entry)
            continue

        for event in found:
            data = event.vobject_instance.vevent
            dtstart = data.dtstart.value
            dtend = data.dtend.value if getattr(data, "dtend", None) is not None else None

            if dtend is None and getattr(data, "duration", None) is not None:
                # Certains agendas ne donnent que la duree : on en deduit l'heure de fin.
                try:
                    dtend = dtstart + data.duration.value
                except TypeError:  # pragma: no cover - duree illisible
                    dtend = None

            events.append({
                "summary": str(data.summary.value),
                "location": _property_text(getattr(data, "location", None)),
                "description": _property_text(getattr(data, "description", None)),
                "start": dtstart,
                "end": dtend,
                "all_day": not isinstance(dtstart, datetime),
                "calendar": entry["display_name"] or want.name,
                "color": want.color,
            })
            entry["event_count"] += 1

        report["requested_calendars"].append(entry)

    events.sort(key=lambda e: (not e["all_day"], _to_local(e["start"], tz)))
    report["total_events"] = len(events)
    return events, report
