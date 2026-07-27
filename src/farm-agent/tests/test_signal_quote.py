"""
test_signal_quote.py -- Unit tests for SignalClient.is_valid_quote (SIG-04 / SC#3).

No HTTP, no DB required -- pure unit tests for the quote shape validator.
"""


# ---------------------------------------------------------------------------
# is_valid_quote tests (port of signal.js:71-80 isValidQuote)
# ---------------------------------------------------------------------------


def _is_valid_quote(q):
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415

    return SignalClient.is_valid_quote(q)


def test_valid_quote_with_int_timestamp():
    """Numeric int timestamp, non-empty author, any message."""
    assert _is_valid_quote({"timestamp": 1779562666675, "author": "+10000000001", "message": "hi"})


def test_valid_quote_with_string_timestamp():
    """Numeric string timestamp is accepted (signal-cli returns stringified ts)."""
    assert _is_valid_quote({"timestamp": "1779562666675", "author": "+10000000001", "message": "hi"})


def test_valid_quote_empty_message_allowed():
    """Empty string message is valid (signal.js:79 typeof q.message === 'string')."""
    assert _is_valid_quote({"timestamp": 123, "author": "+1", "message": ""})


def test_invalid_quote_missing_author():
    """Missing author key → invalid."""
    assert not _is_valid_quote({"timestamp": 123, "message": "x"})


def test_invalid_quote_empty_author():
    """Empty author string → invalid."""
    assert not _is_valid_quote({"timestamp": 123, "author": "", "message": "x"})


def test_invalid_quote_missing_timestamp():
    """Missing timestamp → invalid."""
    assert not _is_valid_quote({"author": "+1", "message": "x"})


def test_invalid_quote_non_numeric_timestamp():
    """Non-numeric string timestamp → invalid."""
    assert not _is_valid_quote({"timestamp": "abc", "author": "+1", "message": "x"})


def test_invalid_quote_not_a_dict():
    """Non-dict → invalid."""
    assert not _is_valid_quote("not a dict")
    assert not _is_valid_quote(None)
    assert not _is_valid_quote(123)


def test_invalid_quote_missing_message():
    """Missing message key → invalid (must be str type)."""
    assert not _is_valid_quote({"timestamp": 123, "author": "+1"})


def test_invalid_quote_author_not_string():
    """Non-string author → invalid."""
    assert not _is_valid_quote({"timestamp": 123, "author": 42, "message": "x"})


def test_quote_timestamp_coercion_int_str():
    """int(str(ts)) coercion: a string '123' yields 123, not 123.0."""
    # This tests the coercion used in the payload build (not is_valid_quote itself)
    ts = "1779562666675"
    coerced = int(str(ts))
    assert isinstance(coerced, int)
    assert coerced == 1779562666675
