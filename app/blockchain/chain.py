"""
chain.py
--------
Defines the Blockchain class: an in-memory, ordered list of Block
objects representing the full certificate chain, plus the logic to
validate, extend, and search that chain.

Persistence (loading/saving blocks to MySQL) is deliberately NOT done
here -- that's repository.py's job. This class only knows about Block
objects and Python lists; it has zero database or Flask dependencies,
which makes it fully unit-testable in isolation (see tests/test_blockchain.py).
"""

import logging
from datetime import datetime

from app.blockchain.block import Block, ZERO_HASH

logger = logging.getLogger(__name__)


class BlockchainError(Exception):
    """Base exception for all blockchain-related errors."""
    pass


class InvalidChainError(BlockchainError):
    """Raised when the chain fails integrity validation."""
    pass


class DuplicateCertificateError(BlockchainError):
    """Raised when attempting to add a certificate_hash that is already
    present in the chain (defense-in-depth alongside the DB's UNIQUE
    constraint on certificates.combined_hash)."""
    pass


class Blockchain:
    """
    Manages an ordered, in-memory chain of Block objects.

    The chain always starts with a Genesis Block (index 0) whose
    previous_hash and certificate_hash are both ZERO_HASH.
    """

    def __init__(self):
        """
        Initialize an EMPTY blockchain (no genesis block yet).

        Callers should either:
          - call create_genesis_block() for a brand-new chain, or
          - call rebuild_chain_from_database(blocks) to restore an
            existing chain from persisted MySQL rows.

        We do NOT auto-create a genesis block in __init__, because that
        would make it too easy to accidentally create a SECOND, different
        genesis block in memory that doesn't match the one already
        seeded in the database (schema.sql already inserts the real
        genesis block once, at DB-init time).
        """
        self.chain = []  # list[Block], ordered by index ascending

    # -----------------------------------------------------------------
    # Genesis block
    # -----------------------------------------------------------------
    def create_genesis_block(self, timestamp=None):
        """
        Create and append the Genesis Block (index 0) to an empty chain.

        Args:
            timestamp (datetime | None): Timestamp to use. If None,
                uses datetime.now(). Tests should pass an explicit
                timestamp for reproducible hashes.

        Returns:
            Block: the created genesis block.

        Raises:
            BlockchainError: if the chain already has blocks (genesis
                must only ever be created once, on an empty chain).
        """
        if len(self.chain) > 0:
            raise BlockchainError(
                "Cannot create a genesis block: chain is not empty. "
                "A blockchain must have exactly one genesis block at index 0."
            )

        genesis = Block(
            index=0,
            timestamp=timestamp or datetime.now(),
            certificate_hash=ZERO_HASH,
            previous_hash=ZERO_HASH,
            # current_hash intentionally omitted -> Block computes it fresh
        )
        self.chain.append(genesis)
        logger.info("Genesis block created: %s", genesis)
        return genesis

    # -----------------------------------------------------------------
    # Reading the chain
    # -----------------------------------------------------------------
    def get_latest_block(self):
        """
        Return the most recently added block (highest index).

        Returns:
            Block

        Raises:
            BlockchainError: if the chain is empty (not yet initialized).
        """
        if not self.chain:
            raise BlockchainError(
                "Blockchain is empty -- no genesis block exists yet. "
                "Call create_genesis_block() or rebuild_chain_from_database() first."
            )
        return self.chain[-1]

    def find_block_by_certificate_hash(self, certificate_hash):
        """
        Search the chain for a block protecting a given certificate_hash.

        Used during verification: given a certificate's combined_hash
        (recomputed from the certificate's current DB row + PDF file),
        find the block that was created for it, so we can confirm the
        block itself hasn't been tampered with.

        Args:
            certificate_hash (str): 64-char SHA-256 hex digest to search for.

        Returns:
            Block | None: the matching block, or None if not found.
        """
        if not certificate_hash:
            return None
        certificate_hash = certificate_hash.lower()
        for block in self.chain:
            if block.certificate_hash == certificate_hash:
                return block
        return None

    # -----------------------------------------------------------------
    # Writing to the chain
    # -----------------------------------------------------------------
    def add_block(self, certificate_hash, timestamp=None):
        """
        Create a new block for a given certificate_hash and append it
        to the chain, linking it to the current latest block.

        Args:
            certificate_hash (str): 64-char SHA-256 combined_hash of the
                certificate this block will protect.
            timestamp (datetime | None): Defaults to datetime.now().

        Returns:
            Block: the newly created block (NOT yet saved to MySQL --
                the caller, typically the certificates upload route via
                repository.py, is responsible for persisting it inside
                the same DB transaction as the certificate row itself).

        Raises:
            BlockchainError: if the chain has no genesis block yet.
            DuplicateCertificateError: if this certificate_hash already
                exists somewhere in the chain.
        """
        if not self.chain:
            raise BlockchainError(
                "Cannot add a block: blockchain has no genesis block. "
                "Initialize the chain first."
            )

        # ZERO_HASH is a reserved sentinel meaning "no certificate" -- it
        # is only legitimate on the Genesis Block. Accepting it here would
        # let it silently match the genesis block's certificate_hash in
        # find_block_by_certificate_hash() below, incorrectly raising
        # DuplicateCertificateError and masking whatever real bug produced
        # an all-zero hash in the first place.
        if certificate_hash and certificate_hash.lower() == ZERO_HASH:
            raise BlockchainError(
                "Cannot add a block for the reserved zero-hash "
                "(certificate_hash consisting of 64 zeros). This value is "
                "reserved for the Genesis Block only -- it likely indicates "
                "an upstream bug that failed to compute a real hash."
            )

        # In-memory duplicate guard. This is a defense-in-depth check --
        # the ultimate source of truth is the DB's UNIQUE constraint on
        # certificates.combined_hash, but catching it here too means we
        # never even attempt a doomed DB insert, and we give a clearer,
        # blockchain-specific error message.
        existing = self.find_block_by_certificate_hash(certificate_hash)
        if existing is not None:
            raise DuplicateCertificateError(
                f"A block already exists for certificate_hash={certificate_hash!r} "
                f"(block index {existing.index}). Duplicate certificate uploads "
                f"are not allowed."
            )

        previous_block = self.get_latest_block()
        new_block = Block(
            index=previous_block.index + 1,
            timestamp=timestamp or datetime.now(),
            certificate_hash=certificate_hash,
            previous_hash=previous_block.current_hash,
            # current_hash omitted -> computed fresh from the above fields
        )
        self.chain.append(new_block)
        logger.info("Block added: %s", new_block)
        return new_block

    # -----------------------------------------------------------------
    # Validation -- THE core tamper-detection logic
    # -----------------------------------------------------------------
    def is_chain_valid(self):
        """
        Validate the ENTIRE chain for tampering. Two independent checks
        run for every block:

          1. Self-consistency: does block.current_hash actually match
             what compute_hash() produces from that block's own fields?
             (Catches: someone edited a block's stored certificate_hash,
             timestamp, or previous_hash directly in the DB.)

          2. Chain-linkage: does block[i].previous_hash equal
             block[i-1].current_hash? (Catches: someone deleted, reordered,
             or swapped a block, OR fixed up one block's hash but forgot
             to also update the NEXT block's previous_hash pointer -- which
             is exactly why tampering with block N breaks the visible
             validity of every block after N, not just block N itself.)

        Returns:
            tuple[bool, str | None]: (is_valid, reason). reason is None
                if valid, otherwise a human-readable message identifying
                which block failed and why -- useful for admin-facing
                diagnostics and for the "Tampered Certificate" result page.
        """
        if not self.chain:
            return False, "Blockchain is empty -- no genesis block found."

        # Rule: genesis block (index 0) must have previous_hash == ZERO_HASH.
        genesis = self.chain[0]
        if genesis.index != 0:
            return False, f"First block in chain has index {genesis.index}, expected 0 (genesis)."
        if genesis.previous_hash != ZERO_HASH:
            return False, "Genesis block's previous_hash is not the expected zero-hash."
        if not genesis.is_hash_valid():
            return False, "Genesis block's current_hash does not match its own recomputed hash (tampered)."

        # Walk the rest of the chain.
        # seen_certificate_hashes guards against a scenario the DB schema
        # alone doesn't prevent: blockchain_blocks.certificate_hash has NO
        # unique constraint (only current_hash does), so an attacker with
        # direct DB access could insert two structurally-valid blocks that
        # both claim to protect the SAME certificate. Per-block and
        # per-link checks alone would not catch that -- this set does.
        seen_certificate_hashes = {genesis.certificate_hash} if genesis.certificate_hash != ZERO_HASH else set()

        for i in range(1, len(self.chain)):
            current = self.chain[i]
            previous = self.chain[i - 1]

            # Check 1: self-consistency of this block's own hash.
            if not current.is_hash_valid():
                return False, (
                    f"Block {current.index} is tampered: its stored current_hash "
                    f"does not match a fresh SHA-256 computation of its own fields."
                )

            # Check 2: linkage to the previous block.
            if current.previous_hash != previous.current_hash:
                return False, (
                    f"Chain broken between block {previous.index} and block {current.index}: "
                    f"block {current.index}'s previous_hash does not match "
                    f"block {previous.index}'s current_hash."
                )

            # Check 3: indices must be sequential with no gaps or duplicates.
            if current.index != previous.index + 1:
                return False, (
                    f"Block indices are not sequential: block after index "
                    f"{previous.index} has index {current.index}, expected {previous.index + 1}."
                )

            # Check 4: no two blocks may protect the same certificate_hash.
            # (ZERO_HASH is exempt -- it's the reserved genesis marker, not
            # a real certificate, and only ever appears on block 0.)
            if current.certificate_hash != ZERO_HASH:
                if current.certificate_hash in seen_certificate_hashes:
                    return False, (
                        f"Block {current.index} protects a certificate_hash that is "
                        f"already used by an earlier block in the chain -- a certificate "
                        f"hash must appear in exactly one block."
                    )
                seen_certificate_hashes.add(current.certificate_hash)
            else:
                # A non-genesis block claiming the reserved zero-hash is
                # itself a form of tampering / corruption.
                return False, (
                    f"Block {current.index} has certificate_hash equal to the reserved "
                    f"zero-hash, which is only valid for the Genesis Block (index 0)."
                )

        return True, None

    # -----------------------------------------------------------------
    # Rebuilding from persisted storage
    # -----------------------------------------------------------------
    def rebuild_chain_from_database(self, blocks):
        """
        Replace this Blockchain's in-memory chain with a list of Block
        objects loaded from MySQL (via repository.load_all_blocks()),
        then validate the reconstructed chain.

        This is called once at Flask app startup so the in-memory chain
        always reflects what's actually in the database, and so any
        tampering that happened directly at the DB level (bypassing the
        app entirely) is caught immediately on the next server start.

        Args:
            blocks (list[Block]): blocks loaded from the DB, expected to
                already be sorted by block_index ascending (repository.py
                guarantees this ordering via `ORDER BY block_index ASC`).

        Returns:
            tuple[bool, str | None]: result of is_chain_valid() after
                rebuilding, so the caller (app factory) can decide whether
                to log a critical warning, refuse to start, or continue.

        Raises:
            BlockchainError: if blocks is empty (a properly initialized
                DB should always have at least the genesis block -- see
                schema.sql's genesis INSERT).
        """
        if not blocks:
            raise BlockchainError(
                "Cannot rebuild chain: no blocks were loaded from the database. "
                "Did schema.sql's genesis block insertion run successfully?"
            )

        # Defensive copy + re-sort by index, even though repository.py
        # already orders by block_index ASC -- never trust an external
        # boundary (the DB layer) to guarantee an in-memory invariant;
        # verify it here too.
        sorted_blocks = sorted(blocks, key=lambda b: b.index)

        self.chain = sorted_blocks
        is_valid, reason = self.is_chain_valid()

        if is_valid:
            logger.info(
                "Blockchain rebuilt from database: %d blocks loaded, chain is VALID.",
                len(self.chain),
            )
        else:
            # We do NOT raise here -- a tampered chain is a fact about the
            # world the app needs to report (e.g. via an admin alert /
            # verification results), not necessarily a reason to crash the
            # whole server. The caller decides what to do with this result.
            logger.critical(
                "Blockchain rebuilt from database but FAILED VALIDATION: %s", reason
            )

        return is_valid, reason

    def rollback_last_block(self, expected_certificate_hash):
        """
        Remove the most recently added block from the IN-MEMORY chain,
        but only if it matches expected_certificate_hash.

        WHY THIS EXISTS (Phase 4 integration need): a new block is added
        to the in-memory chain via add_block() BEFORE the corresponding
        database transaction (certificate row + blockchain_blocks row)
        is committed, so the block object is available to pass to the
        repository for persisting inside that same transaction. If the
        database transaction then fails and rolls back, the in-memory
        chain must be rolled back too -- otherwise the in-memory chain
        would contain a block that was never actually persisted, and the
        next add_block() call would compute a previous_hash pointing at
        a "ghost" block that doesn't exist in the database.

        The expected_certificate_hash check is a safety guard against
        accidentally popping the wrong block if this is ever called from
        the wrong place in a future code change.

        Args:
            expected_certificate_hash (str): the certificate_hash of the
                block we expect to be removing (defensive check).

        Returns:
            bool: True if a block was removed, False if the chain was
                empty, only had the genesis block, or the last block did
                not match expected_certificate_hash (nothing removed).
        """
        if len(self.chain) <= 1:
            # Never remove the genesis block.
            return False

        last_block = self.chain[-1]
        if last_block.certificate_hash.lower() != expected_certificate_hash.lower():
            logger.error(
                "rollback_last_block called with mismatched certificate_hash "
                "(expected last block to protect %s, but it protects %s) -- "
                "refusing to remove a block that wasn't the one just added.",
                expected_certificate_hash, last_block.certificate_hash,
            )
            return False

        removed = self.chain.pop()
        logger.warning("Rolled back in-memory block due to a failed database transaction: %s", removed)
        return True

    def __len__(self):
        return len(self.chain)

    def __repr__(self):
        return f"Blockchain(blocks={len(self.chain)})"
