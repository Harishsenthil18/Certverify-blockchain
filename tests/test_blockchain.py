"""
test_blockchain.py
-------------------
Unit tests for the Blockchain class in app/blockchain/chain.py
Run with: python -m pytest tests/test_blockchain.py -v
"""

import unittest
from datetime import datetime

from app.blockchain.block import Block, ZERO_HASH  # noqa: F401 (ZERO_HASH used directly below)
from app.blockchain.chain import (
    Blockchain,
    BlockchainError,
    DuplicateCertificateError,
)

CERT_HASH_1 = "1" * 64
CERT_HASH_2 = "2" * 64
CERT_HASH_3 = "3" * 64
FIXED_TIMESTAMP = datetime(2026, 1, 1)


class TestGenesisBlock(unittest.TestCase):

    def test_create_genesis_block(self):
        chain = Blockchain()
        genesis = chain.create_genesis_block(timestamp=FIXED_TIMESTAMP)
        self.assertEqual(genesis.index, 0)
        self.assertEqual(genesis.previous_hash, ZERO_HASH)
        self.assertEqual(genesis.certificate_hash, ZERO_HASH)
        self.assertEqual(len(chain), 1)

    def test_cannot_create_second_genesis_block(self):
        chain = Blockchain()
        chain.create_genesis_block(timestamp=FIXED_TIMESTAMP)
        with self.assertRaises(BlockchainError):
            chain.create_genesis_block(timestamp=FIXED_TIMESTAMP)

    def test_get_latest_block_on_empty_chain_raises(self):
        chain = Blockchain()
        with self.assertRaises(BlockchainError):
            chain.get_latest_block()


class TestAddBlock(unittest.TestCase):

    def setUp(self):
        self.chain = Blockchain()
        self.chain.create_genesis_block(timestamp=FIXED_TIMESTAMP)

    def test_add_single_block(self):
        block = self.chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)
        self.assertEqual(block.index, 1)
        self.assertEqual(block.previous_hash, self.chain.chain[0].current_hash)
        self.assertEqual(len(self.chain), 2)

    def test_add_multiple_blocks_links_correctly(self):
        b1 = self.chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)
        b2 = self.chain.add_block(CERT_HASH_2, timestamp=FIXED_TIMESTAMP)
        b3 = self.chain.add_block(CERT_HASH_3, timestamp=FIXED_TIMESTAMP)
        self.assertEqual(b2.previous_hash, b1.current_hash)
        self.assertEqual(b3.previous_hash, b2.current_hash)
        self.assertEqual([b.index for b in self.chain.chain], [0, 1, 2, 3])

    def test_cannot_add_block_without_genesis(self):
        empty_chain = Blockchain()
        with self.assertRaises(BlockchainError):
            empty_chain.add_block(CERT_HASH_1)

    def test_duplicate_certificate_hash_rejected(self):
        self.chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)
        with self.assertRaises(DuplicateCertificateError):
            self.chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)

    def test_find_block_by_certificate_hash(self):
        added = self.chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)
        found = self.chain.find_block_by_certificate_hash(CERT_HASH_1)
        self.assertEqual(found, added)

    def test_find_block_by_certificate_hash_not_found(self):
        self.chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)
        found = self.chain.find_block_by_certificate_hash(CERT_HASH_2)
        self.assertIsNone(found)

    def test_find_block_case_insensitive(self):
        self.chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)
        found = self.chain.find_block_by_certificate_hash(CERT_HASH_1.upper())
        self.assertIsNotNone(found)

    def test_cannot_add_block_with_reserved_zero_hash(self):
        """ZERO_HASH is reserved for the Genesis Block only. Passing it to
        add_block() must be rejected outright, rather than silently being
        treated as a 'duplicate' of the genesis block (which would produce
        a confusing, misleading error message for a real upstream bug)."""
        with self.assertRaises(BlockchainError):
            self.chain.add_block(ZERO_HASH)


