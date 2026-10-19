"""Python randomized-restart engine for school invigilation scheduling.
The renderer sends normalized tasks/teachers/rules and receives the best assignment found.
"""
from __future__ import annotations
import random, time, math
from collections import Counter, defaultdict


def solve_batch(payload):
    tasks = payload.get('tasks') or []
    teachers = payload.get('teachers') or []
    rules = payload.get('rules') or {}
    exclusions = payload.get('exclusions') or []
    day_index = payload.get('dayIndex') or {}
    attempts = max(1, min(int(payload.get('attempts', 100)), 500))
    seconds = max(.1, min(float(payload.get('seconds', 3.0)), 8.0))
    relax_single = bool(payload.get('relaxSingleDuty'))
    allow_two_reserves = bool(payload.get('allowTwoReserves'))
    max_day = max(1, int(rules.get('maxPerDay', 2) or 2))
    avoid_adjacent = rules.get('avoidConsecutiveDay') is True
    prefer_consecutive = rules.get('requireConsecutiveDays') is True
    subject_rule = rules.get('subjectTeacherRule', 'must')
    quota = max(1, int(rules.get('subjectReserveCount', 2) or 2))
    teacher_by_id = {str(t.get('id')): t for t in teachers}
    ex_by_teacher = defaultdict(list)
    for ex in exclusions: ex_by_teacher[str(ex.get('teacherId'))].append(ex)
    deadline = time.monotonic() + seconds
    best = None
    completed = 0

    def blocked(t, task):
        sid = str(t.get('id'))
        se = task.get('se') or {}
        for ex in ex_by_teacher[sid]:
            if ex.get('allGuard') is True or ex.get('date') == se.get('date'):
                if not ex.get('start') or not ex.get('end') or (ex.get('start') < se.get('end','') and ex.get('end') > se.get('start','')):
                    return True
        subs = set(map(str, task.get('subjects') or []))
        ts = str(t.get('subjectId') or '')
        role = task.get('role', 'guard')
        if ts and ts in subs:
            if subject_rule == 'exempt': return True
            if subject_rule == 'reserve' and role != 'reserve': return True
            if subject_rule in ('must', 'guard') and role == 'reserve': return True
        return False

    def valid(t, task, assigned, task_idx):
        if blocked(t, task): return False
        se = task.get('se') or {}; date = se.get('date'); start = se.get('start',''); end = se.get('end','')
        same = []
        for j in assigned[str(t.get('id'))]:
            old = tasks[j]; ose = old.get('se') or {}
            if ose.get('date') != date: continue
            same.append(old)
            if (ose.get('start','') < end and start < ose.get('end','')): return False
            if avoid_adjacent and (ose.get('end') == start or ose.get('start') == end): return False
        if len(same) >= max_day: return False
        mine = [tasks[j] for j in assigned[str(t.get('id'))]] + [task]
        perday = Counter((x.get('se') or {}).get('date') for x in mine)
        if sum(1 for n in perday.values() if n == 1) > (2 if relax_single else 1): return False
        if (task.get('role') == 'reserve') and sum(1 for j in assigned[str(t.get('id'))] if tasks[j].get('role') == 'reserve') >= (2 if allow_two_reserves else 1): return False
        if prefer_consecutive:
            ds = sorted({(tasks[j].get('se') or {}).get('date') for j in assigned[str(t.get('id'))]} | {date}, key=lambda d: day_index.get(d, 9999))
            if any(day_index.get(ds[i], 0) - day_index.get(ds[i-1], 0) > 2 for i in range(1, len(ds))): return False
        return True

    def score(assignments, unfilled):
        loads=[]; days=[]; minutes=[]; singles=0; lone_reserve=0
        for t in teachers:
            arr=[tasks[j] for j,v in enumerate(assignments) if str(v)==str(t.get('id'))]
            loads.append(len(arr)); per=Counter((x.get('se') or {}).get('date') for x in arr)
            days.append(len(per)); minutes.append(sum(int(x.get('mins') or 0) for x in arr))
            singles += sum(1 for n in per.values() if n==1)
            lone_reserve += sum(1 for x in arr if x.get('role')=='reserve' and per[(x.get('se') or {}).get('date')]==1)
        spread=lambda a: (max(a)-min(a)) if a else 0
        return (len(unfilled)*10**15 + lone_reserve*10**14 + max(0,singles-(2 if relax_single else 1))*10**13 + max(0,spread(loads)-1)*10**11 + max(0,spread(days)-1)*10**10 + max(0,spread(minutes)-120)*10**6 + sum(x*x for x in loads)*100 + random.random())

    while completed < attempts and time.monotonic() < deadline:
        completed += 1
        assignment = [None] * len(tasks)
        assigned = {str(t.get('id')): [] for t in teachers}
        # Keep mandatory/fixed duties first.
        fixed_bad = []
        for i, task in enumerate(tasks):
            fid = task.get('fixed')
            if fid is not None and str(fid) in assigned:
                t = teacher_by_id[str(fid)]
                if valid(t, task, assigned, i): assignment[i] = str(fid); assigned[str(fid)].append(i)
                else: assignment[i] = str(fid); assigned[str(fid)].append(i); fixed_bad.append(i)
        order = [i for i,t in enumerate(tasks) if t.get('fixed') is None]
        random.shuffle(order)
        # Hardest tasks first, with randomized tie-breaking.
        def option_count(i):
            task=tasks[i]
            return sum(1 for t in teachers if valid(t,task,assigned,i))
        order.sort(key=lambda i: option_count(i) + random.random()*.8)
        for i in order:
            task=tasks[i]
            candidates=[t for t in teachers if valid(t,task,assigned,i)]
            if not candidates: continue
            loads={str(t.get('id')):len(assigned[str(t.get('id'))]) for t in teachers}
            mins={str(t.get('id')):sum(int(tasks[j].get('mins') or 0) for j in assigned[str(t.get('id'))]) for t in teachers}
            daycounts={str(t.get('id')):len({(tasks[j].get('se') or {}).get('date') for j in assigned[str(t.get('id'))]}) for t in teachers}
            random.shuffle(candidates)
            candidates.sort(key=lambda t:(loads[str(t.get('id'))]*10000 + daycounts[str(t.get('id'))]*1000 + mins[str(t.get('id'))] + random.random()*250))
            chosen=candidates[0]; tid=str(chosen.get('id')); assignment[i]=tid; assigned[tid].append(i)
        # Small local-repair pass: try move unfilled tasks by exchanging a non-fixed duty.
        for i, task in enumerate(tasks):
            if assignment[i] is not None or time.monotonic() >= deadline: continue
            candidates=[t for t in teachers if valid(t,task,assigned,i)]
            if candidates:
                t=min(candidates,key=lambda x:len(assigned[str(x.get('id'))])+random.random()*.2)
                assignment[i]=str(t.get('id')); assigned[str(t.get('id'))].append(i)
        unfilled=[i for i,v in enumerate(assignment) if v is None]
        sc=score(assignment,unfilled)
        if best is None or sc < best['score']:
            best={'assignments':assignment,'unfilled':unfilled,'score':sc,'attempts':completed,'fixedConflicts':fixed_bad if 'fixed_bad' in locals() else []}
        # Early stop only when complete and balanced enough; caller can request another batch otherwise.
        if not unfilled and best['score'] < 100000: break
    return {'ok':True,'best':best,'attempts':completed,'timedOut':time.monotonic()>=deadline}
