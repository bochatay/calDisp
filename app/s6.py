"""Palette Spectra 6 et format binaire ``.s6`` (4 bits par pixel, ESP32).

L'ecran Spectra 6 n'affiche que 6 couleurs indexees. Les indices internes
suivent la numerotation de la dalle (Spectra 6) ; les indices 4 et 7 sont
reserves par l'ecran et ne sont jamais dessines :

    idx  nom       RGB d'apercu
    0    BLACK     #191E21  (25, 30, 33)
    1    WHITE     #E8E8E8  (232, 232, 232)
    2    YELLOW    #EFDE44  (239, 222, 68)
    3    RED       #B21318  (178, 19, 24)
    4    (reserve)
    5    BLUE      #2157BA  (33, 87, 186)
    6    GREEN     #125F20  (18, 95, 32)
    7    (reserve)

Ces valeurs RGB servent a l'apercu sur ecran normal : ce sont les couleurs que
le spectre de l'ecran restitue pour chaque index.

Au-dela de ces 6 couleurs natives, ``LOGICAL_PALETTE`` definit des couleurs
*logiques* (``orange``, ``cyan``, ``gray``, ``pink``...) comme des melanges de
couleurs natives, exprimes en proportion de pixels. Elles sont rendues sur
l'ecran par tramage (voir le module ``dither``). Le fichier ``.env`` ne
reference que des noms de cette palette logique : les codes hexadecimaux ne sont
plus acceptes.

Au-dela des couleurs, on peut demander un *motif* :
``ENCRE_motifs[_parametre]_espacement``, ou l'encre est l'une des 6 couleurs
primaires (en majuscules dans le ``.env``). ``motifs`` est soit un ou deux
angles (lignes continues), soit une lettre de motif. Exemples :

    YELLOW_45_3      lignes jaunes a 45 degres, une ligne tous les 3 pixels
    YELLOW_135_4     idem a 135 degres (diagonale en sens inverse)
    RED_0_90_4       grille rouge : lignes horizontales ET verticales tous les 4
    BLUE_45_135_5    croix bleue : les deux diagonales, tous les 5

    RED_p_10         pointille : un point tous les 10 pixels en V et H
    RED_p_3_12       pointille : points tous les 3 px, lignes tous les 12 px
    BLUE_p2_8        pointille a gros points : 2x2 px tous les 8 pixels
    GREEN_t_3_10     tirets : traits de 3 px tous les 10 pixels (V et H)
    BLUE_b_4_16      bandes : traits pleins de 4 px tous les 16 (V et H)
    BLACK_d_8        damier : cases de 8x8 px alternees

Un suffixe ``h`` ou ``v`` restreint un pointille, des tirets ou des bandes a un
seul sens (sans suffixe, les deux sens sont cumules) :

    RED_pv_10        pointille vertical : points tous les 10 px sur des
                     colonnes espacees de 10 px
    GREEN_th_3_10    tirets horizontaux : traits de 3 px toutes les 10 px
    BLUE_bv_4_16     bandes verticales : traits pleins de 4 px toutes les 16 px

Le deuxieme angle est optionnel et tout angle entier est accepte (0 =
horizontale, 90 = verticale). Le fond du motif est blanc.

Format du fichier ``.s6`` -- version 1, en-tete de 17 octets, little-endian :

    offset  taille  champ
    0       8       nom du format : ``SPECTRA6`` (ASCII, non termine)
    8       1       version du format (1)
    9       2       largeur de la dalle en pixels  (uint16, 1200)
    11      2       hauteur de la dalle en pixels  (uint16, 1600)
    13      1       nombre de bits par pixel (4)
    14      1       nombre de couleurs de la palette (6)
    15      2       offset des donnees pixels (17)

La dalle est native en portrait (1200x1600) et divisee en deux moities de
600x1600 (gauche puis droite). Les donnees suivent l'en-tete dans cet ordre :
moitie gauche complete, puis moitie droite. Dans chaque moitie, les lignes vont
de haut en bas et les pixels de gauche a droite, 4 bits par pixel, avec le pixel
pair (le plus a gauche) dans le quartet de poids fort (bits 7-4) et le suivant
dans le quartet de poids faible (bits 3-0). Chaque ligne fait 300 octets.

L'image source est dessinee en paysage (1600x1200) puis tournee a la
generation (voir ``S6_ROTATION``) : les deux representations decrivent la meme
dalle physique.

Pour la dalle 1200x1600 : 17 + 600 * 1600 = 960017 octets.
"""