class TestChainValidation(unittest.TestCase):

    def setUp(self):
        self.chain = Blockchain()
        self.chain.create_genesis_block(timestamp=FIXED_TIMESTAMP)
        self.chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)
        self.chain.add_block(CERT_HASH_2, timestamp=FIXED_TIMESTAMP)
        self.chain.add_block(CERT_HASH_3, timestamp=FIXED_TIMESTAMP)

    def test_valid_chain_passes(self):
        is_valid, reason = self.chain.is_chain_valid()
        self.assertTrue(is_valid)
        self.assertIsNone(reason)

    def test_empty_chain_is_invalid(self):
        empty_chain = Blockchain()
        is_valid, reason = empty_chain.is_chain_valid()
        self.assertFalse(is_valid)
        self.assertIsNotNone(reason)

    def test_tampering_certificate_hash_detected(self):
        """Simulates an attacker directly editing a block's certificate_hash
        in the database (e.g. to point a block at a forged certificate)."""
        self.chain.chain[2].certificate_hash = CERT_HASH_3  # tamper block index 2
        is_valid, reason = self.chain.is_chain_valid()
        self.assertFalse(is_valid)
        self.assertIn("Block 2", reason)

    def test_tampering_current_hash_detected(self):
        """Simulates an attacker patching current_hash to hide a change."""
        self.chain.chain[1].current_hash = "f" * 64
        is_valid, reason = self.chain.is_chain_valid()
        self.assertFalse(is_valid)

    def test_tampering_breaks_downstream_link(self):
        """This is the KEY blockchain property: even if an attacker
        recomputes block N's own hash correctly after editing its data,
        block N+1's previous_hash pointer no longer matches, so the
        tampering is still detected -- just at a different point in the
        chain. This test proves the chain-linkage check (not just the
        self-consistency check) is doing real work."""
        tampered_block = self.chain.chain[1]
        tampered_block.certificate_hash = CERT_HASH_3
        # Attacker "fixes" the self-hash to hide direct evidence on block 1:
        tampered_block.current_hash = tampered_block.compute_hash()

        is_valid, reason = self.chain.is_chain_valid()
        self.assertFalse(is_valid)
        # Block 1 itself now looks self-consistent, but block 2's
        # previous_hash no longer matches block 1's new current_hash.
        self.assertIn("broken", reason.lower())

    def test_genesis_previous_hash_tampering_detected(self):
        self.chain.chain[0].previous_hash = "f" * 64
        is_valid, reason = self.chain.is_chain_valid()
        self.assertFalse(is_valid)

    def test_reordered_blocks_detected(self):
        """Swap two blocks -- indices become non-sequential."""
        self.chain.chain[1], self.chain.chain[2] = self.chain.chain[2], self.chain.chain[1]
        is_valid, reason = self.chain.is_chain_valid()
        self.assertFalse(is_valid)

    def test_duplicate_certificate_hash_across_chain_detected(self):
        """Simulates an attacker with direct DB access inserting a second
        block that protects the SAME certificate_hash as an earlier block.
        blockchain_blocks.certificate_hash has no DB-level UNIQUE constraint
        (only current_hash does), so this must be caught here, in
        is_chain_valid(), not assumed to be impossible."""
        # Force block index 3 to duplicate block index 1's certificate_hash,
        # then recompute its own current_hash so per-block self-consistency
        # still passes (isolating this test to the duplicate-hash check only).
        tampered = self.chain.chain[3]
        tampered.certificate_hash = self.chain.chain[1].certificate_hash
        tampered.current_hash = tampered.compute_hash()

        is_valid, reason = self.chain.is_chain_valid()
        self.assertFalse(is_valid)
        self.assertIn("already used", reason)

    def test_non_genesis_block_with_zero_hash_rejected(self):
        """A non-genesis block should never legitimately have
        certificate_hash == ZERO_HASH -- that value is reserved for the
        Genesis Block only."""
        tampered = self.chain.chain[2]
        tampered.certificate_hash = ZERO_HASH
        tampered.current_hash = tampered.compute_hash()

        is_valid, reason = self.chain.is_chain_valid()
        self.assertFalse(is_valid)
        self.assertIn("reserved zero-hash", reason)


class TestRebuildFromDatabase(unittest.TestCase):

    def _build_valid_block_list(self):
        """Helper: build a valid 3-block chain (genesis + 2) as plain
        Block objects, simulating what repository.load_all_blocks()
        would return."""
        chain = Blockchain()
        chain.create_genesis_block(timestamp=FIXED_TIMESTAMP)
        chain.add_block(CERT_HASH_1, timestamp=FIXED_TIMESTAMP)
        chain.add_block(CERT_HASH_2, timestamp=FIXED_TIMESTAMP)
        return chain.chain  # list[Block]

    def test_rebuild_valid_chain(self):
        blocks = self._build_valid_block_list()
        new_chain = Blockchain()
        is_valid, reason = new_chain.rebuild_chain_from_database(blocks)
        self.assertTrue(is_valid)
        self.assertIsNone(reason)
        self.assertEqual(len(new_chain), 3)

    def test_rebuild_empty_list_raises(self):
        new_chain = Blockchain()
        with self.assertRaises(BlockchainError):
            new_chain.rebuild_chain_from_database([])

    def test_rebuild_detects_tampered_data(self):
        """Simulates the real-world scenario: an attacker directly
        modified a row in blockchain_blocks via raw SQL, bypassing the
        Flask app entirely. On next server startup, rebuild must catch it."""
        blocks = self._build_valid_block_list()
        blocks[1].certificate_hash = CERT_HASH_3  # tamper after loading from "DB"

        new_chain = Blockchain()
        is_valid, reason = new_chain.rebuild_chain_from_database(blocks)
        self.assertFalse(is_valid)
        self.assertIsNotNone(reason)

    def test_rebuild_sorts_out_of_order_input(self):
        """repository.py already orders by block_index ASC, but this
        test proves rebuild_chain_from_database() doesn't blindly trust
        that ordering -- it re-sorts defensively."""
        blocks = self._build_valid_block_list()
        shuffled = [blocks[2], blocks[0], blocks[1]]

        new_chain = Blockchain()
        is_valid, _ = new_chain.rebuild_chain_from_database(shuffled)
        self.assertTrue(is_valid)
        self.assertEqual([b.index for b in new_chain.chain], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
