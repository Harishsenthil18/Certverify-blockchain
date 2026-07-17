"""
repository.py
-------------
Bridges the pure-Python Block/Blockchain classes and the MySQL
`blockchain_blocks` table. This is the ONLY file in the blockchain
module allowed to know about database connections/SQL -- block.py and
chain.py stay framework- and database-agnostic on purpose, so they can
be unit tested with zero infrastructure (see tests/test_blockchain.py).

Uses PyMySQL-style DB-API connections (works the same with mysql-connector
or PyMySQL; Phase 4 will wire up the actual connection pool in extensions.py).
"""

import logging
from datetime import datetime

from app.blockchain.block import Block, TIMESTAMP_FORMAT

logger = logging.getLogger(__name__)


class RepositoryError(Exception):
    """Raised when a blockchain persistence operation fails."""
    pass


class BlockchainRepository:
    """
    Handles all reads/writes between blockchain_blocks (MySQL) and
    Block objects (Python).
    """

    def __init__(self, db_connection_provider):
        """
        Args:
            db_connection_provider (callable): a zero-argument function
                that returns a live DB-API connection (e.g. a bound
                method on a connection pool). Injecting this rather than
                importing a global connection makes the repository
                trivially mockable in unit tests.
        """
        self._get_connection = db_connection_provider

    def load_all_blocks(self):
        """
        Load every row from blockchain_blocks, ordered by block_index
        ascending, and convert each into a Block object.

        Returns:
            list[Block]: all persisted blocks, in chain order.

        Raises:
            RepositoryError: on any database error, wrapping the
                original exception for easier debugging without leaking
                raw DB-API exceptions into the blockchain/business logic.
        """
        query = """
            SELECT id, block_index, block_timestamp, certificate_hash,
                   previous_hash, current_hash
            FROM blockchain_blocks
            ORDER BY block_index ASC
        """
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
        except Exception as exc:
            logger.exception("Failed to load blocks from database")
            raise RepositoryError(f"Could not load blockchain blocks: {exc}") from exc

        blocks = []
        for row in rows:
            try:
                blocks.append(self._row_to_block(row))
            except ValueError as exc:
                # A malformed row (e.g. corrupted hash length) should not
                # silently vanish -- log it clearly and re-raise, because
                # loading a chain that's missing a block would make
                # is_chain_valid() report a false "chain broken" error at
                # the WRONG block, confusing debugging.
                logger.error("Malformed block row in database: %s (%s)", row, exc)
                raise RepositoryError(f"Malformed block row in database: {exc}") from exc

        logger.info("Loaded %d blocks from database.", len(blocks))
        return blocks

    def get_latest_block_row(self):
        """
        Fetch just the single highest-index block, for the common case
        of "what do I link a new block to" without loading the whole chain.

        Returns:
            Block | None: the latest block, or None if the table is empty
                (should not normally happen once genesis is seeded).
        """
        query = """
            SELECT id, block_index, block_timestamp, certificate_hash,
                   previous_hash, current_hash
            FROM blockchain_blocks
            ORDER BY block_index DESC
            LIMIT 1
        """
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query)
                row = cursor.fetchone()
        except Exception as exc:
            logger.exception("Failed to fetch latest block from database")
            raise RepositoryError(f"Could not fetch latest block: {exc}") from exc

        return self._row_to_block(row) if row else None

    def save_block(self, block, cursor):
        """
        Persist a single Block to blockchain_blocks.

        IMPORTANT: this method takes an existing `cursor` rather than
        opening its own connection, because in Phase 4 a new block MUST
        be inserted in the SAME transaction as its corresponding
        certificates row (all-or-nothing: either both are saved, or
        neither is -- we never want a block with no certificate, or a
        certificate with no block). The caller (certificates upload
        route) owns the transaction boundary (commit/rollback); this
        method only issues the INSERT.

        Args:
            block (Block): the block to persist. Must not already have
                a db_id (i.e. must be a brand-new, unsaved block).
            cursor: an open DB-API cursor, part of an active transaction.

        Returns:
            int: the auto-generated primary key (block.id) assigned by MySQL.

        Raises:
            RepositoryError: on any database error.
        """
        if block.db_id is not None:
            raise RepositoryError(
                f"Block at index {block.index} already has db_id={block.db_id} -- "
                f"refusing to insert a duplicate row for an already-persisted block."
            )

        query = """
            INSERT INTO blockchain_blocks
                (block_index, block_timestamp, certificate_hash, previous_hash, current_hash)
            VALUES (%s, %s, %s, %s, %s)
        """
        params = (
            block.index,
            block.timestamp.strftime(TIMESTAMP_FORMAT),
            block.certificate_hash,
            block.previous_hash,
            block.current_hash,
        )
        try:
            cursor.execute(query, params)
            block.db_id = cursor.lastrowid
        except Exception as exc:
            logger.exception("Failed to save block at index %d", block.index)
            raise RepositoryError(f"Could not save block {block.index}: {exc}") from exc

        return block.db_id

    @staticmethod
    def _row_to_block(row):
        """
        Convert one DB row (dict-style, as returned by a DictCursor) into
        a Block object.

        We explicitly re-parse the stored timestamp string using
        TIMESTAMP_FORMAT rather than trusting whatever datetime object
        the DB driver hands back -- some MySQL drivers return
        microsecond-naive datetimes for DATETIME(6) columns depending on
        driver/version, and if that happened silently here, every
        recomputed hash would mismatch the stored one and EVERY block
        would look "tampered" even though nothing was actually altered.
        This is exactly the failure mode flagged in Phase 2's
        COMMON_ERRORS.md (#9) -- we handle it here, once, in one place.

        Args:
            row (dict): a single row with keys id, block_index,
                block_timestamp, certificate_hash, previous_hash,
                current_hash.

        Returns:
            Block
        """
        timestamp_value = row["block_timestamp"]
        if isinstance(timestamp_value, datetime):
            # Re-serialize then re-parse through our canonical format
            # string, to strip out any driver-specific quirks (e.g.
            # missing microseconds) and guarantee exact reproducibility.
            timestamp_str = timestamp_value.strftime(TIMESTAMP_FORMAT)
        else:
            timestamp_str = str(timestamp_value)
        timestamp = datetime.strptime(timestamp_str, TIMESTAMP_FORMAT)

        return Block(
            index=row["block_index"],
            timestamp=timestamp,
            certificate_hash=row["certificate_hash"],
            previous_hash=row["previous_hash"],
            current_hash=row["current_hash"],   # trust-but-verify: passed in as-is,
                                                  # is_chain_valid() checks correctness later
            db_id=row["id"],
        )