import logging
import os
import struct
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

MAGIC = b"SPECTRA6"
VERSION = 1
BITS_PER_PIXEL = 4
HEADER_SIZE = 17

# Dalle native : portrait, divisee en deux moities envoyees l'une apres l'autre.
PANEL_WIDTH = 1200
PANEL_HEIGHT = 1600
PANEL_HALF_WIDTH = PANEL_WIDTH // 2

# Image source : paysage, dessinee par le renderer avant rotation.
LANDSCAPE_WIDTH = PANEL_HEIGHT
LANDSCAPE_HEIGHT = PANEL_WIDTH

# Sens de rotation paysage -> portrait (voir config.S6_ROTATION). Pillow nomme ses
# rotations par l'angle dans le sens anti-horaire : ROTATE_270 est donc bien une
# rotation de 90 degres dans le sens horaire.
ROTATION_TRANSPOSE = {
    90: Image.Transpose.ROTATE_270,
    270: Image.Transpose.ROTATE_90,
}
DEFAULT_ROTATION = 90

SPECTRA6 = {
    "black": (25, 30, 33),      # #191E21
    "white": (232, 232, 232),   # #E8E8E8
    "yellow": (239, 222, 68),   # #EFDE44
    "red": (178, 19, 24),       # #B21318
    "blue": (33, 87, 186),      # #2157BA
    "green": (18, 95, 32),      # #125F20
}

# Les indices internes suivent la numerotation de la dalle (Spectra 6) :
#
#     idx  nom       idx  nom
#     0    black      4    (reserve)
#     1    white      5    blue
#     2    yellow     6    green
#     3    red        7    (reserve)
#
# Un indice interne EST donc directement un indice de la dalle : plus aucun
# remappage n'est necessaire. Les emplacements 4 et 7, reserves par l'ecran, ne
# sont jamais dessines.
PANEL_NUMBERING = {
    "black": 0,
    "white": 1,
    "yellow": 2,
    "red": 3,
    "blue": 5,
    "green": 6,
}
PANEL_SLOTS = 8
VALID_INDICES = tuple(sorted(PANEL_NUMBERING.values()))
RESERVED_PANEL_INDICES = tuple(
    slot for slot in range(PANEL_SLOTS) if slot not in VALID_INDICES
)

# Les 6 couleurs utilisables, dans l'ordre des indices (iteration, labels).
PALETTE_NAMES = tuple(PANEL_NUMBERING)
# Nom de chaque emplacement (``None`` pour les indices reserves).
NAMES_BY_INDEX = [
    next((name for name, slot in PANEL_NUMBERING.items() if slot == index), None)
    for index in range(PANEL_SLOTS)
]

INDEX = dict(PANEL_NUMBERING)
BLACK_INDEX = INDEX["black"]
WHITE_INDEX = INDEX["white"]
YELLOW_INDEX = INDEX["yellow"]

# Couleur RGB de chaque emplacement, indexee par indice (reserves -> noir).
PALETTE_RGB = [
    SPECTRA6[name] if name is not None else (0, 0, 0) for name in NAMES_BY_INDEX
]

# Table ``bytes.translate`` (256 entrees) : les indices internes sont deja ceux
# de la dalle ; seules les entrees de remplissage (indices >= 8) retombent sur
# le noir (voir aussi ``PADDING_REMAP`` plus bas).
INDEX_TO_PANEL = bytes(
    position if position < PANEL_SLOTS else BLACK_INDEX for position in range(256)
)

