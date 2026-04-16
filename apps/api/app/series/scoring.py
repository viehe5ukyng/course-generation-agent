from __future__ import annotations

import re
from dataclasses import dataclass

from app.series.schema import CourseFramework, LessonOutline

PRACTICE_KEYWORDS = {"实战", "实践", "案例", "应用", "演练", "训练", "项目", "落地", "复盘", "工作流"}
FOUNDATION_KEYWORDS = {"基础", "入门", "理解", "认知", "定位", "框架", "概念", "准备"}
ADVANCED_KEYWORDS = {"策略", "优化", "进阶", "方案", "案例", "实战", "应用", "复盘", "闭环"}
SPECIFICITY_HINTS = {"提升", "完成", "建立", "优化", "设计", "掌握", "搭建", "独立", "系统", "转变", "应用"}
MIXED_TOPIC_PAIRS = [("招聘", "周报"), ("招聘", "组织管理"), ("招聘", "团队管理")]
BOUNDARY_KEYWORDS = {"边界", "风险", "合规", "审批", "人工", "校验", "免责声明", "安全"}


@dataclass(slots=True)
class SeriesCriterion:
    criterion_id: str
    name: str
    weight: float
    score: float
    max_score: float
    reason: str


@dataclass(slots=True)
class SeriesSuggestion:
    criterion_id: str
    problem: str
    suggestion: str
    evidence_span: str
    severity: str = "medium"


@dataclass(slots=True)
class SeriesReviewReport:
    total_score: float
    criteria: list[SeriesCriterion]
    suggestions: list[SeriesSuggestion]
    summary: str


