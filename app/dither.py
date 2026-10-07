"""Tramage *blue noise* des couleurs logiques sur la palette Spectra 6.

L'ecran n'affiche que 6 couleurs : une couleur logique (``orange``, ``cyan``,
``gray``...) est rendue en repartissant ses pixels entre ses couleurs natives
selon un masque *blue noise* calcule une seule fois, puis pave sur la surface a
remplir. Le texte pose par-dessus reste plein : la lisibilite est preservee et
aucun pixel hors palette n'est produit.

Le masque est un classement (``void-and-cluster`` d'Ulichney) ou les rangs les
plus bas sont les pixels les mieux repartis : prendre les rangs inferieurs a la
proportion voulue distribue donc la couleur minoritaire de facon quasi uniforme,
quelle que soit cette proportion.

Ce module rend egalement les *motifs* (voir ``s6._parse_hatch``) : lignes,
pointilles, tirets, bandes ou damier d'une couleur native poses sur un fond uni.
La phase est ancree sur l'origine de l'image, pour que les motifs de plusieurs
blocs restent alignes.
"""

import logging
import math
import os
import random
import time
from functools import lru_cache

from PIL import Image, ImageDraw

from s6 import ColorSpec, palette_flat

logger = logging.getLogger(__name__)

# Taille du masque carre : 64 (texture fine) ou 32 (generation instantanee).
DEFAULT_NOISE_SIZE = 64
ALLOWED_NOISE_SIZES = (32, 64)

# Graine fixe : le masque est identique d'un demarrage a l'autre.
NOISE_SEED = 20261001


@lru_cache(maxsize=None)
def noise_size() -> int:
    """Taille du masque, lue dans ``DITHER_NOISE_SIZE`` (defaut 64).

    Toute valeur hors ``ALLOWED_NOISE_SIZES`` est ignoree avec un avertissement,
    afin qu'une faute de frappe dans le ``.env`` ne casse pas le rendu.
    """
    raw = os.environ.get("DITHER_NOISE_SIZE", "").strip()
    if not raw:
        return DEFAULT_NOISE_SIZE

    try:
        size = int(raw)
    except ValueError:
        size = -1

    if size not in ALLOWED_NOISE_SIZES:
        logger.warning(
            "DITHER_NOISE_SIZE=%r invalide (valeurs acceptees : %s) : %d utilise",
            raw,
            " ou ".join(str(value) for value in ALLOWED_NOISE_SIZES),
            DEFAULT_NOISE_SIZE,
        )
        return DEFAULT_NOISE_SIZE

    return size


