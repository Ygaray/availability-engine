"""Proves D-02/D-03/PKG-03: the example adapter satisfies the consumer's
`AvailabilityContractSuite` end to end against the real engine.

No test methods of its own — all 9 are inherited from the shared suite.
"""

from __future__ import annotations

from chatbot_engine.availability.testing.contract import AvailabilityContractSuite


class TestChatbotConformance(AvailabilityContractSuite):
    pass
