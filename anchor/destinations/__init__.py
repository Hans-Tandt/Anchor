from .base import Destination, DestinationError
from .local import LocalDestination
from .factory import open_destination, test_destination

__all__ = [
    "Destination",
    "DestinationError",
    "LocalDestination",
    "open_destination",
    "test_destination",
]
