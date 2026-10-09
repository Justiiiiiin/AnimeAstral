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

    def test_consistent_jump_is_accepted(self):
        # owner's log 09.10.2026: “Implausible reading 57 after 4 … 10x in a row” – the counter really was at 55+
        tr = WaveTracker(3, 0)
        feed(tr, [1, 2, 3, 4], step=1.0)
        events, _ = feed(tr, [55, 55, 56, 57, 57], start=10.0, step=0.5)
        self.assertEqual(events, [])
        self.assertEqual(tr.last_value, 57)               # accepted once it kept rising consistently
        self.assertEqual(tr.run.max_wave, 57)

    def test_consistent_jump_never_ends_the_raid(self):
        tr = WaveTracker(1, 0)
        feed(tr, [1, 2, 3, 4], step=1.0)
        events, _ = feed(tr, [98, 99, 99, 99, 99], start=10.0, step=0.5)   # misread near the end: no raid end
        self.assertEqual(events, [])
        self.assertEqual(tr.last_value, 4)

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
        # real case 06.10.: frozen frame while switching (F11), “25” read as “29”, then 25 again
        tr = WaveTracker(3, 0)
        events, t = feed(tr, [20, 21, 22, 23, 24, 29, 29, 29, 29] + [None] * 6 + [25, 25, 26])
        self.assertEqual(events, [])
        self.assertEqual(tr.run.first_wave, 20)
        self.assertEqual(tr.run.max_wave, 26)

    def test_cut_leading_digit_is_not_a_restart(self):
        # real case 07.10.: at wave 54 “4” was read twice (front digit hidden), then 55, 57 again
        tr = WaveTracker(3, 0)
        events, t = feed(tr, list(range(40, 54)))
        events, _ = feed(tr, [4, 4, 55, 56], t, step=0.5)
        self.assertEqual(events, [])
        self.assertEqual(tr.run.max_wave, 56)

    def test_restart_that_looks_cut_still_counts_when_it_stays(self):
        tr = WaveTracker(3, 0)
        events, t = feed(tr, list(range(40, 54)))
        events, _ = feed(tr, [3, 3, 3, 4, 4], t)           # real restart that happens to look like “53” without the 5
        self.assertEqual([e[0] for e in events], ["run_end"])
        self.assertEqual(events[0][1]["max_wave"], 53)

    def test_hold_while_macro_clicks(self):
        tr = WaveTracker(3, 0)
        _, t = feed(tr, [20, 21, 22])
        for _ in range(30):                                # macro opens menus: readings are not counted
            t += 0.5
            tr.hold()
        events, _ = feed(tr, [None, 30, 31], t)
        self.assertEqual(events, [])
        self.assertEqual(tr.run.max_wave, 31)

    def test_restart_from_low_wave_still_counts(self):
        tr = WaveTracker(3, 0)
        events, t = feed(tr, [1, 2, 3, 4, 5, 6, 7, 8, 9])
        events, _ = feed(tr, [2, 2, 3], t)                  # new run, start just missed
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
