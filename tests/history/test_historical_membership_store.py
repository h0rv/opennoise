import unittest

from opennoise.history.historical_membership_store import (
    HistoricalMembershipStore,
    HistoricalMembershipStoreError,
)
from tests._test_client import run_async


class HistoricalMembershipStoreTests(unittest.TestCase):
    def test_unconfigured_store_never_falls_back_to_another_database(self) -> None:
        store = HistoricalMembershipStore(None)
        run_async(store.start(None))
        with self.assertRaisesRegex(HistoricalMembershipStoreError, "unavailable"):
            run_async(store.members("enao-legacy:item3"))


if __name__ == "__main__":
    unittest.main()
