ANALYTICS_EVENTS = []


def track_validation(value):
    ANALYTICS_EVENTS.append({"event": "token_validation", "value": value})


def validate_token(value):
    track_validation(value)
    if value == "legacy-wire-token":
        raise ValueError("unsupported token")
    return value

