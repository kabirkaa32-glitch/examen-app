"""Python/SQLite port of the original Electron db.js; keeps the original schema."""
import sqlite3, json, hashlib, secrets, hmac
from pathlib import Path
SCHEMA=Path(__file__).with_name('schema.sql')
SETTINGS=['schoolName','directorate','wilaya','address','schoolYear','semester','subgroupCount','printOrientation']
RULES=['guardsPerRoom','reserveGuards','maxPerDay','avoidConsecutiveDay','requireConsecutiveDays','balance','subjectTeacherRule','subjectRuleExplicit','subjectReserveCount','balanceExtraGuards']
def connect(path):
 c=sqlite3.connect(path, timeout=20); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA foreign_keys=ON'); c.executescript(SCHEMA.read_text(encoding='utf-8')); c.commit(); return c
def _extra(o, known): return json.dumps({k:v for k,v in (o or {}).items() if k not in known},ensure_ascii=False)
def _group(rows,key,val):
 out={}
 for r in rows: out.setdefault(str(r[key]),[]).append(r[val])
 return out
def load_all(c):
 allrows=lambda q:[dict(x) for x in c.execute(q).fetchall()]
 s=dict(c.execute('SELECT * FROM settings WHERE id=1').fetchone()); r=dict(c.execute('SELECT * FROM invigilation_rules WHERE id=1').fetchone())
 stu=_group(allrows('SELECT * FROM assignment_students'),'assignment_id','student_id'); grp=_group(allrows('SELECT * FROM assignment_groups'),'assignment_id','group_id'); dr=_group(allrows('SELECT * FROM double_room_rule_rooms'),'rule_id','room_id')
 def e(v): return '' if v is None else v
 return {'settings':{**json.loads(s['extra_json'] or '{}'),'schoolName':s['school_name'],'directorate':s['directorate'],'wilaya':s['wilaya'],'address':s['address'],'schoolYear':s['school_year'],'semester':s['semester'],'subgroupCount':s['subgroup_count'],'printOrientation':s['print_orientation']},
 'invigilationRules':{**json.loads(r['extra_json'] or '{}'),'guardsPerRoom':r['guards_per_room'],'reserveGuards':r['reserve_guards'],'maxPerDay':r['max_per_day'],'avoidConsecutiveDay':bool(r['avoid_consecutive_day']),'requireConsecutiveDays':bool(r['require_consecutive_days']),'balance':r['balance'],'subjectTeacherRule':r['subject_teacher_rule'],'subjectRuleExplicit':bool(r['subject_rule_explicit']),'subjectReserveCount':r['subject_reserve_count'],'balanceExtraGuards':bool(r['balance_extra_guards'])},
 'groups':[{'id':x['id'],'level':x['level'],'branch':x['branch'],'number':x['number']} for x in allrows('SELECT * FROM groups')],
 'students':[{'id':x['id'],'studentNo':x['student_no'],'last':x['last_name'],'first':x['first_name'],'groupId':e(x['group_id']),'subgroup':x['subgroup']} for x in allrows('SELECT * FROM students')],
 'teachers':[{'id':x['id'],'last':x['last_name'],'first':x['first_name'],'subjectId':e(x['subject_id'])} for x in allrows('SELECT * FROM teachers')],
 'subjects':[{'id':x['id'],'name':x['name']} for x in allrows('SELECT * FROM subjects')],
 'rooms':[{'id':x['id'],'number':x['number'],'type':x['type'],'capacity':x['capacity'],'note':x['note']} for x in allrows('SELECT * FROM rooms')],
 'examSessions':[{'id':x['id'],'day':x['day'],'date':x['date'],'start':x['start'],'end':x['end']} for x in allrows('SELECT * FROM exam_sessions')],
 'examBookings':[{'id':x['id'],'sessionId':x['session_id'],'subjectId':e(x['subject_id']),'groupId':e(x['group_id'])} for x in allrows('SELECT * FROM exam_bookings')],
 'assignments':[dict({'id':x['id'],'groupId':e(x['group_id']),'roomId':e(x['room_id']),'sub':x['sub'],'count':x['count'],'studentIds':stu.get(str(x['id']),[]),'manual':bool(x['manual'])}, **({'merged':True,'groupIds':grp.get(str(x['id']),[])} if x['merged'] else {})) for x in allrows('SELECT * FROM assignments')],
 'absences':[{'id':x['id'],'date':x['date'],'time':x['time'],'subjectId':e(x['subject_id']),'groupId':e(x['group_id']),'studentId':e(x['student_id']),'justified':x['justified'],'reason':x['reason'],'sessionId':e(x['session_id'])} for x in allrows('SELECT * FROM absences')],
 'invigilations':[{'id':x['id'],'date':x['date'],'period':x['period'],'time':x['time'],'teacherId':e(x['teacher_id']),'roomId':e(x['room_id']),'status':x['status'],'justified':x['justified'],'note':x['note'],'sessionId':e(x['session_id']),'seat':x['seat'],'mandatory':bool(x['mandatory'])} for x in allrows('SELECT * FROM invigilations')],
 'teacherGuardAbsences':[{'id':x['id'],'sessionId':e(x['session_id']),'date':x['date'],'period':x['period'],'time':x['time'],'teacherId':e(x['teacher_id']),'justified':x['justified'],'note':x['note']} for x in allrows('SELECT * FROM teacher_guard_absences')],
 'doubleRoomRules':[{'id':x['id'],'sessionId':x['session_id'],'roomIds':dr.get(str(x['id']),[]),'count':x['count']} for x in allrows('SELECT * FROM double_room_rules')],
 'exclusionRules':[{'id':x['id'],'teacherId':x['teacher_id'],'date':x['date'] or '', 'start':x['start'] or '', 'end':x['end'] or '', 'allGuard':not bool(x['date'])} for x in allrows('SELECT * FROM exclusion_rules')]}
