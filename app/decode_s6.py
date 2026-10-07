#!/usr/bin/env python3
"""Decodeur .s6 -> PNG, ecrit uniquement a partir de la doc du panneau.

Usage (dans le conteneur) :
    python decode_s6.py output/calendar.s6 output/calendar_depuis_s6.png

Ce script est volontairement independant du code d'ecriture : il relit le
fichier octet par octet, applique la numerotation de la dalle puis la rotation
inverse, et reconstruit un PNG au format paysage (1600x1200) comparable a
``output/calendar.png``.

Format attendu (version 1, en-tete 17 octets, little-endian) :

    offset  taille  champ
    0       8       "SPECTRA6"
    8       1       version (1)
    9       2       largeur de la dalle  (1200)
    11      2       hauteur de la dalle  (1600)
    13      1       bits par pixel (4)
    14      1       couleurs (6)
    15      2       offset des donnees (17)

Pixels : 4 bits par pixel, deux par octet, le pixel pair (le plus a gauche) dans
les bits 7..4. Les donnees sont la moitie gauche (600x1600) puis la droite.
Numerotation de la dalle : 0 noir, 1 blanc, 2 jaune, 3 rouge, 4 reserve,
5 bleu, 6 vert, 7 reserve.
"""

import struct
import sys

from PIL import Image

# Couleurs de la dalle (index 0..7), telles que restituees par l'ecran.
PANEL_RGB = {
    0: (25, 30, 33),      # noir
    1: (232, 232, 232),   # blanc
    2: (239, 222, 68),    # jaune
    3: (178, 19, 24),     # rouge
    5: (33, 87, 186),     # bleu
    6: (18, 95, 32),      # vert
}
RESERVED = (4, 7)

MAGIC = b"SPECTRA6"
HEADER_SIZE = 17


def unpack(blob):
    """Separe l'en-tete de la charge utile et verifie la coherence."""
    if len(blob) < HEADER_SIZE:
        raise SystemExit("fichier trop court pour un en-tete .s6")

    magic, version, width, height, bpp, colours, offset = struct.unpack(
        "<8sBHHBBH", blob[:HEADER_SIZE]
    )

    print("  magic          : %r" % magic)
    print("  version        : %d" % version)
    print("  dalle          : %d x %d" % (width, height))
    print("  bits par pixel : %d" % bpp)
    print("  couleurs       : %d" % colours)
    print("  offset pixels  : %d" % offset)
    print("  taille fichier : %d octets" % len(blob))

    if magic != MAGIC:
        raise SystemExit("magic inattendu : %r" % magic)
    if version != 1:
        raise SystemExit("version %d non geree (ce script decode la version 1)" % version)
    if bpp != 4:
        raise SystemExit("ce script attend 4 bits par pixel, pas %d" % bpp)
    if width % 2:
        raise SystemExit("largeur impaire (%d) : structure inattendue" % width)

    expected = offset + (width // 2) * height
    if len(blob) != expected:
        print("  ATTENTION      : taille attendue %d, fichier %d" % (expected, len(blob)))

    return width, height, offset


def nibbles(body):
    """Extrait les quartets : le pixel pair est dans les bits 7..4."""
    high = body.translate(bytes(byte >> 4 for byte in range(256)))
    low = body.translate(bytes(byte & 0x0F for byte in range(256)))
    out = bytearray(2 * len(body))
    out[0::2] = high
    out[1::2] = low
    return bytes(out)


def build_panel(values, width, height):
    """Reconstruit le portrait : moitie gauche a gauche, moitie droite a droite.

    Les deux moities sont des blocs de 600x1600 pixels. Les concatener
    directement donnerait une image de 1200 pixels de large dont chaque ligne
    serait composee de la fin de la gauche et du debut de la droite : il faut
    donc les recoller par ``paste`` cote a cote, ligne par ligne.
    """
    half_width = width // 2
    half_pixels = half_width * height

    left = Image.frombytes("P", (half_width, height), values[:half_pixels])
    right = Image.frombytes("P", (half_width, height), values[half_pixels:half_pixels * 2])
    left.putpalette(palette())
    right.putpalette(palette())

    panel = Image.new("P", (width, height))
    panel.putpalette(palette())
    panel.paste(left, (0, 0))
    panel.paste(right, (half_width, 0))
    return panel


def palette():
    """Palette Pillow : les 8 couleurs de la dalle (reservees en noir)."""
    flat = []
    for index in range(8):
        flat.extend(PANEL_RGB.get(index, (0, 0, 0)))
    flat.extend([0] * (768 - len(flat)))
    return flat


def main():
    arguments = [value for value in sys.argv[1:] if not value.startswith("--")]
    options = [value for value in sys.argv[1:] if value.startswith("--")]

    if len(arguments) != 2:
        raise SystemExit(
            "usage : decode_s6.py ENTREE.s6 SORTIE.png [--rotation 90|270] [--toutes]\n"
            "  --rotation 90   (defaut) inverse une ecriture faite avec S6_ROTATION=90\n"
            "  --rotation 270  inverse une ecriture faite avec S6_ROTATION=270\n"
            "  --toutes        ecrit aussi SORTIE-90.png et SORTIE-270.png pour comparer"
        )

    source, target = arguments
    rotation = 90
    if "--rotation" in options:
        position = options.index("--rotation")
        try:
            rotation = int(options[position + 1]) if position + 1 < len(options) else 90
        except ValueError:
            raise SystemExit("--rotation attend 90 ou 270")

    with open(source, "rb") as handle:
        blob = handle.read()

    print("Lecture de %s" % source)
    width, height, offset = unpack(blob)

    values = nibbles(blob[offset:])
    used = sorted(set(values))
    print("  quartets utilises :", used)

    reserved = [value for value in used if value in RESERVED]
    if reserved:
        print("  ATTENTION      : couleurs reservees presentes :", reserved)
    unknown = [value for value in used if value not in PANEL_RGB]
    if unknown:
        print("  ATTENTION      : quartets inconnus :", unknown)

    panel = build_panel(values, width, height)
    print("  portrait       : %s" % (panel.size,))

    # Sens de rotation inverse de celui de l'ecriture : ROTATE_90 est
    # anti-horaire, ROTATE_270 est horaire (noms Pillow).
    back = {
        90: Image.Transpose.ROTATE_90,
        270: Image.Transpose.ROTATE_270,
    }
    if rotation not in back:
        raise SystemExit("rotation %s inconnue (90 ou 270)" % rotation)

    chosen = panel.transpose(back[rotation]).convert("RGB")
    chosen.save(target)
    print("  rotation %3d    : paysage %s" % (rotation, chosen.size))
    print("Ecrit %s" % target)

    if "--toutes" in options:
        root = target[:-4] if target.lower().endswith(".png") else target
        for angle in (90, 270):
            other = panel.transpose(back[angle]).convert("RGB")
            path = "%s-%d.png" % (root, angle)
            other.save(path)
            print("Ecrit %s (rotation %d)" % (path, angle))


if __name__ == "__main__":
    main()