def _contains_keyword(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _keyword_hits(text: str, keywords: set[str]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _clamp_score(value: int) -> int:
    return max(1, min(5, value))


def _lesson_text(lesson: LessonOutline) -> str:
    return f"{lesson.title} {lesson.summary}"


def _late_stage_lessons(lessons: list[LessonOutline]) -> list[LessonOutline]:
    return lessons[max(0, len(lessons) // 2) :]


def _joined_lessons_text(lessons: list[LessonOutline]) -> str:
    return " ".join(_lesson_text(lesson) for lesson in lessons)


def parse_framework_markdown(markdown_text: str) -> CourseFramework:
    blocks = [line.strip() for line in markdown_text.splitlines() if line.strip()]
    field_patterns = {
        "course_name": r"^课程名称[:：](.+)$",
        "target_user": r"^目标学员[:：](.+)$",
        "learner_current_state": r"^学员当前状态[:：](.+)$",
        "learner_expected_state": r"^学员期望状态[:：](.+)$",
        "mindset_shift": r"^思维转换[:：](.+)$",
        "core_problem": r"^课程核心问题[:：](.+)$",
        "application_scenario": r"^课程应用场景[:：](.+)$",
    }

    parsed: dict[str, str] = {}
    for line in blocks:
        for field_name, pattern in field_patterns.items():
            matched = re.match(pattern, line)
            if matched:
                parsed[field_name] = matched.group(1).strip()

    lessons: list[LessonOutline] = []
    lesson_pattern = re.compile(r"^第(\d+)课[:：](.+)$")
    content_pattern = re.compile(r"^内容[:：](.+)$")
    current_lesson: LessonOutline | None = None
    for line in blocks:
        lesson_match = lesson_pattern.match(line)
        if lesson_match:
            current_lesson = LessonOutline(
                lesson_number=int(lesson_match.group(1)),
                title=lesson_match.group(2).strip(),
                summary="",
            )
            lessons.append(current_lesson)
            continue
        content_match = content_pattern.match(line)
        if content_match and current_lesson is not None:
            current_lesson.summary = content_match.group(1).strip()

    return CourseFramework(
        course_name=parsed.get("course_name", "未命名系列课"),
        target_user=parsed.get("target_user", "待补充"),
        learner_current_state=parsed.get("learner_current_state", "待补充"),
        learner_expected_state=parsed.get("learner_expected_state", "待补充"),
        mindset_shift=parsed.get("mindset_shift", "待补充"),
        core_problem=parsed.get("core_problem", "待补充"),
        application_scenario=parsed.get("application_scenario", "待补充"),
        lessons=lessons,
    )


def _criterion_from_feature(feature_name: str, score: int, reason: str, weight: float = 1.0) -> SeriesCriterion:
    return SeriesCriterion(
        criterion_id=feature_name,
        name=feature_name,
        weight=weight,
        score=round(score * 2.0, 1),
        max_score=10.0,
        reason=reason,
    )


def _feature_scores(framework: CourseFramework) -> dict[str, tuple[int, str]]:
    lessons = framework.lessons
    joined_lessons = _joined_lessons_text(lessons)
    late_lessons = _late_stage_lessons(lessons)

    goal_text = " ".join([framework.course_name, framework.core_problem, framework.learner_expected_state])
    goal_score = 3
    if len(framework.course_name) >= 8:
        goal_score += 1
    if _keyword_hits(goal_text, SPECIFICITY_HINTS) >= 2:
        goal_score += 1
    if len(framework.core_problem) < 12:
        goal_score -= 1

    audience_text = " ".join([framework.target_user, framework.learner_current_state])
    audience_score = 3
    if any(token in audience_text for token in ["零基础", "有经验", "转型", "岗位", "团队", "经理", "顾问", "老师"]):
        audience_score += 1
    if len(framework.learner_current_state) >= 24:
        audience_score += 1
    if len(framework.target_user) < 8:
        audience_score -= 1

    logic_score = 3
    if lessons:
        first_text = _lesson_text(lessons[0])
        last_text = _lesson_text(lessons[-1])
        if _contains_keyword(first_text, FOUNDATION_KEYWORDS):
            logic_score += 1
        if _contains_keyword(last_text, PRACTICE_KEYWORDS | ADVANCED_KEYWORDS):
            logic_score += 1
        ordered_numbers = [lesson.lesson_number for lesson in lessons] == list(range(1, len(lessons) + 1))
        if not ordered_numbers:
            logic_score -= 1
        early_practice = any(_contains_keyword(_lesson_text(lesson), PRACTICE_KEYWORDS) for lesson in lessons[:2])
        if early_practice and not _contains_keyword(first_text, FOUNDATION_KEYWORDS):
            logic_score -= 1
    else:
        logic_score = 1

    mindset_score = 3
    if "从" in framework.mindset_shift and "到" in framework.mindset_shift:
        mindset_score += 1
    if "转变" in framework.mindset_shift or len(framework.mindset_shift) >= 18:
        mindset_score += 1
    if len(framework.mindset_shift) < 10:
        mindset_score -= 1

    scenario_score = 3
    if len(framework.application_scenario) >= 12:
        scenario_score += 1
    if any(token in framework.application_scenario for token in ["场景", "流程", "客户", "项目", "协作", "运营", "转化", "交付"]):
        scenario_score += 1
    if len(framework.application_scenario) < 8:
        scenario_score -= 1

    size_score = 3
    lesson_count = len(lessons)
    if 4 <= lesson_count <= 8:
        size_score += 1
    if 5 <= lesson_count <= 7:
        size_score += 1
    if lesson_count <= 2 or lesson_count >= 12:
        size_score -= 1
    if lesson_count and len(joined_lessons) / lesson_count < 18:
        size_score -= 1

    practice_hits = _keyword_hits(joined_lessons, PRACTICE_KEYWORDS)
    late_practice_hits = sum(1 for lesson in late_lessons if _contains_keyword(_lesson_text(lesson), PRACTICE_KEYWORDS))
    practice_score = 2
    if practice_hits >= 2:
        practice_score += 1
    if late_practice_hits >= 1:
        practice_score += 1
    if late_practice_hits >= 2 or "工作流" in joined_lessons:
        practice_score += 1

    boundary_text = " ".join([framework.core_problem, framework.application_scenario, joined_lessons])
    boundary_score = 3
    if _contains_keyword(boundary_text, BOUNDARY_KEYWORDS):
        boundary_score += 1
    if "高风险" in boundary_text or "审批" in boundary_text:
        boundary_score += 1

    return {
        "目标清晰度": (_clamp_score(goal_score), "课程名称、核心问题和期望结果越具体，目标清晰度越高。"),
        "目标学员明确度": (_clamp_score(audience_score), "目标学员和当前状态写得越具体，内容越容易收束。"),
        "内容逻辑性": (_clamp_score(logic_score), "前半段铺认知、后半段做应用，系列课的结构会更稳。"),
        "思维转换明确度": (_clamp_score(mindset_score), "思维转换最好写成“从旧做法到新做法”的明确迁移。"),
        "应用场景清晰度": (_clamp_score(scenario_score), "应用场景越具体，越容易判断这套课最终怎么用起来。"),
        "课程规模合理性": (_clamp_score(size_score), "课时规模和单课信息密度匹配时，系列课更像可交付产品。"),
        "实战性": (_clamp_score(practice_score), "后半段有没有案例、项目和复盘，是系列课是否能落地的关键。"),
        "边界与约束清晰度": (_clamp_score(boundary_score), "涉及限制、风险或人工判断的地方说明得越清楚，交付风险越小。"),
    }


def _deduction_suggestions(framework: CourseFramework) -> list[SeriesSuggestion]:
    suggestions: list[SeriesSuggestion] = []
    text = " ".join([framework.course_name, framework.core_problem, framework.application_scenario])
    lessons = framework.lessons
    lesson_text = _joined_lessons_text(lessons)
    late_lessons = _late_stage_lessons(lessons)
    late_has_practice = any(_contains_keyword(_lesson_text(lesson), PRACTICE_KEYWORDS) for lesson in late_lessons)
    ordered_numbers = [lesson.lesson_number for lesson in lessons] == list(range(1, len(lessons) + 1))
    early_practice = lessons and _contains_keyword(_lesson_text(lessons[0]), PRACTICE_KEYWORDS) and not _contains_keyword(_lesson_text(lessons[0]), FOUNDATION_KEYWORDS)

    if not late_has_practice:
        suggestions.append(
            SeriesSuggestion(
                criterion_id="实战性",
                problem="后半段缺少明显的案例、项目或复盘，系列课会更像知识讲解而不是带结果的训练。",
                suggestion="把最后三分之一课时改成案例拆解、完整演练或项目复盘，让前面的方法真正落地。",
                evidence_span="课程框架",
                severity="high",
            )
        )
    if not ordered_numbers or early_practice:
        suggestions.append(
            SeriesSuggestion(
                criterion_id="内容逻辑性",
                problem="当前课时递进不够稳定，容易出现基础未立住就进入应用的情况。",
                suggestion="把系列课重排为“认知/基础 -> 方法/拆解 -> 应用/案例 -> 实战/复盘”的顺序。",
                evidence_span="课程框架",
                severity="high",
            )
        )
    if len(framework.target_user) < 8:
        suggestions.append(
            SeriesSuggestion(
                criterion_id="目标学员明确度",
                problem="目标学员描述过宽，后面每节课就容易失焦。",
                suggestion="把目标学员写成“谁、现在卡在哪里、想拿到什么结果”的格式，收窄课程边界。",
                evidence_span="目标学员",
                severity="medium",
            )
        )
    if len(framework.core_problem) < 12:
        suggestions.append(
            SeriesSuggestion(
                criterion_id="目标清晰度",
                problem="课程核心问题还不够聚焦，用户难以快速理解这套课到底解决什么。",
                suggestion="把课程核心问题改写成一个明确矛盾，并与课程名称、期望结果保持一致。",
                evidence_span="课程核心问题",
                severity="medium",
            )
        )
    if len(lessons) <= 2 or len(lessons) >= 12:
        suggestions.append(
            SeriesSuggestion(
                criterion_id="课程规模合理性",
                problem="当前系列课规模偏失衡，可能出现内容挤压或注水。",
                suggestion="把课程调整到更合理的课时粒度，让每一课都承担一个清晰任务。",
                evidence_span="课程框架",
                severity="medium",
            )
        )
    if not _contains_keyword(text + lesson_text, BOUNDARY_KEYWORDS) and any(keyword in text for keyword in ["医疗", "法务", "合规", "审批"]):
        suggestions.append(
            SeriesSuggestion(
                criterion_id="边界与约束清晰度",
                problem="涉及高风险或需要人工把关的场景，但课程里没有明确边界和人工校验点。",
                suggestion="补上风险边界、人工复核和使用限制，让这套课的交付条件更完整。",
                evidence_span="课程应用场景",
                severity="high",
            )
        )
    for left, right in MIXED_TOPIC_PAIRS:
        if left in text and right in text:
            suggestions.append(
                SeriesSuggestion(
                    criterion_id="目标清晰度",
                    problem="课程主题把两个相对独立的大问题混在一起，系列主线容易发散。",
                    suggestion=f"先决定主线要聚焦“{left}”还是“{right}”，避免一套课同时承担两条产品线。",
                    evidence_span="课程名称",
                    severity="high",
                )
            )
            break
    return suggestions


def score_framework_markdown(markdown_text: str) -> SeriesReviewReport:
    framework = parse_framework_markdown(markdown_text)
    feature_scores = _feature_scores(framework)
    criteria = [
        _criterion_from_feature("目标清晰度", *feature_scores["目标清晰度"], weight=1.6),
        _criterion_from_feature("目标学员明确度", *feature_scores["目标学员明确度"], weight=1.2),
        _criterion_from_feature("内容逻辑性", *feature_scores["内容逻辑性"], weight=1.8),
        _criterion_from_feature("课程规模合理性", *feature_scores["课程规模合理性"], weight=1.2),
        _criterion_from_feature("实战性", *feature_scores["实战性"], weight=2.0),
        _criterion_from_feature("应用场景清晰度", *feature_scores["应用场景清晰度"], weight=1.0),
        _criterion_from_feature("边界与约束清晰度", *feature_scores["边界与约束清晰度"], weight=0.8),
    ]
    weighted_total = sum(item.score * item.weight for item in criteria)
    total_weight = sum(item.weight for item in criteria)
    total_score = round(weighted_total / total_weight, 2)
    suggestions = _deduction_suggestions(framework)
    if total_score >= 8.0 and not suggestions:
        suggestions.append(
            SeriesSuggestion(
                criterion_id="实战性",
                problem="整体已经达到可通过水平，但还可以再增强成果感和交付感。",
                suggestion="补一个代表性案例或结果展示说明，让系列课更像可直接售卖和交付的完整产品。",
                evidence_span="课程框架",
                severity="low",
            )
        )

    summary = (
        f"当前系列课综合得分 {total_score:.2f} 分。"
        f"{'结构已经基本成立。' if total_score >= 8.0 else '结构还需要继续补强。'}"
        "评分会重点看目标是否收敛、课时递进是否合理，以及后半段有没有真正落地的应用。"
    )
    return SeriesReviewReport(total_score=total_score, criteria=criteria, suggestions=suggestions[:5], summary=summary)
