"""Helpers de présentation française pour le module coaching."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

DAY_ABBR = ("Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim.")
DAY_NAMES = (
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
)
MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _as_local(value):
    if value is None:
        return None
    if isinstance(value, datetime) and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def fr_date(value, year=False):
    """« jeudi 24 octobre » (ou avec l'année)."""
    value = _as_local(value)
    if value is None:
        return "—"
    label = "%s %d %s" % (
        DAY_NAMES[value.weekday()], value.day, MONTHS[value.month - 1],
    )
    return "%s %d" % (label, value.year) if year else label


def fr_date_cap(value, year=False):
    text = fr_date(value, year=year)
    return text[:1].upper() + text[1:] if text else text


def fr_day_short(value):
    """« Jeu. 24 oct. »."""
    value = _as_local(value)
    if value is None:
        return "—"
    return "%s %d %s" % (
        DAY_ABBR[value.weekday()], value.day, MONTHS[value.month - 1][:4].rstrip("."),
    )


def fr_time(value):
    """« 14h30 »."""
    value = _as_local(value)
    if value is None:
        return "—"
    return "%02dh%02d" % (value.hour, value.minute)


def fr_day_time(value, with_date=True):
    if with_date:
        return "%s · %s" % (fr_day_short(value), fr_time(value))
    return fr_time(value)


def fr_date_time(value):
    value = _as_local(value)
    if value is None:
        return "—"
    return "%s · %s" % (fr_date_cap(value), fr_time(value))


def fr_date_year(value):
    value = _as_local(value)
    if value is None:
        return "—"
    return "%d %s %d" % (value.day, MONTHS[value.month - 1], value.year)


def relative_day(value, reference=None):
    """« aujourd'hui », « hier », « il y a 3 jours », « dans 6 jours »."""
    if value is None:
        return "—"
    value = _as_local(value)
    if isinstance(value, datetime):
        value = value.date()
    reference = reference or timezone.localdate()
    days = (value - reference).days
    if days == 0:
        return "aujourd'hui"
    if days == 1:
        return "demain"
    if days == -1:
        return "hier"
    if days > 0:
        return "dans %d jour%s" % (days, "s" if days > 1 else "")
    return "il y a %d jour%s" % (-days, "s" if -days > 1 else "")


def relative_since(value, reference=None):
    """« il y a 22 jours » ou « à l'instant »."""
    if value is None:
        return "Aucun échange"
    value = _as_local(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return relative_day(value, reference)
    reference = reference or timezone.now()
    delta = reference - value
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "à l'instant"
    minutes = seconds // 60
    if minutes < 60:
        return "il y a %d min" % minutes
    hours = minutes // 60
    if hours < 24:
        return "il y a %d h" % hours
    days = hours // 24
    return "il y a %d jour%s" % (days, "s" if days > 1 else "")


def minutes_label(minutes):
    minutes = int(minutes or 0)
    if minutes < 60:
        return "%d min" % minutes
    hours, rest = divmod(minutes, 60)
    if rest:
        return "%dh%02d" % (hours, rest)
    return "%dh" % hours


def hours_label(minutes):
    minutes = int(minutes or 0)
    if minutes % 60 == 0:
        return "%dh" % (minutes // 60)
    return "%dh%02d" % (minutes // 60, minutes % 60)


def percent(part, total):
    if not total:
        return 0
    return int(round(part * 100.0 / total))


def fr_decimal(value, digits=1):
    if value is None or value == "":
        return "—"
    if isinstance(value, str):
        try:
            value = Decimal(value.replace(",", "."))
        except Exception:
            return value
    quantized = Decimal(value).quantize(Decimal("1." + "0" * digits))
    return str(quantized).replace(".", ",")


def initials(name):
    parts = [part for part in (name or "").replace("-", " ").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "?"


def week_bounds(reference=None):
    reference = reference or timezone.localdate()
    if isinstance(reference, datetime):
        reference = reference.date()
    start = reference - timedelta(days=reference.weekday())
    return start, start + timedelta(days=6)


def week_number(reference=None):
    reference = reference or timezone.localdate()
    if isinstance(reference, datetime):
        reference = reference.date()
    return reference.isocalendar()[1]


def combine(day, clock):
    return timezone.make_aware(datetime.combine(day, clock))


def parse_clock(value):
    try:
        hours, minutes = (value or "").split(":")[:2]
        return time(int(hours), int(minutes))
    except (TypeError, ValueError):
        return time(9, 0)


def streak_days(dates, reference=None):
    """Série de jours consécutifs avec au moins une entrée."""
    reference = reference or timezone.localdate()
    unique = sorted({value for value in dates if value}, reverse=True)
    if not unique:
        return 0
    current = unique[0]
    if (reference - current).days > 1:
        return 0
    streak = 1
    for value in unique[1:]:
        if (current - value).days == 1:
            streak += 1
            current = value
        elif (current - value).days == 0:
            continue
        else:
            break
    return streak


def best_streak(dates):
    unique = sorted({value for value in dates if value})
    best = 0
    run = 0
    previous = None
    for value in unique:
        if previous is not None and (value - previous).days == 1:
            run += 1
        else:
            run = 1
        best = max(best, run)
        previous = value
    return best
