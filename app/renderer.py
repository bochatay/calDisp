"""Generation des images e-paper 1600x1200 (vue 7 jours).

Deux fichiers sont produits a chaque rafraichissement :

* le PNG de visualisation, dessine avec les couleurs reelles de l'ecran
  (palette Spectra 6, voir le module ``s6``) ;
* le binaire ``.s6`` (4 bits par pixel) a programmer sur l'ESP32.

Le dessin se fait directement dans une image en mode ``P`` : le texte reste
net (aucun pixel hors palette issu de l'antialiasing) et la meme image sert
de source unique aux deux formats.
"""

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

import dither
from config import Config, DEFAULT_FIRST_COLUMN_SCALE
from s6 import (
    BLACK_INDEX,
    PALETTE_RGB,
    WHITE_INDEX,
    ColorSpec,
    color_spec,
    palette_flat,
    write_s6,
)

logger = logging.getLogger(__name__)

WIDTH = 1600
HEIGHT = 1200
MONTH_HEIGHT = 50
DAY_HEADER_HEIGHT = 120

# Tous les traits noirs de la mise en page font cette epaisseur.
LINE_WIDTH = 2

# La colonne du jour (la premiere) est plus large que les autres. Le ratio est
# reglable par la variable d'environnement ``FIRST_COLUMN_SCALE`` (defaut 1.5).


FR_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
MONTH_PADDING = 12

# Fonds des colonnes : une couleur par jour de la semaine, lue dans le .env
# (variables MONDAY..SUNDAY, voir ``config.column_colors``). Le defaut est blanc.
# Le texte de l'en-tete de colonne est choisi pour rester lisible sur ce fond.

# Blocs d'evenements : marge interne du bloc, hauteur des lignes et espace
# vertical laisse entre deux blocs. L'en-tete horaire de chaque bloc est plus
# petit et en gras ; le texte de l'evenement garde sa taille normale.
BLOCK_PADDING = 6
LINE_TIME = 22
LINE_EVENT = 28
LINE_DETAIL = 21
BLOCK_GAP = 10

# Les evenements « toute la journee » sont des blocs multi-lignes comme les
# autres ; faute d'heure a afficher, leur en-tete porte ce libelle.
ALL_DAY_HEADER = "Toute la journée"

# Pied de page : bande en bas avec la legende des calendriers (teinte + nom) et
# l'heure de generation, en heure locale.
FOOTER_HEIGHT = 46
FOOTER_PADDING = 14
FOOTER_SWATCH_WIDTH = 22
FOOTER_SWATCH_HEIGHT = 16
FOOTER_GAP = 24


# Police principale : Noto Sans (paquet Debian "fonts-noto-core"). Les polices
# DejaVu et Liberation restent en repli si Noto n'est pas installe.
_REGULAR_FONTS = (
    "fonts/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/local/share/fonts/NotoSans-Regular.ttf",
    # Repli (police equivalente si Noto est absent)
    "fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/local/share/fonts/DejaVuSans.ttf",
)
_BOLD_FONTS = (
    "fonts/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/local/share/fonts/NotoSans-Bold.ttf",
    # Repli (police equivalente si Noto est absent)
    "fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/local/share/fonts/DejaVuSans-Bold.ttf",
)


_warned_missing_font = False


def _font_path(bold: bool = False):
    """Retourne le chemin d'une police TrueType lisible, sinon ``None``.

    Un fichier peut etre force via ``FONT_PATH`` / ``FONT_BOLD_PATH``. Sinon on
    cherche Noto Sans aux emplacements usuels (installe dans l'image Docker),
    puis DejaVu en repli.
    """
    global _warned_missing_font

    forced = os.environ.get("FONT_BOLD_PATH" if bold else "FONT_PATH")
    candidates = ([forced] if forced else []) + list(_BOLD_FONTS if bold else _REGULAR_FONTS)

    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            ImageFont.truetype(path, 12)  # verifie que le fichier est lisible
            return path
        except OSError:
            logger.warning("Police illisible, ignoree : %s", path)

    if not _warned_missing_font:
        _warned_missing_font = True
        logger.warning(
            "Aucune police TrueType trouvee : repli sur la police par defaut, "
            "les caracteres accentues (é, à, ç...) risquent de ne pas s'afficher. "
            "Installez 'fonts-noto-core' ou definissez FONT_PATH."
        )
    return None