# Palette logique : chaque couleur est un melange de couleurs natives, exprime en
# proportion de pixels. Les 6 couleurs natives y figurent avec un unique
# composant a 1.0 : leur rendu reste uni (aucun tramage).
LOGICAL_PALETTE = {name: {name: 1.0} for name in PALETTE_NAMES}

LOGICAL_PALETTE.update({
    # -- Rouge / jaune --
    "orange": {"red": 0.50, "yellow": 0.50},
    "red_orange": {"red": 0.75, "yellow": 0.25},
    "yellow_orange": {"red": 0.25, "yellow": 0.75},

    # -- Rouge / bleu --
    "purple": {"red": 0.50, "blue": 0.50},
    "red_purple": {"red": 0.75, "blue": 0.25},
    "blue_purple": {"red": 0.25, "blue": 0.75},

    # -- Vert / jaune --
    "lime": {"green": 0.50, "yellow": 0.50},
    "green_yellow": {"green": 0.75, "yellow": 0.25},
    "yellow_green": {"green": 0.25, "yellow": 0.75},

    # -- Vert / bleu --
    "cyan": {"green": 0.50, "blue": 0.50},
    "green_cyan": {"green": 0.75, "blue": 0.25},
    "blue_cyan": {"green": 0.25, "blue": 0.75},

    # -- Rouge / vert --
    "brown": {"red": 0.50, "green": 0.50},
    "red_brown": {"red": 0.75, "green": 0.25},
    "green_brown": {"red": 0.25, "green": 0.75},

    # -- Noir / blanc --
    "gray": {"black": 0.50, "white": 0.50},
    "dark_gray": {"black": 0.75, "white": 0.25},
    "light_gray": {"black": 0.25, "white": 0.75},

    # -- Eclaircies avec du blanc --
    "pink": {"red": 0.75, "white": 0.25},
    "light_red": {"red": 0.50, "white": 0.50},
    "light_yellow": {"yellow": 0.75, "white": 0.25},
    "light_green": {"green": 0.75, "white": 0.25},
    "light_blue": {"blue": 0.75, "white": 0.25},

    # -- Assombries avec du noir --
    "dark_red": {"red": 0.75, "black": 0.25},
    "dark_yellow": {"yellow": 0.75, "black": 0.25},
    "dark_green": {"green": 0.75, "black": 0.25},
    "dark_blue": {"blue": 0.75, "black": 0.25},
})


def palette_flat():
    """Palette Pillow : un emplacement RGB par indice de la dalle, puis du noir.

    Les emplacements reserves (4 et 7) sont laisses en noir : ils ne sont jamais
    dessines.
    """
    flat = [channel for rgb in PALETTE_RGB for channel in rgb]
    return flat + [0] * (768 - len(flat))


def palette_image():
    """Image 1x1 en mode ``P`` portant la palette Spectra 6 (pour quantize)."""
    image = Image.new("P", (1, 1))
    image.putpalette(palette_flat())
    return image


def nearest_index(rgb) -> int:
    """Indice natif le plus proche d'une couleur RGB (distance euclidienne).

    Usage interne : ramene les entrees de remplissage de la palette Pillow vers
    une couleur Spectra 6 (voir ``PADDING_REMAP``). Les couleurs du ``.env`` ne
    passent plus par ici : elles ne referencent que des noms de la palette logique.
    """
    red, green, blue = rgb
    return min(
        VALID_INDICES,
        key=lambda index: (PALETTE_RGB[index][0] - red) ** 2
        + (PALETTE_RGB[index][1] - green) ** 2
        + (PALETTE_RGB[index][2] - blue) ** 2,
    )


