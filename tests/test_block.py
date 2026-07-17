"""
test_block.py
-------------
Unit tests for the Block class in app/blockchain/block.py
Run with: python -m pytest tests/test_block.py -v
"""

import hashlib
import unittest
from datetime import datetime

from app.blockchain.block import Block, ZERO_HASH, TIMESTAMP_FORMAT

VALID_HASH_A = "a" * 64
VALID_HASH_B = "b" * 64
FIXED_TIMESTAMP = datetime(2026, 1, 1, 0, 0, 0, 0)


class TestBlockConstruction(unittest.TestCase):

    def test_valid_block_creation(self):
        """A block with valid fields should construct without error."""
        block = Block(
            index=1,
            timestamp=FIXED_TIMESTAMP,
            certificate_hash=VALID_HASH_A,
            previous_hash=VALID_HASH_B,
        )
        self.assertEqual(block.index, 1)
        self.assertEqual(block.certificate_hash, VALID_HASH_A)
        self.assertEqual(block.previous_hash, VALID_HASH_B)
        self.assertEqual(len(block.current_hash), 64)

    def test_negative_index_rejected(self):
        with self.assertRaises(ValueError):
            Block(index=-1, timestamp=FIXED_TIMESTAMP,
                  certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)

    def test_non_integer_index_rejected(self):
        with self.assertRaises(ValueError):
            Block(index="1", timestamp=FIXED_TIMESTAMP,
                  certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)

    def test_non_datetime_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            Block(index=1, timestamp="2026-01-01",
                  certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)

    def test_short_hash_rejected(self):
        with self.assertRaises(ValueError):
            Block(index=1, timestamp=FIXED_TIMESTAMP,
                  certificate_hash="abc123", previous_hash=VALID_HASH_B)

    def test_non_hex_hash_rejected(self):
        not_hex = "z" * 64
        with self.assertRaises(ValueError):
            Block(index=1, timestamp=FIXED_TIMESTAMP,
                  certificate_hash=not_hex, previous_hash=VALID_HASH_B)

    def test_hash_case_normalized_to_lowercase(self):
        upper_hash = "A" * 64
        block = Block(index=1, timestamp=FIXED_TIMESTAMP,
                       certificate_hash=upper_hash, previous_hash=VALID_HASH_B)
        self.assertEqual(block.certificate_hash, "a" * 64)


class TestBlockHashComputation(unittest.TestCase):

    def test_compute_hash_matches_manual_sha256(self):
        """The hash formula must be EXACTLY reproducible outside the class,
        since schema.sql's genesis block was computed independently in Python
        during Phase 2 -- this test proves both computations agree."""
        block = Block(
            index=0,
            timestamp=FIXED_TIMESTAMP,
            certificate_hash=ZERO_HASH,
            previous_hash=ZERO_HASH,
        )
        timestamp_str = FIXED_TIMESTAMP.strftime(TIMESTAMP_FORMAT)
        expected_payload = f"0{timestamp_str}{ZERO_HASH}{ZERO_HASH}"
        expected_hash = hashlib.sha256(expected_payload.encode("utf-8")).hexdigest()
        self.assertEqual(block.current_hash, expected_hash)

    def test_matches_phase2_genesis_hash_exactly(self):
        """Regression test: this MUST equal the genesis current_hash we
        inserted into schema.sql in Phase 2, or the app will report the
        real genesis block as tampered on very first startup."""
        timestamp = datetime.strptime("2026-01-01 00:00:00.000000", TIMESTAMP_FORMAT)
        block = Block(
            index=0,
            timestamp=timestamp,
            certificate_hash=ZERO_HASH,
            previous_hash=ZERO_HASH,
        )
        self.assertEqual(
            block.current_hash,
            "0352a0f4aa338a25b3957d69ec7eb396b86800d9eafaf8a732af82d77f5aae04",
        )

    def test_is_hash_valid_true_for_untampered_block(self):
        block = Block(index=1, timestamp=FIXED_TIMESTAMP,
                       certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)
        self.assertTrue(block.is_hash_valid())

    def test_is_hash_valid_false_when_current_hash_tampered(self):
        """Simulate an attacker directly editing the current_hash column."""
        block = Block(index=1, timestamp=FIXED_TIMESTAMP,
                       certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)
        block.current_hash = "f" * 64  # tamper directly
        self.assertFalse(block.is_hash_valid())

    def test_is_hash_valid_false_when_certificate_hash_tampered(self):
        """Simulate an attacker changing which certificate this block
        protects (e.g. swapping in a different combined_hash).

        IMPORTANT: current_hash is a frozen snapshot computed once at
        construction time -- it does NOT auto-recompute when another
        field is mutated afterward. That is intentional and is exactly
        what makes tamper detection possible: is_hash_valid() compares
        the frozen current_hash against a FRESH compute_hash() call, and
        the two are expected to disagree once a field has been tampered
        with. (An earlier version of this test wrongly asserted that
        current_hash itself changes on mutation -- it doesn't, by design.)
        """
        block = Block(index=1, timestamp=FIXED_TIMESTAMP,
                       certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)
        original_hash = block.current_hash
        block.certificate_hash = VALID_HASH_B  # tamper: swap the protected cert

        # current_hash is frozen -- it must NOT silently follow the mutation.
        self.assertEqual(block.current_hash, original_hash)

        # But a fresh recomputation from the (now tampered) fields must
        # differ from the frozen stored hash -- this is the actual
        # tamper signal is_hash_valid() relies on.
        self.assertNotEqual(block.compute_hash(), original_hash)
        self.assertFalse(block.is_hash_valid())

    def test_different_timestamps_produce_different_hashes(self):
        t1 = datetime(2026, 1, 1)
        t2 = datetime(2026, 1, 2)
        b1 = Block(index=1, timestamp=t1, certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)
        b2 = Block(index=1, timestamp=t2, certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)
        self.assertNotEqual(b1.current_hash, b2.current_hash)


class TestBlockSerialization(unittest.TestCase):

    def test_to_dict_contains_all_fields(self):
        block = Block(index=1, timestamp=FIXED_TIMESTAMP,
                       certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)
        d = block.to_dict()
        self.assertEqual(d["index"], 1)
        self.assertEqual(d["certificate_hash"], VALID_HASH_A)
        self.assertEqual(d["previous_hash"], VALID_HASH_B)
        self.assertIn("current_hash", d)
        self.assertIn("timestamp", d)

    def test_equality_based_on_chain_relevant_fields(self):
        b1 = Block(index=1, timestamp=FIXED_TIMESTAMP,
                    certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)
        b2 = Block(index=1, timestamp=FIXED_TIMESTAMP,
                    certificate_hash=VALID_HASH_A, previous_hash=VALID_HASH_B)
        self.assertEqual(b1, b2)


if __name__ == "__main__":
    unittest.main()
