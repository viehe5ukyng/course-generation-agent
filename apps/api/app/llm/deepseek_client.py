from __future__ import annotations

import os
from dataclasses import dataclass
import re
from textwrap import dedent
from typing import AsyncIterator

import httpx
import yaml
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.prompt_registry import PromptRegistry
from app.core.schemas import LLMProviderConfig
from app.core.settings import Settings
from app.series.schema import CourseFramework as SeriesCourseFramework
from app.series.schema import LessonOutline as SeriesLessonOutline


@dataclass(frozen=True)
class ProviderProfiles:
    chat: LLMProviderConfig
    review: LLMProviderConfig


class RequirementExtractionResult(BaseModel):
    subject: str | None = None
    grade_level: str | None = None
    topic: str | None = None
    audience: str | None = None
    objective: str | None = None
    duration: str | None = None
    constraints: str | None = None
    course_positioning: str | None = None
    target_problem: str | None = None
    expected_result: str | None = None
    tone_style: str | None = None
    case_preferences: str | None = None
    script_requirements: str | None = None
    material_requirements: str | None = None


class ReviewCriterionPayload(BaseModel):
    criterion_id: str
    name: str
    weight: float
    score: float
    max_score: float
    reason: str


class ReviewSuggestionPayload(BaseModel):
    criterion_id: str
    problem: str
    suggestion: str
    evidence_span: str
    severity: str = "medium"


class ReviewMarkdownResult(BaseModel):
    total_score: float
    criteria: list[ReviewCriterionPayload]
    suggestions: list[ReviewSuggestionPayload]


class DeepSeekClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.profile = self._load_profile()
        self.prompts = PromptRegistry(settings.prompt_root_dir)

    def _load_profile(self) -> ProviderProfiles:
        if self.settings.llm_config_file.exists():
            payload = yaml.safe_load(self.settings.llm_config_file.read_text(encoding="utf-8")) or {}
            providers = payload.get("providers", {})
            profiles = payload.get("profiles", {})

            def build_profile(name: str, fallback_temperature: float) -> LLMProviderConfig:
                profile_payload = profiles.get(name, {})
                provider_name = profile_payload.get("provider", payload.get("default_provider", "deepseek"))
                provider_payload = providers.get(provider_name, {})
                return LLMProviderConfig(
                    provider=provider_name,
                    model=profile_payload["model"],
                    temperature=float(profile_payload.get("temperature", fallback_temperature)),
                    api_base_env=provider_payload.get("api_base_env"),
                    api_key_env=provider_payload.get("api_key_env"),
                    base_url=provider_payload.get("base_url"),
                )

            return ProviderProfiles(
                chat=build_profile("chat", 0.4),
                review=build_profile("review", 0.1),
            )

        payload = yaml.safe_load(self.settings.deepseek_config_file.read_text(encoding="utf-8")) or {}
        return ProviderProfiles(
            chat=LLMProviderConfig(
                provider="deepseek",
                model=payload["chat_model"],
                temperature=float(payload.get("chat_temperature", 0.4)),
                api_base_env="DEEPSEEK_BASE_URL",
                api_key_env="DEEPSEEK_API_KEY",
                base_url=self.settings.deepseek_base_url,
            ),
            review=LLMProviderConfig(
                provider="deepseek",
                model=payload["review_model"],
                temperature=float(payload.get("review_temperature", 0.1)),
                api_base_env="DEEPSEEK_BASE_URL",
                api_key_env="DEEPSEEK_API_KEY",
                base_url=self.settings.deepseek_base_url,
            ),
        )

    def can_use_remote_llm(self) -> bool:
        if self.settings.app_env == "test":
            return False
        return bool(self._resolve_api_key(self.profile.chat))

    def _resolve_api_key(self, profile: LLMProviderConfig) -> str | None:
        if profile.api_key_env:
            return os.getenv(profile.api_key_env) or self.settings.deepseek_api_key
        return self.settings.deepseek_api_key

    def _resolve_base_url(self, profile: LLMProviderConfig) -> str:
        if profile.api_base_env and os.getenv(profile.api_base_env):
            return os.getenv(profile.api_base_env) or profile.base_url or self.settings.deepseek_base_url
        return profile.base_url or self.settings.deepseek_base_url

    def _build_chat_model(self, profile: LLMProviderConfig) -> ChatOpenAI:
        # trust_env=False prevents httpx from picking up SOCKS/HTTP proxy env vars
        return ChatOpenAI(
            model=profile.model,
            temperature=profile.temperature,
            api_key=self._resolve_api_key(profile),
            base_url=self._resolve_base_url(profile),
            http_client=httpx.Client(trust_env=False),
            http_async_client=httpx.AsyncClient(trust_env=False),
        )

    async def stream_markdown(self, context: dict) -> AsyncIterator[str]:
        if not self.can_use_remote_llm():
            for chunk in self._split_chunks(self._fallback_markdown(context)):
                yield chunk
            return

        model = self._build_chat_model(self.profile.chat)
        prompt = self.prompts.render(
            "deepseek/generate_markdown.md",
            decision_summary=context["decision_summary"],
            slot_summary=context["slot_summary"],
            source_summary=context["source_summary"],
            example_reference=context["example_reference"],
            constraint_summary=context.get("constraint_summary", "无额外约束"),
        )
        async for chunk in model.astream(prompt):
            text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
            if text:
                yield text

    async def stream_step_markdown(self, context: dict) -> AsyncIterator[str]:
        if not self.can_use_remote_llm():
            for chunk in self._split_chunks(self._fallback_step_markdown(context)):
                yield chunk
            return

        model = self._build_chat_model(self.profile.chat)
        prompt = self.prompts.render(
            "deepseek/generate_step_markdown.md",
            step_label=context["step_label"],
            generation_goal=context["generation_goal"],
            required_slots=context["required_slots"],
            optional_slots=context["optional_slots"],
            forbidden_topics=context["forbidden_topics"],
            slot_summary=context["slot_summary"],
            source_summary=context["source_summary"],
            prior_step_artifacts=context["prior_step_artifacts"],
            constraint_summary=context.get("constraint_summary", "无额外约束"),
        )
        async for chunk in model.astream(prompt):
            text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
            if text:
                yield text

    async def stream_series_framework_markdown(self, context: dict) -> AsyncIterator[str]:
        if not self.can_use_remote_llm():
            for chunk in self._split_chunks(self._fallback_series_framework_markdown(context)):
                yield chunk
            return

        model = self._build_chat_model(
            LLMProviderConfig.model_validate(
                {
                    **self.profile.chat.model_dump(),
                    "temperature": 0.35,
                }
            )
        )
        prompt = dedent(
            """
            你是一个资深的系列课程设计顾问。
            你要根据用户的原始想法、结构化问答回答、补充约束和上传资料，产出一套可售卖、可交付、可继续细化的系列课程框架。

            生成要求：
            1. 课程名称自然，不要过度营销。
            2. 目标学员、当前状态、期望状态必须互相一致。
            3. 课程主线要从基础/认知逐步推进到方法、案例、应用和复盘。
            4. 后半段必须明显靠近应用、项目、案例或实战。
            5. 如果用户提供了限制条件、边界、禁区或指定场景，必须显式体现在课程设计里。
            6. 只返回结构化对象，不要额外解释。

            用户原始制课想法：
            {user_input}

            结构化问答回答：
            {guided_answers}

            当前确认信息摘要：
            {slot_summary}

            上传资料摘要：
            {source_summary}

            必须遵守的约束：
            {constraint_summary}

            课时规模提示：
            {course_size_hint}
            """
        ).strip()
        structured = model.with_structured_output(SeriesCourseFramework, method="function_calling")
        framework = await structured.ainvoke(
            prompt.format(
                user_input=context["user_input"],
                guided_answers=context["guided_answers"],
                slot_summary=context["slot_summary"],
                source_summary=context["source_summary"],
                constraint_summary=context.get("constraint_summary", "无额外约束"),
                course_size_hint=context["course_size_hint"],
            )
        )
        markdown = framework.to_markdown()
        for chunk in self._split_chunks(markdown):
            yield chunk

    async def ask_clarification(self, context: dict) -> str:
        if not self.can_use_remote_llm():
            item = context["missing_requirement"]
            return "为了继续制课，我还需要你补充这一个关键信息：\n" + f"- {item['label']}：{item['prompt_hint']}"

        model = self._build_chat_model(
            LLMProviderConfig.model_validate(
                {
                    **self.profile.chat.model_dump(),
                    "temperature": 0.2,
                }
            )
        )
        prompt = self.prompts.render(
            "deepseek/clarify_requirements.md",
            slot_summary=context["slot_summary"],
            missing_requirements=f"- {context['missing_requirement']['label']}：{context['missing_requirement']['prompt_hint']}",
        )
        response = await model.ainvoke(prompt)
        return response.content if isinstance(response.content, str) else str(response.content)

    async def stream_clarification(self, context: dict) -> AsyncIterator[str]:
        if not self.can_use_remote_llm():
            item = context["missing_requirement"]
            text = "为了继续制课，我还需要你补充这一个关键信息：\n" + f"- {item['label']}：{item['prompt_hint']}"
            for chunk in self._split_chunks(text, chunk_size=24):
                yield chunk
            return

        model = self._build_chat_model(
            LLMProviderConfig.model_validate(
                {
                    **self.profile.chat.model_dump(),
                    "temperature": 0.2,
                }
            )
        )
        prompt = self.prompts.render(
            "deepseek/clarify_requirements.md",
            slot_summary=context["slot_summary"],
            missing_requirements=f"- {context['missing_requirement']['label']}：{context['missing_requirement']['prompt_hint']}",
        )
        async for chunk in model.astream(prompt):
            text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
            if text:
                yield text

    async def extract_requirements(
        self,
        *,
        latest_user_message: str,
        known_requirements: dict[str, str | None],
        requirement_defs: list[dict],
    ) -> dict[str, str | None]:
        if not latest_user_message.strip():
            return {}
        if not self.can_use_remote_llm():
            return self._fallback_extract_requirements(latest_user_message)

        model = self._build_chat_model(
            LLMProviderConfig.model_validate(
                {
                    **self.profile.chat.model_dump(),
                    "temperature": 0.0,
                }
            )
        )
        prompt = self.prompts.render(
            "deepseek/extract_requirements.md",
            requirement_defs="\n".join(f"- {item['slot_id']}: {item['label']}，{item['prompt_hint']}" for item in requirement_defs),
            known_requirements="\n".join(f"- {key}: {value}" for key, value in known_requirements.items()) or "无",
            latest_user_message=latest_user_message,
        )
        try:
            structured = model.with_structured_output(RequirementExtractionResult, method="function_calling")
            result = await structured.ainvoke(prompt)
            payload = result.model_dump()
            return {key: value for key, value in payload.items() if value}
        except Exception:
            return self._fallback_extract_requirements(latest_user_message)

    def extract_requirements_local(self, latest_user_message: str) -> dict[str, str | None]:
        if not latest_user_message.strip():
            return {}
        return self._fallback_extract_requirements(latest_user_message)

    def _fallback_extract_requirements(self, latest_user_message: str) -> dict[str, str | None]:
        text = latest_user_message.strip()
        extracted: dict[str, str | None] = {}

        subject_match = re.search(r"(数学|物理|英语|语文|化学|生物|历史|地理)", text)
        if subject_match:
            extracted["subject"] = subject_match.group(1)

        grade_match = re.search(r"(初一|初二|初三|高一|高二|高三|七年级|八年级|九年级)", text)
        if grade_match:
            extracted["grade_level"] = grade_match.group(1)

        audience_match = re.search(r"(初中生|高中生|小学生|零基础学员)", text)
        if audience_match:
            extracted["audience"] = audience_match.group(1)

        inferred_topic = self._infer_series_topic(user_input=text)
        if inferred_topic:
            extracted["topic"] = inferred_topic
        else:
            topic_match = re.search(r"(三角函数|一次函数|二次函数|几何证明|勾股定理|圆|概率|统计)", text)
            if topic_match:
                extracted["topic"] = topic_match.group(1)

        if "入门" in text:
            extracted["course_positioning"] = "入门课"
        elif "进阶" in text:
            extracted["course_positioning"] = "进阶课"
        elif "训练营" in text:
            extracted["course_positioning"] = "训练营"

        if "实操" in text or "带练" in text:
            extracted["tone_style"] = "实操带练"
        elif "讲解" in text:
            extracted["tone_style"] = "知识讲解"
        elif "口语化" in text:
            extracted["tone_style"] = "口语化"

        problem_match = re.search(r"(?:解决|问题是)([^，。,；;\n]+)", text)
        if problem_match:
            extracted["target_problem"] = problem_match.group(1).strip()

        result_match = re.search(r"(?:学完能|结果是)([^，。,；;\n]+)", text)
        if result_match:
            extracted["expected_result"] = result_match.group(1).strip()

        case_match = re.search(r"案例(?:要求|偏好)?是([^。；;\n]+)", text)
        if case_match:
            extracted["case_preferences"] = case_match.group(1).strip()

        script_match = re.search(r"逐字稿(?:要求)?是([^。；;\n]+)", text)
        if script_match:
            extracted["script_requirements"] = script_match.group(1).strip()

        material_match = re.search(r"素材(?:清单)?(?:要求|范围)?是([^。；;\n]+)", text)
        if material_match:
            extracted["material_requirements"] = material_match.group(1).strip()

        return extracted

    async def review_markdown(self, *, markdown: str, rubric: list[dict], threshold: float) -> dict:
        if not self.can_use_remote_llm():
            return self._fallback_review(markdown=markdown, rubric=rubric, threshold=threshold)

        model = self._build_chat_model(self.profile.review)
        rubric_text = "\n".join(
            f"- {item['criterion_id']}: {item['name']} ({item['description']})"
            for item in rubric
        )
        prompt = self.prompts.render(
            "deepseek/review_markdown.md",
            threshold=threshold,
            rubric_text=rubric_text,
            markdown=markdown,
        )
        try:
            structured = model.with_structured_output(ReviewMarkdownResult, method="function_calling")
            result = await structured.ainvoke(prompt)
            return result.model_dump()
        except Exception:
            return self._fallback_review(markdown=markdown, rubric=rubric, threshold=threshold)

    async def improve_markdown(
        self,
        *,
        markdown: str,
        approved_changes: list[str],
        context_summary: str,
        constraint_summary: str = "无额外约束",
        source_version: int | None = None,
        revision_goal: str | None = None,
    ) -> str:
        if not approved_changes:
            return markdown
        if not self.can_use_remote_llm():
            lines = "\n".join(f"- {item}" for item in approved_changes)
            extra = f"\n基础版本：v{source_version}" if source_version else ""
            goal = f"\n修订目标：{revision_goal}" if revision_goal else ""
            return f"{markdown}\n\n## 自动优化说明\n\n本轮自动优化已执行：\n{lines}{extra}{goal}"

        model = self._build_chat_model(
            LLMProviderConfig.model_validate(
                {
                    **self.profile.chat.model_dump(),
                    "temperature": 0.3,
                }
            )
        )
        prompt = self.prompts.render(
            "deepseek/improve_markdown.md",
            context_summary=context_summary,
            approved_changes="\n".join(f"- {item}" for item in approved_changes),
            markdown=markdown,
            constraint_summary=constraint_summary,
            source_version=source_version or "未指定",
            revision_goal=revision_goal or "根据反馈生成更好的新版本",
        )
        response = await model.ainvoke(prompt)
        return response.content if isinstance(response.content, str) else str(response.content)

    async def rewrite_series_framework_markdown(
        self,
        *,
        markdown: str,
        user_input: str,
        guided_answers: str,
        approved_changes: list[str],
        constraint_summary: str = "无额外约束",
        source_version: int | None = None,
        revision_goal: str | None = None,
    ) -> str:
        if not approved_changes:
            return markdown
        if not self.can_use_remote_llm():
            return self._fallback_rewrite_series_framework_markdown(markdown, approved_changes)

        model = self._build_chat_model(
            LLMProviderConfig.model_validate(
                {
                    **self.profile.chat.model_dump(),
                    "temperature": 0.3,
                }
            )
        )
        prompt = dedent(
            """
            你是一个资深的系列课程设计顾问，现在要基于现有系列课框架做定向修订。
            你必须保留原框架里已经合理的部分，但优先修复反馈中指出的问题。
            修订后仍然要保证：目标清晰、对象收敛、递进自然、后半段有真实应用或实战。
            只返回结构化对象，不要额外解释。

            用户原始想法：
            {user_input}

            结构化问答回答：
            {guided_answers}

            当前框架：
            {markdown}

            修订目标：
            {revision_goal}

            需要落实的修改意见：
            {approved_changes}

            必须遵守的约束：
            {constraint_summary}

            基础版本：
            {source_version}
            """
        ).strip()
        structured = model.with_structured_output(SeriesCourseFramework, method="function_calling")
        framework = await structured.ainvoke(
            prompt.format(
                user_input=user_input,
                guided_answers=guided_answers,
                markdown=markdown,
                revision_goal=revision_goal or "根据反馈补强系列课程框架",
                approved_changes="\n".join(f"- {item}" for item in approved_changes),
                constraint_summary=constraint_summary,
                source_version=source_version or "未指定",
            )
        )
        return framework.to_markdown()

    def _fallback_markdown(self, context: dict) -> str:
        topic = context["slots"].get("topic", "待补充主题")
        audience = context["slots"].get("audience", "目标学员")
        objective = context["slots"].get("objective", "完成本节课目标")
        return dedent(
            f"""
            # 单课框架

            本节课解决的核心问题：围绕“{topic}”，帮助{audience}达成“{objective}”。

            ## 你将学会

            - 掌握与“{topic}”相关的核心方法和底层逻辑
            - 能够在真实任务中复用标准化步骤
            - 能够根据反馈继续优化结果

            ## 案例设计

            ### 【案例 1】快速上手案例
            目标：学员能够完成最小可运行结果，并理解基本操作路径。

            ### 【案例 2】业务加压案例
            目标：学员能够在更复杂约束下复用方法，并根据反馈调整输出。

            ### 【案例 3】复盘沉淀案例
            目标：学员能够复盘关键决策，并把方法迁移到新的业务题目。

            ## 整课主线

            先让学员做出结果，再在第二个案例中承受更复杂的条件，最后通过复盘把动作、认知和思维三层目标收拢成稳定方法。

            ## 逐字稿

            大家这节课只盯一件事：{topic}。我们先不讲大背景，先把第一个结果做出来。

            在第一个案例里，你先跟着完成最小动作，拿到一个可用结果。做完以后，我们再解释为什么这样设计。

            进入第二个案例，我们把业务条件收紧。现在不是为了再做一遍，而是为了学会在约束变化时怎么判断、怎么改。

            到第三个案例，我们不再只看输出本身，而是总结你面对类似问题时的下手顺序、判断标准和修正方法。
            """
        ).strip()

    def _fallback_review(self, *, markdown: str, rubric: list[dict], threshold: float) -> dict:
        sections = {
            "core-problem": "本节课解决的核心问题" in markdown,
            "case-design": "案例" in markdown and "目标：" in markdown,
            "mainline": "整课主线" in markdown,
            "script-quality": "逐字稿" in markdown,
            "source-grounding": len(markdown) > 400,
        }
        criteria = []
        suggestions = []
        total_weight = sum(item["weight"] for item in rubric)
        weighted_sum = 0.0
        for item in rubric:
            present = sections.get(item["criterion_id"], False)
            score = 8.5 if present else 5.0
            reason = "结构满足要求。" if present else "该部分信息不足或未明确展开。"
            criteria.append(
                {
                    "criterion_id": item["criterion_id"],
                    "name": item["name"],
                    "weight": item["weight"],
                    "score": score,
                    "max_score": item["max_score"],
                    "reason": reason,
                }
            )
            weighted_sum += score * item["weight"]
            if not present:
                suggestions.append(
                    {
                        "criterion_id": item["criterion_id"],
                        "problem": f"{item['name']}未充分体现。",
                        "suggestion": f"补强“{item['name']}”相关段落，使其满足 rubric。",
                        "evidence_span": item["name"],
                        "severity": "high",
                    }
                )
        total_score = round(weighted_sum / total_weight, 2)
        if total_score >= threshold and not suggestions:
            suggestions.append(
                {
                    "criterion_id": "script-quality",
                    "problem": "整体可通过，但还可以进一步提升表达贴合度。",
                    "suggestion": "检查逐字稿是否更贴近真实授课语气。",
                    "evidence_span": "逐字稿",
                    "severity": "low",
                }
            )
        return {"total_score": total_score, "criteria": criteria, "suggestions": suggestions}

    def _fallback_step_markdown(self, context: dict) -> str:
        return dedent(
            f"""
            # {context['step_label']}

            本步骤目标：{context['generation_goal']}

            ## 当前已确认信息

            {context['slot_summary'] or '暂无'}

            ## 上游已确认产物

            {context['prior_step_artifacts'] or '暂无'}

            ## 上传资料摘要

            {context['source_summary'] or '无上传资料'}

            ## 必须遵守的约束

            {context.get('constraint_summary', '无额外约束')}
            """
        ).strip()

    def _course_size_hint_from_answer(self, answer: str) -> str:
        if "3 到 5" in answer or "3-5" in answer:
            return "建议输出 4 节课左右的系列课程框架。"
        if "6 到 8" in answer or "6-8" in answer:
            return "建议输出 7 节课左右的系列课程框架。"
        if "9 到 12" in answer or "9-12" in answer:
            return "建议输出 10 节课左右的系列课程框架。"
        return "请根据用户描述决定合理的课时数量。"

    def _clean_topic_candidate(self, value: str | None) -> str | None:
        if not value:
            return None

        candidate = re.sub(r"\s+", " ", value).strip("：:，。；;、 \n\t")
        candidate = re.sub(r"^(关于|围绕|聚焦|做|制作|开发|打造|设计|一套|一门|一个)\s*", "", candidate)
        candidate = re.sub(r"(系列课|课程|专题课|训练营|课)$", "", candidate).strip("：:，。；;、 \n\t")
        candidate = re.split(r"[，。；;\n]", candidate, maxsplit=1)[0].strip()

        if not candidate:
            return None
        if candidate in {"这个", "这套", "该课", "课程", "系列课", "核心主题"}:
            return None
        if len(candidate) > 30:
            return None
        return candidate

    def _extract_topic_from_text(self, text: str) -> str | None:
        patterns = [
            r"(?:我要|想|计划)?(?:做|制作|设计|开发|打造)(?:一套|一门|一个)?\s*(?P<topic>[^，。；;\n]{2,30}?)(?:系列课|课程|专题课|训练营)",
            r"(?:关于|围绕|聚焦)\s*(?P<topic>[^，。；;\n]{2,30}?)(?:的)?(?:系列课|课程|专题课|训练营)",
            r"主题(?:是|为|叫|定为)?\s*(?P<topic>[^，。；;\n]{2,30})",
            r"做(?:一套|一门|一个)?\s*(?P<topic>[^，。；;\n]{2,30}?)\s*(?:课|内容)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            topic = self._clean_topic_candidate(match.group("topic"))
            if topic:
                return topic
        return None

    def _infer_series_topic(self, *, user_input: str, answers: dict[str, str] | None = None, fallback_topic: str | None = None) -> str | None:
        answers = answers or {}
        candidates = [
            answers.get("topic"),
            fallback_topic,
            self._extract_topic_from_text(user_input),
        ]
        for candidate in candidates:
            cleaned = self._clean_topic_candidate(candidate)
            if cleaned:
                return cleaned
        return None

    def _series_application_label(self, application: str) -> str:
        cleaned = application.strip()
        if cleaned.endswith("场景"):
            return cleaned[: -len("场景")].strip() or cleaned
        return cleaned

    def _series_expected_state(self, learning_goal: str, application: str) -> str:
        goal = learning_goal.strip()
        if goal.startswith("能"):
            return f"学完后{goal}，并能在{application}中独立完成关键任务。"
        return f"学完后能围绕{goal}，在{application}中独立完成关键任务。"

    def _fallback_series_framework_markdown(self, context: dict) -> str:
        answers = context.get("answers_map", {})
        course_type = answers.get("course_type", "方法认知型")
        target_user = answers.get("target_user", "目标学员待补充")
        learning_goal = answers.get("learning_goal", "能独立完成一个具体成果")
        mindset_shift = answers.get("mindset_shift", "从零散认知转向系统应用")
        application = answers.get("application", "真实工作场景")
        application_label = self._series_application_label(application)
        topic = self._infer_series_topic(
            user_input=context.get("user_input", ""),
            answers=answers,
            fallback_topic=context.get("topic"),
        ) or "系列课主题"
        supplementary = answers.get("supplementary_info", "")
        size_hint = self._course_size_hint_from_answer(answers.get("course_size", ""))

        lesson_count = 6
        if "4 节" in size_hint:
            lesson_count = 4
        elif "10 节" in size_hint:
            lesson_count = 10

        course_name = f"{topic}系列课：从理解到应用的系统训练"
        if "技能实操" in course_type:
            course_name = f"{topic}实战系列课：从入门到项目落地"
        elif "职业转型" in course_type:
            course_name = f"{topic}转型系列课：建立岗位级实战能力"

        lessons = [
            ("建立认知框架", f"明确 {topic} 的整体地图、学习路径和结果标准。"),
            ("拆解核心方法", f"把 {topic} 拆成可复用的方法步骤和判断标准。"),
            ("关键场景演示", f"围绕{application_label}场景演示一遍完整做法。"),
            ("案例练习与纠错", "通过代表性案例练习，暴露常见误区并完成纠偏。"),
            ("项目化应用", f"把前面的方法串成完整工作流，完成一个可交付的小项目。"),
            ("复盘与迁移", "总结方法边界、复盘关键决策，并给出迁移到新场景的方式。"),
        ]
        if lesson_count <= 4:
            lessons = lessons[:4]
        elif lesson_count >= 9:
            lessons = [
                ("行业与问题界定", f"明确 {topic} 在{application}中的价值、边界和结果标准。"),
                ("基础认知搭建", f"建立 {topic} 的核心概念、常见误区和判断框架。"),
                ("方法一：基础动作", "掌握第一层操作流程，完成最小闭环。"),
                ("方法二：结构化拆解", "把零散经验整理成可复用的方法模板。"),
                ("方法三：质量优化", "学习如何诊断问题、优化结果并稳定输出。"),
                ("场景案例一", f"在典型{application_label}场景中完成一次完整演示。"),
                ("场景案例二", "处理更复杂约束，补齐边界、风险和人工判断点。"),
                ("综合项目实战", "完成一个从输入到输出的完整项目练习。"),
                ("成果复盘", "复盘关键决策，沉淀模板、检查表和迁移方法。"),
                ("进阶应用规划", "说明下一阶段如何扩展到更高难度或更多场景。"),
            ]

        framework = SeriesCourseFramework(
            course_name=course_name,
            target_user=target_user,
            learner_current_state=f"目前对 {topic} 有零散理解，但还不能在{application}中稳定用起来。",
            learner_expected_state=self._series_expected_state(learning_goal, application),
            mindset_shift=mindset_shift,
            core_problem=f"如何让{target_user}围绕 {topic} 建立系统方法，并真正用于{application}。",
            application_scenario=application if supplementary in {"", "无补充信息"} else f"{application}；补充要求：{supplementary}",
            lessons=[
                SeriesLessonOutline(lesson_number=index + 1, title=title, summary=summary)
                for index, (title, summary) in enumerate(lessons[:lesson_count])
            ],
        )
        return framework.to_markdown()

    def _fallback_rewrite_series_framework_markdown(self, markdown: str, approved_changes: list[str]) -> str:
        try:
            from app.series.scoring import parse_framework_markdown

            framework = parse_framework_markdown(markdown)
        except Exception:
            return markdown

        suggestions_text = "\n".join(approved_changes)
        if "目标学员" in suggestions_text and "更具体" in suggestions_text:
            framework.target_user += "，并且已经具备基本认知但缺乏系统方法。"
        if "核心问题" in suggestions_text or "目标" in suggestions_text:
            framework.core_problem = framework.core_problem + "，并明确最终要交付的可验证结果。"
        if "顺序" in suggestions_text or "重排" in suggestions_text:
            for index, lesson in enumerate(framework.lessons, start=1):
                lesson.lesson_number = index
            if framework.lessons:
                framework.lessons[0].title = "基础认知与框架搭建"
                framework.lessons[-1].title = "综合实战与复盘迁移"
                framework.lessons[-1].summary = "围绕真实场景完成综合演练，复盘关键决策并沉淀迁移方法。"
        if "实战" in suggestions_text or "案例" in suggestions_text:
            if framework.lessons:
                framework.lessons[-1].summary = "通过项目式任务完成真实应用，并在结尾做复盘和纠错。"
            if len(framework.lessons) >= 2:
                framework.lessons[-2].title = "案例应用与项目演练"
                framework.lessons[-2].summary = "把前面的方法放进真实案例中演练，形成完整工作流。"
        if "边界" in suggestions_text or "风险" in suggestions_text:
            framework.application_scenario += "；课程中明确边界、风险提示和人工复核节点。"
        return framework.to_markdown()

    def _split_chunks(self, text: str, chunk_size: int = 120) -> list[str]:
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
