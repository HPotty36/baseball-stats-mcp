"""Errors that are safe and useful to show to the model."""


class DataError(Exception):
    """An anticipated data problem (not found, ambiguous name, API down, bad CSV).

    The server turns these into MCP tool errors whose message the model can read
    and act on, so messages should say what to try next.
    """
