from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class StepKey(StrEnum):
    COURSE_TYPE = "course_type"
    TARGET_USER = "target_user"
    LEARNING_GOAL = "learning_goal"
    MINDSET_SHIFT = "mindset_shift"
    COURSE_SIZE = "course_size"
    APPLICATION = "application"
    SUPPLEMENTARY_INFO = "supplementary_info"


class QuestionOption(BaseModel):
    key: str = Field(description="选项标识，例如 A/B/C/D")
    label: str = Field(description="选项显示文案")


class GuidedQuestion(BaseModel):
    step: StepKey
    title: str
    question: str
    options: list[QuestionOption] = Field(default_factory=list)
    helper_text: str | None = None
    required: bool = True


class StepAnswer(BaseModel):
    step: StepKey
    question_title: str
    selected_key: str
    selected_label: str
    final_answer: str
    custom_input: str | None = None


class LessonOutline(BaseModel):
    lesson_number: int = Field(description="课程序号，从 1 开始")
    title: str = Field(description="课时标题")
    summary: str = Field(description="本节课的核心内容与产出")


class CourseFramework(BaseModel):
    course_name: str = Field(description="课程名称")
    target_user: str = Field(description="目标学员")
    learner_current_state: str = Field(description="学员当前状态")
    learner_expected_state: str = Field(description="学员期望状态")
    mindset_shift: str = Field(description="关键思维转换")
    core_problem: str = Field(description="课程核心问题")
    application_scenario: str = Field(description="课程应用场景")
    lessons: list[LessonOutline] = Field(description="系列课程框架")

    def to_markdown(self, title: str = "系列课程框架") -> str:
        lines = [
            f"# {title}",
            "",
            f"课程名称：{self.course_name}",
            "",
            f"目标学员：{self.target_user}",
            "",
            f"学员当前状态：{self.learner_current_state}",
            "",
            f"学员期望状态：{self.learner_expected_state}",
            "",
            f"思维转换：{self.mindset_shift}",
            "",
            f"课程核心问题：{self.core_problem}",
            "",
            f"课程应用场景：{self.application_scenario}",
            "",
            "课程框架：",
            "",
        ]

        for lesson in self.lessons:
            lines.append(f"第{lesson.lesson_number}课：{lesson.title}")
            lines.append(f"内容：{lesson.summary}")
            lines.append("")

        return "\n".join(lines).strip()
