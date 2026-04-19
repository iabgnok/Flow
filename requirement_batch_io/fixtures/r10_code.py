"""Sample module for workflow code-edit scenarios."""

def add(a, b):
    return a + b


def BADNAME(x):
    return x * 2


def clamp(value, low, high):
    """Clamp value into [low, high] inclusive."""
    return max(low, min(high, value))
