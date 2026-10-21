# -*- coding: utf-8 -*-
"""Strict invigilation scheduler based on OR-Tools CP-SAT.

Contract: solve_batch(payload) -> {ok, best, ...} compatible with app.py.
Core rules are hard constraints. The engine never returns an invalid/partial
schedule as an approvable result. If no feasible solution is found, it returns
an explicit diagnostic instead of silently relaxing the rules.
"""
from __future__ import annotations

import time
from collections import defaultdict

try:
    from ortools.sat.python import cp_model
except Exception as exc:  # pragma: no cover - depends on installed runtime
    cp_model = None
    _ORTOOLS_IMPORT_ERROR = str(exc)
else:
    _ORTOOLS_IMPORT_ERROR = ""


def _truth(value):
    return value is True


def _as_int(value, default, low=None, high=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if low is not None:
        result = max(low, result)
    if high is not None:
        result = min(high, result)
    return result


def _hour_limit_minutes(rules):
    """Read the configurable maximum weekly hour-spread; default is four hours."""
    raw = rules.get("maxHoursSpread", rules.get("maxHourSpread", rules.get("hourSpreadLimit", 4)))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 4.0
    # UI settings are in hours (2..4); explicit *_minutes values are also accepted.
    if rules.get("maxHoursSpreadMinutes") is not None:
        return max(0, _as_int(rules.get("maxHoursSpreadMinutes"), 240, 0, 100000))
    if value <= 0:
        return 240
    return int(value * 60) if value <= 24 else int(value)


def solve_batch(payload):
    if cp_model is None:
        return {
            "ok": False,
            "error": "محرك OR-Tools غير متاح. ثبّت المتطلبات عبر: python -m pip install -r requirements.txt",
            "details": _ORTOOLS_IMPORT_ERROR,
        }

    started = time.monotonic()
    tasks = payload.get("tasks") or []
    teachers = payload.get("teachers") or []
    rules = payload.get("rules") or {}
    exclusions = payload.get("exclusions") or []
    day_index = payload.get("dayIndex") or {}
    seconds = max(2.0, min(float(payload.get("seconds", 30) or 30), 300.0))
    seed = _as_int(payload.get("seed"), int(time.time()) % 2_000_000_000, 0, 2_000_000_000)
    allow_two_reserves = bool(payload.get("allowTwoReserves"))
    relax_single = bool(payload.get("relaxSingleDuty"))
    toggles = rules.get("constraintToggles") or {}

    def enabled(name, default=True):
        return bool(toggles.get(name, default))

    no_overlap_on = enabled("noOverlap", True)
    max_day_on = enabled("maxPerDay", True)
    avoid_adjacent = enabled("avoidAdjacent", True) and rules.get("avoidConsecutiveDay") is True
    subject_on = enabled("subjectRule", True)
    reserve_limit_on = enabled("reserveLimit", True)
    # These are mandatory policy constraints and cannot be disabled from the UI.
    reserve_no_lone_on = True
    balance_loads_on = True
    balance_days_on = True
    balance_hours_on = True
    max_per_day = _as_int(rules.get("maxPerDay", 2), 2, 1, 1000)
    subject_rule = str(rules.get("subjectTeacherRule", "must") or "must")
    reserve_quota = _as_int(rules.get("subjectReserveCount", 2), 2, 1, 1000)
    hour_spread_limit = _hour_limit_minutes(rules)
    require_consecutive_days = bool(rules.get("requireConsecutiveDays"))

    if not tasks:
        empty = {
            "assignments": [], "unfilled": [], "score": 0, "attempts": 0,
            "iterations": 0, "engine": "OR-Tools CP-SAT", "perfect": True,
            "bestPossible": True,
            "metrics": {"loadSpread": 0, "daySpread": 0, "minuteSpread": 0,
                        "singleDays": 0, "singleDutyViolations": 0, "loneReserves": 0},
            "diagnosis": [], "solverStatus": "OPTIMAL", "strictBalance": True,
            "elapsed": 0.0,
        }
        return {"ok": True, "best": empty, "attempts": 0, "iterations": 0,
                "timedOut": False, "elapsed": 0.0}
    if not teachers:
        return {"ok": False, "error": "لا يوجد أساتذة في قاعدة البيانات لتوزيع الحراسة.",
                "diagnosis": ["أضف الأساتذة المؤهلين ثم أعد التوليد."],
                "elapsed": round(time.monotonic() - started, 3)}

    # Normalize teacher IDs without changing the IDs returned to the UI.
    original_id_by_key = {}
    teacher_by_key = {}
    for teacher in teachers:
        key = str(teacher.get("id"))
        if key not in original_id_by_key:
            original_id_by_key[key] = teacher.get("id")
            teacher_by_key[key] = teacher
    teacher_keys = list(original_id_by_key)
    n, m = len(teacher_keys), len(tasks)
    tidx = {key: i for i, key in enumerate(teacher_keys)}
    subject_ids = [str(teacher_by_key[k].get("subjectId") or "") for k in teacher_keys]

    sessions = [task.get("se") or {} for task in tasks]
    dates_raw = [str(session.get("date") or "") for session in sessions]
    dates = sorted(set(dates_raw), key=lambda d: (day_index.get(d, 999999), d))
    day_id = {date: i for i, date in enumerate(dates)}
    day_of = [day_id[d] for d in dates_raw]
    starts = [str(session.get("start") or "") for session in sessions]
    ends = [str(session.get("end") or "") for session in sessions]
    roles_reserve = [str(task.get("role") or "guard") == "reserve" for task in tasks]
    minutes = [max(0, _as_int(task.get("mins", 0), 0, 0, 100000)) for task in tasks]
    task_subjects = [set(str(s) for s in (task.get("subjects") or [])) for task in tasks]
    session_keys = [
        str(session.get("id")) if session.get("id") is not None
        else f"{dates_raw[i]}|{starts[i]}|{ends[i]}"
        for i, session in enumerate(sessions)
    ]

    by_day = defaultdict(list)
    for i, day in enumerate(day_of):
        by_day[day].append(i)

    # Exemptions are hard constraints.
    exclusions_by_teacher = defaultdict(list)
    for exclusion in exclusions:
        key = str(exclusion.get("teacherId"))
        if key in tidx:
            exclusions_by_teacher[tidx[key]].append(exclusion)

    def is_exempt(t, i):
        for exclusion in exclusions_by_teacher.get(t, []):
            if _truth(exclusion.get("allGuard")) or str(exclusion.get("date") or "") == dates_raw[i]:
                ex_start, ex_end = exclusion.get("start"), exclusion.get("end")
                if not ex_start or not ex_end or (str(ex_start) < ends[i] and str(ex_end) > starts[i]):
                    return True
        return False

    # Choose a stable subset for the existing "some reserve" subject rule.
    subject_reserve_teachers = {}
    if subject_rule == "someReserve" and subject_on:
        subjects_by_session = defaultdict(set)
        for i, session_key in enumerate(session_keys):
            subjects_by_session[session_key].update(task_subjects[i])
        for session_key, subject_set in subjects_by_session.items():
            eligible = [t for t in range(n) if subject_ids[t] and subject_ids[t] in subject_set]
            # Deterministic order makes a repeated run reproducible.
            eligible.sort(key=lambda t: (str(teacher_keys[t]), t))
            subject_reserve_teachers[session_key] = set(eligible[:reserve_quota])

    def subject_blocked(t, i):
        sid = subject_ids[t]
        if not subject_on or not sid or sid not in task_subjects[i]:
            return False
        if subject_rule == "exempt":
            return True
        if subject_rule == "reserve":
            return not roles_reserve[i]
        if subject_rule in ("must", "guard"):
            return roles_reserve[i]
        if subject_rule == "someReserve":
            selected = subject_reserve_teachers.get(session_keys[i], set())
            return (t not in selected) if roles_reserve[i] else (t in selected)
        return False

    fixed = [-1] * m
    exemption_overrides = []
    for i, task in enumerate(tasks):
        fixed_id = task.get("fixed")
        if fixed_id is not None and str(fixed_id) in tidx:
            teacher_index = tidx[str(fixed_id)]
            if is_exempt(teacher_index, i):
                exemption_overrides.append(i)  # exemption takes priority over fixed assignment
            else:
                fixed[i] = teacher_index

    candidates = [[] for _ in range(m)]
    for i in range(m):
        for t in range(n):
            if is_exempt(t, i):
                continue
            if fixed[i] >= 0 and t != fixed[i]:
                continue
            if fixed[i] < 0 and subject_blocked(t, i):
                continue
            candidates[i].append(t)

    no_candidate = [i for i, row in enumerate(candidates) if not row]
    if no_candidate:
        return {
            "ok": False,
            "error": f"تعذر التوليد: توجد {len(no_candidate)} مهمة لا يوجد لها أستاذ مؤهل بعد تطبيق الإعفاءات وقاعدة المادة والتكليفات الإجبارية.",
            "diagnosis": [f"المهام بلا مرشحين: {', '.join(str(i + 1) for i in no_candidate[:30])}"],
            "noCandidateTasks": no_candidate,
            "elapsed": round(time.monotonic() - started, 3),
        }

    # Task conflicts: simultaneous overlap, and optionally adjacent sessions.
    conflicts = []
    if no_overlap_on or avoid_adjacent:
        for day, indexes in by_day.items():
            for pos, i in enumerate(indexes):
                for j in indexes[pos + 1:]:
                    overlap = starts[i] < ends[j] and starts[j] < ends[i]
                    adjacent = avoid_adjacent and (ends[i] == starts[j] or starts[i] == ends[j])
                    if (no_overlap_on and overlap) or adjacent:
                        conflicts.append((i, j))

    # All teachers who can perform at least one task are included in balancing.
    active = sorted({t for row in candidates for t in row})
    if not active:
        return {"ok": False, "error": "لا يوجد أستاذ مؤهل لأي مهمة.", "elapsed": round(time.monotonic()-started, 3)}

    model = cp_model.CpModel()
    x = {}
    for i in range(m):
        for t in candidates[i]:
            x[i, t] = model.NewBoolVar(f"assign_{i}_{t}")
        # Every post must be filled. No unfilled-task escape variable in the strict model.
        model.Add(sum(x[i, t] for t in candidates[i]) == 1)

    # In "mandatory subject teacher" mode, every non-exempt teacher whose
    # subject is examined in a session must receive at least one regular guard
    # assignment in that session. The JavaScript layer may create extra posts
    # for this purpose, but it must NOT pin a teacher to a specific post.
    if subject_on and subject_rule == "must":
        session_subject_union = defaultdict(set)
        session_task_indexes = defaultdict(list)
        for i, session_key in enumerate(session_keys):
            session_subject_union[session_key].update(task_subjects[i])
            session_task_indexes[session_key].append(i)
        for session_key, indexes in session_task_indexes.items():
            subjects_in_session = session_subject_union[session_key]
            for t in active:
                if not subject_ids[t] or subject_ids[t] not in subjects_in_session:
                    continue
                matching_guard_vars = [
                    x[i, t] for i in indexes
                    if not roles_reserve[i] and (i, t) in x
                ]
                # A teacher fully excluded from this session is not forced in.
                if matching_guard_vars:
                    model.Add(sum(matching_guard_vars) >= 1)

    for i, j in conflicts:
        for t in set(candidates[i]).intersection(candidates[j]):
            model.Add(x[i, t] + x[j, t] <= 1)

    # Workload and reserve variables.
    load, day_count, minutes_total, day_active, day_task_count = {}, {}, {}, {}, {}
    reserve_count, two_reserves = {}, {}
    single_vars = []
    subject_match_vars = []
    reserve_by_teacher_day = defaultdict(list)
    guard_by_teacher_day = defaultdict(list)

    for t in range(n):
        all_x = [x[i, t] for i in range(m) if (i, t) in x]
        load[t] = model.NewIntVar(0, m, f"load_{t}")
        model.Add(load[t] == sum(all_x))
        minutes_total[t] = model.NewIntVar(0, sum(minutes) or 1, f"minutes_{t}")
        model.Add(minutes_total[t] == sum(minutes[i] * x[i, t] for i in range(m) if (i, t) in x))
        active_day_vars = []
        for d, indexes in by_day.items():
            task_vars = [x[i, t] for i in indexes if (i, t) in x]
            if not task_vars:
                continue
            count = model.NewIntVar(0, len(task_vars), f"day_tasks_{t}_{d}")
            model.Add(count == sum(task_vars))
            day_task_count[t, d] = count
            is_active = model.NewBoolVar(f"day_active_{t}_{d}")
            model.Add(count >= 1).OnlyEnforceIf(is_active)
            model.Add(count == 0).OnlyEnforceIf(is_active.Not())
            day_active[t, d] = is_active
            active_day_vars.append(is_active)

            single = model.NewBoolVar(f"single_day_{t}_{d}")
            model.Add(count == 1).OnlyEnforceIf(single)
            model.Add(count != 1).OnlyEnforceIf(single.Not())
            single_vars.append(single)

            for i in indexes:
                if (i, t) not in x:
                    continue
                if roles_reserve[i]:
                    reserve_by_teacher_day[t, d].append(x[i, t])
                else:
                    guard_by_teacher_day[t, d].append(x[i, t])
        day_count[t] = model.NewIntVar(0, len(dates), f"day_count_{t}")
        model.Add(day_count[t] == sum(active_day_vars))

        rvars = [x[i, t] for i in range(m) if (i, t) in x and roles_reserve[i]]
        reserve_count[t] = model.NewIntVar(0, len(rvars), f"reserve_count_{t}")
        model.Add(reserve_count[t] == sum(rvars))
        if reserve_limit_on and rvars:
            model.Add(reserve_count[t] <= (2 if allow_two_reserves else 1))
        if allow_two_reserves and reserve_limit_on and rvars:
            two_reserves[t] = model.NewBoolVar(f"two_reserves_{t}")
            model.Add(reserve_count[t] >= 2).OnlyEnforceIf(two_reserves[t])
            model.Add(reserve_count[t] <= 1).OnlyEnforceIf(two_reserves[t].Not())
            # Two reserves must be on two different days.
            for d, indexes in by_day.items():
                rday = [x[i, t] for i in indexes if (i, t) in x and roles_reserve[i]]
                if rday:
                    model.Add(sum(rday) <= 1)
            # Exception belongs only to the most heavily assigned teacher.
            for other in active:
                if other != t:
                    model.Add(load[t] >= load[other]).OnlyEnforceIf(two_reserves[t])

    # A reserve post cannot be a teacher's only assignment for that day.
    # It must be accompanied by at least one regular guard task on the same day.
    if reserve_no_lone_on:
        for (t, d), reserve_vars in reserve_by_teacher_day.items():
            guards = guard_by_teacher_day.get((t, d), [])
            for reserve_var in reserve_vars:
                if guards:
                    model.Add(sum(guards) >= reserve_var)
                else:
                    model.Add(reserve_var == 0)

    # At most one single-duty day per week, unless the explicit break option is on.
    if not relax_single:
        for t in active:
            own_singles = []
            for d in by_day:
                # Only the single vars that correspond to an existing teacher/day count.
                # Recreate a stable lookup by name through the day task variable.
                if (t, d) in day_task_count:
                    sv = model.NewBoolVar(f"single_limit_{t}_{d}")
                    count = day_task_count[t, d]
                    model.Add(count == 1).OnlyEnforceIf(sv)
                    model.Add(count != 1).OnlyEnforceIf(sv.Not())
                    own_singles.append(sv)
            if own_singles:
                model.Add(sum(own_singles) <= 1)

    # Consecutive-day grouping, if enabled: no gap of an unassigned exam day between assigned days.
    if require_consecutive_days:
        for t in active:
            for d in range(max(0, len(dates) - 2)):
                if (t, d) in day_active and (t, d + 2) in day_active:
                    middle = day_active.get((t, d + 1))
                    if middle is not None:
                        model.Add(day_active[t, d] + day_active[t, d + 2] <= 1 + middle)
                    else:
                        model.Add(day_active[t, d] + day_active[t, d + 2] <= 1)

    # Subject-teacher-first: a strong optimization preference, not an impossible
    # requirement that every room be staffed by a subject teacher.
    if subject_on:
        for i in range(m):
            if roles_reserve[i] or not task_subjects[i]:
                continue
            matching = [t for t in candidates[i] if subject_ids[t] and subject_ids[t] in task_subjects[i]]
            if matching:
                subject_match_vars.extend(x[i, t] for t in matching)

    # Strict load/day/hour spreads across every eligible teacher.
    load_spread = model.NewIntVar(0, m, "load_spread")
    day_spread = model.NewIntVar(0, len(dates), "day_spread")
    minute_spread = model.NewIntVar(0, sum(minutes) or 1, "minute_spread")
    max_load = model.NewIntVar(0, m, "max_load")
    min_load = model.NewIntVar(0, m, "min_load")
    max_days = model.NewIntVar(0, len(dates), "max_days")
    min_days = model.NewIntVar(0, len(dates), "min_days")
    max_minutes = model.NewIntVar(0, sum(minutes) or 1, "max_minutes")
    min_minutes = model.NewIntVar(0, sum(minutes) or 1, "min_minutes")
    model.AddMaxEquality(max_load, [load[t] for t in active])
    model.AddMinEquality(min_load, [load[t] for t in active])
    model.AddMaxEquality(max_days, [day_count[t] for t in active])
    model.AddMinEquality(min_days, [day_count[t] for t in active])
    model.AddMaxEquality(max_minutes, [minutes_total[t] for t in active])
    model.AddMinEquality(min_minutes, [minutes_total[t] for t in active])
    model.Add(load_spread == max_load - min_load)
    model.Add(day_spread == max_days - min_days)
    model.Add(minute_spread == max_minutes - min_minutes)
    if balance_loads_on:
        model.Add(load_spread <= 1)
    if balance_days_on:
        model.Add(day_spread <= 1)
    if balance_hours_on:
        model.Add(minute_spread <= hour_spread_limit)

    # Prefer subject teachers, avoid unnecessary single-duty days when allowed,
    # and minimize hour spread after hard balance constraints have been satisfied.
    # CP-SAT integer objective: weights are ordered so one subject mismatch costs
    # more than a small improvement in minute spread.
    subject_reward = sum(subject_match_vars) if subject_match_vars else 0
    single_penalty = sum(single_vars) if single_vars else 0
    objective = minute_spread * 100 + single_penalty * 10000 - subject_reward * 100000
    model.Minimize(objective)

    # Warm-start from the previous result, if it still matches the task count.
    warm = payload.get("warmStart")
    if isinstance(warm, list) and len(warm) == m:
        for i, assigned_id in enumerate(warm):
            assigned_key = str(assigned_id) if assigned_id is not None else None
            for t in candidates[i]:
                model.AddHint(x[i, t], 1 if teacher_keys[t] == assigned_key else 0)

    deadline = started + seconds
    best_assignment = None
    best_values = None
    total_branches = 0
    total_conflicts = 0
    final_status = None
    runs = 0

    # Repeated CP-SAT runs with changing seeds and no-good cuts explore genuinely
    # different full schedules instead of repeatedly patching the same assignments.
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.2, min(8.0, remaining))
        solver.parameters.num_search_workers = max(1, min(8, (os_cpu_count() or 8)))
        solver.parameters.random_seed = (seed + runs * 104729) % 2_000_000_000
        solver.parameters.randomize_search = True
        solver.parameters.log_search_progress = False
        solver.parameters.cp_model_presolve = True
        status = solver.Solve(model)
        runs += 1
        total_branches += solver.NumBranches()
        total_conflicts += solver.NumConflicts()
        final_status = status

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            assignment = [-1] * m
            for i in range(m):
                for t in candidates[i]:
                    if solver.Value(x[i, t]):
                        assignment[i] = t
                        break
            if all(t >= 0 for t in assignment):
                # This model's constraints are strict; keep the first valid solution,
                # but continue seeking a better objective unless it is proven optimal.
                if best_assignment is None or solver.ObjectiveValue() < best_values["objective"]:
                    best_assignment = assignment
                    best_values = {"objective": solver.ObjectiveValue(), "status": status}
                if status == cp_model.OPTIMAL:
                    break
                # Exclude this complete assignment to force a different solution next run.
                selected = [x[i, assignment[i]] for i in range(m)]
                model.Add(sum(selected) <= m - 1)
            else:
                break
        elif status == cp_model.INFEASIBLE:
            break
        # UNKNOWN means no feasible result in this slice; use a different seed.

    elapsed = round(time.monotonic() - started, 3)
    if best_assignment is None:
        if final_status == cp_model.INFEASIBLE:
            reason = "أثبت المحرك أن القيود الحالية لا تسمح بحل كامل. لم يتم تخفيف أي قيد ولم يتم إنشاء توزيع مخالف."
            status_name = "INFEASIBLE"
        else:
            reason = "انتهت مهلة البحث دون العثور على حل صالح. لم يتم اعتماد توزيع جزئي؛ زد زمن البحث أو راجع القيود المتعارضة."
            status_name = "UNKNOWN"
        return {
            "ok": False, "error": reason,
            "diagnosis": [
                "تحقق من التكليفات الإجبارية والإعفاءات وقاعدة أستاذ المادة.",
                "تحقق من إمكان توزيع الحصص على جميع الأساتذة المؤهلين مع فارق الحصص والأيام المحدد.",
                f"قيد فارق الساعات المطبق: {hour_spread_limit // 60} ساعة كحد أقصى." if balance_hours_on else "قيد توازن الساعات غير مفعّل.",
            ],
            "solverStatus": status_name, "runs": runs,
            # Attempts means actual CP-SAT solve invocations, not branch count.
            # Branches may legitimately be zero when presolve proves infeasibility.
            "attempts": runs, "branches": total_branches, "iterations": total_conflicts,
            "timedOut": status_name == "UNKNOWN", "elapsed": elapsed,
        }

    assignment_idx = best_assignment
    assignment_ids = [original_id_by_key[teacher_keys[t]] for t in assignment_idx]
    loads = [sum(1 for assigned in assignment_idx if assigned == t) for t in range(n)]
    day_sets = [set(day_of[i] for i, assigned in enumerate(assignment_idx) if assigned == t) for t in range(n)]
    hour_totals = [sum(minutes[i] for i, assigned in enumerate(assignment_idx) if assigned == t) for t in range(n)]
    relevant_loads = [loads[t] for t in active]
    relevant_days = [len(day_sets[t]) for t in active]
    relevant_minutes = [hour_totals[t] for t in active]
    load_spread_value = max(relevant_loads, default=0) - min(relevant_loads, default=0)
    day_spread_value = max(relevant_days, default=0) - min(relevant_days, default=0)
    minute_spread_value = max(relevant_minutes, default=0) - min(relevant_minutes, default=0)

    single_days = 0
    lone_reserves = 0
    singles_per_teacher = [0] * n
    reserves_per_teacher = [0] * n
    for t in range(n):
        for d in range(len(dates)):
            indexes = [i for i, assigned in enumerate(assignment_idx) if assigned == t and day_of[i] == d]
            if len(indexes) == 1:
                single_days += 1
                singles_per_teacher[t] += 1
                if roles_reserve[indexes[0]]:
                    lone_reserves += 1
            reserves_per_teacher[t] += sum(1 for i in indexes if roles_reserve[i])

    single_violations = sum(max(0, count - 1) for count in singles_per_teacher) if not relax_single else 0
    subject_matches = sum(1 for i, t in enumerate(assignment_idx)
                          if not roles_reserve[i] and subject_ids[t] and subject_ids[t] in task_subjects[i])
    proven_optimal = (final_status == cp_model.OPTIMAL)
    diagnosis = ["تم العثور على توزيع كامل يحقق القيود الصلبة المفعّلة."]
    if not proven_optimal:
        diagnosis.append("الحل صالح، لكن لم يثبت المحرك أنه الحل الأمثل قبل انتهاء زمن البحث.")
    best = {
        "assignments": assignment_ids,
        "unfilled": [],
        "score": int(max(0, minute_spread_value)),
        "attempts": runs,
        "branches": total_branches,
        "iterations": total_conflicts,
        "engine": "OR-Tools CP-SAT (strict multi-start)",
        "perfect": True,
        "bestPossible": proven_optimal,
        "key": [0, load_spread_value, day_spread_value, minute_spread_value, single_violations, -subject_matches],
        "metrics": {
            "loadSpread": load_spread_value,
            "daySpread": day_spread_value,
            "minuteSpread": minute_spread_value,
            "singleDays": single_days,
            "singleDutyViolations": single_violations,
            "loneReserves": lone_reserves,
            "subjectMatches": subject_matches,
            "eligibleTeachers": len(active),
            "runs": runs,
        },
        "diagnosis": diagnosis,
        "lowerBounds": {"unfilled": 0},
        "exemptionOverrides": exemption_overrides,
        "fixedConflicts": [],
        "solverStatus": "OPTIMAL" if proven_optimal else "FEASIBLE",
        "strictBalance": True,
        "elapsed": elapsed,
    }
    return {"ok": True, "best": best, "attempts": runs, "branches": total_branches,
            "iterations": total_conflicts, "timedOut": not proven_optimal,
            "elapsed": elapsed}


def os_cpu_count():
    try:
        import os
        return os.cpu_count()
    except Exception:
        return 8
