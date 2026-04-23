"""PayU SHA-512 hash generation for payment APIs.

Implements hash formulas as specified in PayU's Integration Lab.
All hashes are computed with SHA-512 and returned as lowercase hex strings.
"""

import hashlib
from typing import Optional


def _sha512_hex(input_string: str) -> str:
    """Compute SHA-512 hash of input string and return lowercase hex."""
    return hashlib.sha512(input_string.encode("utf-8")).hexdigest().lower()


def generate_payment_hash(
    key: str,
    txnid: str,
    amount: str,
    productinfo: str,
    firstname: str,
    email: str,
    salt: str,
    udf1: str = "",
    udf2: str = "",
    udf3: str = "",
    udf4: str = "",
    udf5: str = "",
) -> str:
    """Generate hash for standard PayU Payment API.
    
    Formula: sha512(key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||salt)
    
    Args:
        key: Merchant key
        txnid: Transaction ID
        amount: Transaction amount
        productinfo: Product description
        firstname: Customer first name
        email: Customer email
        salt: Merchant salt (v1)
        udf1-udf5: User defined fields (optional, default empty)
        
    Returns:
        Lowercase hex SHA-512 hash (128 characters)
    """
    hash_string = (
        f"{key}|{txnid}|{amount}|{productinfo}|{firstname}|{email}"
        f"|{udf1}|{udf2}|{udf3}|{udf4}|{udf5}||||||{salt}"
    )
    return _sha512_hex(hash_string)


def generate_si_payment_hash(
    key: str,
    txnid: str,
    amount: str,
    productinfo: str,
    firstname: str,
    email: str,
    si_details: str,
    salt: str,
    udf1: str = "",
    udf2: str = "",
    udf3: str = "",
    udf4: str = "",
    udf5: str = "",
) -> str:
    """Generate hash for PayU Payment API with api_version=7 (Subscription/SI).
    
    Formula: sha512(key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5||||||si_details|salt)
    
    Args:
        key: Merchant key
        txnid: Transaction ID
        amount: Transaction amount
        productinfo: Product description
        firstname: Customer first name
        email: Customer email
        si_details: JSON string with subscription details
        salt: Merchant salt (v1)
        udf1-udf5: User defined fields (optional)
        
    Returns:
        Lowercase hex SHA-512 hash (128 characters)
    """
    hash_string = (
        f"{key}|{txnid}|{amount}|{productinfo}|{firstname}|{email}"
        f"|{udf1}|{udf2}|{udf3}|{udf4}|{udf5}||||||{si_details}|{salt}"
    )
    return _sha512_hex(hash_string)


def generate_postservice_hash(
    key: str,
    command: str,
    var1: str,
    salt: str,
) -> str:
    """Generate hash for PayU PostService APIs (verify, refund, etc).
    
    Formula: sha512(key|command|var1|salt)
    
    Args:
        key: Merchant key
        command: API command name (e.g., "verify_payment")
        var1: Command-specific variable (e.g., transaction ID)
        salt: Merchant salt (v1)
        
    Returns:
        Lowercase hex SHA-512 hash
    """
    hash_string = f"{key}|{command}|{var1}|{salt}"
    return _sha512_hex(hash_string)


def generate_response_verification_hash(
    key: str,
    txnid: str,
    amount: str,
    productinfo: str,
    firstname: str,
    email: str,
    status: str,
    salt: str,
    udf1: str = "",
    udf2: str = "",
    udf3: str = "",
    udf4: str = "",
    udf5: str = "",
) -> str:
    """Generate hash to verify PayU response callback.
    
    Formula: sha512(salt||||||udf5|udf4|udf3|udf2|udf1|email|firstname|productinfo|amount|txnid|key|status)
    
    Args:
        key: Merchant key
        txnid: Transaction ID
        amount: Transaction amount
        productinfo: Product description
        firstname: Customer first name
        email: Customer email
        status: Transaction status (success/failure)
        salt: Merchant salt (v1)
        udf1-udf5: User defined fields (must match original request)
        
    Returns:
        Lowercase hex SHA-512 hash
    """
    hash_string = (
        f"{salt}||||||{udf5}|{udf4}|{udf3}|{udf2}|{udf1}"
        f"|{email}|{firstname}|{productinfo}|{amount}|{txnid}|{key}|{status}"
    )
    return _sha512_hex(hash_string)


def get_hash_formula_string(
    flow_hash_formula: str,
    key: str = "YOUR_KEY",
    txnid: str = "TXN_123",
    amount: str = "100.00",
    productinfo: str = "Test Product",
    firstname: str = "John",
    email: str = "john@example.com",
    salt: str = "YOUR_SALT",
    si_details: Optional[str] = None,
    **udf_fields,
) -> str:
    """Build a hash string from a formula template for documentation/debugging.
    
    Replaces placeholders in the formula with actual values.
    Useful for showing users exactly what string was hashed.
    """
    result = flow_hash_formula
    replacements = {
        "key": key,
        "txnid": txnid,
        "amount": amount,
        "productinfo": productinfo,
        "firstname": firstname,
        "email": email,
        "salt": salt,
        "udf1": udf_fields.get("udf1", ""),
        "udf2": udf_fields.get("udf2", ""),
        "udf3": udf_fields.get("udf3", ""),
        "udf4": udf_fields.get("udf4", ""),
        "udf5": udf_fields.get("udf5", ""),
    }
    if si_details:
        replacements["si_details"] = si_details
    
    # Replace whole-word tokens in the formula
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    
    return result
