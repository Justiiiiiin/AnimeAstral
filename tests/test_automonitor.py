"""Auto-start: monitoring follows the game state, your own actions take precedence."""
import unittest

import _env  # noqa: F401
from astral_monitor.automonitor import (GAME_PLACE, GONE, IN_GAME, START_DELAY, STOP_GRACE, TROUBLE, TROUBLE_STOP,
                                        AutoMonitor, phase_of)


class Sim:
    """Simulates the monitoring: carries out the actions like the main window."""

    def __init__(self, rejoin_on=True):
        self.am, self.now = AutoMonitor(), 0.0
        self.running = self.paused = False
        self.rejoin_on, self.log = rejoin_on, []

    def run(self, phase, seconds, gave_up=False):
        end = self.now + seconds
        while True:
            for act in self.am.tick(self.now, phase, self.running, self.paused, self.rejoin_on, gave_up):
                self.log.append(act)
                if act == "start":
                    self.running, self.paused = True, False
                elif act == "stop":
                    self.running = self.paused = False
                elif act in ("pause", "resume"):
                    self.paused = act == "pause"
            if self.now >= end:
                break
            self.now = min(end, self.now + 1.0)
        return self


class AutoMonitorTests(unittest.TestCase):
    def test_phase(self):
        self.assertEqual(phase_of("in_game", GAME_PLACE), IN_GAME)
        self.assertEqual(phase_of("in_game", 123), "elsewhere")
        self.assertEqual(phase_of("rejoining", GAME_PLACE), TROUBLE)
        self.assertEqual(phase_of("left", GAME_PLACE), GONE)

    def test_full_session(self):
        sim = Sim().run(GONE, 3).run(IN_GAME, START_DELAY - 1)
        self.assertFalse(sim.running)                                   # wait briefly until the window is there
        sim.run(IN_GAME, 2)
        self.assertTrue(sim.running)
        sim.run(TROUBLE, 30)
        self.assertTrue(sim.paused)                                     # disconnect: pause instead of stop
        sim.run(IN_GAME, 2)
        self.assertEqual((sim.running, sim.paused), (True, False))      # after rejoin continue in the same session
        sim.run(GONE, STOP_GRACE - 2)
        self.assertTrue(sim.running)                                    # server change/teleport: don't stop yet
        sim.run(IN_GAME, 3).run(GONE, STOP_GRACE + 2)
        self.assertFalse(sim.running)
        self.assertEqual(sim.log, ["start", "pause", "resume", "stop"])

    def test_user_stop_wins_until_next_join(self):
        sim = Sim().run(IN_GAME, START_DELAY + 1)
        sim.am.user_stopped()
        sim.running = False
        sim.run(IN_GAME, 60)
        self.assertFalse(sim.running)                                   # stays off while in the same game
        sim.run(GONE, 5).run(IN_GAME, START_DELAY + 1)
        self.assertTrue(sim.running)                                    # entered again: automatic again

    def test_manual_start_outside_game_is_kept(self):
        sim = Sim().run(GONE, 2)
        sim.running = True
        sim.run(GONE, 120)
        self.assertTrue(sim.running)

    def test_user_pause_not_undone(self):
        sim = Sim().run(IN_GAME, START_DELAY + 1)
        sim.am.user_paused()
        sim.paused = True
        sim.run(IN_GAME, 30)
        self.assertTrue(sim.paused)

    def test_trouble_without_rejoin_stops_later(self):
        sim = Sim(rejoin_on=False).run(IN_GAME, START_DELAY + 1).run(TROUBLE, TROUBLE_STOP - 5)
        self.assertEqual((sim.running, sim.paused), (True, True))
        sim.run(TROUBLE, 10)
        self.assertFalse(sim.running)

    def test_gave_up_stops(self):
        sim = Sim().run(IN_GAME, START_DELAY + 1).run(TROUBLE, 5).run(TROUBLE, 2, gave_up=True)
        self.assertFalse(sim.running)

    def test_failed_start_retries(self):
        am = AutoMonitor()
        self.assertEqual(am.tick(0, IN_GAME, False, False, True), [])
        self.assertEqual(am.tick(START_DELAY, IN_GAME, False, False, True), ["start"])
        am.start_failed(START_DELAY)
        self.assertEqual(am.tick(START_DELAY + 10, IN_GAME, False, False, True), [])
        self.assertEqual(am.tick(START_DELAY + 31, IN_GAME, False, False, True), ["start"])


if __name__ == "__main__":
    unittest.main()