def _void_and_cluster(size: int, sigma: float = 1.9, relax: int = 20):
    """Rangs d'un masque blue noise, de 0 (pixel le plus isole) a size^2-1.

    Le filtre gaussien est applique en tore, si bien que le masque obtenu est
    carrelable sans couture. ``relax`` equilibre le motif de depart en deplacant
    le paquet de points le plus serre vers le plus grand vide.
    """
    rng = random.Random(NOISE_SEED)
    radius = max(1, int(round(3 * sigma)))
    kernel = [
        (dx, dy, math.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma)))
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
    ]
    count = size * size

    def energies(pattern):
        field = [0.0] * count
        for y in range(size):
            for x in range(size):
                if pattern[y * size + x]:
                    for dx, dy, weight in kernel:
                        field[((y + dy) % size) * size + (x + dx) % size] += weight
        return field

    def shift(field, position, sign):
        x = position % size
        y = position // size
        for dx, dy, weight in kernel:
            field[((y + dy) % size) * size + (x + dx) % size] += sign * weight

    def select(pattern, field, set_points):
        best = -1.0 if set_points else math.inf
        chosen = -1
        for position, value in enumerate(field):
            if pattern[position] != set_points:
                continue
            if (set_points and value > best) or (not set_points and value < best):
                best = value
                chosen = position
        return chosen

    pattern = [0] * count
    points = max(1, count // 10)
    placed = 0
    while placed < points:
        position = rng.randrange(count)
        if not pattern[position]:
            pattern[position] = 1
            placed += 1

    field = energies(pattern)
    for _ in range(relax):
        cluster = select(pattern, field, True)
        pattern[cluster] = 0
        shift(field, cluster, -1.0)
        void = select(pattern, field, False)
        pattern[void] = 1
        shift(field, void, 1.0)

    relaxed = list(pattern)
    ranks = [0] * count

    # Rangs 0..points-1 : on retire les paquets les plus serres ; les points qui
    # restent le plus longtemps sont les plus isoles et prennent les rangs bas.
    field = energies(pattern)
    for rank in range(points - 1, -1, -1):
        cluster = select(pattern, field, True)
        pattern[cluster] = 0
        shift(field, cluster, -1.0)
        ranks[cluster] = rank

    # Rangs points..count-1 : on remplit les plus grands vides.
    pattern = list(relaxed)
    field = energies(pattern)
    for rank in range(points, count):
        void = select(pattern, field, False)
        pattern[void] = 1
        shift(field, void, 1.0)
        ranks[void] = rank

    return tuple(ranks)


@lru_cache(maxsize=None)
def blue_noise(size: int) -> tuple:
    """Masque de rangs ``size x size``, genere une seule fois et memoise."""
    started = time.perf_counter()
    ranks = _void_and_cluster(size)
    logger.info(
        "Masque blue noise %dx%d genere en %.2f s",
        size,
        size,
        time.perf_counter() - started,
    )
    return ranks


@lru_cache(maxsize=None)
def tile(spec: ColorSpec, size: int) -> Image.Image:
    """Motif carre (mode ``P``) repartissant les couleurs natives de ``spec``.

    Le premier composant de ``spec`` (le plus lourd) occupe les rangs les plus
    bas du masque, donc les emplacements les mieux repartis.
    """
    ranks = blue_noise(size)
    count = size * size

    thresholds = []
    cumulative = 0.0
    for index, weight in spec.weights[:-1]:
        cumulative += weight
        thresholds.append((cumulative * count, index))
    fallback = spec.weights[-1][0]

    pixels = bytearray(count)
    for position, rank in enumerate(ranks):
        chosen = fallback
        for threshold, index in thresholds:
            if rank < threshold:
                chosen = index
                break
        pixels[position] = chosen

    pattern = Image.frombytes("P", (size, size), bytes(pixels))
    pattern.putpalette(palette_flat())
    return pattern


def _clip_segment(ax, ay, bx, by, xmax, ymax):
    """Clippe un segment sur ``[0, xmax] x [0, ymax]`` (Liang-Barsky).

    Retourne ``(ax, ay, bx, by)`` ou ``None`` si le segment est entierement
    dehors. Le rognage explicite evite les artefacts de Pillow pour les lignes
    situees juste a l'exterieur du patch (une ligne verticale a ``x = -1`` sur
    un patch large de 1 pixel remplissait toute la colonne).
    """
    dx, dy = bx - ax, by - ay
    bounds = ((-dx, ax), (dx, xmax - ax), (-dy, ay), (dy, ymax - ay))
    u0, u1 = 0.0, 1.0

    for p, q in bounds:
        if p == 0.0:
            if q < 0.0:
                return None
        else:
            ratio = q / p
            if p < 0.0:
                if ratio > u1:
                    return None
                if ratio > u0:
                    u0 = ratio
            else:
                if ratio < u0:
                    return None
                if ratio < u1:
                    u1 = ratio

    return (ax + u0 * dx, ay + u0 * dy, ax + u1 * dx, ay + u1 * dy)


# Diagonales "sur la grille de pixels" : la famille de droites est
# ``A*x + B*y = c`` avec ``c`` entier. L'ecart entre deux lignes est alors un
# nombre entier de pixels, ce qui supprime le "saut" d'un pixel que produisent
# les diagonales a espacement non entier (``period * sqrt(2)`` n'est jamais
# entier : il vaut par exemple 7.071 pour un espacement de 5).
LATTICE_FAMILIES = {
    45: (-1, 1),   # y - x = c
    135: (1, 1),   # x + y = c
}


def _draw_lattice(draw, origin, size, ink, family, period) -> None:
    """Trace la famille ``A*x + B*y = k * step`` sur la grille de pixels.

    ``step`` vaut ``round(period * sqrt(2))`` : l'entier le plus proche de
    l'ecart reel des diagonales, ce qui conserve la densite tout en rendant le
    trace parfaitement regulier. La phase est ancree sur l'origine globale de
    l'image, pour que les hachures de plusieurs blocs restent alignees.
    """
    a, b = family
    step = max(1, round(period * math.sqrt(2)))
    ox, oy = origin
    width, height = size
    xmax, ymax = width - 1, height - 1
    base = a * ox + b * oy
    reach = width + height + step

    corners = ((0, 0), (xmax, 0), (0, ymax), (xmax, ymax))
    projected = [a * x + b * y for x, y in corners]
    k_min = math.ceil((min(projected) + base) / step)
    k_max = math.floor((max(projected) + base) / step)

    dx, dy = b, -a  # direction de la droite (perpendiculaire a la normale A,B)
    for k in range(k_min, k_max + 1):
        constant = k * step - base  # a*x + b*y = constant (coordonnees locales)
        point_x, point_y = (constant / a, 0) if a else (0, constant / b)
        segment = _clip_segment(
            point_x - reach * dx, point_y - reach * dy,
            point_x + reach * dx, point_y + reach * dy,
            xmax, ymax,
        )
        if segment is not None:
            # La geometrie est entiere : arrondir les extremites efface les
            # erreurs d'arrondi flottant du rognage (une extremite a
            # 34.999999999999886 ferait deriver le trace d'un pixel).
            draw.line(tuple(round(value) for value in segment), fill=ink, width=1)


def _draw_hatch(draw, origin, size, ink, angles, period) -> None:
    """Trace les lignes d'une hachure sur un patch (coordonnees locales).

    Les diagonales a 45/135 degres sont tracees sur la grille de pixels
    (espacement regulier) ; les autres angles utilisent une projection
    perpendiculaire. La phase est ancree sur l'origine globale de l'image
    (``origin``), pour que les hachures de plusieurs blocs restent alignees.
    Chaque ligne est rognee sur le patch avant d'etre tracee.
    """
    ox, oy = origin
    width, height = size
    xmax, ymax = width - 1, height - 1
    corners = ((0.0, 0.0), (width, 0.0), (0.0, height), (width, height))
    reach = width + height + period

    for angle in angles:
        family = LATTICE_FAMILIES.get(angle % 180)
        if family is not None:
            _draw_lattice(draw, origin, size, ink, family, period)
            continue

        theta = math.radians(angle)
        dx, dy = math.cos(theta), math.sin(theta)
        nx, ny = -dy, dx
        base = ox * nx + oy * ny
        projections = [px * nx + py * ny for px, py in corners]
        k_min = math.floor((min(projections) + base) / period)
        k_max = math.ceil((max(projections) + base) / period)

        for k in range(k_min, k_max + 1):
            offset = k * period - base
            px, py = offset * nx, offset * ny
            segment = _clip_segment(
                px - reach * dx, py - reach * dy,
                px + reach * dx, py + reach * dy,
                xmax, ymax,
            )
            if segment is not None:
                draw.line(segment, fill=ink, width=1)


def _draw_dots(patch, origin, size, hatch) -> None:
    """Pointilles : points de ``hatch.size`` px, dans les sens demandes.

    Le sens ``h`` pose des points tous les ``steps[0]`` px sur des lignes
    horizontales espacees de ``steps[1]`` ; le sens ``v`` fait de meme a la
    verticale (les deux sens se cumulent).
    """
    ox, oy = origin
    width, height = size
    mark, line = hatch.steps
    dot = hatch.size
    pixels = patch.load()

    for direction in hatch.directions:
        if direction == "h":
            rows = range((-oy) % line, height, line)
            cols = range((-ox) % mark, width, mark)
        else:
            rows = range((-oy) % mark, height, mark)
            cols = range((-ox) % line, width, line)
        for top in rows:
            for left in cols:
                for y in range(top, min(top + dot, height)):
                    for x in range(left, min(left + dot, width)):
                        pixels[x, y] = hatch.ink


def _draw_dashes(patch, origin, size, hatch) -> None:
    """Tirets : traits de ``hatch.size`` px, dans les sens demandes."""
    ox, oy = origin
    width, height = size
    length = hatch.size
    period = hatch.steps[0]
    pixels = patch.load()

    if "h" in hatch.directions:
        for y in range((-oy) % period, height, period):
            for left in range((-ox) % period, width, period):
                for x in range(left, min(left + length, width)):
                    pixels[x, y] = hatch.ink
    if "v" in hatch.directions:
        for x in range((-ox) % period, width, period):
            for top in range((-oy) % period, height, period):
                for y in range(top, min(top + length, height)):
                    pixels[x, y] = hatch.ink


def _draw_bands(patch, origin, size, hatch) -> None:
    """Bandes : traits pleins de ``hatch.size`` px, dans les sens demandes."""
    ox, oy = origin
    width, height = size
    band = hatch.size
    period = hatch.steps[0]
    pixels = patch.load()

    if "h" in hatch.directions:
        for y in range(height):
            if (oy + y) % period < band:
                for x in range(width):
                    pixels[x, y] = hatch.ink
    if "v" in hatch.directions:
        for x in range(width):
            if (ox + x) % period < band:
                for y in range(height):
                    pixels[x, y] = hatch.ink


def _draw_checker(patch, origin, size, hatch) -> None:
    """Damier : cases ``hatch.steps[0]`` x ``hatch.steps[0]`` alternees."""
    ox, oy = origin
    width, height = size
    cell = hatch.steps[0]
    pixels = patch.load()

    for top in range(0, height, cell):
        for left in range(0, width, cell):
            if ((ox + left) // cell + (oy + top) // cell) % 2:
                continue
            for y in range(top, min(top + cell, height)):
                for x in range(left, min(left + cell, width)):
                    pixels[x, y] = hatch.ink


_PATTERN_DRAWERS = {
    "dots": _draw_dots,
    "dashes": _draw_dashes,
    "bands": _draw_bands,
    "checker": _draw_checker,
}


def _pattern_fill(image: Image.Image, box, spec: ColorSpec) -> None:
    """Peint ``box`` avec le motif de ``spec``, pose sur un fond uni.

    La phase de chaque motif est ancree sur l'origine globale de l'image, pour
    que les motifs de plusieurs blocs restent alignes.
    """
    x0, y0, x1, y1 = (int(value) for value in box)
    width = x1 - x0 + 1
    height = y1 - y0 + 1
    hatch = spec.hatch

    patch = Image.new("P", (width, height), hatch.background)
    patch.putpalette(palette_flat())

    if hatch.motif == "lines":
        _draw_hatch(
            ImageDraw.Draw(patch), (x0, y0), (width, height),
            hatch.ink, hatch.angles, hatch.steps[0],
        )
    else:
        drawer = _PATTERN_DRAWERS.get(hatch.motif)
        if drawer is not None:
            drawer(patch, (x0, y0), (width, height), hatch)

    image.paste(patch, (x0, y0))


def fill(image: Image.Image, box, spec: ColorSpec) -> None:
    """Peint ``box`` = ``(x0, y0, x1, y1)`` (bornes incluses) avec ``spec``.

    Un motif (lignes, pointilles, tirets, bandes, damier) est pose sur un fond
    uni ; une couleur native remplit d'un seul aplat, sans tramage ; une couleur
    logique est tramee en pavant le motif blue noise sur toute la zone.
    """
    x0, y0, x1, y1 = (int(value) for value in box)

    if spec.hatch is not None:
        _pattern_fill(image, box, spec)
        return

    if spec.is_solid:
        ImageDraw.Draw(image).rectangle((x0, y0, x1, y1), fill=spec.solid)
        return

    size = noise_size()
    pattern = tile(spec, size)
    patch = Image.new("P", (x1 - x0 + 1, y1 - y0 + 1))
    patch.putpalette(palette_flat())
    for y in range(0, patch.height, size):
        for x in range(0, patch.width, size):
            patch.paste(pattern, (x, y))
    image.paste(patch, (x0, y0))
