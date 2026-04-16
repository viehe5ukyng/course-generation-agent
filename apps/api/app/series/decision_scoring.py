from __future__ import annotations

import pickle
import re
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from app.llm.deepseek_client import DeepSeekClient
from app.series.schema import CourseFramework, LessonOutline
from app.series.scoring import parse_framework_markdown

ROOT_DIR = Path(__file__).resolve().parents[4]
MODEL_PATH = ROOT_DIR / "data" / "series_scoring" / "course_scoring_model.pkl"
PASS_THRESHOLD = 80.0
LOCAL_SCORE_WEIGHT = 0.2
DECISION_AGENT_WEIGHT = 0.8

PRACTICE_KEYWORDS = {"实战", "实践", "案例", "应用", "演练", "训练", "项目", "落地", "复盘", "操作", "工作流"}
FOUNDATION_KEYWORDS = {"基础", "入门", "理解", "认知", "定位", "框架", "概念", "准备"}
ADVANCED_KEYWORDS = {"策略", "优化", "进阶", "诊断", "方案", "案例", "实战", "应用", "复盘", "闭环"}
SPECIFICITY_HINTS = {"提升", "完成", "建立", "优化", "设计", "掌握", "搭建", "独立", "系统", "转变", "应用"}
FORBIDDEN_DOMAIN_KEYWORDS = {"医学", "医疗", "医美", "诊断", "治疗", "患者", "处方", "临床"}
HIGH_RISK_DOMAIN_KEYWORDS = {"法务", "保险", "公关", "舆情", "医疗", "医美", "合规"}
BOUNDARY_KEYWORDS = {"边界", "风险", "合规", "审批", "人工", "校验", "免责声明", "安全"}
OVERSIZED_TOPIC_KEYWORDS = {"一人公司", "产品线", "经营分析", "组织管理", "完整工作流", "全流程", "系统搭建"}
UNDERSIZED_TOPIC_KEYWORDS = {"合同初审", "会议纪要", "简历初筛", "JD生成", "口播脚本", "切片文案"}
MIXED_TOPIC_PAIRS = [("招聘", "周报"), ("招聘", "组织管理"), ("招聘", "团队管理")]
CORE_WORKFLOW_REQUIREMENTS = (
    (
        {"漫剧", "漫画剧", "AI漫剧"},
        {"视频生成", "转视频", "动画生成", "视频制作", "视频剪辑", "运镜", "动态镜头", "镜头衔接", "成片输出"},
        "课程承诺的是“漫剧”交付，但课程里没有覆盖视频生成、动态镜头或成片环节，核心工作流不闭合。",
    ),
)
FEATURE_NAMES = [
    "goal_clarity",
    "target_audience_clarity",
    "content_logic",
    "mindset_shift_clarity",
    "application_scenario_clarity",
    "course_size_reasonableness",
    "practicality",
]
FEATURE_LABELS = {
    "goal_clarity": "目标清晰度",
    "target_audience_clarity": "目标学员明确度",
    "content_logic": "内容逻辑性",
    "mindset_shift_clarity": "思维转换明确度",
    "application_scenario_clarity": "应用场景清晰度",
    "course_size_reasonableness": "课程规模合理性",
    "practicality": "实战性",
}
LOCAL_STANDARD_WEIGHTS = {
    "goal_clarity": 5.0,
    "target_audience_clarity": 10.0,
    "content_logic": 20.0,
    "mindset_shift_clarity": 5.0,
    "application_scenario_clarity": 15.0,
    "course_size_reasonableness": 20.0,
    "practicality": 25.0,
}
DIMENSION_WEIGHTS = {
    "目标清晰度": 10,
    "目标学员明确度": 12,
    "内容逻辑性": 20,
    "思维转换明确度": 8,
    "应用场景清晰度": 12,
    "课程规模合理性": 18,
    "实战性": 20,
}


class DecisionGrade(StrEnum):
    STRONG_PASS = "强通过"
    PASS = "可通过"
    BORDERLINE_REWORK = "临界需重做"
    REWORK = "需重做"


class DecisionDirection(StrEnum):
    STRENGTH = "strength"
    NEUTRAL = "neutral"
    WEAKNESS = "weakness"


class DecisionPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DecisionDimensionItem(BaseModel):
    score: int = Field(ge=1, le=5)
    direction: DecisionDirection
    reason: str


class DecisionDimensionScores(BaseModel):
    goal_clarity: DecisionDimensionItem
    target_audience_clarity: DecisionDimensionItem
    content_logic: DecisionDimensionItem
    mindset_shift_clarity: DecisionDimensionItem
    application_scenario_clarity: DecisionDimensionItem
    course_size_reasonableness: DecisionDimensionItem
    practicality: DecisionDimensionItem


class DecisionFlags(BaseModel):
    topic_too_broad: bool = False
    topic_too_narrow: bool = False
    topic_mixed: bool = False
    difficulty_jump: bool = False
    late_stage_practice_weak: bool = False
    core_workflow_gap: bool = False
    boundary_unclear: bool = False
    unsafe_domain: bool = False


class CriticalIssue(BaseModel):
    title: str
    description: str
    impact: str
    priority: DecisionPriority
    related_flags: list[str] = Field(default_factory=list)


class DecisionImprovementSuggestion(BaseModel):
    title: str
    problem: str
    suggestion: str
    priority: DecisionPriority
    related_flags: list[str] = Field(default_factory=list)


class DecisionAgentOutput(BaseModel):
    agent_total_score: float = Field(ge=0, le=100)
    agent_grade: DecisionGrade
    agent_passed: bool
    confidence: float = Field(ge=0, le=1)
    summary: str
    pass_decision_reason: str
    dimension_scores: DecisionDimensionScores
    decision_flags: DecisionFlags
    critical_issues: list[CriticalIssue] = Field(default_factory=list)
    improvement_suggestions: list[DecisionImprovementSuggestion] = Field(default_factory=list)


