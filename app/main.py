"""Service FastAPI : genere periodiquement l'image du calendrier e-paper."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from caldav_client import fetch
from config import load_config
from renderer import generate_image
from s6 import color_spec
from state import (
    DEFAULT_STATE,
    content_signature,
    load_state,
    save_state,
    state_path,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ``misfire_grace_time=None`` : ne jamais sauter une execution en retard (par
# exemple un conteneur momentanement mis en pause) ; ``max_instances=1`` : une
# seule execution a la fois pour ne pas empiler les rafraichissements.
scheduler = BackgroundScheduler(
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": None}
)

# Etat du dernier rafraichissement planifie (expose par ``GET /status``).
last_run = {"at": None, "ok": None, "events": None, "version": None,
            "changed": None, "skipped": None, "error": None}

# Numero de version courant de l'image et empreinte associee (persiste au sol).
version_state = dict(DEFAULT_STATE)
version_file = None


def _file_size(path):
    """Taille d'un fichier, ou ``None`` s'il n'existe pas."""
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def _reference_day(config):
    """Jour affiche en premiere colonne (aujourd'hui, dans le fuseau d'affichage)."""
    return datetime.now(ZoneInfo(config.display_timezone)).date()


def _within_hours(config, hour: int) -> bool:
    """Vrai si ``hour`` (heure locale) est dans la plage de rafraichissement.

    Plage ``[start, end)`` ; si ``start > end`` la plage passe minuit (ex. 22 -> 6) ;
    si ``start == end`` il n'y a pas de restriction (24 h).
    """
    start, end = config.start_hour, config.end_hour
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def refresh(force: bool = False) -> dict:
    """Recupere les evenements et regenere l'image *si le contenu a change*.

    Le numero de version n'augmente que lorsque l'empreinte du contenu change
    (evenements differents, jour different, mise en page differente). L'heure de
    generation n'entre pas dans l'empreinte : regenerer a l'identique ne change
    donc pas la version. ``force`` reecrit les fichiers meme sans changement
    (utile au demarrage), sans incrementer la version.
    """
    config = load_config()
    events, report = fetch(config)

    signature = content_signature(events, config, _reference_day(config))
    changed = signature != version_state["signature"]

    if changed or force:
        png_path, s6_path = generate_image(events, config)

        if changed:
            version_state["version"] += 1
            version_state["signature"] = signature
        version_state["generated_at"] = datetime.now(timezone.utc).isoformat()
        if version_file:
            save_state(version_file, version_state)

        report["output"] = {
            "png": png_path,
            "s6": s6_path,
            "s6_size": _file_size(s6_path),
        }
        logger.info(
            "Image %s -> version %d",
            "regeneree" if changed else "reecrite (contenu inchange)",
            version_state["version"],
        )
    else:
        report["output"] = {
            "png": config.image_path,
            "s6": config.s6_path,
            "s6_size": _file_size(config.s6_path),
        }
        logger.info(
            "Aucun changement : image conservee (version %d)", version_state["version"]
        )

    report["changed"] = changed
    report["version"] = version_state["version"]
    report["generated_at"] = version_state["generated_at"]

    for entry in report["requested_calendars"]:
        # Couleur resolue : rend visible dans POST /generate toute faute de frappe
        # ou tout ancien code hexadecimal restant dans CALDAV_CALENDARS.
        specification = color_spec(entry["color"])
        entry["color_spec"] = specification.label
        entry["color_valid"] = specification.valid

        if not entry["matched"]:
            logger.warning(
                "Calendrier demande '%s' : introuvable cote serveur",
                entry["requested"],
            )
        elif entry["error"]:
            logger.error(
                "Calendrier '%s' : erreur de lecture (%s)",
                entry.get("display_name") or entry["requested"],
                entry["error"],
            )
        else:
            logger.info(
                "Calendrier '%s' (%s -> %s) : %d evenement(s)",
                entry.get("display_name") or entry["requested"],
                entry["color"],
                specification.label,
                entry["event_count"],
            )

    return report


