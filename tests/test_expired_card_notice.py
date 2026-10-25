from tarveri.services.verification_service import VerificationService


def test_expired_card_gets_alumni_notice():
    notice = VerificationService._expired_card_notice("2000-01-01")
    assert "Alumni / Academic Status Notice" in notice
    assert "TARUMT Alumni" in notice


def test_valid_card_gets_no_notice():
    assert VerificationService._expired_card_notice("2999-01-01") == ""
    assert VerificationService._expired_card_notice(None) == ""
