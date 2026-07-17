"""
block.py
--------
Defines the Block class: a single, immutable unit in our custom
certificate blockchain.

IMPORTANT (for viva/interview): This is a *simplified educational*
blockchain. There is no mining, no nonce, no Proof-of-Work, and no
network of nodes. The "blockchain" property we care about here is
tamper-evidence through hash-chaining, not decentralized consensus.
That is a deliberate, documented scope decision -- not an oversight.
"""

import hashlib
from datetime import datetime


# Fixed timestamp format used EVERYWHERE a Block's timestamp is turned
# into a string for hashing. Using one constant avoids a whole class of
# bugs where MySQL's datetime formatting differs slightly from Python's
# default str(datetime), which would make recomputed hashes never match
# stored hashes even though nothing was actually tampered with.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

# Convention (not a real hash): 64 zero-characters represent "no
# predecessor" (used only by the Genesis Block) or "no certificate"
# (also only the Genesis Block, which doesn't represent a real
# certificate). This mirrors how many textbook blockchain examples
# use an all-zero hash to mark the start of a chain.
ZERO_HASH = "0" * 64


class Block:
    """
    Represents one block in the certificate blockchain.

    Attributes:
        index (int): Position of this block in the chain. 0 = Genesis Block.
        timestamp (datetime): When this block was created.
        certificate_hash (str): SHA-256 hex digest representing the
            certificate this block protects (combined_hash from the
            certificates table). For the Genesis Block, this is ZERO_HASH.
        previous_hash (str): current_hash of the previous block in the
            chain. For the Genesis Block, this is ZERO_HASH.
        current_hash (str): SHA-256 hex digest of this block's own
            contents -- this is what "seals" the block and links it to
            the next one.
        db_id (int | None): The primary key of this block's row in the
            blockchain_blocks table, once persisted. None for a block
            that exists only in memory and has not been saved yet.
    """

    def __init__(self, index, timestamp, certificate_hash, previous_hash,
                 current_hash=None, db_id=None):
        """
        Create a Block.

        Args:
            index (int): Block position (0 = genesis).
            timestamp (datetime): Creation time of the block.
            certificate_hash (str): 64-char SHA-256 hex digest.
            previous_hash (str): 64-char SHA-256 hex digest of prior block.
            current_hash (str | None): If provided (e.g. when loading an
                existing block from the DB), it is used as-is. If None,
                it is computed fresh via compute_hash() -- this is the
                path taken when a NEW block is being created.
            db_id (int | None): DB primary key, if this block was loaded
                from or already saved to MySQL.

        Raises:
            ValueError: if any hash string is not exactly 64 hex characters,
                or if index is negative, or timestamp is not a datetime.
        """
        # --- Input validation: fail loudly and early rather than let a
        # malformed block silently corrupt the chain's integrity later. ---
        if not isinstance(index, int) or index < 0:
            raise ValueError(f"Block index must be a non-negative integer, got: {index!r}")

        if not isinstance(timestamp, datetime):
            raise ValueError(f"Block timestamp must be a datetime object, got: {type(timestamp)!r}")

        self._validate_hash_format(certificate_hash, "certificate_hash")
        self._validate_hash_format(previous_hash, "previous_hash")

        self.index = index
        self.timestamp = timestamp
        self.certificate_hash = certificate_hash.lower()
        self.previous_hash = previous_hash.lower()
        self.db_id = db_id

        # If a current_hash was supplied (block loaded from DB), trust it
        # as stored -- validation of whether it's CORRECT happens later,
        # in Blockchain.is_chain_valid(), not at construction time. This
        # separation lets us load a tampered block from the DB and still
        # detect/report the tampering, instead of crashing on load.
        if current_hash is not None:
            self._validate_hash_format(current_hash, "current_hash")
            self.current_hash = current_hash.lower()
        else:
            self.current_hash = self.compute_hash()

    @staticmethod
    def _validate_hash_format(value, field_name):
        """
        Ensure a value looks like a proper SHA-256 hex digest:
        exactly 64 characters, all valid hexadecimal.

        Raises:
            ValueError: if the value is not a proper 64-char hex string.
        """
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string, got: {type(value)!r}")
        if len(value) != 64:
            raise ValueError(
                f"{field_name} must be exactly 64 characters (SHA-256 hex digest), "
                f"got length {len(value)}: {value!r}"
            )
        try:
            int(value, 16)  # confirms every character is valid hex
        except ValueError:
            raise ValueError(f"{field_name} must be a valid hexadecimal string, got: {value!r}")

    def compute_hash(self):
        """
        Compute this block's current_hash from its own fields.

        Formula (fixed, must match exactly everywhere it's used --
        genesis seeding in schema.sql, this method, and any future
        re-verification code):

            SHA256(index + timestamp_str + certificate_hash + previous_hash)

        Returns:
            str: 64-character SHA-256 hex digest.
        """
        timestamp_str = self.timestamp.strftime(TIMESTAMP_FORMAT)
        payload = f"{self.index}{timestamp_str}{self.certificate_hash}{self.previous_hash}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def is_hash_valid(self):
        """
        Check whether this block's stored current_hash matches what its
        own fields would produce. If they differ, this specific block's
        data has been altered after the hash was originally computed.

        Returns:
            bool: True if current_hash == compute_hash(), else False.
        """
        return self.current_hash == self.compute_hash()

    def to_dict(self):
        """
        Serialize this block to a plain dict, e.g. for JSON API responses
        or for persisting to MySQL via the repository layer.
        """
        return {
            "db_id": self.db_id,
            "index": self.index,
            "timestamp": self.timestamp.strftime(TIMESTAMP_FORMAT),
            "certificate_hash": self.certificate_hash,
            "previous_hash": self.previous_hash,
            "current_hash": self.current_hash,
        }

    def __repr__(self):
        return (
            f"Block(index={self.index}, "
            f"certificate_hash={self.certificate_hash[:10]}..., "
            f"current_hash={self.current_hash[:10]}...)"
        )

    def __eq__(self, other):
        """Two blocks are equal if all their chain-relevant fields match."""
        if not isinstance(other, Block):
            return NotImplemented
        return (
            self.index == other.index
            and self.certificate_hash == other.certificate_hash
            and self.previous_hash == other.previous_hash
            and self.current_hash == other.current_hash
        )
