import asyncio
import unittest

from musix.historical_membership_store import (
    HistoricalMembershipStore,
    HistoricalMembershipStoreError,
)


class HistoricalMembershipStoreTests(unittest.TestCase):
    def test_unconfigured_store_never_falls_back_to_another_database(self) -> None:
        store = HistoricalMembershipStore(None)
        asyncio.run(store.start(None))
        with self.assertRaisesRegex(HistoricalMembershipStoreError, "unavailable"):
            asyncio.run(store.members("enao-legacy:item3"))


if __name__ == "__main__":
    unittest.main()