def save_all(c,d):
 def insert(sql, rows): c.executemany(sql,rows)
 def n(v): return None if v is None or v=='' else v
 s=d.get('settings') or {}; r=d.get('invigilationRules') or {}
 tables=['assignment_students','assignment_groups','double_room_rule_rooms','assignments','absences','invigilations','teacher_guard_absences','double_room_rules','exclusion_rules','exam_bookings','exam_sessions','students','teachers','rooms','subjects','groups']
 with c:
  for t in tables: c.execute('DELETE FROM '+t)
  c.execute('UPDATE settings SET school_name=?,directorate=?,wilaya=?,address=?,school_year=?,semester=?,subgroup_count=?,print_orientation=?,extra_json=? WHERE id=1',(s.get('schoolName',''),s.get('directorate',''),s.get('wilaya',''),s.get('address',''),s.get('schoolYear',''),s.get('semester','الأول'),s.get('subgroupCount',4),'landscape' if s.get('printOrientation')=='landscape' else 'portrait',_extra(s,SETTINGS)))
  c.execute('UPDATE invigilation_rules SET guards_per_room=?,reserve_guards=?,max_per_day=?,avoid_consecutive_day=?,require_consecutive_days=?,balance=?,subject_teacher_rule=?,subject_rule_explicit=?,subject_reserve_count=?,balance_extra_guards=?,extra_json=? WHERE id=1',(r.get('guardsPerRoom',1),r.get('reserveGuards',1),r.get('maxPerDay',2),int(bool(r.get('avoidConsecutiveDay'))),int(bool(r.get('requireConsecutiveDays'))),r.get('balance','equal'),r.get('subjectTeacherRule','must'),int(bool(r.get('subjectRuleExplicit'))),r.get('subjectReserveCount',2),int(bool(r.get('balanceExtraGuards'))),_extra(r,RULES)))
  insert('INSERT OR REPLACE INTO groups VALUES (?,?,?,?)',[(x['id'],x.get('level',''),x.get('branch',''),str(x.get('number',''))) for x in d.get('groups',[])])
  insert('INSERT OR REPLACE INTO subjects VALUES (?,?)',[(x['id'],x.get('name','')) for x in d.get('subjects',[])])
  insert('INSERT OR REPLACE INTO teachers VALUES (?,?,?,?)',[(x['id'],x.get('last',''),x.get('first',''),n(x.get('subjectId'))) for x in d.get('teachers',[])])
  insert('INSERT OR REPLACE INTO rooms VALUES (?,?,?,?,?)',[(x['id'],str(x.get('number','')),x.get('type',''),int(x.get('capacity') or 0),x.get('note','')) for x in d.get('rooms',[])])
  insert('INSERT OR REPLACE INTO students VALUES (?,?,?,?,?,?)',[(x['id'],x.get('studentNo',''),x.get('last',''),x.get('first',''),n(x.get('groupId')),x.get('subgroup','')) for x in d.get('students',[])])
  insert('INSERT OR REPLACE INTO exam_sessions VALUES (?,?,?,?,?)',[(x['id'],x.get('day',''),x.get('date',''),x.get('start',''),x.get('end','')) for x in d.get('examSessions',[])])
  insert('INSERT OR REPLACE INTO exam_bookings VALUES (?,?,?,?)',[(x['id'],x.get('sessionId'),n(x.get('subjectId')),n(x.get('groupId'))) for x in d.get('examBookings',[])])
  for x in d.get('assignments',[]):
   c.execute('INSERT OR REPLACE INTO assignments VALUES (?,?,?,?,?,?,?)',(x['id'],n(x.get('groupId')),n(x.get('roomId')),x.get('sub','كامل'),x.get('count',0),int(bool(x.get('manual'))),int(bool(x.get('merged')))))
   insert('INSERT OR IGNORE INTO assignment_students VALUES (?,?)',[(x['id'],i) for i in x.get('studentIds',[])])
   insert('INSERT OR IGNORE INTO assignment_groups VALUES (?,?)',[(x['id'],i) for i in x.get('groupIds',[])])
  insert('INSERT OR REPLACE INTO absences VALUES (?,?,?,?,?,?,?,?,?)',[(x['id'],n(x.get('date')),x.get('time',''),n(x.get('subjectId')),n(x.get('groupId')),n(x.get('studentId')),n(x.get('sessionId')),x.get('justified',''),x.get('reason','')) for x in d.get('absences',[])])
  insert('INSERT OR REPLACE INTO invigilations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',[(x['id'],n(x.get('date')),x.get('period',''),x.get('time',''),n(x.get('teacherId')),n(x.get('roomId')),n(x.get('sessionId')),'احتياط' if x.get('status')=='احتياط' else 'حارس',x.get('justified',''),x.get('note',''),x.get('seat'),int(bool(x.get('mandatory')))) for x in d.get('invigilations',[])])
  insert('INSERT OR REPLACE INTO teacher_guard_absences VALUES (?,?,?,?,?,?,?,?)',[(x['id'],n(x.get('sessionId')),n(x.get('date')),x.get('period',''),x.get('time',''),n(x.get('teacherId')),x.get('justified',''),x.get('note','')) for x in d.get('teacherGuardAbsences',[])])
  for x in d.get('doubleRoomRules',[]):
   c.execute('INSERT OR REPLACE INTO double_room_rules VALUES (?,?,?)',(x['id'],x.get('sessionId'),x.get('count',1))); insert('INSERT OR IGNORE INTO double_room_rule_rooms VALUES (?,?)',[(x['id'],i) for i in x.get('roomIds',[])])
  insert('INSERT OR REPLACE INTO exclusion_rules VALUES (?,?,?,?,?)',[(x['id'],x.get('teacherId'),None if x.get('allGuard') else n(x.get('date')),None if x.get('allGuard') else n(x.get('start')),None if x.get('allGuard') else n(x.get('end'))) for x in d.get('exclusionRules',[])])
def get_user(c): return c.execute('SELECT username FROM app_user WHERE id=1').fetchone()['username'] or 'admin'
def set_user(c,name): c.execute('UPDATE app_user SET username=? WHERE id=1',(name,)); c.commit()
def set_password(c,pw):
 salt=secrets.token_hex(16); hashed=hashlib.scrypt(pw.encode(),salt=salt.encode(),n=16384,r=8,p=1,dklen=32).hex(); c.execute('UPDATE app_user SET password_hash=?,password_salt=? WHERE id=1',(hashed,salt)); c.commit()
def check_password(c,pw):
 r=c.execute('SELECT password_hash,password_salt FROM app_user WHERE id=1').fetchone()
 if not r['password_hash']: return pw=='admin123'
 try: return hmac.compare_digest(hashlib.scrypt(pw.encode(),salt=r['password_salt'].encode(),n=16384,r=8,p=1,dklen=32).hex(),r['password_hash'])
 except Exception:return False
def reset_account(c): c.execute("UPDATE app_user SET username='admin',password_hash='',password_salt='' WHERE id=1"); c.commit()
