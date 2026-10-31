"""Decide which country a posting is in, from location text and any structured hints.

Only explicit evidence counts: 'Remote' alone is unknown, not UK. Same-named cities abroad
('London, Ontario', 'Cambridge, MA') are excluded.
"""

import re

_UK_NAMES = re.compile(
    r"\b(united kingdom|great britain|britain|u\.?k\.?|gb|england|scotland|wales|"
    r"northern ireland)\b",
    re.IGNORECASE,
)
_UK_CITIES = re.compile(
    r"\b(london|manchester|edinburgh|glasgow|bristol|cambridge|oxford|leeds|birmingham|"
    r"belfast|cardiff|reading|sheffield|newcastle|nottingham|liverpool|brighton|"
    r"southampton|milton keynes|bath|guildford|york|aberdeen|dundee|coventry|leicester|"
    r"swansea|exeter|norwich)\b",
    re.IGNORECASE,
)
_US_STATE = (
    r"AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|"
    r"NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
_CA_PROVINCE = r"ON|BC|QC|NS|NB|MB|SK|AB|NL|PE"
_ABROAD = re.compile(
    rf"(,\s*({_US_STATE}|{_CA_PROVINCE})\b)|\b(united states|usa|u\.s\.|canada|ontario|"
    rf"massachusetts|alabama|new hampshire|connecticut|kentucky|new york|new south wales|"
    rf"tasmania|australia)\b",
    re.IGNORECASE,
)
_ISO_ALIASES = {"GB": {"GB", "UK", "GBR", "UNITED KINGDOM", "GREAT BRITAIN", "ENGLAND"}}


def _uk_location(location: str) -> bool:
    if _ABROAD.search(location):
        return False
    return bool(_UK_NAMES.search(location) or _UK_CITIES.search(location))


def in_country(locations: tuple[str, ...], hints: tuple[str, ...], country: str = "GB") -> bool:
    """True if any structured hint or any location string places the posting in `country`."""
    aliases = _ISO_ALIASES.get(country, {country})
    if any(h.strip().upper() in aliases for h in hints):
        return True
    if country != "GB":
        return False  # free-text matching is only implemented for the UK so far
    return any(_uk_location(loc) for loc in locations)
