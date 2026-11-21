"""python -m unittest discover -s tools/tests

The analysis' last step (tools/tracker.py answers_table): what the outside sources' files gained goes into the answers
table through PHP's backfill (tools/source-answers.php backfill, app/sourceanswers.php). It never stops the analysis:
without PHP nothing is run, and a failing backfill is logged.
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('FOREVER_TRACKER_CONFIG', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config.sample.ini'))

import tracker  # noqa: E402


class AnswersTable(unittest.TestCase):
    def run_it(self, which='/usr/bin/php', result=None, error=None):
        said = []
        run = mock.Mock(return_value=result, side_effect=error)
        with mock.patch.object(tracker.shutil, 'which', return_value=which), mock.patch.object(tracker.subprocess, 'run', run), \
                mock.patch.object(tracker, 'log', said.append):
            tracker.answers_table()
        return run, said

    def test_runs_the_backfill_and_logs_its_last_line(self):
        run, said = self.run_it(result=subprocess.CompletedProcess([], 0, b'icyveins: 3 answer(s) written\n12 answer(s) written (wowhead 9, icyveins 3) in 0.4 s\n', b''))
        command = run.call_args[0][0]
        self.assertEqual(command[0], '/usr/bin/php')
        self.assertTrue(command[1].endswith(os.path.join('tools', 'source-answers.php')))
        self.assertEqual(command[2:], ['backfill'])
        self.assertEqual(said, ['answers table: 12 answer(s) written (wowhead 9, icyveins 3) in 0.4 s'])

    def test_a_failure_is_logged_not_raised(self):
        _, said = self.run_it(result=subprocess.CompletedProcess([], 1, b'', b"the tracker's database cannot be reached\n"))
        self.assertEqual(said, ["answers table: the tracker's database cannot be reached"])
        _, said = self.run_it(error=subprocess.TimeoutExpired('php', 3600))
        self.assertTrue(said[0].startswith('answers table not written'))

    def test_without_php_nothing_runs(self):
        run, said = self.run_it(which=None)
        run.assert_not_called()
        self.assertEqual(said, [])


if __name__ == '__main__':
    unittest.main()
