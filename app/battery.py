"""Incrustation "live" de la tension batterie dans le pied de page du ``.s6``.

L'ESP32 transmet sa tension dans l'en-tete HTTP ``X-Battery-Voltage`` (format
``"3.85"``) au moment ou il demande l'image : c'est lui qui mesure, mais c'est le
serveur qui dessine. La valeur est donc ajoutee au binaire **deja genere**, a la
volee, dans le pied de page.

Rien d'autre n'est recalcule : ni les evenements, ni le dessin du calendrier, ni
les ~960 000 pixels de l'image. Seule la bande du pied de page est relue
(``s6.read_box``), retouchee, puis reinscrite (``s6.write_box``) : le fichier
``.s6`` sur disque, sa taille, la version de l'image et son ``ETag`` restent
inchanges.

Le pied de page est en bas de l'image **paysage** (1600x1200) ; apres rotation
vers le portrait natif de la dalle, il se retrouve dans la premiere moitie du
binaire (``S6_ROTATION=90``) ou dans la seconde (``270``). C'est ``s6`` qui
connait ce passage, ``battery`` ne travaille qu'en coordonnees paysage.

La date et l'heure sont decalees vers la gauche pour laisser la place a la
tension, affichee en bas a droite ; les entrees de legende qui ne tiennent plus
sont retirees.
"""

import logging
import re

from PIL import ImageDraw

from renderer import (
    FONT_FOOTER,
    FOOTER_PADDING,
    WIDTH,
    footer_box,
    footer_text_y,
)
from s6 import BLACK_INDEX, WHITE_INDEX, read_box, write_box

logger = logging.getLogger(__name__)

# Tension acceptee : "3.85", "3,85", "3.85V" (espaces et casse toleres).
_VOLTAGE = re.compile(r"^\s*(\d{1,3}(?:[.,]\d{1,6})?)\s*[vV]?\s*$")

# Plage de plausibilite (volts) : hors plage, la valeur est ignoree et l'image
# est servie telle quelle.
VOLTAGE_MIN = 0.5
VOLTAGE_MAX = 12.0

# Espace laisse entre la date/heure decalee et la tension (en pixels).
BATTERY_GAP = 16

# Ecart (en pixels) separant deux blocs de texte du pied de page : en dessous,
# les colonnes encrees appartiennent au meme bloc. Les entrees de legende sont
# espacees de ``renderer.FOOTER_GAP`` (24 px) et le nom suit sa pastille de 6 px :
# ce seuil isole donc chaque entree, puis la date/heure.
CLUSTER_GAP = 16


def parse_voltage(raw) -> str:
    """Libelle a afficher, ou ``None`` si la valeur est absente ou invalide.

    ``"3.85"``, ``"3,85"`` et ``"3.85V"`` donnent ``"3.85V"`` ; la valeur est
    ramenee a deux decimales au plus, sans zero inutile (``"4"`` -> ``"4V"``).
    """
    if not raw:
        return None

    match = _VOLTAGE.match(raw)
    if match is None:
        logger.warning("X-Battery-Voltage=%r illisible : tension ignoree", raw)
        return None

    value = float(match.group(1).replace(",", "."))
    if not VOLTAGE_MIN <= value <= VOLTAGE_MAX:
        logger.warning(
            "X-Battery-Voltage=%r hors plage (%.1f a %.1f V) : tension ignoree",
            raw, VOLTAGE_MIN, VOLTAGE_MAX,
        )
        return None

    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}V"


def _ink_columns(image) -> list:
    """Colonnes de la bande portant au moins un pixel non blanc (le texte)."""
    width, height = image.size
    values = image.tobytes()
    ink = bytearray(width)

    for line in range(height):
        row = values[line * width:(line + 1) * width]
        for x, value in enumerate(row):
            if value != WHITE_INDEX:
                ink[x] = 1

    return [x for x in range(width) if ink[x]]


def _clusters(columns) -> list:
    """Regroupe des colonnes encrees en blocs separes d'au moins ``CLUSTER_GAP``."""
    clusters = []
    for x in columns:
        if clusters and x - clusters[-1][1] <= CLUSTER_GAP:
            clusters[-1][1] = x
        else:
            clusters.append([x, x])
    return [(start, end) for start, end in clusters]


def stamp(payload: bytes, rotation: int, label: str):
    """Incruste ``label`` en bas a droite du pied de page de ``payload``.

    ``payload`` est le contenu complet d'un ``.s6`` (en-tete + pixels). Retourne
    un nouveau ``bytes`` de meme taille, ou ``None`` si le pied de page n'a pas pu
    etre exploite (aucun texte detecte, pas assez de place) : l'appelant sert
    alors l'image inchangee.
    """
    box = footer_box()
    buf = bytearray(payload)
    band = read_box(buf, rotation, box)

    clusters = _clusters(_ink_columns(band))
    if not clusters:
        logger.warning("Pied de page vide : tension %s non incrustee", label)
        return None

    draw = ImageDraw.Draw(band)
    text_y = footer_text_y(draw) - box[1]

    # Le bloc date/heure est le dernier ; la tension se pose a sa droite, donc on
    # le decale de la largeur du libelle (plus un espace de respiration).
    time_left, time_right = clusters[-1]
    label_width = draw.textlength(label, font=FONT_FOOTER)
    delta = round(label_width + BATTERY_GAP)

    new_left = time_left - delta
    if new_left <= 0:
        logger.warning(
            "Pied de page trop rempli : tension %s non incrustee (decalage %d px)",
            label, delta,
        )
        return None

    # Une entree de legende qui empieterait sur la place liberee est retiree en
    # entier (les blocs sont separes par CLUSTER_GAP, donc rien n'est tronque).
    keep_x = new_left - CLUSTER_GAP
    removed = [start for start, end in clusters[:-1] if end > keep_x]
    if removed:
        logger.info(
            "Pied de page : %d entree(s) de legende retiree(s) pour placer %s",
            len(removed), label,
        )

    block = band.crop((time_left, 0, time_right + 1, band.height))
    clear_x = min(removed) if removed else keep_x
    draw.rectangle((clear_x, 0, band.width - 1, band.height - 1), fill=WHITE_INDEX)
    band.paste(block, (new_left, 0))

    draw.text(
        (WIDTH - FOOTER_PADDING - label_width, text_y),
        label,
        font=FONT_FOOTER,
        fill=BLACK_INDEX,
    )

    write_box(buf, rotation, box, band)
    return bytes(buf)