@dataclass(frozen=True)
class Hatch:
    """Motif pose sur un fond uni (voir ``_parse_hatch`` pour la syntaxe).

    ``motif`` vaut ``"lines"`` (lignes continues), ``"dots"`` (pointilles),
    ``"dashes"`` (tirets), ``"bands"`` (bandes) ou ``"checker"`` (damier).
    ``ink`` et ``background`` sont des indices natifs de la palette Spectra 6.
    ``angles`` porte les orientations du motif ``lines``. ``size`` est la taille
    du point, la longueur du tiret ou la largeur de la bande. ``steps`` contient
    le pas des marques et/ou des lignes selon le motif. ``directions`` vaut
    ``"hv"`` (les deux sens, defaut), ``"h"`` (lignes horizontales) ou ``"v"``
    (lignes verticales) pour les pointilles, tirets et bandes.
    """

    motif: str
    ink: int
    background: int
    angles: Tuple[int, ...] = ()
    size: int = 1
    steps: Tuple[int, ...] = ()
    directions: str = "hv"


@dataclass(frozen=True)
class ColorSpec:
    """Couleur resolue : couleur native, melange trame ou hachure.

    ``weights`` associe a chaque indice natif la part de pixels qui lui revient
    (la somme vaut 1.0) et ``solid`` l'indice unique quand la couleur est native
    (le remplissage est alors uni, sans tramage). ``hatch`` decrit une hachure
    (lignes sur fond), rendue par le module ``dither``.
    """

    weights: Tuple[Tuple[int, float], ...]
    solid: Optional[int]
    label: str
    valid: bool
    hatch: Optional[Hatch] = None

    @property
    def is_solid(self) -> bool:
        """Vrai quand la couleur tient en un seul pixel natif (aucun tramage)."""
        return self.solid is not None

    @property
    def is_hatched(self) -> bool:
        """Vrai quand la couleur est une hachure (lignes sur fond uni)."""
        return self.hatch is not None


# Repli applique lorsqu'une couleur du .env est inconnue : noir uni.
UNKNOWN_SPEC = ColorSpec(
    ((BLACK_INDEX, 1.0),), BLACK_INDEX, "black (couleur inconnue, repli)", False
)


def _normalize(value: str) -> str:
    """Nom de couleur normalise : accents composes, bords et casse ignores."""
    return unicodedata.normalize("NFC", value or "").strip().casefold()


def _build_spec(weights) -> ColorSpec:
    """Construit la spec, composants tries du plus lourd au plus leger."""
    ordered = tuple(sorted(weights, key=lambda item: (-item[1], item[0])))
    if len(ordered) == 1:
        index = ordered[0][0]
        return ColorSpec(ordered, index, NAMES_BY_INDEX[index], True)

    label = " + ".join(
        "%s %d%%" % (NAMES_BY_INDEX[index], round(100 * weight))
        for index, weight in ordered
    )
    return ColorSpec(ordered, None, label, True)


# Bornes des parametres de motif (voir ``_parse_hatch``).
HATCH_MIN_STEP = 2
HATCH_MAX_STEP = 100
HATCH_MAX_SIZE = 9


def _make_spec(hatch: Hatch, fraction: float, label: str) -> ColorSpec:
    """Assemble une ``ColorSpec`` de motif (poids = encre + fond, pour le texte)."""
    # Fraction de pixels d'encre : sert a choisir la couleur du texte lisible.
    weights = tuple(
        sorted(
            ((hatch.ink, fraction), (hatch.background, 1.0 - fraction)),
            key=lambda item: (-item[1], item[0]),
        )
    )
    return ColorSpec(weights, None, label, True, hatch)


