"""Slug generation utilities."""
import re


SLUG_PATTERN = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def slugify(text):
    """Convert a string to a URL-safe slug.

    Examples:
        'Hello World' -> 'hello-world'
        'My Queue Group!' -> 'my-queue-group'
        '  Multiple   spaces  ' -> 'multiple-spaces'
    """
    if not text:
        return ''
    text = str(text).lower().strip()
    # Replace any run of non-alphanumeric characters with a single hyphen
    text = re.sub(r'[^a-z0-9]+', '-', text)
    # Strip leading/trailing hyphens
    text = text.strip('-')
    return text


def unique_slug(base, exists, default='untitled', start=1):
    """Return a unique slug based on `base`.

    `exists` is a callable that takes a slug and returns True if it is already
    in use. If `base` is taken, appends `-1`, `-2`, etc. until a free slug is
    found.

    Args:
        base: The text or slug to start from.
        exists: Callable(slug: str) -> bool.
        default: Fallback string when `base` slugifies to something empty.
        start: First suffix to try. `saved_view_service` numbered its
            duplicates from 2 and kept a private copy of this loop for that one
            difference (plan 75 §G6); a parameter is cheaper than a second
            implementation, and changing its numbering would have renamed
            handles users already had.

    Returns:
        A unique slug string.
    """
    base_slug = slugify(base) or default
    if not exists(base_slug):
        return base_slug

    counter = start
    while True:
        candidate = f'{base_slug}-{counter}'
        if not exists(candidate):
            return candidate
        counter += 1


def is_valid_slug(value):
    """Return True if `value` is a non-empty, well-formed slug."""
    return bool(value and SLUG_PATTERN.match(value))


def validate_slug(value):
    """Validate a slug and return a normalized value or raise ValueError.

    This is stricter than `slugify`: it rejects empty values and values that
    contain characters outside `[a-z0-9-]`, rather than converting them.
    """
    slug = (value or '').strip().lower()
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    slug = re.sub(r'-{2,}', '-', slug).strip('-')
    if not slug:
        raise ValueError('Slug is required')
    if not SLUG_PATTERN.match(slug):
        raise ValueError('Slug can only contain lowercase letters, numbers, and hyphens')
    return slug


# Common "app/service" name pattern: lowercase alphanumeric with internal hyphens,
# must start/end with alphanumeric (a single alphanumeric char is allowed).
_APP_NAME_RE = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')


def validate_app_name(name, min_length=3, max_length=63,
                      allow_consecutive_hyphens=False, reserved=None):
    """Validate an application or service name.

    Args:
        name: The name to validate.
        min_length: Minimum allowed length.
        max_length: Maximum allowed length.
        allow_consecutive_hyphens: If False, reject names containing ``--``.
        reserved: Optional iterable of reserved names (case-insensitive).

    Returns:
        Tuple of ``(is_valid, error_message)``. ``error_message`` is ``None``
        when the name is valid.

    Examples:
        >>> validate_app_name('my-app')
        (True, None)
        >>> validate_app_name('My App')
        (False, 'Name must contain only lowercase letters, numbers, and hyphens...')
    """
    if not name:
        return False, 'Name is required'
    if len(name) < min_length:
        return False, f'Name must be at least {min_length} characters'
    if len(name) > max_length:
        return False, f'Name cannot exceed {max_length} characters'
    if not _APP_NAME_RE.match(name):
        return False, (
            'Name must contain only lowercase letters, numbers, and hyphens '
            '(cannot start or end with hyphen)'
        )
    if not allow_consecutive_hyphens and '--' in name:
        return False, 'Name cannot contain consecutive hyphens'
    if reserved and name.lower() in {r.lower() for r in reserved}:
        return False, f'Name "{name}" is reserved'
    return True, None
