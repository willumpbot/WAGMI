"""
Dual Wallet System — Conservative (A) and Aggressive (B) trading profiles.

Both wallets share the same analytical engine (data, strategies, ensemble)
but apply independent risk filters, leverage, and position management.
"""

from wallet.profile import WalletProfile, wallet_a_default, wallet_b_default
from wallet.context import WalletContext
from wallet.dispatcher import WalletDispatcher
from wallet.guardian import AccountGuardian

__all__ = [
    "WalletProfile",
    "wallet_a_default",
    "wallet_b_default",
    "WalletContext",
    "WalletDispatcher",
    "AccountGuardian",
]
