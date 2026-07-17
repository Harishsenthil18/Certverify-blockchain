"""
test_repository.py
-------------------
Unit tests for app/blockchain/repository.py

Uses unittest.mock to simulate a DB-API connection/cursor so these tests
run without a real MySQL server -- repository.py's job is to translate
between SQL rows and Block objects, and that logic is testable in
isolation from any actual database.

Run with: python -m pytest tests/test_repository.py -v
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock

from app.blockchain.block import Block, ZERO_HASH, TIMESTAMP_FORMAT
from app.blockchain.repository import BlockchainRepository, RepositoryError

CERT_HASH_1 = "1" * 64
FIXED_TIMESTAMP = datetime(2026, 1, 1, 0, 0, 0, 0)


def make_row(db_id, index, timestamp_str, cert_hash, prev_hash, curr_hash):
    """Build a dict-style row mimicking a DictCursor result."""
    return {
        "id": db_id,
        "block_index": index,
        "block_timestamp": timestamp_str,
        "certificate_hash": cert_hash,
        "previous_hash": prev_hash,
        "current_hash": curr_hash,
    }


class TestLoadAllBlocks(unittest.TestCase):

    def _make_repo_with_rows(self, rows):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = False

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        return BlockchainRepository(lambda: mock_conn)

    def test_load_all_blocks_converts_rows_to_blocks(self):
        genesis_block = Block(index=0, timestamp=FIXED_TIMESTAMP,
                               certificate_hash=ZERO_HASH, previous_hash=ZERO_HASH)
        row = make_row(1, 0, FIXED_TIMESTAMP.strftime(TIMESTAMP_FORMAT),
                        ZERO_HASH, ZERO_HASH, genesis_block.current_hash)

        repo = self._make_repo_with_rows([row])
        blocks = repo.load_all_blocks()

        self.assertEqual(len(blocks), 1)
        self.assertIsInstance(blocks[0], Block)
        self.assertEqual(blocks[0].db_id, 1)
        self.assertEqual(blocks[0].index, 0)
        self.assertTrue(blocks[0].is_hash_valid())

    def test_load_all_blocks_empty_table_returns_empty_list(self):
        repo = self._make_repo_with_rows([])
        blocks = repo.load_all_blocks()
        self.assertEqual(blocks, [])

    def test_load_all_blocks_malformed_row_raises_repository_error(self):
        """A row with a corrupted hash length (e.g. DB truncation) must
        surface as a clear RepositoryError, not a confusing raw ValueError
        or a silently-skipped block (which would make is_chain_valid()
        misreport WHICH block failed)."""
        bad_row = make_row(1, 0, FIXED_TIMESTAMP.strftime(TIMESTAMP_FORMAT),
                            "short_hash", ZERO_HASH, ZERO_HASH)
        repo = self._make_repo_with_rows([bad_row])
        with self.assertRaises(RepositoryError):
            repo.load_all_blocks()

    def test_load_all_blocks_db_error_wrapped_as_repository_error(self):
        mock_cursor = MagicMock()
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = False
        mock_cursor.execute.side_effect = Exception("connection lost")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        repo = BlockchainRepository(lambda: mock_conn)
        with self.assertRaises(RepositoryError):
            repo.load_all_blocks()

    def test_load_all_blocks_orders_by_index_ascending_query(self):
        """Confirm the SQL query itself requests ascending order -- this is
        the guarantee chain.rebuild_chain_from_database() partially relies
        on (even though it also defensively re-sorts)."""
        repo = self._make_repo_with_rows([])
        repo.load_all_blocks()
        # Inspect what was actually executed
        conn = repo._get_connection()
        cursor = conn.cursor.return_value
        executed_sql = cursor.execute.call_args[0][0]
        self.assertIn("ORDER BY block_index ASC", executed_sql)


class TestSaveBlock(unittest.TestCase):

    def test_save_block_assigns_db_id_from_lastrowid(self):
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 42

        repo = BlockchainRepository(lambda: None)
        block = Block(index=0, timestamp=FIXED_TIMESTAMP,
                       certificate_hash=ZERO_HASH, previous_hash=ZERO_HASH)

        returned_id = repo.save_block(block, mock_cursor)

        self.assertEqual(returned_id, 42)
        self.assertEqual(block.db_id, 42)
        mock_cursor.execute.assert_called_once()

    def test_save_block_rejects_already_persisted_block(self):
        """A block that already has a db_id must not be inserted again --
        this would create a duplicate row for the same logical block."""
        repo = BlockchainRepository(lambda: None)
        block = Block(index=0, timestamp=FIXED_TIMESTAMP,
                       certificate_hash=ZERO_HASH, previous_hash=ZERO_HASH,
                       db_id=99)
        mock_cursor = MagicMock()

        with self.assertRaises(RepositoryError):
            repo.save_block(block, mock_cursor)
        mock_cursor.execute.assert_not_called()

    def test_save_block_wraps_db_error(self):
        repo = BlockchainRepository(lambda: None)
        block = Block(index=0, timestamp=FIXED_TIMESTAMP,
                       certificate_hash=ZERO_HASH, previous_hash=ZERO_HASH)
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("duplicate key")

        with self.assertRaises(RepositoryError):
            repo.save_block(block, mock_cursor)


class TestGetLatestBlockRow(unittest.TestCase):

    def test_returns_none_when_table_empty(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = False
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        repo = BlockchainRepository(lambda: mock_conn)
        result = repo.get_latest_block_row()
        self.assertIsNone(result)

    def test_returns_block_when_row_exists(self):
        genesis_block = Block(index=0, timestamp=FIXED_TIMESTAMP,
                               certificate_hash=ZERO_HASH, previous_hash=ZERO_HASH)
        row = make_row(1, 0, FIXED_TIMESTAMP.strftime(TIMESTAMP_FORMAT),
                        ZERO_HASH, ZERO_HASH, genesis_block.current_hash)

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = row
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = False
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        repo = BlockchainRepository(lambda: mock_conn)
        result = repo.get_latest_block_row()
        self.assertIsInstance(result, Block)
        self.assertEqual(result.db_id, 1)


if __name__ == "__main__":
    unittest.main()
