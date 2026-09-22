from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger("sentinel.edge.alpr.validator")

# Recognized Indian States & Union Territories
INDIAN_STATES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN",
    "GA", "GJ", "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD",
    "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY", "RJ",
    "SK", "TN", "TR", "TS", "UK", "UP", "WB",
}

# Regex patterns for Indian license plate formats
# Standard: State (2) + District RTO (1-2) + Series (1-3) + Unique Number (4)
STANDARD_PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")

# Bharat Series (BH): Year (2) + "BH" + Unique Number (4) + Series (1-2)
BH_SERIES_REGEX = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")

# Vintage / Legacy / Commercial short formats (e.g., GJ011234, DL1C1234)
SHORT_PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,2}[0-9]{3,4}$")

# Optical Character Recognition (EasyOCR) Confusion Dictionaries
ALPHA_TO_DIGIT = {
    "O": "0", "D": "0", "Q": "0",
    "I": "1", "L": "1",
    "Z": "2",
    "E": "3",
    "S": "5",
    "G": "6", "b": "6",
    "T": "7",
    "B": "8",
    "q": "9", "g": "9",
}

DIGIT_TO_ALPHA = {
    "0": "O",
    "1": "I",
    "2": "Z",
    "3": "E",
    "4": "A",
    "5": "S",
    "6": "G",
    "8": "B",
}


class PlateValidator:
    """
    Gujarat Police High-Precision License Plate Validator & Positional Fuzzy Corrector.
    Enforces strict Indian Motor Vehicles Act formats and corrects optical confusion errors.
    """

    MIN_LENGTH = 8
    MAX_LENGTH = 11

    @classmethod
    def clean(cls, text: Optional[str]) -> str:
        """Strip spaces, punctuation, and non-alphanumeric characters."""
        if not text:
            return ""
        return re.sub(r"[^A-Z0-9]", "", text.upper())

    @classmethod
    def is_valid_strict(cls, plate: str) -> bool:
        """
        Check whether the plate string conforms strictly to official Indian standards.
        """
        if not plate or len(plate) < cls.MIN_LENGTH or len(plate) > cls.MAX_LENGTH:
            return False

        if BH_SERIES_REGEX.match(plate):
            return True

        if STANDARD_PLATE_REGEX.match(plate):
            m = re.match(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{1,3})([0-9]{4})$", plate)
            if m:
                state, rto, series, num = m.groups()
                if rto == "0":
                    return False
            state_code = plate[:2]
            return state_code in INDIAN_STATES

        return False

    @classmethod
    def fuzzy_correct(cls, raw: str) -> str:
        """
        Apply positional character correction based on Indian number plate grammar:
        [State Code: 2 Alpha] [RTO Code: 1-2 Digits] [Series: 1-3 Alpha] [Number: 4 Digits]
        """
        s = cls.clean(raw)
        if not s:
            return ""

        # Bharat Series format does not use standard state-code positional layout
        if BH_SERIES_REGEX.match(s):
            return s

        chars = list(s)
        n = len(chars)

        # -------------------------------------------------------------
        # 1. State Code Correction (First 2 Characters MUST be Letters)
        # -------------------------------------------------------------
        if n >= 2:
            # Special Gujarat state prefix optical corrections
            if chars[0] in ("6", "C", "Q", "O", "0") and chars[1] == "J":
                chars[0] = "G"
            elif chars[0] == "G" and chars[1] in ("1", "I", "L", "|", "T"):
                chars[1] = "J"
            elif chars[0] in DIGIT_TO_ALPHA:
                chars[0] = DIGIT_TO_ALPHA[chars[0]]
            if chars[1] in DIGIT_TO_ALPHA:
                chars[1] = DIGIT_TO_ALPHA[chars[1]]

        # -------------------------------------------------------------
        # 2. Positional Grammar by Plate Length
        # -------------------------------------------------------------
        if n == 10:
            # Standard: AA 00 AA 0000 (e.g. GJ01AB1234)
            # District RTO: chars[2, 3] -> DIGITS
            for i in (2, 3):
                if chars[i] in ALPHA_TO_DIGIT:
                    chars[i] = ALPHA_TO_DIGIT[chars[i]]

            # Series: chars[4, 5] -> LETTERS
            for i in (4, 5):
                if chars[i] in DIGIT_TO_ALPHA:
                    chars[i] = DIGIT_TO_ALPHA[chars[i]]

            # Registration Number: chars[6..9] -> DIGITS
            for i in range(6, 10):
                if chars[i] in ALPHA_TO_DIGIT:
                    chars[i] = ALPHA_TO_DIGIT[chars[i]]

        elif n == 9:
            # Format A: AA 00 A 0000 (e.g. GJ01A1234)
            # Format B: AA 0 AA 0000 (e.g. GJ1AB1234)
            # Registration Number: last 4 chars (5..8) -> ALWAYS DIGITS
            for i in range(5, 9):
                if chars[i] in ALPHA_TO_DIGIT:
                    chars[i] = ALPHA_TO_DIGIT[chars[i]]

            # If char 2 is '0', RTO MUST be 2 digits (Format A) because RTO 0 does not exist
            if chars[2] in ("0", "O"):
                chars[2] = "0"
                chars[3] = ALPHA_TO_DIGIT.get(chars[3], chars[3])
                chars[4] = DIGIT_TO_ALPHA.get(chars[4], chars[4])
            elif chars[3].isdigit() and not chars[4].isdigit():
                # Format A: pos 2, 3 digits, pos 4 letter
                chars[2] = ALPHA_TO_DIGIT.get(chars[2], chars[2])
                chars[3] = ALPHA_TO_DIGIT.get(chars[3], chars[3])
                chars[4] = DIGIT_TO_ALPHA.get(chars[4], chars[4])
            else:
                # Format B: pos 2 digit, pos 3, 4 letters
                chars[2] = ALPHA_TO_DIGIT.get(chars[2], chars[2])
                chars[3] = DIGIT_TO_ALPHA.get(chars[3], chars[3])
                chars[4] = DIGIT_TO_ALPHA.get(chars[4], chars[4])

        elif n == 11:
            # 3-Letter Series: AA 00 AAA 0000 (e.g. DL01ABC1234)
            for i in (2, 3):
                if chars[i] in ALPHA_TO_DIGIT:
                    chars[i] = ALPHA_TO_DIGIT[chars[i]]
            for i in (4, 5, 6):
                if chars[i] in DIGIT_TO_ALPHA:
                    chars[i] = DIGIT_TO_ALPHA[chars[i]]
            for i in range(7, 11):
                if chars[i] in ALPHA_TO_DIGIT:
                    chars[i] = ALPHA_TO_DIGIT[chars[i]]

        corrected = "".join(chars)
        return corrected

    @classmethod
    def validate_and_format(cls, raw: Optional[str]) -> Tuple[Optional[str], bool]:
        """
        Normalize, correct, and validate an OCR string.
        Returns: (corrected_plate, is_valid_boolean)
        """
        if not raw:
            return None, False

        cleaned = cls.clean(raw)
        if len(cleaned) < cls.MIN_LENGTH:
            return None, False

        corrected = cls.fuzzy_correct(cleaned)
        is_valid = cls.is_valid_strict(corrected)

        if not is_valid:
            # Fallback check for short / vintage format
            if SHORT_PLATE_REGEX.match(corrected) and corrected[:2] in INDIAN_STATES:
                is_valid = True

        return (corrected if is_valid else cleaned), is_valid

    @classmethod
    def normalize(cls, text: Optional[str]) -> Optional[str]:
        """
        Standard interface: returns normalized and corrected valid plate string,
        or None if it fails Indian plate validation.
        """
        plate, is_valid = cls.validate_and_format(text)
        if is_valid and plate:
            return plate
        # Allow clean alphanumeric string if it meets basic length bounds (min 6, max 12)
        clean = cls.clean(text)
        if 6 <= len(clean) <= 12 and clean[:2] in INDIAN_STATES:
            return clean
        return None

    @classmethod
    def validate(cls, text: Optional[str]) -> bool:
        """Boolean check for plate validity."""
        _, is_valid = cls.validate_and_format(text)
        return is_valid

    @classmethod
    def get_rto_jurisdiction(cls, plate: Optional[str]) -> Optional[dict[str, str]]:
        """
        Derive state and district law enforcement jurisdiction from validated Indian plate.
        """
        clean = cls.clean(plate)
        if len(clean) < 4:
            return None
        state_code = clean[:2]
        if state_code != "GJ":
            return {"state": state_code, "district": "Interstate Registration", "jurisdiction": f"{state_code} Police"}
        rto_code = clean[2:4]
        district = GUJARAT_RTO_DISTRICTS.get(rto_code, f"Gujarat RTO {rto_code}")
        return {
            "state": "Gujarat",
            "rto_code": rto_code,
            "district": district,
            "jurisdiction": f"{district} Police / Gujarat Police",
        }


