import unittest

from validator import validate_token


class ContractTest(unittest.TestCase):
    def test_rejects_legacy_wire_token(self):
        with self.assertRaises(ValueError):
            validate_token("legacy-wire-token")


if __name__ == "__main__":
    unittest.main()

