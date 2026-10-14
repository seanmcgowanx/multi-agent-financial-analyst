"""Specialist agents. One file per specialist; each owner picks its model and tools.

SPECIALISTS maps the routing label to the class, used by Coordinator.route().
"""

from .earnings import EarningsAnalyst
from .market import MarketAnalyst

# Add news when its implementation becomes available.
SPECIALISTS = {"earnings": EarningsAnalyst, "market": MarketAnalyst}
