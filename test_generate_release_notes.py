"""Exercise release ranges and local changes against real temporary Git repositories."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from generate_release_notes import generate_notes, previous_release


class ReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Release Test')
        self.git('config', 'user.email', 'release@example.test')
        self.commit('Inicio')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, subject):
        path = self.root / 'launcher.py'
        path.write_text(subject + '\n', encoding='utf-8')
        self.git('add', 'launcher.py')
        self.git('commit', '-qm', subject)
        return self.git('rev-parse', 'HEAD')

    def notes(self, **kwargs):
        return generate_notes(self.root, '0.1.6A', 'owner/project',
                              {'windows': 'launcher.exe'}, **kwargs)

    def test_version_commit_is_used_when_no_tags_exist(self):
        base = self.commit('0.1.5A')
        change = self.commit('Corrige URL guardada')
        notes = self.notes()
        self.assertEqual(previous_release(self.root, '0.1.6A'), base)
        self.assertIn('Corrige URL guardada', notes)
        self.assertNotIn('- Inicio', notes)
        self.assertIn(f'/compare/{base}...{change}', notes)

    def test_previous_tag_is_used_even_when_head_is_tagged_with_current_version(self):
        self.git('tag', 'v0.1.5A')
        self.commit('Arregla salas')
        self.git('tag', 'v0.1.6A')
        self.assertEqual(previous_release(self.root, '0.1.6A'), 'v0.1.5A')
        self.assertIn('Arregla salas', self.notes())
        self.assertNotIn('- Inicio', self.notes())

    def test_explicit_range_and_pending_changes(self):
        base = self.git('rev-parse', 'HEAD')
        self.commit('Corrige [URL]')
        (self.root / 'launcher.py').write_text('pending\n')
        self.git('add', 'launcher.py')
        notes = self.notes(since=base, include_uncommitted=True,
                           highlights=['Migra el servidor anterior'])
        self.assertIn('Corrige \\[URL\\]', notes)
        self.assertIn('Migra el servidor anterior', notes)
        self.assertIn('## Cambios locales pendientes de commit', notes)
        self.assertIn('- launcher.py', notes)
        self.assertNotIn('## Cambios locales pendientes de commit', self.notes(since=base))

    def test_first_release_and_empty_range_are_supported(self):
        self.assertIn('- Inicio', self.notes())
        self.assertIn('No hay commits descriptivos nuevos', self.notes(since='HEAD'))
        self.assertIn('Pendiente de documentar', self.notes())

    def test_invalid_reference_fails(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.notes(since='missing-tag')


if __name__ == '__main__':
    unittest.main()
