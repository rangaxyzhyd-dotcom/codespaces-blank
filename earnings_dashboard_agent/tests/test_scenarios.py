import unittest

from analytics.scenarios import classify_scenario, load_scenario_config


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_scenario_config()

    def classify(self, pat, ebitda, guidance, margins=True):
        return classify_scenario(pat, ebitda, guidance, margins, self.config)

    def test_strong_beat_requires_pat_ebitda_and_raised_guidance(self):
        result = self.classify(10, 12, "raised")
        self.assertEqual(result["label"], "Strong beat")
        self.assertIn("not a return prediction", result["basis"])

    def test_moderate_beat_requires_stable_margins(self):
        self.assertEqual(self.classify(5, 2, "unchanged", True)["label"], "Moderate beat")
        self.assertEqual(self.classify(10, 2, "unchanged", True)["label"], "Moderate beat")
        self.assertEqual(self.classify(5, 2, "unchanged", False)["label"], "Mixed / insufficient evidence")

    def test_in_line_and_moderate_miss_boundaries(self):
        self.assertEqual(self.classify(3, -3, "unchanged")["label"], "In-line")
        self.assertEqual(self.classify(-3.01, None, "unchanged")["label"], "Moderate miss")

    def test_major_miss_requires_guidance_cut(self):
        self.assertEqual(self.classify(-10.1, -12, "cut")["label"], "Major miss")
        self.assertEqual(self.classify(-10, None, "unchanged")["label"], "Moderate miss")
        self.assertEqual(self.classify(-10.1, -12, "unchanged")["label"], "Mixed / insufficient evidence")

    def test_conflicting_pat_and_ebitda_signals_are_not_forced_into_a_scenario(self):
        self.assertEqual(self.classify(5, -5, "unchanged")["label"], "Mixed / insufficient evidence")

    def test_missing_results_do_not_create_a_recommendation(self):
        result = self.classify(None, None, None)
        self.assertEqual(result["label"], "Mixed / insufficient evidence")


if __name__ == "__main__":
    unittest.main()