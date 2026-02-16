"""SEPA field parsing for German banking transactions."""

import re


class SepaFieldParser:
    """Parse SEPA structured fields from German banking transaction strings.

    Patterns follow:
    - IBAN: ISO 13616
    - Creditor-ID: EU Regulation 260/2012
    - Field markers (EREF+, SVWZ+, etc.): German DK DFÜ-Abkommen
    """

    # --- Extraction patterns ---

    # Creditor-ID via CRED+ marker
    _CREDITOR_ID_CRED = re.compile(r"CRED\+([A-Z]{2}\d{2}[A-Z0-9]{3}[A-Z0-9]+)")
    # Creditor-ID via label (Glaeubiger-ID, Gläubiger-ID, or Creditor ID)
    _CREDITOR_ID_LABEL = re.compile(
        r"(?:Gl(?:ae|ä)ubiger-?ID|Creditor\s*ID):?\s*([A-Z]{2}\d{2}[A-Z0-9]{3}[A-Z0-9]+)", re.IGNORECASE
    )

    # IBAN extraction (ISO 13616) — handles 16-20 digit BBANs with optional spaces
    _IBAN_EXTRACT = re.compile(r"(?:IBAN:?\s*)?([A-Z]{2}\d{2})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{0,4})")

    # Mandate reference via MREF+ marker
    _MANDATE_MREF = re.compile(r"MREF\+\S+")
    # Mandate reference via label
    _MANDATE_LABEL = re.compile(r"Mandat(?:sreferenz)?:?\s*\S+", re.IGNORECASE)

    # --- Noise stripping patterns ---

    # Markers where content is a reference/ID (strip marker + content)
    _NOISE_MARKERS = re.compile(r"(?:EREF|KREF|MREF|CRED|DDAT|ABWA|ABWE)\+\S*")
    # SVWZ+ marker only (content after it is the semantic purpose text)
    _SVWZ_MARKER = re.compile(r"SVWZ\+")
    # SEPA transaction type prefixes (BASISLASTSCHRIFT before LASTSCHRIFT to avoid partial match)
    _SEPA_PREFIXES = re.compile(
        r"\b(?:SEPA[-\s]?BASISLASTSCHRIFT|SEPA[-\s]?LASTSCHRIFT|SEPA[-\s]?GUTSCHRIFT"
        r"|SEPA[-\s]?[ÜUE]BERWEISUNG|KARTENZAHLUNG|FOLGELASTSCHRIFT)\b",
        re.IGNORECASE,
    )
    # IBAN with optional label
    _IBAN_STRIP = re.compile(r"(?:IBAN:?\s*)?\b[A-Z]{2}\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{0,4}")
    # BIC with label prefix
    _BIC_STRIP = re.compile(r"\bBIC[+:]?\s*[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?")
    # Long reference numbers (6+ digits standalone)
    _LONG_REF = re.compile(r"\b\d{6,}\b")

    def extract_creditor_id(self, text: str) -> str | None:
        """Extract SEPA Creditor-ID (EU Regulation 260/2012).

        Looks for CRED+ marker or Glaeubiger-ID/Gläubiger-ID label.
        Format: 2-letter country + 2 check digits + 3-char business code + identifier.
        """
        if not text:
            return None
        match = self._CREDITOR_ID_CRED.search(text)
        if match:
            return match.group(1)
        match = self._CREDITOR_ID_LABEL.search(text)
        if match:
            return match.group(1)
        return None

    def extract_iban(self, text: str) -> str | None:
        """Extract IBAN (ISO 13616).

        Handles both spaced (DE89 3704 0044 ...) and unspaced formats.
        """
        if not text:
            return None
        match = self._IBAN_EXTRACT.search(text)
        if match:
            return "".join(g for g in match.groups() if g)
        return None

    def extract_iban_bank_prefix(self, text: str) -> str:
        """Extract first 8 characters of IBAN (country + check + bank code).

        Returns empty string if no IBAN found.
        """
        iban = self.extract_iban(text)
        if iban:
            return iban[:8]
        return ""

    def has_mandate_ref(self, text: str) -> bool:
        """Check for SEPA mandate reference (Mandatsreferenz).

        Looks for MREF+ marker or Mandatsreferenz/Mandat label.
        """
        if not text:
            return False
        return bool(self._MANDATE_MREF.search(text) or self._MANDATE_LABEL.search(text))

    def extract_fields(self, text: str) -> dict:
        """Extract all SEPA fields from transaction text.

        Returns:
            Dict with keys: has_creditor_id, creditor_id, has_iban,
            iban_bank_prefix, has_mandate_ref.
        """
        creditor_id = self.extract_creditor_id(text)
        iban = self.extract_iban(text)
        mandate = self.has_mandate_ref(text)
        return {
            "has_creditor_id": int(creditor_id is not None),
            "creditor_id": creditor_id or "",
            "has_iban": int(iban is not None),
            "iban_bank_prefix": iban[:8] if iban else "",
            "has_mandate_ref": int(mandate),
        }

    def strip_noise(self, text: str) -> str:
        """Remove SEPA markers, identifiers, and banking noise from text.

        Preserves semantic content (merchant names, purpose descriptions).
        SVWZ+ marker is stripped but its content (the purpose text) is preserved.
        """
        if not text:
            return ""
        result = text
        # Order matters: strip markers before their content gets fragmented
        result = self._NOISE_MARKERS.sub("", result)
        result = self._SVWZ_MARKER.sub("", result)
        result = self._SEPA_PREFIXES.sub("", result)
        result = self._IBAN_STRIP.sub("", result)
        result = self._BIC_STRIP.sub("", result)
        result = self._LONG_REF.sub("", result)
        # Normalize whitespace
        result = re.sub(r"\s+", " ", result).strip()
        return result
