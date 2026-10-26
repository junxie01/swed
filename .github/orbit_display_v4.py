"""Purpose: reversibly project accepted v4 edges into static display events.
Input: public original source events, direct automatic groups and review state.
Output: a copied data index; original science, sources and graph stay unchanged.
Config / Parameters: the accepted graph comes from the office v4 policy; this
    standalone module adds no model, threshold, fit or automatic relation.
How to run: project_public_orbits(data, state), from website or the review job.
What this module does not do: no network, file writes, waveform reads, QC or
    magnitude calculation, new parents, chained merge or review authorization.
GitHub's maintained MIT actions/toolkit was assessed; its JS dependencies are
unnecessary here. This pure standard-library helper shares the existing trusted
checkout/strict JSON review path, following GitHub's secure-use documentation.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json


def _ids(event):
    members=event.get('members')
    if not isinstance(members,list) or not members or any(not isinstance(row,dict) for row in members):
        raise ValueError('Invalid orbit source members')
    ids=[row.get('id') for row in members]
    if (any(not isinstance(key,str) or not key for key in ids) or len(set(ids))!=len(ids)
            or event.get('representative_member_id') not in ids):
        raise ValueError('Invalid orbit source member identity')
    return sorted(ids)


def _signature(ids):
    return hashlib.sha256(json.dumps(sorted(ids),separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def _matching(row,event):
    if not isinstance(row,dict):return False
    ids=_ids(event)
    return (row.get('event_id')==event['id'] and row.get('representative_member_id')==event['representative_member_id']
        and row.get('member_ids')==ids and row.get('member_signature',_signature(ids))==_signature(ids))


def separation_preferences(sources,reviews):
    """A stale explicit display preference remains conservative by old anchor."""
    result={}
    for event in sources:
        members=set(_ids(event));preferences=[]
        for key,row in reviews.items():
            if (isinstance(row,dict) and row.get('decision')=='keep_separate'
                    and row.get('event_id')==key and row.get('representative_member_id') in members):
                preferences.append(dict(review_event_id=key,
                    representative_member_id=row['representative_member_id'],
                    stale=not _matching(row,event),display_preference_only=True))
        if preferences:result[event['id']]=sorted(preferences,key=lambda row:row['review_event_id'])
    return result


def _sources(data):
    sources=data['orbit_source_events'];groups=data.get('orbit_auto_groups')
    if not isinstance(sources,list) or not isinstance(groups,list):
        raise ValueError('Original orbit sources and accepted groups are required')
    by_id={};all_ids=set()
    for event in sources:
        if (not isinstance(event,dict) or not isinstance(event.get('id'),str) or not event['id']
                or event['id'] in by_id or event.get('orbit_association_v4')):
            raise ValueError('Invalid original orbit source identity')
        ids=set(_ids(event))
        if ids & all_ids:raise ValueError('Original orbit source records overlap')
        all_ids.update(ids);by_id[event['id']]=event
    return sources,groups,by_id


def project_public_orbits(data,state=None):
    """Apply display-only separations to a previously accepted direct graph.

    Caller authenticates/validates state. A root's own still-matching reject is
    retained as a distinct display preference, never represented as review of
    newly attached children. Explicit review of the current group takes priority.
    """
    if 'orbit_source_events' not in data:return deepcopy(data)
    sources,groups,by_id=_sources(data)
    reviews=deepcopy((state or {}).get('reviews',{}))
    if not isinstance(reviews,dict):raise ValueError('Invalid orbit review mapping')
    # Office's validated archive uses microsecond UTC timestamps; GitHub's
    # signed state commonly uses whole-second UTC. Canonicalize that equivalent
    # representation so either caller produces the identical public projection.
    for review in reviews.values():
        if isinstance(review,dict) and isinstance(review.get('reviewed_at'),str):
            stamp=datetime.fromisoformat(review['reviewed_at'].replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError('Naive orbit review timestamp')
            review['reviewed_at']=stamp.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    preferences=separation_preferences(sources,reviews)
    roots={row.get('root_event_id') for row in groups}
    if len(roots)!=len(groups) or not roots<=set(by_id):raise ValueError('Invalid direct orbit roots')
    child_owner={};active={}
    for group in groups:
        root=group['root_event_id'];children=group.get('children')
        if not isinstance(children,list):raise ValueError('Invalid direct orbit children')
        selected=[]
        for link in children:
            child=link.get('event_id') if isinstance(link,dict) else None
            if (child not in by_id or child in roots or child in child_owner
                    or link.get('phase') not in {'R2','R3'}):
                raise ValueError('Invalid, duplicated or chained orbit child')
            child_owner[child]=root
            if root not in preferences and child not in preferences:selected.append(deepcopy(link))
        if selected:active[root]=selected
    owner={link['event_id']:root for root,children in active.items() for link in children}
    events=[]
    for original in sources:
        root=original['id']
        if root in owner:continue
        event=deepcopy(original)
        if root in active:
            children=active[root];source_ids=[root]+[row['event_id'] for row in children]
            event.update(id='SWED_EVENT_V4_'+hashlib.sha256(original['representative_member_id'].encode()).hexdigest()[:20],
                catalogue_version='realtime_orbit_v4')
            event['event_id']=event['id'];event.pop('manual_review',None)
            event['members']=[deepcopy(member) for sid in source_ids for member in by_id[sid]['members']]
            if 'member_count' in original:event['member_count']=len(event['members'])
            event['orbit_association_v4']=dict(schema_version=4,root_source_event_id=root,
                source_event_ids=source_ids,
                source_representative_member_ids=[by_id[sid]['representative_member_id'] for sid in source_ids],
                aliases=[dict(source_event_id=row['event_id'],representative_member_id=by_id[row['event_id']]['representative_member_id'],
                    phase=row['phase'],periods_s=deepcopy(row.get('periods_s',[]))) for row in children],
                direct_root_only=True,reversible=True,duplicate_members_contribute_period_or_magnitude=False)
        if root in preferences:event['orbit_independent_display']=deepcopy(preferences[root])
        current=reviews.get(event['id'])
        matching=_matching(current,event)
        if current:
            event['manual_review']=dict(deepcopy(current),archived=True,membership_matches=matching,
                effective_decision=current['decision'] if matching else 'unreviewed')
        if root in active:
            source_review=reviews.get(root,original.get('manual_review'))
            if _matching(source_review,original) and source_review.get('decision')=='reject':
                event['root_source_rejection']=dict(source_event_id=root,
                    source_representative_member_id=original['representative_member_id'],
                    source_member_signature=_signature(_ids(original)),
                    source_review=deepcopy(source_review),effective_in_display=not matching,
                    new_group_members_reviewed=False)
        events.append(event)
    if (len({row['id'] for row in events})!=len(events)
            or sorted(key for event in events for key in _ids(event))!=sorted(key for event in sources for key in _ids(event))):
        raise ValueError('Orbit display failed original record conservation')
    events.sort(key=lambda row:(row.get('origin_time_utc',''),row['id']),reverse=True)
    result=deepcopy(data);result['events']=events;result['event_count']=len(events)
    summary=result.setdefault('event_summary',{})
    summary.update(catalogue_version='realtime_orbit_v4',event_count=len(events),
        multi_period_event_count=sum(len(event.get('periods_s',[]))>1 for event in events),
        magnitude_available_event_count=sum(event.get('magnitude') is not None for event in events),
        event_figure_complete_count=sum(event.get('event_figure_status')=='complete' for event in events),
        event_figure_blocked_count=sum(event.get('event_figure_status')!='complete' for event in events))
    # These are counts of current displayed event objects, including removed
    # events. They are not counts of source queries or inherited child reviews.
    if 'usgs_event_count' in summary or any(event.get('usgs_match') for event in events):
        summary['usgs_event_count']=len(events)
        for status in ('matched_strict','matched_broad_only','unmatched','unmatched_to_usgs_scope','unavailable'):
            summary['usgs_'+status+'_event_count']=sum(event.get('usgs_match',{}).get('status')==status for event in events)
    decisions=('unreviewed','keep','reject','needs_context','keep_separate')
    applied=stale=0;counts={decision:0 for decision in decisions}
    for event in events:
        review=event.get('manual_review')
        if not review:continue
        matching=_matching(review,event)
        applied+=int(matching);stale+=int(not matching)
        if matching and review.get('decision') in counts:counts[review['decision']]+=1
    summary.update(human_review_applied_event_count=applied,human_review_stale_event_count=stale,
        **{'human_review_'+decision+'_event_count':count for decision,count in counts.items()})
    result['orbit_projection_state_sha256']=hashlib.sha256(json.dumps(reviews,sort_keys=True,
        separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
    return result
