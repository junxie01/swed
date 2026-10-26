"""Purpose: validate GitHub-authenticated human reviews and update shared state.
Input: GITHUB_EVENT_PATH, GITHUB_EVENT_NAME, trusted .github/swed-review-policy.json,
       root data.json and optional root human_reviews.json in GITHUB_WORKSPACE.
Output: atomic review state and reversible data.json display for issues:opened;
        review_health.json for push;
        fixed, non-secret step outputs in GITHUB_OUTPUT when supplied.
Config / Parameters: policy repository/id/branch, allowed_reviewers login+numeric id,
                     title_prefix, max_note_length and max_batch_reviews (default 20).
How to run: python3 .github/process_review_20261017.py in the published repository;
            the accompanying swed-review.yml supplies the GitHub environment.
What this script does not do: no network, issue comments, git operations, scientific
                             QC changes, event deletion or browser authentication.
Publication mapping: this file -> .github/process_review_20261017.py;
                     swed-review.yml -> .github/workflows/swed-review.yml.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

DECISIONS = {'keep', 'reject', 'needs_context', 'unreviewed', 'keep_separate'}
SOURCE = 'swed_github_review'
ENTRY_FIELDS = {'event_id', 'representative_member_id', 'member_signature', 'decision', 'note'}


class ReviewError(ValueError):
    """A review is not authorized, current, or structurally valid."""


def _require(condition, reason):
    if not condition:
        raise ReviewError(reason)


def _integer(value):
    return type(value) is int and value > 0


def _utc(value):
    _require(isinstance(value, str) and bool(value), 'missing_server_timestamp')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ReviewError('invalid_server_timestamp') from exc
    _require(stamp.tzinfo is not None, 'naive_server_timestamp')
    return stamp.astimezone(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def _json(text):
    def invalid_constant(_):
        raise ReviewError('nonfinite_json_constant')
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ReviewError('invalid_json') from exc


def member_signature(member_ids):
    """SHA256 of the approved compact, sorted raw-member ID JSON contract."""
    _require(isinstance(member_ids, list) and bool(member_ids)
             and all(isinstance(value, str) and value for value in member_ids)
             and len(set(member_ids)) == len(member_ids), 'invalid_member_ids')
    canonical = json.dumps(sorted(member_ids), separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _policy(policy):
    _require(isinstance(policy, dict) and type(policy.get('schema_version')) is int
             and policy['schema_version'] == 1, 'invalid_policy_schema')
    _require(isinstance(policy.get('repository'), str)
             and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', policy['repository']), 'invalid_policy_repository')
    _require(_integer(policy.get('repository_id')), 'invalid_policy_repository_id')
    _require(isinstance(policy.get('branch'), str) and bool(policy['branch']), 'invalid_policy_branch')
    _require(isinstance(policy.get('title_prefix'), str) and bool(policy['title_prefix']), 'invalid_policy_title_prefix')
    allowed = policy.get('allowed_reviewers')
    _require(isinstance(allowed, list) and bool(allowed), 'missing_allowed_reviewers')
    _require(all(isinstance(row, dict) and isinstance(row.get('login'), str) and row['login']
                 and _integer(row.get('id')) for row in allowed), 'invalid_allowed_reviewers')
    _require(_integer(policy.get('max_note_length')) and policy['max_note_length'] <= 2000, 'invalid_policy_note_limit')
    _require(_integer(policy.get('max_batch_reviews', 20)) and policy.get('max_batch_reviews', 20) <= 100,
             'invalid_policy_batch_limit')
    return policy


def _repository(event, policy):
    repository = event.get('repository', {})
    _require(isinstance(repository, dict) and repository.get('full_name') == policy['repository']
             and type(repository.get('id')) is int and repository['id'] == policy['repository_id'], 'repository_identity_mismatch')


def _authorized(user, policy):
    return (isinstance(user, dict) and type(user.get('id')) is int
            and any(user.get('login') == allowed['login'] and user['id'] == allowed['id']
                    for allowed in policy['allowed_reviewers']))


def _state(state, policy):
    if state is None:
        return dict(schema_version=1, source=SOURCE, repository=policy['repository'],
                    repository_id=policy['repository_id'], reviews={}, processed_issues={}, updated_at=None)
    _require(isinstance(state, dict) and type(state.get('schema_version')) is int
             and state['schema_version'] == 1 and state.get('source') == SOURCE
             and state.get('repository') == policy['repository']
             and state.get('repository_id', policy['repository_id']) == policy['repository_id']
             and isinstance(state.get('reviews'), dict) and isinstance(state.get('processed_issues'), dict), 'invalid_existing_review_state')
    for event_id, row in state['reviews'].items():
        _require(isinstance(row, dict) and row.get('event_id') == event_id and row.get('decision') in DECISIONS
                 and row.get('representative_member_id') in row.get('member_ids', [])
                 and row.get('member_signature') == member_signature(row.get('member_ids'))
                 and isinstance(row.get('note'), str) and len(row['note']) <= 2000
                 and isinstance(row.get('reviewer_login'), str) and _integer(row.get('reviewer_id'))
                 and _integer(row.get('issue_number'))
                 and row.get('issue_url') == 'https://github.com/%s/issues/%d' % (policy['repository'], row['issue_number']),
                 'invalid_existing_review_row')
        _utc(row.get('reviewed_at'))
    if state.get('updated_at') is not None:
        _utc(state['updated_at'])
    return deepcopy(state)


def _entries(body, policy):
    _require(isinstance(body, str), 'missing_review_body')
    match = re.fullmatch(r'SWED_REVIEW_V1\s*\n```json\s*\n(.*?)\n```\s*', body, re.DOTALL)
    _require(match is not None, 'invalid_review_body_marker')
    payload = _json(match.group(1))
    _require(isinstance(payload, dict) and type(payload.get('schema_version')) is int and payload['schema_version'] == 1
             and payload.get('source') == SOURCE, 'invalid_review_payload_schema')
    if 'reviews' in payload:
        _require(set(payload) == {'schema_version', 'source', 'reviews'}, 'unexpected_batch_payload_fields')
        rows = payload['reviews']
    else:
        _require(set(payload) == ENTRY_FIELDS | {'schema_version', 'source'}, 'unexpected_review_payload_fields')
        rows = [{key: payload[key] for key in ENTRY_FIELDS}]
    _require(isinstance(rows, list) and 1 <= len(rows) <= policy.get('max_batch_reviews', 20), 'invalid_review_batch_size')
    seen = set()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == ENTRY_FIELDS, 'unexpected_review_entry_fields')
        _require(all(isinstance(row[key], str) and row[key] for key in ['event_id', 'representative_member_id']), 'missing_review_event_identity')
        _require(row['event_id'] not in seen, 'duplicate_event_in_review_batch')
        seen.add(row['event_id'])
        _require(isinstance(row['member_signature'], str) and re.fullmatch('[0-9a-f]{64}', row['member_signature']), 'invalid_member_signature')
        _require(isinstance(row['decision'], str) and row['decision'] in DECISIONS, 'invalid_review_decision')
        _require(isinstance(row['note'], str) and len(row['note']) <= policy['max_note_length'], 'invalid_review_note')
    return rows


def _review_target(source, events, data, current):
    """Authorize a separation of an original source, or reset its exact receipt.

    Resetting an obsolete separation is the sole historical-target exception;
    it cannot create or clear an unrelated scientific/truth review.
    """
    previous=current['reviews'].get(source['event_id'])
    if (source['decision']=='unreviewed' and previous and previous['decision']=='keep_separate'
            and source['representative_member_id']==previous['representative_member_id']
            and source['member_signature']==previous['member_signature']):
        return dict(id=previous['event_id'],representative_member_id=previous['representative_member_id'],
                    members=[dict(id=key) for key in previous['member_ids']])
    item=events.get(source['event_id'])
    if item is not None:
        _require(source['decision']!='keep_separate' or not item.get('orbit_association_v4'),
                 'select_original_source_for_separation')
        return item
    rows=data.get('orbit_source_events',[])
    _require(isinstance(rows,list),'invalid_original_orbit_source_index')
    originals={}
    for item in rows:
        _require(isinstance(item,dict) and isinstance(item.get('id'),str)
                 and item['id'] not in originals,'invalid_original_orbit_source_index')
        originals[item['id']]=item
    item=originals.get(source['event_id'])
    _require(item is not None,'event_not_in_current_catalogue')
    _require(source['decision']=='keep_separate','source_target_supports_separation_only')
    return item


def process_event(event, policy, data, state=None, event_name='issues'):
    """Return (new_state, report); validate the entire batch before changing state.

    Inputs are never mutated. Invalid requests raise ReviewError. An unrelated
    issue returns the original state and an ignored report, without creating it.
    """
    policy = _policy(policy)
    _require(isinstance(event, dict) and event_name == 'issues' and event.get('action') == 'opened', 'only_new_issues_are_supported')
    _repository(event, policy)
    issue = event.get('issue', {})
    _require(isinstance(issue, dict), 'invalid_issue')
    if not isinstance(issue.get('title'), str) or not issue['title'].startswith(policy['title_prefix']):
        return state, dict(action='ignored', state_changed=False, close_issue=False, issue_number=0, review_count=0)
    _require('pull_request' not in issue, 'pull_request_is_not_a_review_issue')
    _require(_authorized(issue.get('user'), policy) and _authorized(event.get('sender'), policy), 'unauthorized_review_author_or_sender')
    _require(issue['user']['id'] == event['sender']['id'], 'review_author_sender_mismatch')
    number = issue.get('number')
    _require(_integer(number), 'invalid_issue_number')
    issue_url = 'https://github.com/%s/issues/%d' % (policy['repository'], number)
    _require(issue.get('html_url') == issue_url, 'issue_url_mismatch')
    created = _utc(issue.get('created_at'))
    reviewed_at = _iso(created)
    rows = _entries(issue.get('body'), policy)
    current = _state(state, policy)
    digest = hashlib.sha256(issue['body'].encode('utf-8')).hexdigest()
    receipt = current['processed_issues'].get(str(number))
    if receipt is not None:
        _require(isinstance(receipt, dict) and receipt.get('payload_sha256') == digest
                 and receipt.get('issue_number') == number and receipt.get('reviewer_id') == issue['user']['id'], 'processed_issue_payload_changed')
        return current, dict(action='duplicate', state_changed=False, close_issue=True, issue_number=number, review_count=len(rows))
    _require(isinstance(data, dict) and isinstance(data.get('events'), list), 'missing_current_event_catalogue')
    events = {}
    for item in data['events']:
        _require(isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'] not in events, 'invalid_current_event_catalogue')
        events[item['id']] = item
    validated = []
    for source in rows:
        item = _review_target(source,events,data,current)
        members = item.get('members')
        _require(isinstance(members, list) and all(isinstance(member, dict) for member in members), 'invalid_current_event_members')
        member_ids = [member.get('id') for member in members]
        signature = member_signature(member_ids)
        member_ids.sort()
        _require(source['representative_member_id'] == item.get('representative_member_id')
                 and source['representative_member_id'] in member_ids, 'representative_member_changed')
        _require(source['member_signature'] == signature, 'event_members_changed')
        validated.append(dict(source, member_ids=member_ids, reviewed_at=reviewed_at,
                              reviewer_login=issue['user']['login'], reviewer_id=issue['user']['id'],
                              issue_number=number, issue_url=issue_url, source=SOURCE))
    outcomes = {}
    for row in validated:
        previous = current['reviews'].get(row['event_id'])
        newer = previous is None or (created, number) > (_utc(previous['reviewed_at']), previous['issue_number'])
        outcomes[row['event_id']] = 'applied' if newer else 'superseded'
        if newer:
            current['reviews'][row['event_id']] = row
    receipt = dict(issue_number=number, issue_url=issue_url, reviewer_login=issue['user']['login'],
                   reviewer_id=issue['user']['id'], reviewed_at=reviewed_at, payload_sha256=digest,
                   event_ids=sorted(outcomes), review_count=len(validated), outcomes=outcomes)
    if len(validated) == 1:
        receipt.update({key: validated[0][key] for key in ['event_id', 'decision', 'member_signature']})
        receipt['outcome'] = outcomes[validated[0]['event_id']]
    current['processed_issues'][str(number)] = receipt
    current['updated_at'] = _iso(max(created, _utc(current['updated_at']))) if current.get('updated_at') else reviewed_at
    action = 'applied' if 'applied' in outcomes.values() else 'superseded'
    return current, dict(action=action, state_changed=True, close_issue=True, issue_number=number, review_count=len(validated))


def self_test(policy):
    """Exercise authorization and atomicity in memory; never use published events."""
    policy = _policy(policy)
    user = policy['allowed_reviewers'][0]
    members = ['SELF_TEST_RAW_A', 'SELF_TEST_RAW_B']
    row = dict(schema_version=1, source=SOURCE, event_id='SELF_TEST_EVENT', representative_member_id=members[0],
               member_signature=member_signature(members), decision='needs_context', note='Offline processor assertion only')
    body = 'SWED_REVIEW_V1\n```json\n' + json.dumps(row) + '\n```'
    event = dict(action='opened', repository=dict(full_name=policy['repository'], id=policy['repository_id']), sender=dict(user),
                 issue=dict(number=1, title=policy['title_prefix'] + ' offline assertion', user=dict(user),
                            created_at='2000-01-01T00:00:00Z', html_url='https://github.com/' + policy['repository'] + '/issues/1', body=body))
    data = dict(events=[dict(id=row['event_id'], representative_member_id=members[0], members=[dict(id=value) for value in members])])
    state, report = process_event(event, policy, data)
    _require(report['action'] == 'applied' and state['reviews'][row['event_id']]['member_ids'] == members, 'self_test_apply_failed')
    duplicate, report = process_event(event, policy, data, state)
    _require(report['action'] == 'duplicate' and duplicate == state, 'self_test_idempotency_failed')
    checks = ['valid_owner_and_membership', 'issue_idempotency']
    for name, change in [('unauthorized_author', 'author'), ('unauthorized_sender', 'sender'),
                         ('stale_member_set', 'members'), ('edited_issue', 'action')]:
        bad, catalogue = deepcopy(event), deepcopy(data)
        if change == 'author':
            bad['issue']['user']['id'] = -1
        elif change == 'sender':
            bad['sender']['id'] = -1
        elif change == 'members':
            catalogue['events'][0]['members'].append(dict(id='SELF_TEST_NEW_MEMBER'))
        else:
            bad['action'] = 'edited'
        try:
            process_event(bad, policy, catalogue)
        except ReviewError:
            checks.append(name)
        else:
            raise ReviewError('self_test_' + name + '_failed')
    return checks


def _path(root, relative):
    path = root / relative
    for parent in [path, *path.parents]:
        if parent == root.parent:
            break
        _require(not parent.is_symlink(), 'symlink_repository_input_or_output')
    _require(path.resolve().is_relative_to(root), 'repository_path_escape')
    return path


def _write(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp',
                                     encoding='utf-8', delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _project_display(data,state):
    if 'orbit_source_events' not in data:
        return data
    import importlib.util
    module_path=Path(__file__).with_name('orbit_display_v4.py')
    _require(module_path.is_file() and not module_path.is_symlink(),'missing_or_unsafe_orbit_display_helper')
    spec=importlib.util.spec_from_file_location('swed_review_orbit_display',module_path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.project_public_orbits(data,state)


def run_environment(environ=None):
    """Execute the fixed repository-file contract; no command-line path overrides."""
    env = os.environ if environ is None else environ
    root = Path(env['GITHUB_WORKSPACE']).resolve()
    policy = _policy(_json(_path(root, '.github/swed-review-policy.json').read_text(encoding='utf-8')))
    _require(env.get('GITHUB_REPOSITORY') == policy['repository']
             and env.get('GITHUB_REPOSITORY_ID') == str(policy['repository_id']), 'workflow_repository_identity_mismatch')
    event = _json(Path(env['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    name = env.get('GITHUB_EVENT_NAME')
    if name == 'push':
        _repository(event, policy)
        _require(event.get('ref') == 'refs/heads/' + policy['branch'] and event.get('deleted') is not True, 'untrusted_self_test_branch')
        checks = self_test(policy)
        health = dict(schema_version=1, source='swed_github_review_health', repository=policy['repository'],
                      repository_id=policy['repository_id'], status='processor_self_test_passed',
                      checked_at=_iso(datetime.now(timezone.utc)), run_id=env.get('GITHUB_RUN_ID', ''),
                      run_attempt=env.get('GITHUB_RUN_ATTEMPT', ''), commit_sha=env.get('GITHUB_SHA', ''),
                      assertion_count=len(checks), checks=checks, review_state_modified=False,
                      pages_request_verified=False)
        _write(_path(root, 'review_health.json'), health)
        report = dict(action='self_test', state_changed=False, close_issue=False, issue_number=0, review_count=0)
    else:
        path = _path(root, 'human_reviews.json')
        previous = _json(path.read_text(encoding='utf-8')) if path.exists() else None
        data = _json(_path(root, 'data.json').read_text(encoding='utf-8'))
        state, report = process_event(event, policy, data, previous, event_name=name)
        projected=_project_display(data,state) if report['close_issue'] else data
        report['display_data_changed']=projected!=data
        if report['state_changed']:
            _write(path, state)
        if report['display_data_changed']:
            _write(_path(root,'data.json'),projected)
    report.setdefault('display_data_changed',False)
    if env.get('GITHUB_OUTPUT'):
        with Path(env['GITHUB_OUTPUT']).open('a', encoding='utf-8') as handle:
            for key in ['action', 'state_changed', 'display_data_changed', 'close_issue', 'issue_number', 'review_count']:
                value = report[key]
                handle.write(key + '=' + (str(value).lower() if isinstance(value, bool) else str(value)) + '\n')
    return report


if __name__ == '__main__':
    try:
        result = run_environment()
        print(json.dumps(result, sort_keys=True))
    except (ReviewError, OSError, KeyError, TypeError, ValueError) as exc:
        # No issue body, note, token, or arbitrary exception payload is printed.
        print(json.dumps(dict(action='blocked', reason=str(exc) if isinstance(exc, ReviewError) else type(exc).__name__)))
        raise SystemExit(1)
