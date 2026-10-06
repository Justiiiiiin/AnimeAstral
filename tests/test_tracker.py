import unittest

import _env  # noqa: F401
from astral_monitor.tracker import WaveTracker


def feed(tracker, values, start=0.0, step=1.0):
    events, t = [], start
    for v in values:
        t += step
        events += tracker.update(v, 100 if v is not None else None, t)
    return events, t


class TrackerTests(unittest.TestCase):
    def test_misread_jump_is_ignored(self):
        tr = WaveTracker(3, 0)
        events, _ = feed(tr, [20, 21, 22, 23, 24, 25, 95, 95, 95, 25, 26])
        self.assertEqual(events, [])
        self.assertEqual(tr.run.max_wave, 26)
        self.assertEqual(tr.rejected, 3)

    def test_restart_needs_two_matching_reads(self):
        tr = WaveTracker(3, 0)
        events, t = feed(tr, list(range(1, 28)))
        events, t = feed(tr, [1, 1, 2], t)
        self.assertEqual([e[0] for e in events], ["run_end"])
        self.assertEqual(events[0][1]["max_wave"], 27)

    def test_single_low_misread_is_not_a_restart(self):
        tr = WaveTracker(3, 0)
        events, _ = feed(tr, [10, 11, 12, 1, 13, 14])
        self.assertEqual(events, [])
        self.assertEqual(tr.run.first_wave, 10)

    def test_small_drop_corrects_misread_instead_of_restart(self):
        # echter Fall 06.10.: eingefrorenes Bild beim Umschalten (F11), „25“ als „29“ gelesen, danach wieder 25
        tr = WaveTracker(3, 0)
        events, t = feed(tr, [20, 21, 22, 23, 24, 29, 29, 29, 29] + [None] * 6 + [25, 25, 26])
        self.assertEqual(events, [])
        self.assertEqual(tr.run.first_wave, 20)
        self.assertEqual(tr.run.max_wave, 26)

    def test_restart_from_low_wave_still_counts(self):
        tr = WaveTracker(3, 0)
        events, t = feed(tr, [1, 2, 3, 4, 5, 6, 7, 8, 9])
        events, _ = feed(tr, [2, 2, 3], t)                  # neuer Lauf, Beginn knapp verpasst
        self.assertEqual([e[0] for e in events], ["run_end"])
        self.assertEqual(events[0][1]["max_wave"], 9)

    def test_counter_vanishing_ends_the_run(self):
        tr = WaveTracker(3, 0)
        _, t = feed(tr, [5, 6, 7])
        events, _ = feed(tr, [None] * 10, t)
        self.assertEqual(events[0][0], "run_end")
        self.assertEqual(events[0][1]["result"], "abgebrochen")

    def test_success_candidate_and_confirm(self):
        tr = WaveTracker(1, 0)
        events, t = feed(tr, [97, 98, 99])
        self.assertEqual([e[0] for e in events], ["candidate"])
        info = tr.confirm(t)
        self.assertEqual(info["max_wave"], 99)

    def test_unseen_start_gives_observation_data(self):
        tr = WaveTracker(3, 0)
        _, t = feed(tr, [12, 13, 14])
        events, _ = feed(tr, [None] * 9, t)
        info = events[0][1]
        self.assertIsNone(info["duration"])
        self.assertEqual(info["first_wave"], 12)
        self.assertGreater(info["observed"], 0)


if __name__ == "__main__":
    unittest.main()