def _lines_spec(ink: str, angle_tokens, period_token) -> Optional[ColorSpec]:
    """``ENCRE_angle1[_angle2]_espacement`` : lignes continues."""
    try:
        period = int(period_token)
        angles = tuple(sorted({int(token) % 180 for token in angle_tokens}))
    except ValueError:
        return None

    if not angles or not (HATCH_MIN_STEP <= period <= HATCH_MAX_STEP):
        return None

    ink_index = INDEX[ink]
    direction = " + ".join("%d deg" % angle for angle in angles)
    # Une ligne de 1 pixel tous les ``period`` pixels, par direction demandee.
    fraction = min(1.0, len(angles) / period)
    hatch = Hatch("lines", ink_index, WHITE_INDEX, angles, 1, (period,))
    label = "%s %s / %d (hachure sur blanc)" % (
        NAMES_BY_INDEX[ink_index], direction, period,
    )
    return _make_spec(hatch, fraction, label)


def _motif_token(token: str):
    """Decoupe ``p2v`` -> ``("p", 2, "v")`` ; ``None`` si la forme est invalide.

    La lettre designe le motif (``p`` points, ``t`` tirets, ``b`` bandes, ``d``
    damier), le chiffre optionnel la taille des points, et la lettre finale
    optionnelle ``h``/``v`` le sens (horizontal / vertical).
    """
    if not token:
        return None

    letter, rest = token[0], token[1:]
    directions = "hv"
    if rest and rest[-1] in "hv":
        directions, rest = rest[-1], rest[:-1]
    if rest and not rest.isdigit():
        return None
    size = int(rest) if rest else 1
    return letter, size, directions


# Suffixe de direction dans un libelle (pour le rapport de debogage).
DIRECTION_LABEL = {"hv": "", "h": " horizontaux", "v": " verticaux"}


def _motif_spec(ink: str, head: str, param_tokens) -> Optional[ColorSpec]:
    """``ENCRE_motif[_A]_B`` : pointilles, tirets, bandes ou damier."""
    parsed = _motif_token(head)
    if parsed is None:
        return None
    letter, size, directions = parsed

    try:
        params = [int(token) for token in param_tokens]
    except ValueError:
        return None

    if not params or not all(1 <= value <= HATCH_MAX_STEP for value in params):
        return None
    if not 1 <= size <= HATCH_MAX_SIZE:
        return None

    ink_index = INDEX[ink]
    background = WHITE_INDEX
    where = DIRECTION_LABEL[directions]
    # Nombre de sens traces : double la fraction d'encre (couleur du texte).
    senses = 2 if directions == "hv" else 1

    if letter == "p":  # pointilles
        if len(params) == 1:
            mark = line = params[0]
        elif len(params) == 2:
            mark, line = params
        else:
            return None
        if mark < HATCH_MIN_STEP or line < HATCH_MIN_STEP:
            return None
        hatch = Hatch("dots", ink_index, background, (), size, (mark, line), directions)
        fraction = min(1.0, senses * size * size / (mark * line))
        label = "%s pointille%s %dpx / pas %d x %d" % (
            NAMES_BY_INDEX[ink_index], where, size, mark, line,
        )
    elif letter == "t":  # tirets
        if size != 1 or len(params) != 2:
            return None
        length, period = params
        if period < HATCH_MIN_STEP or length > period:
            return None
        hatch = Hatch("dashes", ink_index, background, (), length, (period,), directions)
        fraction = min(1.0, senses * length / period)
        label = "%s tirets%s %d/%d" % (
            NAMES_BY_INDEX[ink_index], where, length, period,
        )
    elif letter == "b":  # bandes
        if size != 1 or len(params) != 2:
            return None
        band, period = params
        if period < HATCH_MIN_STEP or band > period:
            return None
        hatch = Hatch("bands", ink_index, background, (), band, (period,), directions)
        fraction = min(1.0, senses * band / period)
        label = "%s bandes%s %d/%d" % (
            NAMES_BY_INDEX[ink_index], where, band, period,
        )
    elif letter == "d":  # damier
        if size != 1 or directions != "hv" or len(params) != 1 or params[0] < HATCH_MIN_STEP:
            return None
        hatch = Hatch("checker", ink_index, background, (), 1, (params[0],))
        fraction = 0.5
        label = "%s damier %d" % (NAMES_BY_INDEX[ink_index], params[0])
    else:
        return None

    return _make_spec(hatch, fraction, label)


