"""Specialist agents. One file per specialist; each owner picks its model and tools.

SPECIALISTS maps the routing label to the class, used by Coordinator.route().
"""

from .earnings import EarningsAnalyst
from .market import MarketAnalyst
from .news import NewsAnalyst

SPECIALISTS = {
    "earnings": EarningsAnalyst,
    "market": MarketAnalyst,
    "news": NewsAnalyst,
}
