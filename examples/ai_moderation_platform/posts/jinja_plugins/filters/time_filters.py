import datetime


def timeago(value):
    """Return a human-readable relative time string."""
    if not isinstance(value, datetime.datetime):
        return str(value)

    # Ensure value is offset-naive for comparison if utcnow returns naive
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)

    delta = datetime.datetime.utcnow() - value
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if delta.days < 30:
        return f"{delta.days}d ago"
    return value.strftime("%b %d, %Y")