def _load_font(size: int, bold: bool = False):
    """Charge la police TrueType (accents geres) au format demande."""
    path = _font_path(bold)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:  # pragma: no cover - deja verifie dans _font_path
            logger.warning("Police illisible, ignoree : %s", path)

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - anciennes versions de Pillow
        return ImageFont.load_default()


FONT_DAY = _load_font(34)
FONT_DAY_NUM = _load_font(40)
FONT_TIME = _load_font(22)
FONT_BLOCK_TIME = _load_font(18, bold=True)
FONT_EVENT = _load_font(24)
FONT_DETAIL = _load_font(19)
FONT_FOOTER = _load_font(22)

# Polices de l'en-tete des mois, de la plus grande a la plus petite : le libelle
# est retreci quand un mois n'occupe qu'une ou deux colonnes.
MONTH_FONTS = tuple((size, _load_font(size, bold=True)) for size in (36, 30, 26, 22))


def _spec(color: str) -> ColorSpec:
    """Couleur d'un calendrier : nom natif, melange logique ou hachure."""
    return color_spec(color)


def _event_datetime(value, tz: ZoneInfo) -> datetime:
    """Normalise une datetime/date d'evenement en datetime dans le fuseau local."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)
    return datetime(value.year, value.month, value.day, tzinfo=tz)


def _wrap(draw, text: str, font, max_width: float):
    """Decoupe un texte en lignes tenant dans ``max_width`` pixels."""
    lines = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _month_groups(days):
    """Groupes de colonnes consecutives partageant le meme mois.

    Chaque element vaut ``(premiere_colonne, derniere_colonne, annee, mois)``,
    ce qui permet d'ecrire le mois juste au-dessus des colonnes concernees.
    """
    groups = []
    for index, day in enumerate(days):
        if groups and (groups[-1][2], groups[-1][3]) == (day.year, day.month):
            groups[-1][1] = index
        else:
            groups.append([index, index, day.year, day.month])
    return [(first, last, year, month) for first, last, year, month in groups]


def _fit_font(draw, text: str, fonts, max_width: float):
    """Premiere police proposee (de la plus grande a la plus petite) ou le texte tient."""
    chosen = fonts[-1]
    for size, font in fonts:
        chosen = (size, font)
        if draw.textlength(text, font=font) <= max_width:
            break
    return chosen


def _luminance(rgb) -> float:
    """Luminance relative WCAG d'une couleur sRGB (0 = noir, 1 = blanc)."""
    linear = []
    for value in rgb:
        channel = value / 255.0
        linear.append(
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


_NATIVE_LUMINANCE = [_luminance(rgb) for rgb in PALETTE_RGB]


def _contrast(first: float, second: float) -> float:
    """Rapport de contraste WCAG entre deux luminances."""
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


def _text_on(spec: ColorSpec) -> int:
    """Noir ou blanc : la couleur de texte qui ressort le mieux sur ``spec``.

    La luminance retenue est celle du melange (moyenne ponderee des couleurs
    natives), soit ce que l'oeil percoit d'un tramage fin. Sur les 6 couleurs
    natives, cela reproduit exactement la regle « noir uniquement sur jaune ».
    """
    luminance = sum(weight * _NATIVE_LUMINANCE[index] for index, weight in spec.weights)
    return (
        BLACK_INDEX
        if _contrast(luminance, _NATIVE_LUMINANCE[BLACK_INDEX])
        >= _contrast(luminance, _NATIVE_LUMINANCE[WHITE_INDEX])
        else WHITE_INDEX
    )


def _detail_lines(draw, event, max_width: float):
    """Lignes de detail d'un evenement : le lieu puis la description, en entier.

    Le texte est replie sur la largeur de la colonne mais jamais tronque : il
    occupe autant de lignes que necessaire. La hauteur du bloc s'adapte d'elle
    meme (voir ``generate_image``).
    """
    lines = []
    for key in ("location", "description"):
        value = " ".join(str(event.get(key) or "").split())
        if value:
            lines.extend(_wrap(draw, value, FONT_DETAIL, max_width))
    return lines


def _time_range(event, tz: ZoneInfo, window) -> str:
    """En-tete d'un bloc horaire : ``09:00 - 11:00``.

    Un evenement qui se termine un **autre jour** precise ce jour : son nom s'il
    tombe dans la fenetre affichee (``09:00 - jeudi 11:00``), sinon sa date
    (``09:00 - 15.12.2026 11:00``). Sans fin exploitable, seule l'heure de debut
    est affichee.
    """
    start = _event_datetime(event["start"], tz)
    end = event.get("end")
    if end is None:
        return start.strftime("%H:%M")

    end = _event_datetime(end, tz)
    if end <= start:
        return start.strftime("%H:%M")

    if end.date() == start.date():
        return f"{start:%H:%M} - {end:%H:%M}"

    day_label = FR_DAYS[end.weekday()] if end.date() in window else end.strftime("%d.%m.%Y")
    return f"{start:%H:%M} - {day_label} {end:%H:%M}"


def _column_edges(count: int, width: int, first_scale: float = DEFAULT_FIRST_COLUMN_SCALE):
    """Bords x de chaque colonne (``count + 1`` valeurs, de 0 a ``width``).

    La premiere colonne (aujourd'hui) est ``first_scale`` fois plus large que les
    suivantes ; les autres se partagent l'espace restant.
    """
    step = width / (count - 1 + first_scale)
    edges = [0.0]
    for index in range(count):
        edges.append(edges[-1] + step * (first_scale if index == 0 else 1.0))
    return edges


def _footer_legend(events, config):
    """Calendriers de la legende : ceux configures, sinon ceux vus dans les evenements."""
    if config.calendars:
        return [(calendar.name, calendar.color) for calendar in config.calendars]

    seen = {}
    for event in events:
        seen.setdefault(event["calendar"], event["color"])
    return list(seen.items())


def _footer_text_y(draw, top: float) -> float:
    """Ordonnee de depart pour centrer verticalement le texte du pied de page."""
    box = draw.textbbox((0, 0), "Ag", font=FONT_FOOTER)
    return top + FOOTER_HEIGHT / 2 - (box[1] + box[3]) / 2


def _draw_footer(draw, img, legend, generated_at) -> None:
    """Bande du bas : legende des calendriers (teinte + nom) et heure de generation.

    ``legend`` est une liste de couples ``(nom, couleur)`` ; ``generated_at`` la
    date-heure de generation, deja dans le fuseau local.
    """
    top = HEIGHT - FOOTER_HEIGHT
    draw.line((0, top, WIDTH, top), fill=BLACK_INDEX, width=LINE_WIDTH)

    text_y = _footer_text_y(draw, top)
    swatch_top = round(top + (FOOTER_HEIGHT - FOOTER_SWATCH_HEIGHT) / 2)

    # Heure de generation, alignee a droite.
    time_text = generated_at.strftime("%d/%m/%Y %H:%M")
    time_x = WIDTH - FOOTER_PADDING - draw.textlength(time_text, font=FONT_FOOTER)
    draw.text((time_x, text_y), time_text, font=FONT_FOOTER, fill=BLACK_INDEX)

    # Legende, de gauche a droite ; on s'arrete avant l'heure de generation.
    x = FOOTER_PADDING
    for name, color in legend:
        width = draw.textlength(name, font=FONT_FOOTER)
        entry_end = x + FOOTER_SWATCH_WIDTH + 6 + width
        if entry_end > time_x - FOOTER_GAP:
            break

        box = (x, swatch_top,
               x + FOOTER_SWATCH_WIDTH - 1, swatch_top + FOOTER_SWATCH_HEIGHT - 1)
        dither.fill(img, box, _spec(color))
        draw.rectangle(box, outline=BLACK_INDEX, width=1)
        draw.text((x + FOOTER_SWATCH_WIDTH + 6, text_y), name,
                  font=FONT_FOOTER, fill=BLACK_INDEX)
        x = entry_end + FOOTER_GAP


def generate_image(events, config: Config):
    """Genere l'image et l'enregistre dans ``config.image_path``."""
    tz = ZoneInfo(config.display_timezone)
    today = datetime.now(tz).date()
    days = [today + timedelta(days=i) for i in range(config.days_ahead)]
    # Jours affiches (pour nommer le jour de fin d'un evenement a cheval).
    window = set(days)

    # Dessin direct en mode palette ("P") : le texte reste net et l'image sert
    # de source unique au PNG de visualisation et au binaire .s6.
    img = Image.new("P", (WIDTH, HEIGHT), WHITE_INDEX)
    img.putpalette(palette_flat())
    draw = ImageDraw.Draw(img)

    # Pas de marge ni de cadre dessine : les bords de l'ecran e-ink suffisent.
    # La colonne du jour (la premiere) est plus large (FIRST_COLUMN_SCALE).
    edges = _column_edges(len(days), WIDTH, config.first_column_scale)

    month_bottom = MONTH_HEIGHT
    events_top = month_bottom + DAY_HEADER_HEIGHT
    # Le pied de page occupe le bas de l'image : les colonnes s'arretent au-dessus.
    footer_top = HEIGHT - FOOTER_HEIGHT

    # En-tete du tableau : le mois ecrit sur toute la largeur des colonnes qu'il couvre.
    # Il occupe le haut de l'image : il n'y a plus de bande de titre.
    month_groups = _month_groups(days)
    for first, last, year, month in month_groups:
        left = edges[first]
        right = edges[last + 1]
        label = f"{FR_MONTHS[month - 1]} {year}"
        size, font = _fit_font(draw, label, MONTH_FONTS, right - left - 2 * MONTH_PADDING)
        w = draw.textlength(label, font=font)
        draw.text(
            ((left + right - w) / 2, (MONTH_HEIGHT - size) / 2 - 3),
            label,
            font=font,
            fill=BLACK_INDEX,
        )
    draw.line((0, month_bottom, WIDTH, month_bottom), fill=BLACK_INDEX, width=LINE_WIDTH)

    # Regroupement par jour
    by_day = {day: [] for day in days}
    for event in events:
        day = _event_datetime(event["start"], tz).date()
        if day in by_day:
            by_day[day].append(event)
    for day in by_day:
        by_day[day].sort(key=lambda e: (not e["all_day"], _event_datetime(e["start"], tz)))

    # Fond des colonnes : une couleur par jour (MONDAY..SUNDAY dans le .env),
    # posee du filet de l'en-tete des mois jusqu'au bas de l'ecran.
    column_specs = [_spec(color) for color in config.column_colors]
    table_top = month_bottom + 2

    for index, day in enumerate(days):
        dither.fill(
            img,
            (
                round(edges[index]),
                table_top,
                round(edges[index + 1]) - 1,
                footer_top - 1,
            ),
            column_specs[day.weekday()],
        )

    # Changement de mois : le trait remonte dans l'en-tete des mois
    month_break = {first for first, _, _, _ in month_groups if first > 0}

    # Separateurs entre les colonnes, sous l'en-tete des mois
    for i in range(1, len(days)):
        if i in month_break:
            continue
        x = edges[i]
        draw.line((x, month_bottom, x, footer_top), fill=BLACK_INDEX, width=LINE_WIDTH)

    for i in sorted(month_break):
        x = edges[i]
        draw.line((x, 0, x, footer_top), fill=BLACK_INDEX, width=LINE_WIDTH)

    # Contenu des colonnes
    for i, day in enumerate(days):
        x_left = edges[i]
        column_width = edges[i + 1] - x_left
        x_center = x_left + column_width / 2
        text_left = x_left + 12
        text_width = column_width - 24

        # Couleur lisible (noir ou blanc) sur le fond de la colonne du jour.
        header_color = _text_on(column_specs[day.weekday()])

        # Nom du jour, puis numero seul (le mois est dans l'en-tete du tableau)
        name = FR_DAYS[day.weekday()]
        w = draw.textlength(name, font=FONT_DAY)
        draw.text((x_center - w / 2, month_bottom + 12), name, font=FONT_DAY, fill=header_color)

        number = str(day.day)
        w = draw.textlength(number, font=FONT_DAY_NUM)
        draw.text((x_center - w / 2, month_bottom + 54), number, font=FONT_DAY_NUM, fill=header_color)

        draw.line((x_left, events_top - 8, edges[i + 1], events_top - 8),
                  fill=header_color, width=LINE_WIDTH)

        y = events_top
        for event in by_day[day]:
            spec = _spec(event["color"])
            text_color = _text_on(spec)

            if event["all_day"]:
                # Faute d'horaire, l'en-tete du bloc porte le libelle « toute la journee »
                header = ALL_DAY_HEADER
            else:
                header = _time_range(event, tz, window)

            # Bloc inverse : fond de la couleur du calendrier, texte lisible dessus.
            # Titre, lieu et description sont affiches en entier : la hauteur suit.
            lines = _wrap(draw, event["summary"], FONT_EVENT, text_width)
            detail = _detail_lines(draw, event, text_width)
            height = (2 * BLOCK_PADDING + LINE_TIME
                      + len(lines) * LINE_EVENT + len(detail) * LINE_DETAIL)
            if y + height > footer_top:
                logger.warning(
                    "Bloc trop haut pour rester dans la colonne, evenement ignore : %r",
                    event["summary"],
                )
                break

            box = (x_left + 6, y, edges[i + 1] - 6, y + height - 1)
            dither.fill(img, box, spec)
            if event["all_day"]:
                # Bordure noire : le bloc « toute la journee » se detache des blocs horaires
                draw.rectangle(box, outline=BLACK_INDEX, width=LINE_WIDTH)

            draw.text(
                (text_left, y + BLOCK_PADDING),
                header,
                font=FONT_BLOCK_TIME,
                fill=text_color,
            )
            line_y = y + BLOCK_PADDING + LINE_TIME
            for line in lines:
                draw.text((text_left, line_y), line, font=FONT_EVENT, fill=text_color)
                line_y += LINE_EVENT
            for line in detail:
                draw.text((text_left, line_y), line, font=FONT_DETAIL, fill=text_color)
                line_y += LINE_DETAIL

            y += height + BLOCK_GAP

    # Pied de page : legende des calendriers (teinte + nom) et heure de generation.
    _draw_footer(draw, img, _footer_legend(events, config), datetime.now(tz))

    directory = os.path.dirname(config.image_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    # PNG de visualisation : conversion vers les couleurs exactes de l'ecran.
    img.convert("RGB").save(config.image_path)

    # Binaire "proprietaire" pour l'ESP32 (4 bits par pixel, en-tete compris).
    # L'image paysage y est tournee vers le portrait natif de la dalle.
    size = write_s6(img, config.s6_path, config.s6_rotation)
    logger.info(
        "Images ecrites : %s et %s (%d octets)",
        config.image_path,
        config.s6_path,
        size,
    )

    return config.image_path, config.s6_path
