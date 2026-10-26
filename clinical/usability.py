"""Prepare empty clinician tasks and freeze explicitly labelled local observations."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import stat


PROTOCOL = 'department-agent-usability-v1'
COLUMNS = ['pseudonymous_clinician_id', 'task_id', 'start', 'end',
           'corrected', 'rejected', 'outcome', 'note']
TASKS = [
    ('T01', 'Review the first synthetic visit', 'Upload the labelled fixture; accept a supported field, correct one field with exact source evidence, reject one field with a reason, and defer one field.'),
    ('T02', 'Separate same-day examinations', 'Open the two explicitly identified same-day events and locate each event and its original source.'),
    ('T03', 'Resume partial archive', 'Use the operator-prepared isolated fault, inspect the completed and failed fields, retry the frozen publication, and check for duplicates.'),
    ('T04', 'Correct an archived value', 'Create a supported correction with a reason, archive it, and locate both the old value and the amended value with their source evidence.'),
    ('T05', 'Read longitudinal history', 'Open the second reviewed visit, inspect the timeline and follow-up task, and distinguish a visit-based completion from actual patient contact.'),
]


def _write_new(path, content):
    with path.open('x', encoding='utf-8', newline='') as writer:
        writer.write(content)


def _fresh(path):
    if path.exists() or path.is_symlink():
        raise ValueError('Destination must not exist')
    if not path.parent.is_dir():
        raise ValueError('Destination parent must exist')


def _csv_text(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def template(destination):
    destination = pathlib.Path(destination)
    _fresh(destination)
    destination.mkdir()
    protocol = {'protocol': PROTOCOL, 'version': 1, 'tasks': [
        {'id': task_id, 'title': title, 'instruction': instruction}
        for task_id, title, instruction in TASKS],
        'data_origin': 'not_collected', 'actual_clinicians_participated': 0,
        'clinical_accuracy_evaluation': 'NOT_RUN',
        'synthetic_scenario_only': True}
    _write_new(destination / 'protocol.json', json.dumps(protocol, indent=2) + '\n')
    _write_new(destination / 'observations.empty.csv', _csv_text([]))
    _write_new(destination / 'README.md', '''# Clinician usability collection kit

This delivered kit is empty. No actual clinicians participated in its preparation.
The task scenarios use synthetic fixtures. No clinical accuracy, time saving,
doctor feedback, or patient benefit has been measured.

Use one row per pseudonymous clinician and task. Assign IDs such as CLIN-A001
without storing an identity mapping in this project. Observe the operator doing
the task; do not prefill times or outcomes. Record ISO-8601 start/end timestamps
with an explicit UTC offset, nonnegative corrected/rejected field counts, and
outcome completed, blocked, or abandoned. Notes describe UI observations only;
never enter patient material, names, credentials, or contact information. Use
zero counts only when actually observed. Leave the delivered template empty.

Before collecting real observations, arrange the institution's applicable
participation and data-use process. This toolkit does not establish that process.
The task IDs and instructions are frozen in protocol.json. A future change to
the task design requires a new protocol version rather than editing a snapshot.

Validation: python usability.py validate observations.csv
Freeze: python usability.py freeze observations.csv NEW_DIRECTORY --data-origin
human-observed --deidentified
For engineering fixtures, use --data-origin simulated --deidentified instead.
The supplied origin is recorded, not independently verified. Freeze rejects an
empty input and never overwrites an existing directory. It retains the original
CSV hash, a normalized CSV, the protocol, and a manifest. Files become read-only;
SHA-256 detects modification, but this is not an OS-enforced immutable archive.
No statistical or clinical conclusion is computed automatically.
''')
    return protocol


def validate(source):
    source = pathlib.Path(source)
    info = source.lstat()
    if (source.suffix.lower() != '.csv' or not stat.S_ISREG(info.st_mode) or
            source.is_symlink() or info.st_nlink != 1 or
            getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError('Use an ordinary CSV file, not a link')
    if info.st_size > 1024 * 1024:
        raise ValueError('CSV exceeds the one-MiB collection limit')
    payload = source.read_bytes()
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig'), newline=''))
    if reader.fieldnames != COLUMNS:
        raise ValueError('CSV columns must match the protocol exactly')
    rows, seen = [], set()
    for number, row in enumerate(reader, start=2):
        if set(row) != set(COLUMNS) or any(value is None for value in row.values()):
            raise ValueError(f'Invalid column count at row {number}')
        if not re.fullmatch(r'CLIN-[A-Z0-9]{3,12}', row['pseudonymous_clinician_id']):
            raise ValueError(f'Use a pseudonymous clinician ID at row {number}')
        if row['task_id'] not in {item[0] for item in TASKS}:
            raise ValueError(f'Unknown task at row {number}')
        key = (row['pseudonymous_clinician_id'], row['task_id'])
        if key in seen:
            raise ValueError(f'Duplicate clinician/task at row {number}')
        seen.add(key)
        try:
            start = dt.datetime.fromisoformat(row['start'])
            end = dt.datetime.fromisoformat(row['end'])
            if start.utcoffset() is None or end.utcoffset() is None or end < start:
                raise ValueError()
        except ValueError as error:
            raise ValueError(f'Invalid timestamp pair at row {number}') from error
        if any(not re.fullmatch(r'0|[1-9][0-9]{0,3}', row[name]) for name in ('corrected', 'rejected')):
            raise ValueError(f'Counts must be nonnegative integers at row {number}')
        if row['outcome'] not in {'completed', 'blocked', 'abandoned'}:
            raise ValueError(f'Unknown outcome at row {number}')
        note = row['note']
        if len(note) > 500 or any(ord(char) < 32 for char in note) or note.lstrip().startswith(('=', '+', '-', '@')):
            raise ValueError(f'Unsafe or oversized note at row {number}')
        rows.append(row)
    return rows, hashlib.sha256(payload).hexdigest()


def freeze(source, destination, *, data_origin, deidentified=False):
    if data_origin not in {'simulated', 'human-observed'} or deidentified is not True:
        raise ValueError('Declare origin and confirm de-identified observations')
    destination = pathlib.Path(destination)
    _fresh(destination)
    rows, input_sha256 = validate(source)
    if not rows:
        raise ValueError('Empty templates cannot be frozen as observations')
    destination.mkdir()
    protocol = {'protocol': PROTOCOL, 'version': 1, 'tasks': [
        {'id': task_id, 'title': title, 'instruction': instruction}
        for task_id, title, instruction in TASKS]}
    _write_new(destination / 'protocol.json', json.dumps(protocol, indent=2) + '\n')
    _write_new(destination / 'observations.csv', _csv_text(rows))
    manifest = {'protocol': PROTOCOL, 'version': 1,
                'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'data_origin': data_origin, 'origin_verification': 'CALLER_DECLARED',
                'deidentification': 'CALLER_ATTESTED', 'input_sha256': input_sha256,
                'rows': len(rows), 'pseudonymous_observer_ids': len({row[COLUMNS[0]] for row in rows}),
                'actual_clinician_participation': 'NOT_ESTABLISHED_BY_TOOL',
                'clinical_accuracy_evaluation': 'NOT_RUN',
                'immutability': 'WRITE_ONCE_API_READ_ONLY_FILES_HASH_VERIFIED',
                'files': {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                          for name in ('protocol.json', 'observations.csv')}}
    _write_new(destination / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
    for path in destination.iterdir():
        path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('template')
    prepare.add_argument('destination', type=pathlib.Path)
    check = commands.add_parser('validate')
    check.add_argument('source', type=pathlib.Path)
    save = commands.add_parser('freeze')
    save.add_argument('source', type=pathlib.Path)
    save.add_argument('destination', type=pathlib.Path)
    save.add_argument('--data-origin', required=True, choices=['simulated', 'human-observed'])
    save.add_argument('--deidentified', action='store_true')
    args = parser.parse_args()
    if args.command == 'template':
        result = template(args.destination)
    elif args.command == 'freeze':
        result = freeze(args.source, args.destination, data_origin=args.data_origin, deidentified=args.deidentified)
    else:
        rows, digest = validate(args.source)
        result = {'status': 'PASS', 'rows': len(rows), 'sha256': digest,
                  'participation': 'NOT_ESTABLISHED_BY_TOOL'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
