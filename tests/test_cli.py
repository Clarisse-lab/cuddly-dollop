import argparse
import unittest

from govdata.cli import _key_value, _merge_values


class CliParameterTests(unittest.TestCase):
    def test_parses_powershell_safe_string_parameter(self) -> None:
        self.assertEqual(_key_value("state=SP"), ("state", "SP"))

    def test_parses_json_scalar_values(self) -> None:
        self.assertEqual(_key_value("limit=20"), ("limit", 20))

    def test_individual_parameters_override_json_object(self) -> None:
        self.assertEqual(
            _merge_values({"state": "MG"}, [("state", "SP")]),
            {"state": "SP"},
        )

    def test_rejects_missing_key(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            _key_value("SP")


if __name__ == "__main__":
    unittest.main()
