import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'apply_patches', Path(__file__).resolve().parents[1] / 'scripts/apply-patches.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceProfileTests(unittest.TestCase):
    def test_each_known_baseline_selected_as_a_whole(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            profiles = self.profiles()
            for version in ('old', 'new'):
                for index in range(5):
                    (source / str(index)).write_text(version + str(index))
                self.assertEqual(module.select_profile(source, profiles)['id'], version)

    def test_mixed_baselines_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            for index in range(5):
                (source / str(index)).write_text(('old' if index < 4 else 'new') + str(index))
            self.assertIsNone(module.select_profile(source, self.profiles()))

    def test_single_modified_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            for index in range(5):
                (source / str(index)).write_text('new' + str(index))
            (source / '4').write_text('new4 with unrelated local edit')
            self.assertIsNone(module.select_profile(source, self.profiles()))

    @staticmethod
    def profiles():
        return [{'id': version, 'files': [
            {'file': str(i), 'original_sha256': hashlib.sha256((version + str(i)).encode()).hexdigest()}
            for i in range(5)]} for version in ('old', 'new')]


if __name__ == '__main__':
    unittest.main()
