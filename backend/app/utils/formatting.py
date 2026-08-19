"""Text and numeric formatting utilities."""


def format_bytes(n, precision=1, suffix_sep=' '):
    """Format a byte count as a human-readable string using 1024-based units.

    Args:
        n: Byte count. ``None`` or ``0`` renders as ``'0 B'`` (or ``'0B'`` when
           ``suffix_sep`` is empty).
        precision: Number of decimal places to show.
        suffix_sep: Separator between the numeric value and the unit.

    Returns:
        A human-readable string such as ``'1.5 KB'`` or ``'2.3GiB'``.

    Examples:
        >>> format_bytes(512)
        '512.0 B'
        >>> format_bytes(1536)
        '1.5 KB'
        >>> format_bytes(1073741824, suffix_sep='')
        '1.0GB'
    """
    if n is None:
        return ''
    n = float(n)
    if n == 0:
        return f'0{suffix_sep}B'
    for suffix in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f'{n:.{precision}f}{suffix_sep}{suffix}'
        n /= 1024
    return f'{n:.{precision}f}{suffix_sep}PB'


def format_size(num_bytes):
    """Bytes -> a short human string for prose ('512 MB', '1.5 GB', 'unknown').

    Differs from :func:`format_bytes` in two ways that matter where the result
    is read as a sentence rather than a table cell: an unknown value reads as
    ``'unknown'`` rather than an empty string, and precision adapts so figures
    land as '512 MB' instead of '512.0 MB' while small ones keep a decimal.

    Lives here rather than in a service because capacity_service and
    host_inventory_service both need it, and this module imports nothing — the
    duplicate that prompted this was written to dodge an import cycle that
    cannot exist (plan 75 §F1).
    """
    if num_bytes is None:
        return 'unknown'
    step = float(num_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if step < 1024 or unit == 'TB':
            return f'{step:.0f} {unit}' if step >= 10 or unit == 'B' else f'{step:.1f} {unit}'
        step /= 1024
    return f'{step:.1f} TB'