def _parse_hatch(name: str) -> Optional[ColorSpec]:
    """Resout un motif en spec (nom deja normalise).

    Deux formes :

    * ``ENCRE_angle1[_angle2]_espacement`` : lignes continues (0 = horizontale,
      90 = verticale, 45/135 = diagonales, tout angle entier) ;
    * ``ENCRE_motif[_A]_B`` : ``p[K]`` pointilles (points de ``K`` px, defaut 1),
      ``t`` tirets (longueur ``A`` sur une periode ``B``), ``b`` bandes (largeur
      ``A`` sur une periode ``B``), ``d`` damier (cellule ``B``).

    Retourne ``None`` quand la valeur n'est pas un motif : les couleurs natives
    et logiques ne sont pas touchees. L'encre doit etre l'une des 6 couleurs
    primaires ; le fond du motif est blanc.
    """
    tokens = name.split("_")
    if not 3 <= len(tokens) <= 4:
        return None

    ink = tokens[0]
    if ink not in INDEX:  # uniquement les 6 couleurs primaires
        return None

    if tokens[1].lstrip("-").isdigit():
        return _lines_spec(ink, tokens[1:-1], tokens[-1])

    return _motif_spec(ink, tokens[1], tokens[2:])


@lru_cache(maxsize=None)
def color_spec(value: str) -> ColorSpec:
    """Resout une couleur du ``.env`` : hachure, couleur native ou logique.

    Reconnait d'abord une hachure ``ENCRE_angle1[_angle2]_espacement``, puis un
    nom de ``LOGICAL_PALETTE``, sans tenir compte de la casse, des accents ni
    des espaces superflus. Toute autre valeur -- y compris un code hexadecimal --
    retombe sur du noir, avec un avertissement emis une seule fois par valeur
    distincte (le resultat est memoise).
    """
    name = _normalize(value)

    hatch = _parse_hatch(name)
    if hatch is not None:
        return hatch

    mix = LOGICAL_PALETTE.get(name)
    if mix is None:
        logger.warning(
            "Couleur inconnue %r : repli sur noir. Noms acceptes : %s. "
            "Motifs : ENCRE_angle1[_angle2]_espacement ou ENCRE_motif[_A]_B "
            "(ex. YELLOW_45_3, RED_p_10, GREEN_t_3_10, BLUE_b_4_16, BLACK_d_8).",
            value,
            ", ".join(sorted(LOGICAL_PALETTE)),
        )
        return UNKNOWN_SPEC

    return _build_spec(
        (INDEX[colour], float(weight)) for colour, weight in mix.items()
    )


def ensure_indexed(image: Image.Image) -> Image.Image:
    """Garantit une image en mode ``P`` alignee sur la palette Spectra 6."""
    if image.mode == "P":
        palette = image.getpalette() or []
        expected = palette_flat()[: len(PALETTE_RGB) * 3]
        if palette[: len(expected)] == expected:
            return image

    indexed = image.convert("RGB").quantize(
        palette=palette_image(),
        dither=Image.Dither.NONE,
    )

    # Les entrees de remplissage de la palette Pillow (indices 6 a 255) ne sont
    # pas valides pour l'ecran : un pixel strictement egal a l'une d'elles y est
    # accroche (c'est le cas du noir pur, valeur du remplissage). On ramene donc
    # chaque index hors palette vers la couleur Spectra 6 equivalente.
    return indexed.point(PADDING_REMAP)


# Table de correction appliquee aux images quantifiees (voir ensure_indexed).
PADDING_REMAP = [
    index if index in VALID_INDICES
    else nearest_index(palette_flat()[3 * index:3 * index + 3])
    for index in range(256)
]


