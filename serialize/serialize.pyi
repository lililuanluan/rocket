"""
Type stub file for the serialize module.

This module provides Rust-based high-performance parsing for Ripple protocol messages.

IMPORTANT: This is NOT a general protobuf parser!
This only parses Ripple's internal serialization format used in specific fields.
"""

from typing import Dict, Any, Union

def parse_bytes(data: bytes) -> Dict[str, Any]:
    """
    Parse Ripple's internal serialization format into a Python dictionary.
    
    ⚠️  IMPORTANT: This function is ONLY for Ripple's custom serialization format!
    
    Can parse:
    - TMValidation.validation field ✓
    - TMTransaction.transaction field ✓
    
    Cannot parse:
    - TMProposeSet (use protobuf fields directly) ✗
    - TMStatusChange (use protobuf fields directly) ✗
    - Complete packet data (use PacketEncoderDecoder.decode_packet first) ✗
    
    This function parses the internal serialization format used in Ripple protocol
    for signing and hashing. Only certain protobuf fields contain this format.
    
    Args:
        data: Raw bytes containing Ripple-serialized data. This should be:
              - TMValidation.validation field, OR
              - TMTransaction.transaction field
              
              NOT the complete packet.data or other protobuf messages!
    
    Returns:
        A dictionary mapping Ripple field names to their parsed values.
        
        For TMValidation.validation, common fields include:
        
        - "Flags" (int): Validation flags
        - "LedgerSequence" (int): Ledger sequence number
        - "SigningTime" (int): Signing timestamp
        - "LedgerHash" (str): Ledger hash as hex string
        - "SigningPubKey" (str): Signing public key as hex string
        - "Signature" (str): Signature data as hex string
        - "Cookie" (int): Cookie value
        
        Returns an empty dictionary if parsing fails or data is invalid.
    
    Raises:
        ValueError: If the data format is severely malformed (rare, usually returns
                   empty dict instead).
    
    Example:
        >>> import serialize
        >>> from rocket_controller.encoder_decoder import PacketEncoderDecoder
        >>> 
        >>> # Decode a packet first
        >>> message, msg_type = PacketEncoderDecoder.decode_packet(packet)
        >>> 
        >>> # If it's a validation message (type 41)
        >>> if msg_type == 41:
        ...     # Parse the validation data
        ...     parsed = serialize.parse_bytes(message.validation)
        ...     
        ...     # Access fields
        ...     if "LedgerSequence" in parsed:
        ...         ledger_seq = parsed["LedgerSequence"]
        ...         print(f"Ledger: {ledger_seq}")
        ...     
        ...     if "SigningPubKey" in parsed:
        ...         pub_key = parsed["SigningPubKey"]
        ...         print(f"Public Key: {pub_key}")
    
    Note:
        This function is implemented in Rust using PyO3 for high performance.
        Typical parsing time is < 0.1ms per message.
    
    See Also:
        - docs/HOW_TO_USE_PARSE_BYTES.md for detailed usage examples
        - Ripple serialization format: https://xrpl.org/serialization.html
    """
    ...

def serialize_bytes(data: Dict[str, Any]) -> bytes:
    """
    Serialize a Python dictionary into Ripple's internal serialization format.
    
    ⚠️  IMPORTANT: This is the reverse of parse_bytes!
    
    This function takes a dictionary with Ripple fields and converts it back
    to the binary serialization format used in the Ripple protocol.
    
    Args:
        data: A dictionary mapping Ripple field names to their values.
              
              Common fields for TMValidation.validation:
              
              Required fields (order matters):
              - "Flags" (int): Validation flags (UInt32)
              - "LedgerSequence" (int): Ledger sequence number (UInt32)
              - "SigningTime" (int): Signing timestamp (UInt32)
              - "Cookie" (int): Cookie value (UInt64)
              
              Optional hash fields:
              - "LedgerHash" (str): Ledger hash as hex string (Hash256, 64 hex chars)
              - "ConsensusHash" (str): Consensus hash as hex string (Hash256, 64 hex chars)
              - "ValidatedHash" (str): Validated hash as hex string (Hash256, 64 hex chars)
              
              Signature fields:
              - "SigningPubKey" (str): Signing public key as hex string (Blob)
              - "Signature" (str): Signature data as hex string (Blob)
    
    Returns:
        A bytes object containing the serialized data in Ripple's format.
        This can be used to replace TMValidation.validation field.
    
    Raises:
        ValueError: If:
                   - Input is not a dictionary
                   - Required fields are missing or have wrong types
                   - Field values are invalid (e.g., malformed hex strings)
                   - Hash256 fields are not exactly 32 bytes (64 hex chars)
    
    Example:
        >>> import serialize
        >>> 
        >>> # Parse an existing validation
        >>> parsed = serialize.parse_bytes(validation_data)
        >>> print(parsed)
        >>> # {'Flags': 2147483649, 'LedgerSequence': 5, ...}
        >>> 
        >>> # Modify a field
        >>> parsed['LedgerSequence'] = 4
        >>> 
        >>> # Serialize back to bytes
        >>> modified_bytes = serialize.serialize_bytes(parsed)
        >>> 
        >>> # Use modified bytes in packet
        >>> message.validation = modified_bytes
    
    Note:
        - Field order is important for cryptographic signatures
        - All hash fields must be 64-character hex strings (32 bytes)
        - The function automatically handles proper field ordering
        - Modifying signed fields will invalidate the signature!
    
    See Also:
        - parse_bytes(): The reverse operation
        - Ripple serialization format: https://xrpl.org/serialization.html
    """
    ...

__all__ = ["parse_bytes", "serialize_bytes"]