GUJARAT_RTO_DISTRICTS = {
    "01": "Ahmedabad (West)",
    "02": "Mehsana",
    "03": "Rajkot",
    "04": "Bhavnagar",
    "05": "Surat",
    "06": "Vadodara",
    "07": "Kheda (Nadiad)",
    "08": "Banaskantha (Palanpur)",
    "09": "Sabarkantha (Himatnagar)",
    "10": "Jamnagar",
    "11": "Junagadh",
    "12": "Kutch (Bhuj)",
    "13": "Surendranagar",
    "14": "Amreli",
    "15": "Valsad",
    "16": "Bharuch",
    "17": "Panchmahal (Godhra)",
    "18": "Gandhinagar",
    "19": "Bardoli",
    "20": "Dahod",
    "21": "Navsari",
    "22": "Narmada (Rajpipla)",
    "23": "Anand",
    "24": "Patan",
    "25": "Porbandar",
    "26": "Vyara (Tapi)",
    "27": "Ahmedabad (East)",
    "28": "Surat (Rural)",
    "29": "Vadodara (Rural)",
    "30": "Aravalli (Modasa)",
    "31": "Mahisagar (Lunawada)",
    "32": "Gir Somnath (Veraval)",
    "33": "Botad",
    "34": "Chhota Udepur",
    "35": "Mahuva",
    "36": "Morbi",
    "37": "Khambhalia (Devbhumi Dwarka)",
    "38": "Bavla (Ahmedabad Rural)",
}
