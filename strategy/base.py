# strategy/base.py
from abc import ABC, abstractmethod
from typing import Sequence

class Strategy(ABC):
    """Minimal interface all strategies share."""
    @abstractmethod
    def generate_signal(
        self,
        closes: Sequence[float],
        highs:  Sequence[float] | None = None,
        lows:   Sequence[float] | None = None,
        **kwargs
    ) -> str: ...
