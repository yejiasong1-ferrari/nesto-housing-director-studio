#!/usr/bin/env python3
"""Scan public source + Git history without printing credential values.

Optional --private-env compares real local values entirely in this process.
Only file names, line numbers and categories are reported. Binary media is
checked against private values too; heuristic checks apply to text files.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    ('provider credential', re.compile(rb'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}|AKIA[A-Z0-9]{16})\b')),
    ('private key', re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('personal home path', re.compile(rb'(?:/Users/|/home/)[A-Za-z0-9_.-]+/')),
    ('mainland phone number', re.compile(rb'(?<![0-9])(?:\+86[ -]?)?1[3-9][0-9]{9}(?![0-9])')),
]
MAIL = re.compile(rb'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
SAFE_DOMAINS = (b'example.com', b'example.test', b'example.org', b'test.com', b'noreply.github.com', b'users.noreply.github.com')

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], stderr=subprocess.DEVNULL)

def private_values(paths):
    values=set()
    for path in paths:
        for line in path.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#') or '=' not in line:continue
            key,value=line.split('=',1)
            if not re.search(r'KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL|ENDPOINT',key):continue
            value=value.strip().strip('"\'')
            if len(value)>=12 and not value.startswith(('<','your-','YOUR_','http://localhost','http://127.0.0.1')):
                values.add(value.encode())
    return values

def scan(label,data,values):
    issues=[]
    for value in values:
        if value in data:issues.append((label,0,'matches a private environment value'))
    if b'\x00' in data:return issues
    for category,pattern in PATTERNS:
        for m in pattern.finditer(data):issues.append((label,data[:m.start()].count(b'\n')+1,category))
    for m in MAIL.finditer(data):
        address=m.group().lower();domain=address.split(b'@')[-1]
        if domain not in SAFE_DOMAINS and not domain.endswith(b'.example'):
            issues.append((label,data[:m.start()].count(b'\n')+1,'non-placeholder email address'))
    return issues

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-env',type=Path,action='append',default=[],help='Local env file used only for private-value comparison')
    parser.add_argument('--skip-history',action='store_true')
    args=parser.parse_args();values=private_values(args.private_env);issues=[];count=0
    # Git's list excludes ignored runtime files, installed dependencies and .env.
    files=git('ls-files','--cached','--others','--exclude-standard','-z').split(b'\0')
    for raw in files:
        if not raw:continue
        name=raw.decode();path=ROOT/name
        if not path.is_file():continue
        issues+=scan(name,path.read_bytes(),values);count+=1
    blobs=set()
    if not args.skip_history:
        for line in git('rev-list','--objects','--all').decode().splitlines():
            oid,_,name=line.partition(' ')
            if not name or oid in blobs:continue
            if git('cat-file','-t',oid).strip()!=b'blob':continue
            blobs.add(oid);issues+=scan('history:'+name,git('cat-file','blob',oid),values)
    if issues:
        for label,line,category in sorted(set(issues)):
            print(f'{label}:{line}: {category}')
        print(f'REVIEW REQUIRED: {len(set(issues))} findings. Values are intentionally omitted.')
        return 1
    print(f'PASS: {count} working files and {len(blobs)} history blobs checked; no matches. Private values compared: {len(values)}.')
    return 0

if __name__=='__main__':sys.exit(main())
