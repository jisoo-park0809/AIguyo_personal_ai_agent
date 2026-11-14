"""생성 agent가 커리큘럼을 조금씩 쓰고 고치는 작업 공간.

AI는 커리큘럼 전체를 한 번에 글로 쓰지 않고, 이 작업 공간의 함수(tool)로 교과목을 하나씩 추가·수정한다.
그래서 수정할 때 요청하지 않은 부분이 바뀌지 않고, 모든 변경이 change_log에 남는다.
"""
import hashlib
import math
from typing import Dict, List, Optional

from .schemas import (Change, Curriculum, Goal, GenerationInput, ProficiencyMethod, Project, Quiz, QuizQuestion,
                      SkillTarget, Subject, Unit)

QUIZ_CHOICES = 4


class Workspace:
    def __init__(self, inp: GenerationInput):
        self.inp = inp
        self.cur = Curriculum()
        self.touched: set = set()  # 수정 모드에서 이번에 고친 교과목 id
        self.quiz_stale: set = set()  # 퀴즈를 쓴 뒤에 내용이 바뀐 교과목 id
        self.legacy = False  # 수정 모드: 숙련목표·퀴즈가 없던 예전 커리큘럼
        if inp.previous_curriculum:
            self.cur = Curriculum.model_validate(inp.previous_curriculum)
            self.cur.change_log = []
            self.cur.check_report = {}
            self.cur.compliance = []
            self.legacy = not (self.cur.skill_targets or self.cur.quizzes)

    # ---------- 읽기 ----------

    def subject(self, sid: str) -> Optional[Subject]:
        return next((s for s in self.cur.subjects if s.id == sid), None)

    def summary(self) -> Dict:
        return {
            "intent_summary": self.cur.intent_summary,
            "learning_goals": [g.model_dump() for g in self.cur.learning_goals],
            "subjects": [
                {"id": s.id, "title": s.title, "category": s.category, "hours": s.hours,
                 "theory/practice/project": [s.theory_hours, s.practice_hours, s.project_hours],
                 "prerequisites": s.prerequisites, "concepts_taught": s.concepts_taught,
                 "company_task_ids": s.company_task_ids, "units": len(s.units)}
                for s in self.cur.subjects
            ],
            "projects": [p.model_dump() for p in self.cur.projects],
            "skill_targets": [t.model_dump() for t in self.cur.skill_targets],
            "quizzes": [{"id": q.id, "subject_id": q.subject_id, "week": self.quiz_week(q), "questions": len(q.questions)}
                        for q in self.cur.quizzes],
            "proficiency_methods": [m.method for m in self.cur.proficiency_methods],
            "schedule": self.schedule(),
        }

    def quiz_week(self, q: Quiz) -> int:
        """퀴즈 주차: 직접 정하지 않았으면 교과목이 끝나는 주차 (코드가 계산)."""
        if q.week:
            return q.week
        w = next((w for w in self.schedule()["weeks"] if w["id"] == q.subject_id), None)
        return w["week_end"] if w else 0

    def fingerprint(self) -> str:
        """판단 규정 재판정이 필요한지 보려고 커리큘럼 내용의 지문을 만든다."""
        body = self.cur.model_dump_json(include={"subjects", "projects", "skill_targets", "quizzes", "proficiency_methods"})
        return hashlib.md5(body.encode("utf-8")).hexdigest()

    def schedule(self) -> Dict:
        """교과목 순서와 시간으로 주차를 계산한다 (AI가 아니라 코드가 계산)."""
        c = self.inp.course
        per_week = c.daily_hours * c.days_per_week
        rows, acc = [], 0.0
        for s in self.cur.subjects:
            start = acc
            acc += s.hours
            rows.append({"id": s.id, "week_start": int(start // per_week) + 1,
                         "week_end": max(int(math.ceil(acc / per_week)), int(start // per_week) + 1)})
        return {"total_hours": acc, "hours_per_week": per_week,
                "total_days": round(acc / c.daily_hours, 1) if c.daily_hours else 0,
                "total_weeks": math.ceil(acc / per_week) if per_week else 0, "weeks": rows}

    # ---------- 쓰기 ----------

    def _log(self, target: str, action: str, reason: str, source: str):
        self.cur.change_log.append(Change(target=target, action=action, reason=reason, source=source))

    def set_plan(self, intent_summary: str, learning_goals: List[Dict]) -> Dict:
        self.cur.intent_summary = intent_summary
        self.cur.learning_goals = [Goal(id=g.get("id") or f"G{i + 1}", text=g["text"]) for i, g in enumerate(learning_goals)]
        return {"ok": True, "learning_goals": [g.id for g in self.cur.learning_goals]}

    def add_subject(self, subject: Dict, position: Optional[int] = None) -> Dict:
        s = Subject.model_validate(subject)
        if not s.id or self.subject(s.id):
            s.id = f"S{len(self.cur.subjects) + 1:02d}"
            while self.subject(s.id):
                s.id = f"S{int(s.id[1:]) + 1:02d}"
        if position is None or position >= len(self.cur.subjects):
            self.cur.subjects.append(s)
        else:
            self.cur.subjects.insert(max(position, 0), s)
        if self.inp.revise_mode:
            self.touched.add(s.id)
            self._log(s.id, "추가", s.rationale or "교과목 추가", "수정")
        return {"ok": True, "id": s.id, "hours": s.hours}

    def update_subject(self, sid: str, fields: Dict, reason: str, source: str = "설계") -> Dict:
        s = self.subject(sid)
        if not s:
            return {"ok": False, "error": f"교과목 {sid} 없음. get_draft로 id를 확인하세요."}
        data = s.model_dump()
        unknown = [k for k in fields if k not in data or k == "id"]
        if unknown:
            return {"ok": False, "error": f"바꿀 수 없는 항목: {unknown}"}
        data.update(fields)
        new = Subject.model_validate(data)
        if new.units and "units" not in fields and abs(new.hours - s.hours) > 1e-6:
            self._scale_units(new, new.hours)  # 시간이 바뀌면 단원도 비율대로 맞춘다
        self.cur.subjects[self.cur.subjects.index(s)] = new
        self.touched.add(sid)
        if any(q.subject_id == sid for q in self.cur.quizzes) and set(fields) & {"title", "goals", "topics", "concepts_taught"}:
            self.quiz_stale.add(sid)
        self._log(sid, "수정", reason, source)
        return {"ok": True, "id": sid, "hours": new.hours}

    def remove_subject(self, sid: str, reason: str) -> Dict:
        s = self.subject(sid)
        if not s:
            return {"ok": False, "error": f"교과목 {sid} 없음"}
        self.cur.subjects.remove(s)
        for p in self.cur.projects:
            p.subject_ids = [x for x in p.subject_ids if x != sid]
        self.cur.quizzes = [q for q in self.cur.quizzes if q.subject_id != sid]
        for t in self.cur.skill_targets:
            t.subject_ids = [x for x in t.subject_ids if x != sid]
        self._log(sid, "삭제", reason, "설계")
        return {"ok": True}

    def move_subject(self, sid: str, position: int, reason: str) -> Dict:
        s = self.subject(sid)
        if not s:
            return {"ok": False, "error": f"교과목 {sid} 없음"}
        self.cur.subjects.remove(s)
        self.cur.subjects.insert(max(0, min(position, len(self.cur.subjects))), s)
        self._log(sid, "이동", reason, "설계")
        return {"ok": True, "order": [x.id for x in self.cur.subjects]}

    def set_project(self, project: Dict) -> Dict:
        p = Project.model_validate(project)
        if not p.id:
            p.id = f"P{len(self.cur.projects) + 1}"
        self.cur.projects = [x for x in self.cur.projects if x.id != p.id] + [p]
        missing = [x for x in p.subject_ids if not self.subject(x)]
        return {"ok": True, "id": p.id, "unknown_subject_ids": missing}

    def allocate_hours(self, weights: Dict[str, float], theory_share: Dict[str, float], reason: str) -> Dict:
        """AI가 정한 비중으로 코드가 시간을 나눈다 (원칙 p1).

        프로젝트 교과목끼리 프로젝트 목표 시간을, 나머지 교과목끼리 남은 시간을 비중대로 나눈다.
        하루 훈련시간 단위로 반올림하고, 남는 시간은 가장 큰 교과목에 더한다. 단원이 있으면 비율대로 다시 나눈다.
        """
        c = self.inp.course
        step = c.daily_hours or 1
        unknown = [k for k in weights if not self.subject(k)]
        if unknown:
            return {"ok": False, "error": f"없는 교과목 id: {unknown}"}
        missing = [s.id for s in self.cur.subjects if s.id not in weights]
        if missing:
            return {"ok": False, "error": f"모든 교과목의 비중이 필요함. 빠진 id: {missing}"}
        # 기업 과제가 연결됐거나 프로젝트 시간이 있는 교과목은 프로젝트로 본다
        for s in self.cur.subjects:
            if s.company_task_ids or s.project_hours > 0:
                s.category = "프로젝트"
        proj = [s for s in self.cur.subjects if s.category == "프로젝트"]
        rest = [s for s in self.cur.subjects if s.category != "프로젝트"]
        proj_total = math.ceil(self.inp.project_ratio * c.total_hours / step) * step if proj else 0
        groups = [(proj, proj_total), (rest, c.total_hours - proj_total)]
        if not rest:
            groups = [(proj, c.total_hours)]
        for subs, budget in groups:
            if not subs:
                continue
            wsum = sum(max(weights[s.id], 0) for s in subs) or len(subs)
            hours = {s.id: max(step, round(budget * max(weights[s.id], 0) / wsum / step) * step) for s in subs}
            biggest = max(subs, key=lambda s: hours[s.id])
            hours[biggest.id] += budget - sum(hours.values())
            for s in subs:
                self._set_hours(s, hours[s.id], theory_share.get(s.id), step)
        self.touched |= set(weights)
        self._log("전체", "수정", reason, "시간 배분")
        return {"ok": True, "hours": {s.id: s.hours for s in self.cur.subjects},
                "total": sum(s.hours for s in self.cur.subjects),
                "project_hours": sum(s.project_hours for s in self.cur.subjects)}

    def _set_hours(self, s: Subject, hours: float, share: Optional[float], step: float):
        if s.category == "프로젝트":
            s.theory_hours, s.practice_hours, s.project_hours = 0, 0, hours
        else:
            old = s.theory_hours + s.practice_hours
            ratio = share if share is not None else (s.theory_hours / old if old else 0.3)
            s.theory_hours = min(hours, round(hours * ratio / (step / 2)) * (step / 2))
            s.practice_hours, s.project_hours = hours - s.theory_hours, 0
        self._scale_units(s, hours)

    @staticmethod
    def _scale_units(s: Subject, hours: float):
        if not s.units:
            return
        total = sum(max(u.hours, 0) for u in s.units) or len(s.units)
        used = 0.0
        for u in s.units[:-1]:
            u.hours = max(1, round(hours * (max(u.hours, 0) or total / len(s.units)) / total))
            used += u.hours
        s.units[-1].hours = hours - used
        s.units = [u for u in s.units if u.hours > 0]

    def write_units(self, sid: str, units: List[Dict]) -> Dict:
        s = self.subject(sid)
        if not s:
            return {"ok": False, "error": f"교과목 {sid} 없음"}
        if not units:
            return {"ok": False, "error": "단원이 비어 있음"}
        # AI가 적은 시간은 비중으로 보고, 코드가 교과목 시간에 맞춰 나눈다 (원칙 p1)
        s.units = [Unit.model_validate(u) for u in units]
        self._scale_units(s, s.hours)
        return {"ok": True, "id": sid, "unit_hours": [u.hours for u in s.units], "subject_hours": s.hours}

    # ---------- 숙련목표·퀴즈·숙련도 향상 방법 (운영 규정의 숙련목표·주기적 평가·보충학습) ----------

    def set_skill_targets(self, targets: List[Dict]) -> Dict:
        items = [SkillTarget.model_validate(t) for t in targets]
        if not items:
            return {"ok": False, "error": "숙련목표가 비어 있음"}
        for i, t in enumerate(items):
            t.id = t.id or f"K{i + 1}"
        unknown = sorted({x for t in items for x in t.subject_ids if not self.subject(x)})
        if unknown:
            return {"ok": False, "error": f"없는 교과목 id: {unknown}"}
        self.cur.skill_targets = items
        if self.inp.revise_mode:
            self._log("숙련목표", "수정", "숙련목표 다시 정함", "설계")
        return {"ok": True, "skill_targets": [t.id for t in items]}

    def write_quiz(self, sid: str, questions: List[Dict], week: Optional[int] = None) -> Dict:
        """객관식 퀴즈를 쓴다. 형식(보기 4개, 정답 번호, 숙련목표 id)은 코드가 확인하고 틀리면 돌려보낸다."""
        s = self.subject(sid)
        if not s:
            return {"ok": False, "error": f"교과목 {sid} 없음"}
        if not questions:
            return {"ok": False, "error": "문항이 비어 있음"}
        target_ids = {t.id for t in self.cur.skill_targets}
        errors, items = [], []
        for n, q in enumerate(questions, 1):
            try:
                item = QuizQuestion.model_validate(q)
            except Exception as e:
                errors.append(f"{n}번: 형식 오류 ({e.__class__.__name__})")
                continue
            choices = [c.strip() for c in item.choices]
            if len(choices) != QUIZ_CHOICES or not all(choices):
                errors.append(f"{n}번: 보기는 비어 있지 않은 {QUIZ_CHOICES}개여야 함 (지금 {len(choices)}개)")
            elif len(set(choices)) != QUIZ_CHOICES:
                errors.append(f"{n}번: 같은 보기가 있음")
            if not 1 <= item.answer <= QUIZ_CHOICES:
                errors.append(f"{n}번: answer는 정답 보기 번호 1~{QUIZ_CHOICES}")
            if not item.question.strip():
                errors.append(f"{n}번: 문제가 비어 있음")
            bad = [x for x in item.skill_target_ids if x not in target_ids]
            if bad:
                errors.append(f"{n}번: 없는 숙련목표 id {bad} (있는 id: {sorted(target_ids)})")
            items.append(item)
        if errors:
            return {"ok": False, "error": "퀴즈 형식 오류: " + "; ".join(errors)}
        self._spread_answers(sid, items)
        weeks = next((w for w in self.schedule()["weeks"] if w["id"] == sid), {})
        if week is not None and weeks and not weeks["week_start"] <= week <= weeks["week_end"]:
            return {"ok": False, "error": f"week는 교과목 기간({weeks['week_start']}~{weeks['week_end']}주차) 안이어야 함"}
        # 같은 교과목·같은 주차 퀴즈는 덮어쓴다
        same = lambda q: q.subject_id == sid and q.week == week
        self.cur.quizzes = [q for q in self.cur.quizzes if not same(q)]
        quiz = Quiz(id=f"Q-{sid}" + (f"-W{week}" if week else ""), subject_id=sid, week=week, questions=items)
        self.cur.quizzes.append(quiz)
        self.cur.quizzes.sort(key=lambda q: (self.quiz_week(q), q.subject_id))
        self.quiz_stale.discard(sid)
        if self.inp.revise_mode:
            self.touched.add(sid)
            self._log(sid, "수정", f"퀴즈 {len(items)}문항 작성", "설계")
        return {"ok": True, "id": quiz.id, "questions": len(items), "week": self.quiz_week(quiz)}

    @staticmethod
    def _spread_answers(sid: str, items: List[QuizQuestion]):
        """AI는 정답을 앞쪽 보기에 두는 경향이 있어, 코드가 정답 위치를 ①~④에 고르게 돌린다 (같은 입력이면 같은 결과)."""
        offset = sum(map(ord, sid))
        for n, q in enumerate(items):
            pos = (offset + n) % QUIZ_CHOICES
            right = q.choices[q.answer - 1]
            others = [c for i, c in enumerate(q.choices) if i != q.answer - 1]
            q.choices = others[:pos] + [right] + others[pos:]
            q.answer = pos + 1

    def set_proficiency_methods(self, methods: List[Dict]) -> Dict:
        items = [ProficiencyMethod.model_validate(m) for m in methods]
        if not items:
            return {"ok": False, "error": "숙련도 향상 방법이 비어 있음"}
        unknown = sorted({x for m in items for x in m.subject_ids if not self.subject(x)})
        if unknown:
            return {"ok": False, "error": f"없는 교과목 id: {unknown}"}
        self.cur.proficiency_methods = items
        if self.inp.revise_mode:
            self._log("숙련도 향상 방법", "수정", "숙련도 향상 방법 다시 정함", "설계")
        return {"ok": True, "methods": len(items)}
