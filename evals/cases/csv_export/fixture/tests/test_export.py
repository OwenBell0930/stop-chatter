import unittest

from exporter import export_rows


class ExportTest(unittest.TestCase):
    def test_default_csv(self):
        result = export_rows([{"name": "A", "value": "1"}])
        self.assertEqual(result.splitlines(), ["name,value", "A,1"])


if __name__ == "__main__":
    unittest.main()

