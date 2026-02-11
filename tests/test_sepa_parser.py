"""Tests for SEPA field parsing."""

import pytest

from fafycat.ml.sepa_parser import SepaFieldParser


class TestSepaFieldParser:
    """Test SEPA field extraction and noise stripping."""

    def test_creditor_id_from_cred_prefix(self):
        """Test Creditor-ID extraction from CRED+ marker."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("CRED+DE98ZZZ09999999999 SVWZ+Spotify")
        assert fields["creditor_id"] == "DE98ZZZ09999999999"
        assert fields["has_creditor_id"] == 1

    def test_creditor_id_from_free_text(self):
        """Test Creditor-ID extraction from Glaeubiger-ID label."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("Glaeubiger-ID: DE02SAP00000000001")
        assert fields["creditor_id"] == "DE02SAP00000000001"

    def test_iban_with_spaces(self):
        """Test IBAN extraction with spaces between groups."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("IBAN: DE89 3704 0044 0532 0130 00")
        assert fields["has_iban"] == 1
        assert fields["iban_bank_prefix"] == "DE893704"

    def test_iban_without_spaces(self):
        """Test IBAN extraction without spaces."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("IBAN:DE89370400440532013000")
        assert fields["has_iban"] == 1
        assert fields["iban_bank_prefix"] == "DE893704"

    def test_non_german_iban(self):
        """Test IBAN extraction for non-German (Austrian) IBAN."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("IBAN: AT61 1904 3002 3457 3201")
        assert fields["has_iban"] == 1
        assert fields["iban_bank_prefix"] == "AT611904"

    def test_mandate_ref_long_form(self):
        """Test mandate reference detection via Mandatsreferenz label."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("Mandatsreferenz: ABC-123-DEF")
        assert fields["has_mandate_ref"] == 1

    def test_mandate_ref_short_form(self):
        """Test mandate reference detection via Mandat label."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("Mandat: M2024-001")
        assert fields["has_mandate_ref"] == 1

    def test_mandate_ref_mref_marker(self):
        """Test mandate reference detection via MREF+ marker."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("MREF+M-NETFLIX-001")
        assert fields["has_mandate_ref"] == 1

    def test_no_sepa_fields(self):
        """Test that non-SEPA text returns all zeros/empty."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("Kartenzahlung EDEKA Markt")
        assert fields["has_creditor_id"] == 0
        assert fields["creditor_id"] == ""
        assert fields["has_iban"] == 0
        assert fields["iban_bank_prefix"] == ""
        assert fields["has_mandate_ref"] == 0

    def test_empty_string(self):
        """Test that empty string returns all zeros/empty."""
        parser = SepaFieldParser()
        fields = parser.extract_fields("")
        assert fields["has_creditor_id"] == 0
        assert fields["creditor_id"] == ""
        assert fields["has_iban"] == 0
        assert fields["iban_bank_prefix"] == ""
        assert fields["has_mandate_ref"] == 0

    def test_full_sepa_lastschrift(self):
        """Test extraction from a realistic full SEPA Lastschrift string."""
        parser = SepaFieldParser()
        text = (
            "SEPA-BASISLASTSCHRIFT EREF+R2024123456 MREF+M-NETFLIX-001 "
            "CRED+DE98ZZZ09999999999 SVWZ+Netflix Premium Abo "
            "IBAN: DE89 3704 0044 0532 0130 00 BIC COBADEFFXXX"
        )
        fields = parser.extract_fields(text)
        assert fields["has_creditor_id"] == 1
        assert fields["creditor_id"] == "DE98ZZZ09999999999"
        assert fields["has_iban"] == 1
        assert fields["iban_bank_prefix"] == "DE893704"
        assert fields["has_mandate_ref"] == 1

    def test_strip_sepa_noise(self):
        """Test stripping of all SEPA noise, preserving semantic content."""
        parser = SepaFieldParser()
        text = (
            "EREF+R2024123456 KREF+2024012300001 SVWZ+Spotify Premium Monthly "
            "IBAN: DE89 3704 0044 0532 0130 00 BIC COBADEFFXXX"
        )
        result = parser.strip_noise(text)
        assert "EREF" not in result
        assert "KREF" not in result
        assert "SVWZ" not in result
        assert "DE89" not in result
        assert "COBADEFF" not in result
        assert result == "Spotify Premium Monthly"

    def test_strip_sepa_prefixes(self):
        """Test stripping of SEPA transaction type prefixes."""
        parser = SepaFieldParser()
        assert parser.strip_noise("SEPA-LASTSCHRIFT Netflix GmbH") == "Netflix GmbH"

    def test_strip_preserves_svwz_content(self):
        """Test that SVWZ+ marker is stripped but content is preserved."""
        parser = SepaFieldParser()
        assert parser.strip_noise("SVWZ+Spotify Premium Monthly") == "Spotify Premium Monthly"


if __name__ == "__main__":
    pytest.main([__file__])