def scheduled_refresh() -> None:
    """Rafraichissement planifie : ignore hors plage horaire, sinon ``refresh``."""
    config = load_config()
    now = datetime.now(ZoneInfo(config.display_timezone))
    if not _within_hours(config, now.hour):
        last_run.update(at=now.isoformat(), ok=True, events=None, version=None,
                        changed=None, skipped="hors_plage", error=None)
        logger.info(
            "Hors plage horaire (%02d h-%02d h, heure locale %02d h) : "
            "rafraichissement ignore",
            config.start_hour, config.end_hour, now.hour,
        )
        return

    logger.info("Rafraichissement planifie : demarrage")
    try:
        report = refresh(force=False)
    except Exception as exc:
        last_run.update(at=datetime.now(timezone.utc).isoformat(), ok=False,
                        events=None, version=None, changed=None, skipped=None,
                        error=str(exc))
        logger.exception("Echec du rafraichissement planifie")
        return

    last_run.update(
        at=datetime.now(timezone.utc).isoformat(),
        ok=True,
        events=report["total_events"],
        version=report["version"],
        changed=report["changed"],
        skipped=None,
        error=None,
    )
    logger.info(
        "Rafraichissement planifie : %d evenement(s), version %d%s",
        report["total_events"], report["version"],
        "" if report["changed"] else " (inchangee)",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global version_file

    config = load_config()
    version_file = state_path(config.s6_path)
    logger.info("Sortie : image=%s, binaire=%s", config.image_path, config.s6_path)
    version_state.update(load_state(version_file))
    logger.info("Etat initial : version %d", version_state["version"])

    try:
        report = refresh(force=True)
        logger.info(
            "Generation initiale : version %d, %d evenement(s)",
            report["version"], report["total_events"],
        )
    except Exception:
        logger.exception("Echec de la generation initiale")

    scheduler.add_job(
        scheduled_refresh,
        "interval",
        minutes=config.refresh_interval_minutes,
        id="refresh",
        replace_existing=True,
    )
    scheduler.start()
    job = scheduler.get_job("refresh")
    logger.info(
        "Planificateur demarre : toutes les %d min, plage %02d h-%02d h "
        "(prochaine execution : %s)",
        config.refresh_interval_minutes, config.start_hour, config.end_hour,
        job.next_run_time if job else "?",
    )

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


def _image_headers() -> dict:
    """En-tetes communs aux images : version courante, ETag, cache."""
    version = version_state["version"]
    return {
        "X-Image-Version": str(version),
        "ETag": '"%d"' % version,
        "Cache-Control": "no-cache",
    }


def _normalize_etag(value):
    """Normalise un ETag pour comparaison (retire le prefixe ``W/`` et les guillemets)."""
    if value is None:
        return ""
    token = value.strip()
    if token[:2].upper() == "W/":
        token = token[2:].strip()
    return token.strip('"').strip("'")


def _matches_etag(header, etag) -> bool:
    """Vrai si ``If-None-Match`` designe l'ETag courant.

    Tolere les formes ``5``, ``"5"``, ``W/"5"`` et le joker ``*`` (ainsi que les
    listes separees par des virgules).
    """
    target = _normalize_etag(etag)
    for candidate in header.split(","):
        token = _normalize_etag(candidate)
        if token == "*" or (target and token == target):
            return True
    return False


def _not_modified(request: Request, headers: dict):
    """304 si le client possede deja cette version (en-tete ``If-None-Match``)."""
    header = request.headers.get("if-none-match")
    if header is not None and _matches_etag(header, headers["ETag"]):
        return Response(status_code=304, headers=headers)
    return None


@app.get("/")
def root():
    return {"status": "calendar server running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    """Numero de version de l'image courante (change quand le contenu change)."""
    return {
        "version": version_state["version"],
        "generated_at": version_state["generated_at"],
    }


@app.get("/status")
def status():
    """Etat du planificateur et de l'image courante."""
    config = load_config()
    job = scheduler.get_job("refresh")
    hour = datetime.now(ZoneInfo(config.display_timezone)).hour
    return {
        "version": version_state["version"],
        "generated_at": version_state["generated_at"],
        "refresh_interval_minutes": config.refresh_interval_minutes,
        "start_hour": config.start_hour,
        "end_hour": config.end_hour,
        "within_hours": _within_hours(config, hour),
        "days_ahead": config.days_ahead,
        "display_timezone": config.display_timezone,
        "scheduler_running": scheduler.running,
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "last_run": dict(last_run),
    }


@app.get("/calendar.png")
def calendar_image(request: Request):
    config = load_config()
    headers = _image_headers()
    not_modified = _not_modified(request, headers)
    if not_modified is not None:
        return not_modified
    return FileResponse(config.image_path, media_type="image/png", headers=headers)


@app.get("/calendar.s6")
def calendar_binary(request: Request):
    """Binaire Spectra 6 (4 bits/pixel) + version courante dans l'en-tete.

    L'ESP32 peut envoyer ``If-None-Match: "<version>"`` : s'il possede deja cette
    version, le serveur repond ``304`` sans renvoyer l'image.
    """
    config = load_config()
    headers = _image_headers()
    not_modified = _not_modified(request, headers)
    if not_modified is not None:
        return not_modified
    return FileResponse(
        config.s6_path, media_type="application/octet-stream", headers=headers
    )


@app.post("/generate")
def generate(force: bool = True):
    """Regenere l'image ; ``?force=false`` pour ne le faire que si le contenu change."""
    try:
        report = refresh(force=force)
    except Exception as exc:
        logger.exception("Echec de la generation")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(exc)},
        )

    return {"status": "generated", **report}