def _pack_rows(indices: bytes, width: int, height: int) -> bytes:
    """Empaquette deux pixels (4 bits) par octet, ligne par ligne.

    Chaque octet de ``indices`` ne contient qu'un quartet utile : on assemble
    donc une ligne entiere d'un coup avec un decalage binaire sur des entiers
    de taille arbitraire (traite en C, bien plus rapide qu'une boucle Python
    sur pres d'un million de pixels).
    """
    stride = (width + 1) // 2
    packed = bytearray()

    for y in range(height):
        row = indices[y * width:(y + 1) * width]
        if width % 2:  # ligne alignee sur un octet
            row += b"\x00"

        high = int.from_bytes(row[0::2], "big") << 4
        low = int.from_bytes(row[1::2], "big")
        packed += (high | low).to_bytes(stride, "big")

    return bytes(packed)


def portrait(image: Image.Image, rotation: int = DEFAULT_ROTATION) -> Image.Image:
    """Tourne l'image paysage (1600x1200) vers le portrait natif (1200x1600)."""
    if rotation not in ROTATION_TRANSPOSE:
        raise ValueError(
            f"Rotation {rotation!r} inconnue : valeurs acceptees "
            f"{sorted(ROTATION_TRANSPOSE)} degres"
        )

    turned = image.transpose(ROTATION_TRANSPOSE[rotation])
    if turned.size != (PANEL_WIDTH, PANEL_HEIGHT):
        raise ValueError(
            f"Image {image.size} : attendu une image paysage "
            f"{LANDSCAPE_WIDTH}x{LANDSCAPE_HEIGHT} pour la dalle "
            f"{PANEL_WIDTH}x{PANEL_HEIGHT}"
        )
    return turned


def to_panel(image: Image.Image, rotation: int = DEFAULT_ROTATION) -> bytes:
    """Charge utile de la dalle : moitie gauche puis droite, indices de la dalle.

    Les deux moities sont concatenees en octets (aucune image geante
    intermediaire : une image de 960000 pixels de large n'est pas exploitable).
    """
    turned = portrait(image, rotation)
    left = turned.crop((0, 0, PANEL_HALF_WIDTH, PANEL_HEIGHT)).tobytes()
    right = turned.crop((PANEL_HALF_WIDTH, 0, PANEL_WIDTH, PANEL_HEIGHT)).tobytes()
    return (left + right).translate(INDEX_TO_PANEL)


def encode(image: Image.Image, rotation: int = DEFAULT_ROTATION) -> bytes:
    """Retourne le contenu complet (en-tete + pixels) du fichier ``.s6``.

    L'image fournie est l'image paysage du renderer ; elle est tournee, coupee en
    deux moities (gauche puis droite) et ses indices sont convertis vers la
    numerotation de la dalle.
    """
    indexed = ensure_indexed(image)
    indices = indexed.tobytes()

    unexpected = sorted(set(indices) - set(VALID_INDICES))
    if unexpected:
        raise ValueError(
            f"Indice(s) hors palette {unexpected} : l'image doit etre dessinee "
            f"avec la palette Spectra 6 ({len(PALETTE_NAMES)} couleurs, "
            f"{BITS_PER_PIXEL} bits par pixel)"
        )

    payload = to_panel(indexed, rotation)
    stride = PANEL_HALF_WIDTH // 2  # 2 pixels par octet

    header = struct.pack(
        "<8sBHHBBH",
        MAGIC,
        VERSION,
        PANEL_WIDTH,
        PANEL_HEIGHT,
        BITS_PER_PIXEL,
        len(PALETTE_NAMES),
        HEADER_SIZE,
    )
    return header + _pack_rows(payload, PANEL_HALF_WIDTH, 2 * PANEL_HEIGHT)


def write_s6(image: Image.Image, path: str, rotation: int = DEFAULT_ROTATION) -> int:
    """Ecrit ``image`` au format ``.s6`` et retourne la taille du fichier."""
    payload = encode(image, rotation)

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "wb") as handle:
        handle.write(payload)

    return len(payload)
