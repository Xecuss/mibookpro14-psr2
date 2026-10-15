import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

spec = importlib.util.spec_from_file_location('video', Path(__file__).resolve().parents[1] / 'scripts' / 'collect-video-power.py')
video = importlib.util.module_from_spec(spec)
spec.loader.exec_module(video)


class Clock:
    def __init__(self):
        self.now = 1000.0
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class Process:
    def __init__(self, code=0):
        self.code = code
    def poll(self):
        return self.code
    def wait(self, timeout):
        return self.code


class VideoPowerTests(unittest.TestCase):
    def exercise(self, alteration=None, interrupt_at=None, cue_code=0, launch_error=False):
        clock, rows = Clock(), []
        def sample(battery):
            i = len(rows)
            if i == interrupt_at:
                raise KeyboardInterrupt()
            row = {'time': 'test', 'monotonic': clock.now, 'boottime': clock.now,
                   'status': 'Discharging', 'power_uw': 4_000_000 + int(clock.now - 1000) * 10000,
                   'energy_uwh': 40_000_000 - (clock.now - 1000) * 1500,
                   'external_online': {'AC': 0}, 'brightness': {'panel': {'brightness': 102}}}
            if alteration:
                alteration(row, i)
            rows.append(row)
            return row
        def launch(player, tone, errors):
            if launch_error:
                raise OSError('missing player')
            return Process(cue_code), {'time': 'test', 'monotonic': clock.now}
        with tempfile.TemporaryDirectory() as tmp, patch.object(video, 'time', clock), patch.object(video.BASE, 'sample', sample), patch.object(video, 'launch_cue', launch):
            run = Path(tmp)
            result = video.collect_window(Path('BAT0'), run, 'fake-player', Path('tone.wav'))
            stored = json.loads((run / 'summary.json').read_text())
            timing = json.loads((run / 'timing.json').read_text())
            lines = (run / 'samples.jsonl').read_text().splitlines()
            self.assertEqual(result, stored)
            self.assertEqual(len(lines), len(rows))
            self.assertEqual(timing['sampling_finished']['monotonic'], clock.now)
            return result, rows

    def test_complete_window_timing_integral_and_energy(self):
        result, rows = self.exercise()
        self.assertTrue(result['complete'])
        self.assertTrue(result['valid_power_window'])
        self.assertNotIn('valid_idle_baseline', result)
        self.assertEqual(len(rows), 49)
        self.assertEqual([r['seconds_from_cue_request'] for r in rows], list(range(0, 241, 5)))
        self.assertEqual(result['elapsed_seconds'], 240)
        self.assertAlmostEqual(result['time_weighted_mean_w'], 5.2)
        self.assertAlmostEqual(result['energy_based_mean_w'], 5.4)

    def test_ac_brightness_and_suspend_are_rejected(self):
        for field in ('ac', 'brightness', 'suspend'):
            def alter(row, index):
                if index > 10:
                    if field == 'ac': row['external_online']['AC'] = 1
                    elif field == 'brightness': row['brightness']['panel']['brightness'] = 200
                    else: row['boottime'] += 20
            result, rows = self.exercise(alteration=alter)
            self.assertTrue(result['complete'])
            self.assertFalse(result['valid_power_window'], field)
            self.assertTrue(result['invalid_reasons'])

    def test_interrupted_samples_are_saved(self):
        result, rows = self.exercise(interrupt_at=4)
        self.assertEqual(len(rows), 4)
        self.assertFalse(result['complete'])
        self.assertFalse(result['valid_power_window'])
        self.assertIn('KeyboardInterrupt', result['failure'])

    def test_failed_sound_cancels_and_saves(self):
        for kwargs in ({'cue_code': 1}, {'launch_error': True}):
            result, rows = self.exercise(**kwargs)
            self.assertFalse(result['valid_power_window'])
            self.assertFalse(result['complete'])
            self.assertEqual(len(rows), 0)

    def test_wav_format_and_end_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            for count, expected in ((1, 12000), (2, 32640)):
                path = Path(tmp) / 'tone.wav'
                video.make_tone(path, count)
                with wave.open(str(path), 'rb') as wav:
                    self.assertEqual(wav.getnchannels(), 1)
                    self.assertEqual(wav.getsampwidth(), 2)
                    self.assertEqual(wav.getframerate(), 48000)
                    self.assertEqual(wav.getnframes(), expected)

    def test_sound_must_be_explicitly_confirmed(self):
        success = types.SimpleNamespace(returncode=0, stderr='')
        with patch.object(video.shutil, 'which', side_effect=lambda name: '/fake/' + name), patch.object(video.subprocess, 'run', return_value=success) as run, patch('builtins.input', return_value='n'):
            with self.assertRaises(RuntimeError):
                video.audition(Path('tone.wav'))
            self.assertEqual(run.call_count, 3)
        with patch.object(video.shutil, 'which', return_value='/fake/pw-play'), patch.object(video.subprocess, 'run', return_value=success), patch('builtins.input', return_value='y'):
            self.assertEqual(video.audition(Path('tone.wav')), '/fake/pw-play')

    def test_main_flow_saves_before_final_prompt_and_keeps_psr_outside_window(self):
        clock, samples, psr_times, sound_times = Clock(), [], [], []
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            supplies = project / 'supplies'
            battery = supplies / 'BAT0'
            battery.mkdir(parents=True)
            (battery / 'type').write_text('Battery')
            (battery / 'present').write_text('1')
            def sample(path):
                samples.append(clock.now)
                return {'monotonic': clock.now, 'boottime': clock.now, 'status': 'Discharging',
                        'power_uw': 5_000_000, 'energy_uwh': 40_000_000,
                        'external_online': {'AC': 0}, 'brightness': {}}
            def psr(path):
                psr_times.append(clock.now)
                path.write_text('PSR mode: PSR2 enabled\n')
                return True
            def launch(player, tone, errors):
                sound_times.append(clock.now)
                return Process(), {'time': 'test', 'monotonic': clock.now}
            answers = iter(['BVexample 00:00', '1080p fullscreen', '', ''])
            def user_input(prompt):
                if '是否正常播放' in prompt:
                    saved = list((project / 'results').glob('video-power-*/summary.json'))
                    self.assertEqual(len(saved), 1)
                    self.assertTrue(json.loads(saved[0].read_text())['complete'])
                return next(answers)
            with patch.object(video, 'time', clock), patch.object(video.BASE, 'sample', sample), patch.object(video.BASE, 'SUPPLIES', supplies), patch.object(video.BASE, 'PROJECT', project), patch.object(video.BASE, 'psr_snapshot', psr), patch.object(video, 'display_snapshot', return_value=True), patch.object(video, 'audition', return_value='fake-player'), patch.object(video, 'launch_cue', launch), patch.object(video.os, 'geteuid', return_value=1000), patch.object(video.os, 'isatty', return_value=True), patch.object(video.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)), patch('sys.argv', ['collect-video-power.py']), patch('builtins.input', side_effect=user_input):
                video.main()
            run = next((project / 'results').glob('video-power-*'))
            summary = json.loads((run / 'summary.json').read_text())
            self.assertTrue(summary['valid_power_window'])
            self.assertEqual(summary['samples'], 49)
            self.assertEqual(summary['time_weighted_mean_w'], 5)
            self.assertEqual(sound_times, [1045, 1285])
            self.assertEqual(psr_times, [1000, 1285])
            self.assertEqual(samples[1:], list(range(1045, 1286, 5)))

    def test_beep_only_never_samples_or_runs_sudo(self):
        with patch.object(video, 'audition', return_value='fake-player'), patch.object(video.os, 'geteuid', return_value=1000), patch.object(video.os, 'isatty', return_value=True), patch('sys.argv', ['collect-video-power.py', '--test-beep']), patch.object(video.BASE, 'sample') as sample, patch.object(video.subprocess, 'run') as run:
            video.main()
            sample.assert_not_called()
            run.assert_not_called()

    def test_expired_sudo_retries_after_window_without_overwriting_error(self):
        calls = []
        def snapshot(target):
            calls.append(target.name)
            target.write_text('')
            if len(calls) == 1:
                target.with_suffix('.error.txt').write_text('sudo: 需要密码\n')
                return False
            target.write_text('PSR mode: PSR2 enabled\n')
            return True
        with tempfile.TemporaryDirectory() as tmp, patch.object(video.BASE, 'psr_snapshot', side_effect=snapshot), patch.object(video.BASE, 'sample') as sample, patch.object(video.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as auth:
            result = video.after_psr_snapshot(Path(tmp))
            self.assertTrue(result['psr_after_read_ok'])
            self.assertEqual(calls, ['psr-after.txt', 'psr-after-auth-retry.txt'])
            self.assertEqual(len(result['psr_after_attempts']), 2)
            self.assertEqual((Path(tmp) / 'psr-after.error.txt').read_text(), 'sudo: 需要密码\n')
            sample.assert_not_called()
            auth.assert_called_once_with(['sudo', '-v'], check=False)

    def test_non_auth_psr_error_does_not_prompt_for_password(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(video.BASE, 'psr_snapshot', return_value=False), patch.object(video.subprocess, 'run') as auth:
            (Path(tmp) / 'psr-after.error.txt').write_text('debugfs entry unavailable\n')
            result = video.after_psr_snapshot(Path(tmp))
            self.assertFalse(result['psr_after_read_ok'])
            self.assertEqual(len(result['psr_after_attempts']), 1)
            auth.assert_not_called()


if __name__ == '__main__':
    unittest.main()
