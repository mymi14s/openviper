def sentiment_badge(score):
    """Convert a sentiment score (0.0 - 1.0) into a CSS class name."""
    try:
        score = float(score)
    except (ValueError, TypeError):
        return "badge-secondary"

    if score >= 0.8:
        return "badge-success"
    if score >= 0.5:
        return "badge-info"
    if score >= 0.3:
        return "badge-warning"
    return "badge-danger"


def sentiment_label(score):
    """Convert a sentiment score (0.0 - 1.0) into a human label."""
    try:
        score = float(score)
    except (ValueError, TypeError):
        return "Unknown"

    if score >= 0.8:
        return "Positive"
    if score >= 0.5:
        return "Neutral"
    if score >= 0.3:
        return "Flagged"
    return "Toxic"
