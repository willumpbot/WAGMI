"""
Lightweight web dashboard for the NunuIRL trading bot.

No Flask/Django dependency -- uses Python's built-in http.server.
Start via DashboardServer().start() or run server.py directly.
"""

from .server import DashboardServer, get_dashboard_server

__all__ = ["DashboardServer", "get_dashboard_server"]