class LLMFeatureItem(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str


class LLMFeatureExtraction(BaseModel):
    goal_clarity: LLMFeatureItem
    target_audience_clarity: LLMFeatureItem
    content_logic: LLMFeatureItem
    mindset_shift_clarity: LLMFeatureItem
    application_scenario_clarity: LLMFeatureItem
    course_size_reasonableness: LLMFeatureItem
    practicality: LLMFeatureItem
    has_late_stage_application: bool
    sequence_is_reasonable: bool


class LLMImprovementItem(BaseModel):
    title: str
    problem: str
    suggestion: str


class LLMImprovementReport(BaseModel):
    review_summary: str
    improvement_suggestions: list[LLMImprovementItem] = Field(default_factory=list)


class LLMDecisionReview(BaseModel):
    agent_total_score: float = Field(ge=0, le=100)
    agent_grade: DecisionGrade
    agent_passed: bool
    confidence: float = Field(ge=0, le=1)
    summary: str
    pass_decision_reason: str
    decision_flags: DecisionFlags
    critical_issues: list[CriticalIssue] = Field(default_factory=list)


@dataclass(slots=True)
class CourseFeatures:
    goal_clarity: int
    target_audience_clarity: int
    content_logic: int
    mindset_shift_clarity: int
    application_scenario_clarity: int
    course_size_reasonableness: int
    practicality: int
    has_late_stage_application: bool
    sequence_is_reasonable: bool


@dataclass(slots=True)
class FeatureAssessment:
    feature_name: str
    score: int
    reason: str


@dataclass(slots=True)
class FeatureContribution:
    feature_name: str
    raw_value: float
    coefficient: float
    contribution_score: float
    direction: str
    explanation: str


@dataclass(slots=True)
class DeductionItem:
    rule_name: str
    points: float
    reason: str


@dataclass(slots=True)
class ScoreResult:
    raw_model_score: float
    local_standard_score: float
    deduction_total: float
    total_score: float
    grade: str
    passed: bool = False
    feature_contributions: list[FeatureContribution] = field(default_factory=list)
    deductions: list[DeductionItem] = field(default_factory=list)
    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImprovementSuggestion:
    title: str
    problem: str
    suggestion: str


@dataclass(slots=True)
class BlendedScoreResult:
    local_score: float
    decision_agent_score: float
    final_score: float
    local_weight: float
    decision_agent_weight: float
    grade: str
    passed: bool
    rationale: str = ""


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
    extraction_source: str = "rule"
    feature_assessments: list[FeatureAssessment] = field(default_factory=list)
    score_result: ScoreResult | None = None
    decision_agent_output: DecisionAgentOutput | None = None
    decision_agent_source: str = "rule"
    blended_score: BlendedScoreResult | None = None


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


def _framework_text(framework: CourseFramework) -> str:
    return framework.to_markdown(title="系列课程框架")


def _direction_from_score(score: int) -> DecisionDirection:
    if score >= 4:
        return DecisionDirection.STRENGTH
    if score == 3:
        return DecisionDirection.NEUTRAL
    return DecisionDirection.WEAKNESS


def _priority_from_text(priority: str) -> DecisionPriority:
    if priority == "high":
        return DecisionPriority.HIGH
    if priority == "low":
        return DecisionPriority.LOW
    return DecisionPriority.MEDIUM


def _priority_from_flag(flag_name: str) -> DecisionPriority:
    if flag_name in {"unsafe_domain", "topic_mixed", "difficulty_jump", "core_workflow_gap", "boundary_unclear"}:
        return DecisionPriority.HIGH
    return DecisionPriority.MEDIUM


def _grade_from_score(score: float) -> str:
    if score >= 95:
        return "强通过"
    if score >= 90:
        return "优秀"
    if score >= 80:
        return "可通过"
    return "需重做"


def _grade_from_final_score(score: float) -> DecisionGrade:
    if score >= 90:
        return DecisionGrade.STRONG_PASS
    if score >= 80:
        return DecisionGrade.PASS
    if score >= 70:
        return DecisionGrade.BORDERLINE_REWORK
    return DecisionGrade.REWORK


@lru_cache(maxsize=1)
def _load_model_payload() -> dict:
    with MODEL_PATH.open("rb") as file:
        return pickle.load(file)


def _predict_raw_score(features: CourseFeatures) -> float:
    payload = _load_model_payload()
    scaler = payload["scaler"]
    regressor = payload["regressor"]
    vector = np.array([[float(getattr(features, name)) for name in FEATURE_NAMES]], dtype=float)
    scaled = scaler.transform(vector)
    return float(regressor.predict(scaled)[0])


def assess_goal_clarity(framework: CourseFramework) -> FeatureAssessment:
    text = " ".join([framework.course_name, framework.core_problem, framework.learner_expected_state])
    score = 3
    if len(framework.course_name) >= 8:
        score += 1
    if _keyword_hits(text, SPECIFICITY_HINTS) >= 2:
        score += 1
    if len(framework.core_problem) < 12:
        score -= 1
    return FeatureAssessment("目标清晰度", _clamp_score(score), "课程名称、核心问题和期望状态越具体，目标清晰度越高。")


def assess_target_audience_clarity(framework: CourseFramework) -> FeatureAssessment:
    text = " ".join([framework.target_user, framework.learner_current_state])
    score = 3
    if any(token in text for token in ["零基础", "有经验", "转型", "岗位", "团队", "经理", "顾问", "老师"]):
        score += 1
    if len(framework.learner_current_state) >= 30:
        score += 1
    if len(framework.target_user) < 8:
        score -= 1
    return FeatureAssessment("目标学员明确度", _clamp_score(score), "目标学员描述越具体，当前状态越明确，这一项越高。")


def assess_content_logic(framework: CourseFramework) -> FeatureAssessment:
    lessons = framework.lessons
    if not lessons:
        return FeatureAssessment("内容逻辑性", 1, "没有课时内容时，无法形成有效的内容逻辑。")
    first_text = _lesson_text(lessons[0])
    last_text = _lesson_text(lessons[-1])
    score = 3
    if _contains_keyword(first_text, FOUNDATION_KEYWORDS):
        score += 1
    if _contains_keyword(last_text, PRACTICE_KEYWORDS | ADVANCED_KEYWORDS):
        score += 1
    if [lesson.lesson_number for lesson in lessons] != list(range(1, len(lessons) + 1)):
        score -= 1
    early_practice = any(_contains_keyword(_lesson_text(lesson), PRACTICE_KEYWORDS) for lesson in lessons[:2])
    if early_practice and not _contains_keyword(first_text, FOUNDATION_KEYWORDS):
        score -= 1
    return FeatureAssessment("内容逻辑性", _clamp_score(score), "前半段偏基础、后半段偏应用，且课程序号连续时，内容逻辑通常更好。")


def assess_mindset_shift_clarity(framework: CourseFramework) -> FeatureAssessment:
    text = framework.mindset_shift
    score = 3
    if "从" in text and "转变" in text:
        score += 1
    if _keyword_hits(text, SPECIFICITY_HINTS) >= 1 or len(text) >= 18:
        score += 1
    if len(text) < 10:
        score -= 1
    return FeatureAssessment("思维转换明确度", _clamp_score(score), "思维转换写得越像明确的“从 A 到 B”，这一项越高。")


def assess_application_scenario_clarity(framework: CourseFramework) -> FeatureAssessment:
    text = framework.application_scenario
    score = 3
    if len(text) >= 12:
        score += 1
    if any(token in text for token in ["场景", "流程", "客户", "项目", "协作", "运营", "转化", "交付"]):
        score += 1
    if len(text) < 8:
        score -= 1
    return FeatureAssessment("应用场景清晰度", _clamp_score(score), "应用场景越具体，越容易判断课程的真实使用环境。")


def assess_course_size_reasonableness(framework: CourseFramework) -> FeatureAssessment:
    lesson_count = len(framework.lessons)
    joined_text = _joined_lessons_text(framework.lessons)
    score = 3
    if 4 <= lesson_count <= 8:
        score += 1
    if 5 <= lesson_count <= 7:
        score += 1
    if lesson_count <= 2 or lesson_count >= 12:
        score -= 1
    if len(joined_text) / max(lesson_count, 1) < 18:
        score -= 1
    return FeatureAssessment("课程规模合理性", _clamp_score(score), "课时数量与信息密度匹配时，课程规模通常更合理。")


def assess_practicality(framework: CourseFramework) -> FeatureAssessment:
    joined_text = _joined_lessons_text(framework.lessons)
    late_lessons = _late_stage_lessons(framework.lessons)
    practice_hits = _keyword_hits(joined_text, PRACTICE_KEYWORDS)
    late_practice_hits = sum(1 for lesson in late_lessons if _contains_keyword(_lesson_text(lesson), PRACTICE_KEYWORDS))
    score = 2
    if practice_hits >= 2:
        score += 1
    if late_practice_hits >= 1:
        score += 1
    if late_practice_hits >= 2 or "工作流" in joined_text:
        score += 1
    return FeatureAssessment("实战性", _clamp_score(score), "后半段是否出现案例、实战、演练和具体应用，是实战性的关键判断依据。")


def infer_has_late_stage_application(framework: CourseFramework) -> bool:
    return any(_contains_keyword(_lesson_text(lesson), PRACTICE_KEYWORDS) for lesson in _late_stage_lessons(framework.lessons))


def infer_sequence_is_reasonable(framework: CourseFramework) -> bool:
    lessons = framework.lessons
    if not lessons:
        return False
    first_text = _lesson_text(lessons[0])
    early_text = " ".join(_lesson_text(lesson) for lesson in lessons[:2])
    late_text = " ".join(_lesson_text(lesson) for lesson in _late_stage_lessons(lessons))
    has_intro_early = _contains_keyword(early_text, FOUNDATION_KEYWORDS)
    has_application_late = _contains_keyword(late_text, PRACTICE_KEYWORDS | ADVANCED_KEYWORDS)
    practice_too_early = _contains_keyword(first_text, PRACTICE_KEYWORDS) and not _contains_keyword(first_text, FOUNDATION_KEYWORDS)
    ordered = [lesson.lesson_number for lesson in lessons] == list(range(1, len(lessons) + 1))
    return has_intro_early and has_application_late and ordered and not practice_too_early


def extract_features_from_framework(framework: CourseFramework) -> tuple[CourseFeatures, list[FeatureAssessment]]:
    assessments = [
        assess_goal_clarity(framework),
        assess_target_audience_clarity(framework),
        assess_content_logic(framework),
        assess_mindset_shift_clarity(framework),
        assess_application_scenario_clarity(framework),
        assess_course_size_reasonableness(framework),
        assess_practicality(framework),
    ]
    score_map = {item.feature_name: item.score for item in assessments}
    return (
        CourseFeatures(
            goal_clarity=score_map["目标清晰度"],
            target_audience_clarity=score_map["目标学员明确度"],
            content_logic=score_map["内容逻辑性"],
            mindset_shift_clarity=score_map["思维转换明确度"],
            application_scenario_clarity=score_map["应用场景清晰度"],
            course_size_reasonableness=score_map["课程规模合理性"],
            practicality=score_map["实战性"],
            has_late_stage_application=infer_has_late_stage_application(framework),
            sequence_is_reasonable=infer_sequence_is_reasonable(framework),
        ),
        assessments,
    )


def _build_contributions(features: CourseFeatures) -> list[FeatureContribution]:
    contributions: list[FeatureContribution] = []
    for name in FEATURE_NAMES:
        raw_value = getattr(features, name)
        weight = LOCAL_STANDARD_WEIGHTS[name]
        contribution_value = round((float(raw_value) / 5.0) * weight, 2)
        if raw_value >= 4:
            direction = "正向"
            explanation = f"{FEATURE_LABELS[name]}较强，符合你的人工评审偏好。"
        elif raw_value == 3:
            direction = "中性"
            explanation = f"{FEATURE_LABELS[name]}中等，会压住课程的通过空间。"
        else:
            direction = "负向"
            explanation = f"{FEATURE_LABELS[name]}偏弱，按你的标准会明显拖累得分。"
        contributions.append(
            FeatureContribution(
                feature_name=FEATURE_LABELS[name],
                raw_value=float(raw_value),
                coefficient=weight,
                contribution_score=contribution_value,
                direction=direction,
                explanation=explanation,
            )
        )
    contributions.sort(key=lambda item: item.contribution_score, reverse=True)
    return contributions


def _base_deductions(features: CourseFeatures) -> list[DeductionItem]:
    deductions: list[DeductionItem] = []
    if not features.has_late_stage_application:
        deductions.append(DeductionItem("late_stage_application_missing", 15.0, "课程后半段缺少应用或实战内容，按你的标注标准会明显拉低通过概率。"))
    if not features.sequence_is_reasonable:
        deductions.append(DeductionItem("sequence_not_reasonable", 20.0, "课程顺序明显不合理，或存在难度断崖/主题跳跃，按你的标准会被重罚。"))
    return deductions


def _local_standard_score(features: CourseFeatures) -> float:
    return round(sum((float(getattr(features, name)) / 5.0) * weight for name, weight in LOCAL_STANDARD_WEIGHTS.items()), 2)


def score_features(features: CourseFeatures) -> ScoreResult:
    raw_model_score = _predict_raw_score(features) if MODEL_PATH.exists() else _local_standard_score(features)
    deductions = _base_deductions(features)
    deduction_total = round(sum(item.points for item in deductions), 2)
    local_standard_score = _local_standard_score(features)
    total_score = max(0.0, min(100.0, local_standard_score - deduction_total))
    grade = _grade_from_score(total_score)
    passed = total_score >= PASS_THRESHOLD
    contributions = _build_contributions(features)
    strengths = [item.feature_name for item in contributions if item.raw_value >= 4][:2]
    weaknesses = [item.feature_name for item in sorted(contributions, key=lambda item: item.raw_value) if item.raw_value <= 3][:2]
    explanations = [
        f"本地标准基础分为 {local_standard_score:.2f} 分。",
        f"线性回归参考分为 {raw_model_score:.2f} 分。",
        f"规则扣分合计 {deduction_total:.2f} 分。",
        *(item.explanation for item in contributions[:3]),
        *(item.reason for item in deductions),
    ]
    summary = (
        f"课程最终得分 {total_score:.2f} 分，评级为“{grade}”。"
        f"{'达到' if passed else '未达到'} 80 分通过线。"
        "本地评分标准会更强调实战性、课时匹配、逻辑递进和真实落地性。"
    )
    return ScoreResult(
        raw_model_score=round(raw_model_score, 2),
        local_standard_score=local_standard_score,
        deduction_total=deduction_total,
        total_score=round(total_score, 2),
        grade=grade,
        passed=passed,
        feature_contributions=contributions,
        deductions=deductions,
        summary=summary,
        strengths=strengths,
        weaknesses=weaknesses,
        explanations=explanations,
    )


def _apply_framework_standard_overrides(framework: CourseFramework, score_result: ScoreResult) -> ScoreResult:
    text = " ".join(
        [
            framework.course_name,
            framework.target_user,
            framework.learner_current_state,
            framework.learner_expected_state,
            framework.mindset_shift,
            framework.core_problem,
            framework.application_scenario,
            " ".join(_lesson_text(lesson) for lesson in framework.lessons),
        ]
    )
    lesson_text = " ".join(_lesson_text(lesson) for lesson in framework.lessons)
    extra_deductions: list[DeductionItem] = []
    if any(keyword in text for keyword in FORBIDDEN_DOMAIN_KEYWORDS):
        extra_deductions.append(DeductionItem("forbidden_medical_domain", 100.0, "涉及医学/医疗建议场景，按你的标注标准这类 AI 课程需要直接否决。"))
    if any(keyword in text for keyword in HIGH_RISK_DOMAIN_KEYWORDS) and not any(keyword in text for keyword in BOUNDARY_KEYWORDS):
        extra_deductions.append(DeductionItem("risk_boundary_missing", 10.0, "高风险主题没有写清边界、审批或人工判断环节，按你的标准需要额外扣分。"))
    if any(left in text and right in text for left, right in MIXED_TOPIC_PAIRS):
        extra_deductions.append(DeductionItem("mixed_topic_scope", 25.0, "课程把两个相对独立的大主题硬合并在一起，按你的标准会被判为主题发散、需要重做。"))
    if len(framework.lessons) <= 7 and any(keyword in text for keyword in OVERSIZED_TOPIC_KEYWORDS):
        extra_deductions.append(DeductionItem("oversized_topic_for_course_size", 18.0, "课程主题过大，但课时数量不足以真正讲透，按你的标准需要明显扣分。"))
    if len(framework.lessons) >= 6 and any(keyword in text for keyword in UNDERSIZED_TOPIC_KEYWORDS):
        extra_deductions.append(DeductionItem("undersized_topic_overexpanded", 15.0, "课程主题本身较小，却拆成过多课时，按你的标准会被认为内容注水或切分失衡。"))
    for trigger_keywords, required_keywords, reason in CORE_WORKFLOW_REQUIREMENTS:
        if any(keyword in text for keyword in trigger_keywords) and not any(keyword in lesson_text for keyword in required_keywords):
            extra_deductions.append(DeductionItem("core_workflow_gap", 30.0, reason))
            break
    if not extra_deductions:
        return score_result
    all_deductions = [*score_result.deductions, *extra_deductions]
    deduction_total = round(sum(item.points for item in all_deductions), 2)
    total_score = max(0.0, min(100.0, score_result.local_standard_score - deduction_total))
    explanations = [text for text in score_result.explanations if not text.startswith("规则扣分合计")]
    explanations.insert(2, f"规则扣分合计 {deduction_total:.2f} 分。")
    explanations.extend(item.reason for item in extra_deductions)
    summary = (
        f"课程最终得分 {total_score:.2f} 分，评级为“{_grade_from_score(total_score)}”。"
        f"{'达到' if total_score >= PASS_THRESHOLD else '未达到'} 80 分通过线。"
        "本地评分标准会更强调实战性、课时匹配、逻辑递进和真实落地性。"
    )
    return replace(
        score_result,
        deduction_total=deduction_total,
        total_score=round(total_score, 2),
        passed=total_score >= PASS_THRESHOLD,
        grade=_grade_from_score(total_score),
        deductions=all_deductions,
        explanations=explanations,
        summary=summary,
    )


def _build_rule_based_review_summary(score_result: ScoreResult) -> str:
    if score_result.grade == "优秀":
        return "这门课整体结构已经比较完整，重点是继续增强关键模块的说服力和落地细节。"
    if score_result.grade == "良好":
        return "这门课整体方向是对的，但还可以通过补强弱项，让课程更像一门成熟可售的系统课。"
    if score_result.grade == "一般":
        return "这门课已经有基本骨架，但在结构清晰度和落地性上还有明显优化空间。"
    return "这门课当前更像一个初步草案，建议先补齐目标、顺序和实战部分，再继续细化。"


def _build_rule_based_improvement_suggestions(feature_assessments: list[FeatureAssessment], score_result: ScoreResult) -> list[ImprovementSuggestion]:
    suggestions: list[ImprovementSuggestion] = []
    score_map = {item.feature_name: item.score for item in feature_assessments}
    if score_map.get("目标清晰度", 5) <= 3:
        suggestions.append(ImprovementSuggestion("把课程目标说得更具体", "课程收益如果不够具体，用户很难快速判断这门课是否真的适合自己。", "把课程名称、核心问题和学员期望状态统一成一个明确结果，例如“学完后能独立完成什么”。"))
    if score_map.get("目标学员明确度", 5) <= 3:
        suggestions.append(ImprovementSuggestion("把目标学员收窄", "目标学员过宽时，课程内容容易失焦，前后难度也会不稳定。", "明确学员的经验水平、当前卡点和使用场景，尽量用“谁、现在什么状态、想解决什么问题”来重写目标学员描述。"))
    if score_map.get("内容逻辑性", 5) <= 3 or any(item.rule_name == "sequence_not_reasonable" for item in score_result.deductions):
        suggestions.append(ImprovementSuggestion("重排课程顺序", "课程顺序不清晰时，学员会在还没建立理解时就进入技巧或实战，影响吸收效果。", "把课程调整为“认知/基础 -> 方法/拆解 -> 应用/案例 -> 实战/复盘”的递进结构，避免前两节课就直接进入案例实操。"))
    if score_map.get("实战性", 5) <= 3 or any(item.rule_name == "late_stage_application_missing" for item in score_result.deductions):
        suggestions.append(ImprovementSuggestion("加强后半段实战", "如果后半段缺少案例、演练或项目应用，课程会更像知识讲解而不是可落地训练。", "至少在最后三分之一课时中加入真实案例拆解、完整演练或项目式任务，让学员把前面的内容真正用起来。"))
    if any(item.rule_name == "core_workflow_gap" for item in score_result.deductions):
        suggestions.append(ImprovementSuggestion("补齐关键交付环节", "课程承诺的最终交付物缺少关键能力覆盖，导致核心工作流断裂。", "检查课程名和核心问题承诺的最终成果，补上那个成果必须依赖的关键环节。"))
    if score_map.get("应用场景清晰度", 5) <= 3:
        suggestions.append(ImprovementSuggestion("把应用场景写得更真", "应用场景太泛时，课程价值会显得抽象，用户也难以联想到自己的工作场景。", "补充更具体的使用环境，例如具体岗位、业务流程、交付场景或转化场景，而不是只写“工作提效”。"))
    if score_map.get("课程规模合理性", 5) <= 3:
        suggestions.append(ImprovementSuggestion("重新调整课时规模", "课时过多或过少都会影响课程节奏，容易出现信息密度失衡。", "检查是否有过碎的小节需要合并，或是否有重要模块缺失需要拆开，让每节课都承担一个清晰任务。"))
    if score_map.get("思维转换明确度", 5) <= 3:
        suggestions.append(ImprovementSuggestion("重写思维转换", "思维转换不明确时，课程容易只剩知识点堆叠，缺少认知升级主线。", "把思维转换写成“从什么旧做法，转变为哪种新判断或新工作方式”，并让前几节课服务这个转变。"))
    if not suggestions:
        suggestions.append(ImprovementSuggestion("补强高分课的说服力", "虽然课程整体已经较完整，但还可以进一步提升成交感和交付感。", "优先补充代表性案例、课后练习和成果输出说明，让高分框架更像一门可直接交付的课程。"))
    return suggestions[:5]


def _decision_flags_from_score(score_result: ScoreResult) -> DecisionFlags:
    rule_names = {item.rule_name for item in score_result.deductions}
    return DecisionFlags(
        topic_too_broad="oversized_topic_for_course_size" in rule_names,
        topic_too_narrow="undersized_topic_overexpanded" in rule_names,
        topic_mixed="mixed_topic_scope" in rule_names,
        difficulty_jump="sequence_not_reasonable" in rule_names,
        late_stage_practice_weak="late_stage_application_missing" in rule_names,
        core_workflow_gap="core_workflow_gap" in rule_names,
        boundary_unclear="risk_boundary_missing" in rule_names,
        unsafe_domain="forbidden_medical_domain" in rule_names,
    )


def _feature_assessments_to_dimension_scores(feature_assessments: list[FeatureAssessment]) -> DecisionDimensionScores:
    assessment_map = {item.feature_name: item for item in feature_assessments}
    return DecisionDimensionScores(
        goal_clarity=DecisionDimensionItem(score=assessment_map["目标清晰度"].score, direction=_direction_from_score(assessment_map["目标清晰度"].score), reason=assessment_map["目标清晰度"].reason),
        target_audience_clarity=DecisionDimensionItem(score=assessment_map["目标学员明确度"].score, direction=_direction_from_score(assessment_map["目标学员明确度"].score), reason=assessment_map["目标学员明确度"].reason),
        content_logic=DecisionDimensionItem(score=assessment_map["内容逻辑性"].score, direction=_direction_from_score(assessment_map["内容逻辑性"].score), reason=assessment_map["内容逻辑性"].reason),
        mindset_shift_clarity=DecisionDimensionItem(score=assessment_map["思维转换明确度"].score, direction=_direction_from_score(assessment_map["思维转换明确度"].score), reason=assessment_map["思维转换明确度"].reason),
        application_scenario_clarity=DecisionDimensionItem(score=assessment_map["应用场景清晰度"].score, direction=_direction_from_score(assessment_map["应用场景清晰度"].score), reason=assessment_map["应用场景清晰度"].reason),
        course_size_reasonableness=DecisionDimensionItem(score=assessment_map["课程规模合理性"].score, direction=_direction_from_score(assessment_map["课程规模合理性"].score), reason=assessment_map["课程规模合理性"].reason),
        practicality=DecisionDimensionItem(score=assessment_map["实战性"].score, direction=_direction_from_score(assessment_map["实战性"].score), reason=assessment_map["实战性"].reason),
    )


def _build_rule_based_decision_agent_output(score_result: ScoreResult, feature_assessments: list[FeatureAssessment], review_summary: str, improvement_suggestions: list[ImprovementSuggestion]) -> DecisionAgentOutput:
    decision_flags = _decision_flags_from_score(score_result)
    active_flags = [name for name, value in decision_flags.model_dump().items() if value]
    critical_issues: list[CriticalIssue] = []
    flag_map = {
        "oversized_topic_for_course_size": "topic_too_broad",
        "undersized_topic_overexpanded": "topic_too_narrow",
        "mixed_topic_scope": "topic_mixed",
        "sequence_not_reasonable": "difficulty_jump",
        "late_stage_application_missing": "late_stage_practice_weak",
        "core_workflow_gap": "core_workflow_gap",
        "risk_boundary_missing": "boundary_unclear",
        "forbidden_medical_domain": "unsafe_domain",
    }
    for deduction in score_result.deductions[:3]:
        related_flag = flag_map.get(deduction.rule_name)
        critical_issues.append(
            CriticalIssue(
                title=deduction.rule_name.replace("_", " "),
                description=deduction.reason,
                impact=f"该问题会额外扣除 {deduction.points:.0f} 分，并明显压低课程通过概率。",
                priority=_priority_from_flag(related_flag) if related_flag else DecisionPriority.MEDIUM,
                related_flags=[related_flag] if related_flag else [],
            )
        )
    suggestions = [
        DecisionImprovementSuggestion(
            title=item.title,
            problem=item.problem,
            suggestion=item.suggestion,
            priority=DecisionPriority.HIGH if index == 0 else DecisionPriority.MEDIUM,
            related_flags=active_flags[:2],
        )
        for index, item in enumerate(improvement_suggestions[:5])
    ]
    passed = score_result.total_score >= PASS_THRESHOLD and not (decision_flags.unsafe_domain or decision_flags.topic_mixed)
    pass_reason = "课程主体结构已经成立，虽然仍有可优化点，但不足以阻断通过。" if passed else "课程存在关键结构或边界问题，当前版本不建议直接通过。"
    return DecisionAgentOutput(
        agent_total_score=score_result.total_score,
        agent_grade=_grade_from_final_score(score_result.total_score),
        agent_passed=passed,
        confidence=0.55,
        summary=review_summary,
        pass_decision_reason=pass_reason,
        dimension_scores=_feature_assessments_to_dimension_scores(feature_assessments),
        decision_flags=decision_flags,
        critical_issues=critical_issues,
        improvement_suggestions=suggestions,
    )


def _blend_scores(local_score_result: ScoreResult, decision_agent_output: DecisionAgentOutput) -> BlendedScoreResult:
    final_score = round((local_score_result.total_score * LOCAL_SCORE_WEIGHT) + (decision_agent_output.agent_total_score * DECISION_AGENT_WEIGHT), 2)
    if decision_agent_output.decision_flags.unsafe_domain or decision_agent_output.decision_flags.topic_mixed:
        final_score = min(final_score, 79.0)
    rationale = (
        f"综合分由本地评分 {local_score_result.total_score:.2f} 分和评分 agent "
        f"{decision_agent_output.agent_total_score:.2f} 分按 "
        f"{int(LOCAL_SCORE_WEIGHT * 100)}/{int(DECISION_AGENT_WEIGHT * 100)} 融合得到。"
    )
    if decision_agent_output.decision_flags.unsafe_domain or decision_agent_output.decision_flags.topic_mixed:
        rationale += " 由于命中 blocker 级问题，最终结果被限制为不通过。"
    return BlendedScoreResult(
        local_score=local_score_result.total_score,
        decision_agent_score=decision_agent_output.agent_total_score,
        final_score=final_score,
        local_weight=LOCAL_SCORE_WEIGHT,
        decision_agent_weight=DECISION_AGENT_WEIGHT,
        grade=_grade_from_final_score(final_score).value,
        passed=final_score >= PASS_THRESHOLD,
        rationale=rationale,
    )


def _criteria_from_feature_assessments(feature_assessments: list[FeatureAssessment]) -> list[SeriesCriterion]:
    return [
        SeriesCriterion(
            criterion_id=item.feature_name,
            name=item.feature_name,
            weight=float(DIMENSION_WEIGHTS.get(item.feature_name, 10)),
            score=float(item.score),
            max_score=5.0,
            reason=item.reason,
        )
        for item in feature_assessments
    ]


def _suggestions_from_decision_output(output: DecisionAgentOutput) -> list[SeriesSuggestion]:
    suggestions = [
        SeriesSuggestion(
            criterion_id="decision_agent",
            problem=item.problem,
            suggestion=item.suggestion,
            evidence_span=item.title,
            severity="high" if item.priority == DecisionPriority.HIGH else "medium",
        )
        for item in output.improvement_suggestions
    ]
    if not suggestions and output.summary:
        suggestions.append(
            SeriesSuggestion(
                criterion_id="decision_agent",
                problem=output.summary,
                suggestion="继续围绕上述问题补强结构、场景和实战闭环。",
                evidence_span="评分 Agent",
                severity="low",
            )
        )
    return suggestions[:5]


async def _extract_features_with_llm(deepseek: DeepSeekClient, framework: CourseFramework) -> tuple[CourseFeatures, list[FeatureAssessment]]:
    model = deepseek._build_chat_model(deepseek.profile.review)
    structured = model.with_structured_output(LLMFeatureExtraction, method="function_calling")
    result = await structured.ainvoke(
        [
            ("system", "你是一个课程评分特征提取助手。请根据课程框架，对课程做结构化特征判断。只提取特征，不要输出额外解释。评分标准：1=很弱，2=偏弱，3=一般，4=较好，5=很好。请严格判断以下维度：目标清晰度、目标学员明确度、内容逻辑性、思维转换明确度、应用场景清晰度、课程规模合理性、实战性。同时判断：后半段是否有应用/实战内容，课程顺序是否合理。理由必须简短具体，并紧扣课程框架本身。"),
            ("human", _framework_text(framework)),
        ]
    )
    features = CourseFeatures(
        goal_clarity=result.goal_clarity.score,
        target_audience_clarity=result.target_audience_clarity.score,
        content_logic=result.content_logic.score,
        mindset_shift_clarity=result.mindset_shift_clarity.score,
        application_scenario_clarity=result.application_scenario_clarity.score,
        course_size_reasonableness=result.course_size_reasonableness.score,
        practicality=result.practicality.score,
        has_late_stage_application=result.has_late_stage_application,
        sequence_is_reasonable=result.sequence_is_reasonable,
    )
    assessments = [
        FeatureAssessment("目标清晰度", result.goal_clarity.score, result.goal_clarity.reason),
        FeatureAssessment("目标学员明确度", result.target_audience_clarity.score, result.target_audience_clarity.reason),
        FeatureAssessment("内容逻辑性", result.content_logic.score, result.content_logic.reason),
        FeatureAssessment("思维转换明确度", result.mindset_shift_clarity.score, result.mindset_shift_clarity.reason),
        FeatureAssessment("应用场景清晰度", result.application_scenario_clarity.score, result.application_scenario_clarity.reason),
        FeatureAssessment("课程规模合理性", result.course_size_reasonableness.score, result.course_size_reasonableness.reason),
        FeatureAssessment("实战性", result.practicality.score, result.practicality.reason),
    ]
    return features, assessments


async def _generate_review_with_llm(deepseek: DeepSeekClient, framework: CourseFramework, features: CourseFeatures, score_result: ScoreResult) -> tuple[str, list[ImprovementSuggestion]]:
    model = deepseek._build_chat_model(deepseek.profile.review)
    structured = model.with_structured_output(LLMImprovementReport, method="function_calling")
    score_text = "\n".join(
        [
            f"总分: {score_result.total_score}",
            f"评级: {score_result.grade}",
            "结构化特征:",
            f"- 目标清晰度: {features.goal_clarity}",
            f"- 目标学员明确度: {features.target_audience_clarity}",
            f"- 内容逻辑性: {features.content_logic}",
            f"- 思维转换明确度: {features.mindset_shift_clarity}",
            f"- 应用场景清晰度: {features.application_scenario_clarity}",
            f"- 课程规模合理性: {features.course_size_reasonableness}",
            f"- 实战性: {features.practicality}",
            f"- 后半段应用/实战: {'是' if features.has_late_stage_application else '否'}",
            f"- 课程顺序是否合理: {'是' if features.sequence_is_reasonable else '否'}",
        ]
    )
    result = await structured.ainvoke(
        [
            ("system", "你是一个课程优化顾问。现在已经有课程框架、结构化特征评分和最终得分。请输出一份简洁但具体的修改建议，帮助用户优化课程。要求：1.review_summary 总结当前课程的整体判断；2.improvement_suggestions 给出 3-5 条最重要的修改建议；3.每条建议都包含：标题、当前问题、具体怎么改；4.建议必须落到课程结构、课时安排、案例实战、目标学员、应用场景这些具体层面；5.如果课程后半段缺少应用或顺序不合理，要优先指出。"),
            ("human", f"课程框架如下：\n{_framework_text(framework)}\n\n评分信息如下：\n{score_text}"),
        ]
    )
    return (
        result.review_summary,
        [ImprovementSuggestion(title=item.title, problem=item.problem, suggestion=item.suggestion) for item in result.improvement_suggestions],
    )


async def _evaluate_decision_agent_with_llm(deepseek: DeepSeekClient, framework: CourseFramework, feature_assessments: list[FeatureAssessment], score_result: ScoreResult) -> DecisionAgentOutput:
    model = deepseek._build_chat_model(deepseek.profile.review)
    structured = model.with_structured_output(LLMDecisionReview, method="function_calling")
    feature_text = "\n".join(f"- {item.feature_name}: {item.score} 分 | {item.reason}" for item in feature_assessments)
    result = await structured.ainvoke(
        [
            (
                "system",
                "你是一名严格但专业的课程评审顾问。你的职责不是欣赏课程文案，而是判断这门课是否真的能教、能学、能落地，并给出结构化评审结果。评审原则：通过线是 80 分；更重视主题大小和课时匹配、内容递进、后半段实战、真实场景落地、风险边界；如果命中 blocker 级问题，通常应直接建议不通过。输出要求：agent_total_score 为 0-100；decision_flags 必须完整判断八个标签；critical_issues 只保留 1-3 个最影响通过与否的问题；summary 和 pass_decision_reason 要直接回答“这门课为什么过/不过”。",
            ),
            (
                "human",
                "请结合课程框架、本地特征评分和本地评分结论，给出你的课程评审判断。\n\n"
                f"课程框架：\n{_framework_text(framework)}\n\n"
                f"本地特征评分：\n{feature_text}\n\n"
                f"本地评分结果：\n- 本地总分: {score_result.total_score:.2f}\n- 本地评级: {score_result.grade}\n"
                f"- 是否通过: {'通过' if score_result.passed else '需重做'}\n"
                f"- 扣分理由: {'；'.join(item.reason for item in score_result.deductions) if score_result.deductions else '无'}",
            ),
        ]
    )
    return DecisionAgentOutput(
        agent_total_score=result.agent_total_score,
        agent_grade=result.agent_grade,
        agent_passed=result.agent_passed,
        confidence=result.confidence,
        summary=result.summary,
        pass_decision_reason=result.pass_decision_reason,
        dimension_scores=_feature_assessments_to_dimension_scores(feature_assessments),
        decision_flags=result.decision_flags,
        critical_issues=result.critical_issues,
        improvement_suggestions=[],
    )


async def score_series_framework_markdown(markdown_text: str, deepseek: DeepSeekClient) -> SeriesReviewReport:
    framework = parse_framework_markdown(markdown_text)
    extraction_source = "rule"
    if deepseek.can_use_remote_llm():
        try:
            features, feature_assessments = await _extract_features_with_llm(deepseek, framework)
            extraction_source = "llm"
        except Exception:
            features, feature_assessments = extract_features_from_framework(framework)
    else:
        features, feature_assessments = extract_features_from_framework(framework)

    score_result = _apply_framework_standard_overrides(framework, score_features(features))

    if deepseek.can_use_remote_llm():
        try:
            review_summary, improvement_suggestions = await _generate_review_with_llm(deepseek, framework, features, score_result)
        except Exception:
            review_summary = _build_rule_based_review_summary(score_result)
            improvement_suggestions = _build_rule_based_improvement_suggestions(feature_assessments, score_result)
        decision_agent_source = "rule"
        decision_agent_output: DecisionAgentOutput | None = None
        for attempt in range(2):
            try:
                decision_agent_output = await _evaluate_decision_agent_with_llm(deepseek, framework, feature_assessments, score_result)
                decision_agent_output.improvement_suggestions = [
                    DecisionImprovementSuggestion(
                        title=item.title,
                        problem=item.problem,
                        suggestion=item.suggestion,
                        priority=DecisionPriority.HIGH if index == 0 else DecisionPriority.MEDIUM,
                        related_flags=[name for name, value in decision_agent_output.decision_flags.model_dump().items() if value][:2],
                    )
                    for index, item in enumerate(improvement_suggestions[:5])
                ]
                decision_agent_source = "llm"
                break
            except Exception:
                if attempt == 0:
                    time.sleep(1)
        if decision_agent_output is None:
            decision_agent_output = _build_rule_based_decision_agent_output(score_result, feature_assessments, review_summary, improvement_suggestions)
    else:
        review_summary = _build_rule_based_review_summary(score_result)
        improvement_suggestions = _build_rule_based_improvement_suggestions(feature_assessments, score_result)
        decision_agent_output = _build_rule_based_decision_agent_output(score_result, feature_assessments, review_summary, improvement_suggestions)
        decision_agent_source = "rule"

    blended_score = _blend_scores(score_result, decision_agent_output)
    summary = decision_agent_output.summary or review_summary
    return SeriesReviewReport(
        total_score=blended_score.final_score,
        criteria=_criteria_from_feature_assessments(feature_assessments),
        suggestions=_suggestions_from_decision_output(decision_agent_output),
        summary=summary,
        extraction_source=extraction_source,
        feature_assessments=feature_assessments,
        score_result=score_result,
        decision_agent_output=decision_agent_output,
        decision_agent_source=decision_agent_source,
        blended_score=blended_score,
    )


def format_series_review_report_markdown(report: SeriesReviewReport) -> str:
    extraction_source = getattr(report, "extraction_source", "rule")
    feature_assessments = list(getattr(report, "feature_assessments", []) or [])
    score_result = getattr(report, "score_result", None)
    decision_agent_output = getattr(report, "decision_agent_output", None)
    decision_agent_source = getattr(report, "decision_agent_source", "rule")
    blended_score = getattr(report, "blended_score", None)
    lines = [
        "## 课程评分与决策",
        "",
        f"- 最终综合分：{report.total_score:.2f} / 100",
        "### 课程框架自动特征提取",
        f"- 特征提取来源：{extraction_source}",
    ]
    for item in feature_assessments:
        lines.append(f"- {item.feature_name}：{item.score} 分 | {item.reason}")
    if score_result is not None:
        lines.extend(
            [
                "",
                "### 本地评分结果",
                f"- 总分：{score_result.total_score:.2f} / 100",
                f"- 是否通过：{'通过' if score_result.passed else '需重做'}（阈值：80）",
                f"- 评级：{score_result.grade}",
                f"- 总结：{score_result.summary}",
            ]
        )
        if score_result.deductions:
            lines.append("- 扣分项：")
            for item in score_result.deductions:
                lines.append(f"  - {item.reason} (-{item.points:.2f})")
    if decision_agent_output is not None:
        agent = decision_agent_output
        lines.extend(
            [
                "",
                "### 决策打分",
                f"- 评分来源：{decision_agent_source}",
                f"- 决策 Agent 分数：{agent.agent_total_score:.2f} / 100",
                f"- 决策 Agent 评级：{agent.agent_grade.value}",
                f"- 决策 Agent 是否建议通过：{'通过' if agent.agent_passed else '需重做'}",
                f"- 置信度：{agent.confidence:.2f}",
                f"- 总结：{agent.summary}",
                f"- 过线判断：{agent.pass_decision_reason}",
            ]
        )
        active_flags = [key for key, value in agent.decision_flags.model_dump().items() if value]
        lines.append(f"- 关键标签：{'、'.join(active_flags) if active_flags else '无明显关键边界问题'}")
        if agent.critical_issues:
            lines.append("- 关键问题：")
            for item in agent.critical_issues:
                lines.append(f"  - {item.title}（{item.priority.value}）")
                lines.append(f"    当前问题：{item.description}")
                lines.append(f"    影响：{item.impact}")
    if blended_score is not None:
        lines.extend(
            [
                "",
                "### 综合决策",
                f"- 最终分数：{blended_score.final_score:.2f} / 100",
                f"- 最终评级：{blended_score.grade}",
                f"- 最终是否通过：{'通过' if blended_score.passed else '需重做'}（阈值：80）",
                f"- 融合说明：{blended_score.rationale}",
            ]
        )
    if report.suggestions:
        lines.extend(["", "### 修改建议"])
        for item in report.suggestions:
            lines.append(f"- 当前问题：{item.problem}")
            lines.append(f"  修改建议：{item.suggestion}")
    lines.extend(["", "如果你想继续调整，直接在对话里告诉我你要改哪几处，我会基于当前框架继续重做。"])
    return "\n".join(lines)
