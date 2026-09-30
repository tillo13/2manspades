"""tools/cloud_run_crons.py: the Cloud Run job picks its task from the container arg, logs one
line, and exits 1 on a failure so the run shows failed and the error sweeper sees an ERROR."""
import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from tools import cloud_run_crons as job


class CloudRunCrons(unittest.TestCase):
    def run_job(self, *args):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = job.main(['cloud_run_crons.py', *args])
        return code, out.getvalue()

    def test_unknown_or_missing_task_is_refused(self):
        self.assertEqual(self.run_job()[0], 2)
        self.assertEqual(self.run_job('bogus')[0], 2)

    def test_each_task_runs_its_own_work(self):
        for task in job.TASKS:
            with self.subTest(task=task), patch.dict(job.TASKS, {task: lambda: {'played_now': 1}}):
                code, out = self.run_job(task)
                self.assertEqual(code, 0)
                line = json.loads(out)
                self.assertEqual((line['severity'], line['result']), ('INFO', {'played_now': 1}))

    def test_a_failure_logs_error_and_exits_1(self):
        def boom():
            raise RuntimeError('pool gone')
        with patch.dict(job.TASKS, {'otto': boom}):
            code, out = self.run_job('otto')
        self.assertEqual(code, 1)
        line = json.loads(out)
        self.assertEqual(line['severity'], 'ERROR')
        self.assertIn('otto failed: RuntimeError: pool gone', line['message'])


if __name__ == '__main__':
    unittest.main()
