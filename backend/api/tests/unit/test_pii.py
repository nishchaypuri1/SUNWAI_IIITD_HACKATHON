from app.core import pii


def test_aadhaar_with_spaces():
    r = pii.scrub("my aadhaar 1234 5678 9012")
    assert "1234 5678" not in r.text and r.text.endswith("9012") and "aadhaar_masked" in r.flags


def test_pan_removed():
    r = pii.scrub("PAN ABCDE1234F please")
    assert "ABCDE1234F" not in r.text and "pan_removed" in r.flags


def test_card_number():
    r = pii.scrub("card 4111 1111 1111 1111 was charged")
    assert "4111 1111" not in r.text and "XXXX1111" in r.text


def test_account_number():
    r = pii.scrub("account no 123456789012345")
    assert r.text == "account no XXXX2345"


def test_phone_and_email():
    r = pii.scrub("call 9876543210 or mail ravi.kumar@gmail.com")
    assert "9876543210" not in r.text and "ravi.kumar" not in r.text
    assert {"phone_masked", "email_masked"} <= set(r.flags)


def test_otp_and_password_removed():
    r = pii.scrub("OTP is 482913, password: hunter22")
    assert "482913" not in r.text and "hunter22" not in r.text and "sensitive_data_in_input" in r.flags


def test_references_kept():
    t = "UTR 629384710562, order 408-1234567-1234567, complaint number PP20261002118"
    assert pii.scrub(t).text == t


def test_unlabelled_12_digits_treated_as_aadhaar():
    assert pii.scrub("123456789012").text == "XXXX XXXX 9012"


def test_scrub_reference_keeps_value():
    assert pii.scrub_reference("629384710562") == "629384710562"


def test_idempotent():
    once = pii.scrub("aadhaar 1234 5678 9012 card 4111111111111111").text
    assert pii.scrub(once).text == once


def test_find_raw_pii():
    assert pii.find_raw_pii("my number 1234 5678 9012")
    assert not pii.find_raw_pii("XXXX XXXX 9012")


def test_trailing_punctuation_still_masked():
    r = pii.scrub("aadhaar 1234 5678 9012, card 4111 1111 1111 1111. account no 123456789012345, ok")
    assert "1234 5678" not in r.text and "4111 1111 1111" not in r.text and "123456789012345" not in r.text


def test_amounts_untouched():
    assert pii.scrub("Rs 1,49,999 and ₹2,349.50 and 1,499").text == "Rs 1,49,999 and ₹2,349.50 and 1,499"
