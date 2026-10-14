"""Small publication guard. Print paths/rule names only, never matched secrets."""
import argparse
import fnmatch
from pathlib import PurePosixPath
import re
import subprocess

FORBIDDEN_ROOTS = {'data', 'artifacts', 'build', 'dist', 'secrets', 'credentials', 'node_modules', '.venv'}
PATTERNS = ['*.env', '*.db', '*.db-*', '*.sqlite*', '*.log', '*.pem', '*.key', '*.p12', '*.pfx', '*token*.json', '*credentials*.json', '*.bak', '*.tmp']
RULES = {
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'jwt-token': re.compile(rb'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}'),
    'populated-toss-env': re.compile(rb'^TOSS_(?:CLIENT_ID|CLIENT_SECRET|ACCOUNT_SEQ)[ \t]*=[ \t]*[^\s#\r\n]+', re.M),
    'private-home-path': re.compile(rb'[A-Za-z]:[/\\]Users[/\\](?!Public\b|USERNAME\b)[^/\\\s"\']+'),
}

def forbidden(path):
    parts = PurePosixPath(path).parts
    name = parts[-1].lower()
    return any(part in FORBIDDEN_ROOTS or part.endswith('.egg-info') for part in parts) or name == 'design-qa.md' or (name.startswith('.env') and name != '.env.example') or any(fnmatch.fnmatch(name, pattern) for pattern in PATTERNS)

def violations(path, blob):
    issues = ['private-file'] if forbidden(path) else []
    issues.extend(name for name, pattern in RULES.items() if pattern.search(blob))
    return issues

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--staged', action='store_true', help='Inspect index blobs, including the first commit.')
    args = parser.parse_args()
    names = subprocess.check_output(['git', 'ls-files', '-z'] if args.staged else ['git', 'ls-tree', '-r', '--name-only', '-z', 'HEAD']).decode('utf-8').split('\0')
    failures = []
    for path in filter(None, names):
        blob = subprocess.check_output(['git', 'show', (':' if args.staged else 'HEAD:') + path])
        for rule in violations(path, blob):
            failures.append(f'{path}: {rule}')
    if failures:
        print('\n'.join(failures))
        raise SystemExit(1)
    print(f'Public-tree guard passed ({len(list(filter(None, names)))} files).')

if __name__ == '__main__':
    main()
