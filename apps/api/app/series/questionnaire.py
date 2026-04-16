from __future__ import annotations

from app.series.schema import GuidedQuestion, QuestionOption, StepAnswer, StepKey


QUESTION_FLOW: list[GuidedQuestion] = [
    GuidedQuestion(
        step=StepKey.COURSE_TYPE,
        title="课程主题类型",
        question="你的系列课更接近哪一种主题类型？",
        options=[
            QuestionOption(key="A", label="技能实操型：教用户学会一个具体技能"),
            QuestionOption(key="B", label="方法认知型：帮用户建立系统方法和理解框架"),
            QuestionOption(key="C", label="职业转型型：帮助用户完成岗位或能力转变"),
            QuestionOption(key="D", label="以上都不是，请自己输入"),
        ],
        helper_text="请输入 A/B/C/D；如果选 D，请直接输入 `D 你的答案`，也可以直接输入自定义内容。",
    ),
    GuidedQuestion(
        step=StepKey.TARGET_USER,
        title="目标学员",
        question="你的系列课主要面向哪类人？",
        options=[
            QuestionOption(key="A", label="零基础小白"),
            QuestionOption(key="B", label="有基础但不会系统应用的人"),
            QuestionOption(key="C", label="有经验但想进一步提升的人"),
            QuestionOption(key="D", label="以上都不是，请自己输入"),
        ],
        helper_text="请输入 A/B/C/D；如果选 D，请直接输入 `D 你的答案`，也可以直接输入自定义内容。",
    ),
    GuidedQuestion(
        step=StepKey.LEARNING_GOAL,
        title="学习目标",
        question="用户学完整个系列课，最希望获得什么结果？",
        options=[
            QuestionOption(key="A", label="从 0 到 1 建立完整认知"),
            QuestionOption(key="B", label="能独立完成一个具体成果"),
            QuestionOption(key="C", label="能解决工作中的实际问题"),
            QuestionOption(key="D", label="以上都不是，请自己输入"),
        ],
        helper_text="请输入 A/B/C/D；如果选 D，请直接输入 `D 你的答案`，也可以直接输入自定义内容。",
    ),
    GuidedQuestion(
        step=StepKey.MINDSET_SHIFT,
        title="思维转换",
        question="这套系列课最关键的思维转换是什么？",
        options=[
            QuestionOption(key="A", label="从知道概念到会判断"),
            QuestionOption(key="B", label="从零散经验到系统框架"),
            QuestionOption(key="C", label="从学习理解到真正落地应用"),
            QuestionOption(key="D", label="以上都不是，请自己输入"),
        ],
        helper_text="请输入 A/B/C/D；如果选 D，请直接输入 `D 你的答案`，也可以直接输入自定义内容。",
    ),
    GuidedQuestion(
        step=StepKey.COURSE_SIZE,
        title="课程规模",
        question="你希望这套系列课大致做成什么规模？",
        options=[
            QuestionOption(key="A", label="轻量入门：3 到 5 课"),
            QuestionOption(key="B", label="标准系统课：6 到 8 课"),
            QuestionOption(key="C", label="深度专题课：9 到 12 课"),
            QuestionOption(key="D", label="以上都不是，请自己输入"),
        ],
        helper_text="请输入 A/B/C/D；如果选 D，请直接输入 `D 你的答案`，也可以直接输入自定义内容。",
    ),
    GuidedQuestion(
        step=StepKey.APPLICATION,
        title="应用场景",
        question="这套系列课最终更希望在哪类场景中被用起来？",
        options=[
            QuestionOption(key="A", label="求职或转型场景"),
            QuestionOption(key="B", label="日常工作提效场景"),
            QuestionOption(key="C", label="项目实战或副业变现场景"),
            QuestionOption(key="D", label="以上都不是，请自己输入"),
        ],
        helper_text="请输入 A/B/C/D；如果选 D，请直接输入 `D 你的答案`，也可以直接输入自定义内容。",
    ),
    GuidedQuestion(
        step=StepKey.SUPPLEMENTARY_INFO,
        title="补充信息",
        question="如果你还有补充要求、限制条件、禁区或特别想强调的点，可以在这里补充。",
        helper_text="这一题不是必须回答的。可以直接输入补充信息，也可以直接回车跳过。",
        required=False,
    ),
]


QUESTION_BY_STEP = {question.step.value: question for question in QUESTION_FLOW}


def get_question_by_step(step_id: str) -> GuidedQuestion | None:
    return QUESTION_BY_STEP.get(step_id)


def parse_user_answer(question: GuidedQuestion, raw_input: str) -> StepAnswer:
    raw_text = raw_input.strip()
    if not raw_text:
        if question.required:
            raise ValueError("这一题必须回答后才能继续。")
        return StepAnswer(
            step=question.step,
            question_title=question.title,
            selected_key="SKIP",
            selected_label="未补充",
            final_answer="无补充信息",
            custom_input=None,
        )

    normalized = raw_text.upper()
    option_by_key = {opt.key.upper(): opt for opt in question.options}
    custom_option = option_by_key.get("D")

    if not question.options:
        return StepAnswer(
            step=question.step,
            question_title=question.title,
            selected_key="D",
            selected_label="自定义输入",
            final_answer=raw_text,
            custom_input=raw_text,
        )

    for key, option in option_by_key.items():
        prefixes = {key, f"{key}.", f"{key} ", f"{key}：", f"{key}:"}
        if normalized in prefixes or any(normalized.startswith(prefix) for prefix in prefixes):
            custom_input = raw_text[len(key):].lstrip(" .:：、-")
            final_answer = option.label
            if key == "D":
                if not custom_input:
                    raise ValueError("选择 D 时，请补充你的自定义答案。")
                final_answer = custom_input
            return StepAnswer(
                step=question.step,
                question_title=question.title,
                selected_key=key,
                selected_label=option.label,
                final_answer=final_answer,
                custom_input=custom_input or None,
            )

    for option in question.options:
        if raw_text == option.label:
            return StepAnswer(
                step=question.step,
                question_title=question.title,
                selected_key=option.key,
                selected_label=option.label,
                final_answer=option.label,
            )

    fallback_label = custom_option.label if custom_option else "自定义输入"
    return StepAnswer(
        step=question.step,
        question_title=question.title,
        selected_key="D",
        selected_label=fallback_label,
        final_answer=raw_text,
        custom_input=raw_text,
    )


def render_question_prompt(question: GuidedQuestion, current_step: int, total_steps: int) -> str:
    lines = [
        f"系列课结构化问答 {current_step}/{total_steps}",
        f"问题：{question.title}",
        question.question,
    ]
    if question.options:
        lines.append("")
        for option in question.options:
            lines.append(f"{option.key}. {option.label}")
            lines.append("")
    if question.helper_text:
        lines.append(question.helper_text)
    return "\n".join(lines).strip()
