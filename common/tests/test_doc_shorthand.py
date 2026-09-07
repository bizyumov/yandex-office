"""Regression contract for the operator-approved GitMark-style shorthand."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_active_command_examples_use_yo():
    checked = 0
    for path in ROOT.rglob('*.md'):
        if any(part in {'.agent', '.gitmark', 'temp', '.git'} for part in path.parts):
            continue
        if path.name in {'CHANGELOG.md', 'TODO.md'}:
            continue
        text = path.read_text()
        assert 'python3 <full-path-to-yandex-office>/' not in text, path
        if '$YO/' in text:
            checked += 1
            assert text.count('YO="python3 <full-path-to-yandex-office>"') == 1, path
    assert checked == 13


def test_shell_shorthand_preserves_arguments_and_cwd():
    script = '''
python3() { printf '%s\\0' "$@"; }
YO="python3 /example/yandex-office"
$YO/scripts/oauth_setup.py --account "two words" --accounts list
printf '%s\\0' "$PWD"
'''
    result = subprocess.run(['bash', '--noprofile', '--norc', '-c', script],
                            cwd=ROOT, capture_output=True, check=True)
    assert result.stdout.decode().split('\0') == [
        '/example/yandex-office/scripts/oauth_setup.py', '--account', 'two words',
        '--accounts', 'list', str(ROOT), '',
    ]
